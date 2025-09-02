"""
Document upload service for handling file uploads and processing.
"""

import os
import uuid
from datetime import datetime
from typing import Dict, Any
from pathlib import Path
import logging

from services.rag.embed_chunk import embed_single_chunk
from services.classification import ClassificationService
from services.metadata_manager import MetadataManagerService
from database.database_manager import DatabaseManager
from preprocessing.document_processor import DocumentProcessor
from services.chunk_service import ChunkService
from models.document import DocumentMetadata
from utils.config import config
from utils.exceptions import FileProcessingError
from services.summarization import SummarizationService
from services.blob_storage_service import blob_storage_service
from services.ai_search_service import AzureSearchService

logger = logging.getLogger(__name__)

class DocumentUploadService:
    """
    Enhanced service for handling document uploads and processing with improved error handling,
    validation, and resource management.
    """

    def __init__(self):
        self.max_file_size = 50 * 1024 * 1024  # 50MB
        self.allowed_extensions = {
            "pdf",
            "docx",
            "doc",
            "txt",
            "csv",
            "xlsx",
            "xls",
            "pptx",
            "ppt",
        }

        # Initialize services with error handling
        try:
            self.db_manager = DatabaseManager()
            self.metadata_manager = MetadataManagerService()
            self.classification_service = ClassificationService()
            self.ai_search_service = AzureSearchService()

            # Get API keys from config with validation
            api_keys = {
                "gemini": config.GEMINI_API_KEY,
                "openai": getattr(config, "OPENAI_API_KEY", None),
            }

            # Validate at least one API key is available
            if not any(api_keys.values()):
                logger.warning("No API keys found in config, document processing may be limited")

            self.document_processor = DocumentProcessor(api_keys=api_keys)

        except Exception as e:
            logger.error(f"Error initializing services: {e}")
            raise

    def process_single_document(self, task: Dict[str, Any]):
        """Process a single document with comprehensive error handling and cleanup."""
        temp_document_id = task["temp_document_id"]
        project_id = task["project_id"]
        user_id = task["user_id"]
        dest_path = None

        try:
            logger.info(f"Processing single document: {temp_document_id}")

            # Get temp document from database
            temp_doc = self.db_manager.get_temp_document(temp_document_id, project_id, user_id)

            if not temp_doc:
                raise FileProcessingError(f"Temp document {temp_document_id} not found in database")

            # Extract document information
            original_filename = temp_doc["original_filename"]
            file_size = temp_doc.get("file_size", 0)
            mime_type = temp_doc.get("mime_type", "application/octet-stream")
            text_preview = temp_doc.get("text_preview", "")
            ai_purpose = temp_doc.get("ai_purpose", task["ai_purpose"])
            source = task["source"]

            # Determine category folder based on AI classification
            category_folder = temp_doc.get("ai_classification", task["ai_classification"])

            # Create unique destination filename to prevent conflicts
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            unique_filename = f"{timestamp}_{original_filename}"

            source_container = config.TEMP_DOCUMENTS_CONTAINER
            dest_container = config.DOCUMENTS_CONTAINER
            source_blob_name = f"{user_id}/{project_id}/{original_filename}"
            dest_blob_name = f"{category_folder}/{user_id}/{project_id}/{original_filename}"

            # Create document metadata
            document_id = uuid.uuid4()
            metadata_filename = f"{Path(unique_filename).stem}_metadata.json"
            metadata_path = os.path.join(temp_doc['blob_name'], metadata_filename)

            try:
                # Create DocumentMetadata object
                doc_meta = DocumentMetadata(
                    id=str(document_id),
                    originalFilename=original_filename,
                    fileSize=file_size,
                    fileMimeType=mime_type,
                    dateAddedToGiani=datetime.now().isoformat(),
                    userID=user_id,
                    projectID=project_id,
                    source=source,
                    textPreview=text_preview,
                    finalCategory=category_folder,
                    finalPurpose=ai_purpose,
                    priority=task.get("document_priority", "Medium"),
                    finalizedAt=datetime.now().isoformat(),
                    storagePath=dest_blob_name,
                    categoryFolder=category_folder,
                    storedFilename=unique_filename,
                    savedAt=datetime.now().isoformat(),
                )

                # Convert user_id and project_id to proper types for database
                try:
                    user_uuid = (uuid.UUID(user_id) if isinstance(user_id, str) else user_id)
                except ValueError:
                    raise FileProcessingError(f"Invalid user_id format: {user_id}")

                try:
                    project_int = (int(project_id) if isinstance(project_id, str) else project_id)
                except (ValueError, TypeError):
                    raise FileProcessingError(f"Invalid project_id format: {project_id}")

                # Create document in database
                document = self.db_manager.create_document(
                    id=document_id,
                    source=source,
                    original_filename=original_filename,
                    file_size=file_size,
                    file_mime_type=mime_type,
                    storage_path=dest_blob_name,
                    category_folder=category_folder,
                    stored_filename=unique_filename,
                    final_category=task["ai_classification"],
                    final_purpose=task["ai_purpose"],
                    priority=task.get("document_priority", "Medium"),
                    text_preview=text_preview,
                    user_id=user_uuid,
                    project_id=project_int,
                    processed_content=task.get("user_purpose_note", ""),
                    # document_metadata=doc_meta,
                    date_added_to_giani=datetime.utcnow(),
                )

                if not document:
                    raise FileProcessingError("Failed to create document record in database")
                logger.info(f"Successfully processed document: {original_filename}")

            except Exception as db_error:
                logger.error(f"Database/metadata error for {original_filename}: {db_error}")

                # TODO: Cleanup destination file if database operation failed

                raise FileProcessingError(f"Failed to save document metadata: {db_error}")

            # DOCUMENT PROCESSING & CHUNKING
            parsed_blocks = None
            chunk_dtos = None

            try:
                logger.info(
                    f"Starting document processing and chunking for: {original_filename}"
                )

                # Process document once to get parsed blocks
                parsed_blocks = self.document_processor.process_single_file(
                    container_name=source_container, blob_name=source_blob_name, document_id=str(document_id), project_id=project_id
                )

                if parsed_blocks:
                    # Create chunks from parsed blocks using chunk service
                    chunk_service = ChunkService()
                    chunk_dtos = chunk_service.generate_chunks(
                        parsed_blocks=parsed_blocks,
                        document_id=document_id,
                        project_id=project_id,
                        document_type=doc_meta.finalCategory,
                        openai_api_key=config.OPENAI_API_KEY,
                    )

                    if chunk_dtos:
                        # Complete pipeline: embed, save, and index chunks
                        try:
                            import asyncio
                            processing_stats = asyncio.run(
                                chunk_service.embed_save_and_index_chunks(chunk_dtos)
                            )

                            logger.info(f"Chunk processing stats: {processing_stats}")

                            if processing_stats['saved_successfully'] > 0:
                                logger.info(f"Successfully processed {processing_stats['saved_successfully']} chunks")
                            else:
                                logger.warning("No chunks were successfully processed")

                        except Exception as e:
                            logger.error(f"Error during chunk processing pipeline: {e}")
                            # Fallback to basic embedding and saving
                            embedding_stats = chunk_service.embed_and_save_chunks(chunk_dtos)
                            logger.info(f"Fallback embedding stats: {embedding_stats}")

                    else:
                        logger.warning(f"No chunks generated for document: {original_filename}")
                else:
                    logger.warning(f"No parsed blocks generated for document: {original_filename}")

            except Exception as e:
                logger.error(
                    f"Error during document processing and chunking for {original_filename}: {e}"
                )
                # Don't fail the entire process, continue with summarization attempt

            # SUMMARIZATION
            try:
                logger.info(f"Starting summarization for: {original_filename}")

                summarization_service = SummarizationService()

                # Use pre-processed chunks if available, otherwise fall back to file processing
                if chunk_dtos:
                    logger.info(f"Using chunk DTOs ({len(chunk_dtos)}) for summarization")
                    summary = summarization_service.summarize_from_chunk_dtos(doc_meta, chunk_dtos)
                else:
                    logger.warning("No chunks available, falling back to file-based summarization")
                    summary = summarization_service.summarize_document(doc_meta)

                if summary:
                    self.db_manager.save_summary(document_id=document_id, summary_data=summary)
                    logger.info(f"Successfully generated and saved summary for document: {original_filename}")
                else:
                    logger.warning(f"No summary generated for document: {original_filename}")

            except Exception as e:
                logger.error(
                    f"Error during summarization for document {original_filename}: {e}"
                )
                # Don't fail the entire process for summarization errors

            # Clean up temp document and file (only after successful processing)
            try:
                # Remove temp file
                try:
                    blob_storage_service.move_file(
                        source_path=source_blob_name,
                        dest_path=dest_blob_name,
                        source_container=source_container,
                        dest_container=dest_container
                    )
                except Exception as e:
                    logger.error("Unable to move file.")
                    raise

                # Remove temp document from database
                self.db_manager.delete_temp_document(
                    temp_document_id, user_id, cleanup_file=False
                )
                logger.debug(f"Removed temp document from database: {temp_document_id}")

            except Exception as cleanup_error:
                logger.warning(f"Cleanup error for {temp_document_id}: {cleanup_error}")
                # Don't fail the entire process for cleanup errors

            logger.info(
                f"Document processing completed successfully: {original_filename}"
            )

        except Exception as e:
            logger.error(f"Error processing document {temp_document_id}: {e}")

            # Cleanup on error
            try:
                if dest_path and os.path.exists(dest_path):
                    os.remove(dest_path)
                    logger.info(f"Cleaned up destination file after error: {dest_path}")
            except:
                pass

            # Re-raise the error to be handled by the calling function
            raise