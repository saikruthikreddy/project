"""
Document upload service for handling file uploads and processing - Blob Storage Only.
"""
import uuid
import mimetypes
from datetime import datetime
from typing import Dict, List, Any, Optional
import logging
import json
from urllib.parse import urlparse, quote
import tempfile
import os

from azure_functions.services.blob_storage_service import BlobStorageService
from azure_functions.preprocessing.document_processor import DocumentProcessor
from azure_functions.services.classification import ClassificationService
from azure_functions.services.metadata_manager import MetadataManagerService
from azure_functions.models.document import DocumentMetadata
from azure_functions.database.database_manager import DatabaseManager
from azure_functions.utils.config import config
from azure_functions.utils.constants import DOCUMENT_TYPES
from azure_functions.utils.exceptions import FileProcessingError, ValidationError
from azure_functions.services.summarization import SummarizationService
from azure_functions.preprocessing.chunking.strategies import chunk_document_adaptive

logger = logging.getLogger(__name__)


class DocumentUploadService:
    """
    Service for handling document uploads and processing using blob storage only.
    """

    def __init__(self):
        # Blob storage configuration
        self.temp_container = 'temp-documents'
        self.processed_container = 'documents'
        self.max_file_size = 50 * 1024 * 1024  # 50MB
        self.allowed_extensions = {'pdf', 'docx', 'doc', 'txt', 'csv', 'xlsx', 'xls', 'pptx', 'ppt'}

        # Initialize services with error handling
        try:
            self.db_manager = DatabaseManager()
            self.metadata_manager = MetadataManagerService()
            self.classification_service = ClassificationService()
            self.blob_storage_service = BlobStorageService()

            # Get API keys from config with validation
            api_keys = {
                'gemini': config.GEMINI_API_KEY,
                'openai': getattr(config, 'OPENAI_API_KEY', None)
            }
            
            # Validate at least one API key is available
            if not any(api_keys.values()):
                logger.warning("No API keys found in config, document processing may be limited")
                
            self.document_processor = DocumentProcessor(api_keys=api_keys)

        except Exception as e:
            logger.error(f"Error initializing services: {e}")
            raise

    def allowed_file(self, filename: str) -> bool:
        """Check if file extension is allowed with enhanced validation."""
        try:
            if not filename or not isinstance(filename, str):
                return False
                
            if '.' not in filename:
                return False
                
            # Get extension and normalize
            extension = filename.rsplit('.', 1)[1].lower().strip()
            
            # Check against allowed extensions
            is_allowed = extension in self.allowed_extensions
            
            if not is_allowed:
                logger.warning(f"File extension '{extension}' not allowed for file: {filename}")
                
            return is_allowed
            
        except Exception as e:
            logger.error(f"Error checking file extension for {filename}: {e}")
            return False

    def validate_file(self, filename: str, file_size: int, file_content: bytes = None) -> None:
        """Validate uploaded file with comprehensive checks."""
        try:
            # Validate inputs
            if not filename or not isinstance(filename, str):
                raise ValidationError("Invalid filename provided")
                
            if not isinstance(file_size, int) or file_size < 0:
                raise ValidationError("Invalid file size provided")
                
            # Check file size
            if file_size > self.max_file_size:
                raise ValidationError(
                    f"File size {file_size:,} bytes exceeds maximum allowed size "
                    f"{self.max_file_size:,} bytes ({self.max_file_size / (1024*1024):.1f}MB)"
                )
                
            # Check minimum file size (prevent empty files)
            if file_size == 0:
                raise ValidationError("File is empty (0 bytes)")
                
            # Check file extension
            if not self.allowed_file(filename):
                allowed_exts = ', '.join(sorted(self.allowed_extensions))
                raise ValidationError(
                    f"File type not allowed. Allowed extensions: {allowed_exts}"
                )
                
            # Validate file content if provided
            if file_content is not None:
                if len(file_content) != file_size:
                    raise ValidationError(f"File content size mismatch: {len(file_content)} vs {file_size}")
                    
            logger.debug(f"File validation passed for: {filename}")
            
        except ValidationError:
            raise  # Re-raise validation errors
        except Exception as e:
            logger.error(f"Error validating file {filename}: {e}")
            raise ValidationError(f"File validation failed: {e}")

    def extract_text_preview(self, blob_url: str, max_chars: int = 5000) -> str:
        """Extract text preview from blob file with enhanced error handling and safety."""
        temp_file_path = None
        try:
            if not blob_url:
                logger.warning("No blob URL provided for text extraction")
                return "No file available for text extraction"
                
            if max_chars <= 0:
                max_chars = 5000

            logger.info(f"Extracting text preview from blob: {blob_url}")

            # Parse blob URL to get container and blob name
            parsed_url = urlparse(blob_url)
            path_parts = parsed_url.path.lstrip('/').split('/', 1)
            
            if len(path_parts) < 2:
                return "Invalid blob URL format"
                
            container_name = path_parts[0]
            blob_name = path_parts

            # Download blob content
            file_bytes = self.blob_storage_service.download_file(container_name, blob_name)
            
            if not file_bytes:
                return "Empty file content"

            # Create temporary file for processing
            with tempfile.NamedTemporaryFile(delete=False, suffix='_preview') as temp_file:
                temp_file.write(file_bytes)
                temp_file_path = temp_file.name

            # Generate temporary IDs for processing
            temp_doc_id = str(uuid.uuid4())
            temp_proj_id = str(uuid.uuid4())
            
            try:
                # Use process_single_file with timeout protection
                parsed_blocks, chunks = self.document_processor.process_single_file(
                    file_path=temp_file_path,
                    document_id=temp_doc_id,
                    project_id=temp_proj_id
                )
                
                if parsed_blocks and len(parsed_blocks) > 0:
                    # Extract text from the first few blocks
                    text_content = ""
                    for block_text, block_metadata in parsed_blocks:
                        if block_text and isinstance(block_text, str):
                            text_content += block_text.strip() + "\n"
                            if len(text_content) >= max_chars:
                                break
                                
                    # Clean and truncate text
                    preview_text = text_content.strip()[:max_chars]
                    
                    if len(preview_text) == max_chars and len(text_content) > max_chars:
                        preview_text += "... [truncated]"
                        
                    return preview_text if preview_text else "No readable text found"
                else:
                    return "No text content extracted"
                    
            except Exception as processing_error:
                logger.error(f"Document processor error for blob {blob_url}: {processing_error}")
                return self._fallback_text_extraction_from_bytes(file_bytes, max_chars)
            
        except Exception as e:
            logger.error(f"Error extracting text preview from blob {blob_url}: {e}")
            return f"Text extraction failed: {str(e)}"
        finally:
            # Clean up temporary file
            if temp_file_path and os.path.exists(temp_file_path):
                try:
                    os.remove(temp_file_path)
                except Exception as cleanup_error:
                    logger.warning(f"Failed to cleanup temp file {temp_file_path}: {cleanup_error}")

    def _fallback_text_extraction_from_bytes(self, file_bytes: bytes, max_chars: int) -> str:
        """Fallback text extraction from file bytes."""
        try:
            # Try to decode as UTF-8 text
            try:
                text_content = file_bytes.decode('utf-8', errors='ignore')[:max_chars]
                return text_content if text_content.strip() else "No readable text content"
            except:
                pass
                
            # Try other common encodings
            for encoding in ['latin-1', 'cp1252', 'iso-8859-1']:
                try:
                    text_content = file_bytes.decode(encoding, errors='ignore')[:max_chars]
                    if text_content.strip():
                        return text_content
                except:
                    continue
                    
            return "Binary file - text extraction not supported"
            
        except Exception as e:
            logger.error(f"Fallback text extraction failed: {e}")
            return "Text extraction failed"

    def _get_blob_url(self, container: str, blob_name: str) -> str:
        """Generate blob URL for storage reference."""
        try:
            # Construct blob URL - this should match your blob storage URL format
            base_url = getattr(config, 'AZURE_STORAGE_ACCOUNT_URL', '')
            if base_url:
                return f"{base_url.rstrip('/')}/{container}/{blob_name}"
            else:
                # Fallback format
                return f"https://storage.blob.core.windows.net/{container}/{blob_name}"
        except Exception as e:
            logger.error(f"Error generating blob URL: {e}")
            return f"{container}/{blob_name}"  # Simple format as fallback

    def save_temp_document(self, file_content: bytes, filename: str, project_id: str, user_id: str, source: str) -> Dict[str, Any]:
        """Save uploaded file to blob storage and create database entry."""
        try:
            # Input validation
            if not file_content or not isinstance(file_content, bytes):
                raise ValidationError("Invalid file content provided")
                
            if not filename or not isinstance(filename, str):
                raise ValidationError("Invalid filename provided")
                
            if not project_id or not isinstance(project_id, str):
                raise ValidationError("Invalid project_id provided")
                
            if not user_id or not isinstance(user_id, str):
                raise ValidationError("Invalid user_id provided")

            # Get file information
            file_size = len(file_content)
            mime_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"

            # Validate file
            self.validate_file(filename, file_size, file_content)

            # Generate temp document ID
            temp_document_id = str(uuid.uuid4())

            logger.info(f"Saving temp document to blob storage: {filename} ({file_size:,} bytes)")

            # Create blob name with proper structure: user_id/project_id/temp_document_id/filename
            blob_name = f"{user_id}/{project_id}/{temp_document_id}/{filename}"
            
            # Upload to blob storage
            blob_url = self.blob_storage_service.upload_file(
                container_name=self.temp_container,
                blob_name=blob_name,
                file_content=file_content,
                content_type=mime_type
            )
            
            if not blob_url:
                raise FileProcessingError("Failed to upload file to blob storage")

            # Extract text preview with error handling
            try:
                text_preview = self.extract_text_preview(blob_url)
            except Exception as e:
                logger.warning(f"Failed to extract text preview for {filename}: {e}")
                text_preview = f"Text preview unavailable: {str(e)}"

            # Create temp document structure
            temp_doc = {
                'temp_document_id': temp_document_id,
                'project_id': project_id,
                'user_id': user_id,
                'original_filename': filename,
                'source': source,
                'blob_url': blob_url,
                'blob_container': self.temp_container,
                'blob_name': blob_name,
                'file_size': file_size,
                'mime_type': mime_type,
                'text_preview': text_preview,
                'status': 'UPLOADED',
                'upload_timestamp': datetime.utcnow()
            }

            # Save to database
            db_result = self.db_manager.create_temp_document(**temp_doc)
            
            if not db_result:
                # Cleanup blob if database save failed
                try:
                    self.blob_storage_service.delete_file(self.temp_container, blob_name)
                except Exception as cleanup_error:
                    logger.warning(f"Failed to cleanup blob after database error: {cleanup_error}")
                raise FileProcessingError("Failed to save document to database")

            logger.info(f"Successfully saved temp document to blob: {blob_url}")
            return temp_doc

        except ValidationError:
            raise  # Re-raise validation errors
        except Exception as e:
            logger.error(f"Error saving temp document {filename}: {e}")
            raise FileProcessingError(f"Failed to save temp document: {e}")

    def get_ai_suggestions(self, temp_document_id: str, source: str, project_id: str, user_id: str) -> Dict[str, Any]:
        """Get AI suggestions for document classification with enhanced error handling."""
        try:
            # Input validation
            if not all([temp_document_id, project_id, user_id]):
                raise ValidationError("Missing required parameters for AI suggestions")

            logger.info(f"Getting AI suggestions for document: {temp_document_id}")

            # Get temp document from database
            temp_doc = self.db_manager.get_temp_document(temp_document_id, project_id, user_id)
            
            if not temp_doc:
                raise FileProcessingError(f"Temporary document {temp_document_id} not found")

            # Validate temp document has required fields
            if not temp_doc.get('text_preview'):
                logger.warning(f"No text preview available for document {temp_document_id}")
                text_preview = "No text preview available"
            else:
                text_preview = temp_doc['text_preview']

            filename = temp_doc.get('original_filename', 'unknown_file')
            
            logger.debug(f"Text preview length: {len(text_preview)} characters")

            try:
                # Get AI classification with error handling
                ai_classification, ai_purpose, gemini_prompt = self.classification_service.classify_document(
                    filename, text_preview, source
                )

                # Validate AI response
                if not ai_classification:
                    ai_classification = "Generic Document"
                    logger.warning(f"AI classification failed, using default for {filename}")
                    
                if not ai_purpose:
                    ai_purpose = "Purpose not determined"
                    logger.warning(f"AI purpose detection failed, using default for {filename}")

                suggestions = {
                    'temp_document_id': temp_document_id,
                    'original_filename': filename,
                    'ai_classification': ai_classification,
                    'ai_purpose': ai_purpose,
                    'gemini_prompt': gemini_prompt or "No prompt available",
                    'text_preview': text_preview[:1000] + ('...' if len(text_preview) > 1000 else ''),
                    'confidence': 'medium',
                    'processing_timestamp': datetime.utcnow().isoformat()
                }

                logger.info(f"AI suggestions generated for {filename}: {ai_classification}")
                return suggestions

            except Exception as ai_error:
                logger.error(f"AI classification failed for {filename}: {ai_error}")
                
                # Return fallback suggestions
                return {
                    'temp_document_id': temp_document_id,
                    'original_filename': filename,
                    'ai_classification': 'Generic Document',
                    'ai_purpose': 'Classification unavailable due to processing error',
                    'gemini_prompt': 'AI processing failed',
                    'text_preview': text_preview[:1000] + ('...' if len(text_preview) > 1000 else ''),
                    'confidence': 'low',
                    'error': str(ai_error),
                    'processing_timestamp': datetime.utcnow().isoformat()
                }

        except ValidationError:
            raise
        except Exception as e:
            logger.error(f"Error getting AI suggestions for {temp_document_id}: {e}")
            raise FileProcessingError(f"Failed to get AI suggestions: {e}")

    def _process_single_document(self, task: Dict[str, Any]):
        """Process a single document with blob storage only."""
        temp_document_id = task['temp_document_id']
        project_id = task['project_id']
        user_id = task['user_id']
        batch_id = task['batch_id']

        temp_file_path = None

        try:
            logger.info(f"Processing single document: {temp_document_id}")

            # Get temp document from database
            temp_doc = self.db_manager.get_temp_document(temp_document_id, project_id, user_id)

            if not temp_doc:
                raise FileProcessingError(f"Temp document {temp_document_id} not found in database")

            # Extract document information
            original_filename = temp_doc['original_filename']
            blob_url = temp_doc['blob_url']
            blob_container = temp_doc['blob_container']
            blob_name = temp_doc['blob_name']
            file_size = temp_doc.get('file_size', 0)
            mime_type = temp_doc.get('mime_type', 'application/octet-stream')
            text_preview = temp_doc.get('text_preview', '')
            ai_purpose = temp_doc.get('ai_purpose', task['ai_purpose'])
            source = task['source']

            # Download blob content for processing
            try:
                logger.info(f"Downloading blob for processing: {blob_name}")
                file_bytes = self.blob_storage_service.download_file(blob_container, blob_name)

                # Create temporary file for document processing
                temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=f"_{original_filename}")
                temp_file.write(file_bytes)
                temp_file.close()
                temp_file_path = temp_file.name

                logger.info(f"Blob content written to temporary file for processing: {temp_file_path}")

            except Exception as e:
                raise FileProcessingError(f"Failed to download blob {blob_url}: {e}")

            # Determine category folder based on AI classification
            category_folder = temp_doc.get('ai_classification', task['ai_classification'])
            category_path = self._get_category_folder(category_folder)

            # Create unique destination blob name
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            base_name = os.path.splitext(original_filename)[0]
            extension = os.path.splitext(original_filename)
            unique_filename = f"{timestamp}_{base_name}{extension}"
            
            # Processed blob name: category/user_id/project_id/unique_filename
            processed_blob_name = f"{category_path}/{user_id}/{project_id}/{unique_filename}"

            # Upload processed document to blob storage
            try:
                processed_blob_url = self.blob_storage_service.upload_file(
                    container_name=self.processed_container,
                    blob_name=processed_blob_name,
                    file_content=file_bytes,
                    content_type=mime_type
                )

                if not processed_blob_url:
                    raise FileProcessingError("Failed to upload processed document to blob storage")

                logger.info(f"Processed document uploaded to blob: {processed_blob_url}")

            except Exception as upload_error:
                raise FileProcessingError(f"Failed to upload processed document: {upload_error}")

            # Create document metadata
            document_id = uuid.uuid4()

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
                    priority=task.get('document_priority', 'Medium'),
                    finalizedAt=datetime.now().isoformat(),
                    storagePath=processed_blob_url,
                    categoryFolder=category_path,
                    storedFilename=unique_filename,
                    savedAt=datetime.now().isoformat()
                )

                user_uuid = uuid.UUID(user_id)
                project_int = int(project_id)

                # Create document in database
                document = self.db_manager.create_document(
                    id=document_id,
                    source=source,
                    original_filename=original_filename,
                    file_size=file_size,
                    file_mime_type=mime_type,
                    storage_path=processed_blob_url,
                    category_folder=category_path,
                    stored_filename=unique_filename,
                    final_category=task['ai_classification'],
                    final_purpose=task['ai_purpose'],
                    priority=task.get('document_priority', 'Medium'),
                    text_preview=text_preview,
                    user_id=user_uuid,
                    project_id=project_int,
                    processed_content=task.get('user_purpose_note', ''),
                    date_added_to_giani=datetime.utcnow()
                )

                if not document:
                    raise FileProcessingError("Failed to create document record in database")

                self.metadata_manager.update_master_metadata(doc_meta)
                logger.info(f"Successfully processed document: {original_filename}")

            except Exception as db_error:
                logger.error(f"Database/metadata error for {original_filename}: {db_error}")
                # Cleanup processed blob on error
                try:
                    self.blob_storage_service.delete_file(self.processed_container, processed_blob_name)
                except Exception as cleanup_error:
                    logger.warning(f"Failed to cleanup processed blob: {cleanup_error}")
                raise FileProcessingError(f"Failed to save document metadata: {db_error}")

            # Clean up temp document and blob (only after successful processing)
            try:
                # Remove temp blob
                self.blob_storage_service.delete_file(blob_container, blob_name)
                logger.debug(f"Removed temp blob: {blob_name}")

                # Remove temp document from database
                self.db_manager.delete_temp_document(temp_document_id, user_id, cleanup_file=False)
                logger.debug(f"Removed temp document from database: {temp_document_id}")

            except Exception as cleanup_error:
                logger.warning(f"Cleanup error for {temp_document_id}: {cleanup_error}")

            # Summarization and Chunking
            try:
                summarization_service = SummarizationService()
                summary = summarization_service.summarize_document(doc_meta)
                if summary:
                    self.db_manager.save_summary(document_id=document_id, summary_data=summary)
                    logger.info(f"Successfully generated and saved summary for document: {original_filename}")
            except Exception as e:
                logger.error(f"Error during summarization for document {original_filename}: {e}")

            try:
                parsed_blocks, _ = self.document_processor.process_single_file(
                    file_path=temp_file_path, document_id=document_id, project_id=project_id)
                chunks = chunk_document_adaptive(
                    parsed_blocks=parsed_blocks, document_id=document_id, project_id=project_id,
                    document_type=doc_meta.finalCategory, openai_api_key=config.OPENAI_API_KEY)
                if chunks:
                    self.db_manager.save_chunks(document_id=document_id, chunks=chunks)
                    logger.info(f"Successfully chunked and saved document: {original_filename}")
            except Exception as e:
                logger.error(f"Error during chunking for document {original_filename}: {e}")

            logger.info(f"Document processing completed successfully: {original_filename}")

        except Exception as e:
            logger.error(f"Error processing document {temp_document_id}: {e}", exc_info=True)
            raise
        finally:
            # Always clean up temporary file
            if temp_file_path and os.path.exists(temp_file_path):
                try:
                    os.remove(temp_file_path)
                    logger.debug(f"Cleaned up temporary file: {temp_file_path}")
                except Exception as cleanup_error:
                    logger.warning(f"Failed to cleanup temp file {temp_file_path}: {cleanup_error}")

    def _get_category_folder(self, ai_classification: str) -> str:
        """Get category folder based on AI classification with enhanced mapping and validation."""
        try:
            if not ai_classification or not isinstance(ai_classification, str):
                logger.warning(f"Invalid AI classification: {ai_classification}")
                return "39-generic-text-document"

            # Normalize classification for comparison
            classification_lower = ai_classification.lower().strip()

            # Enhanced category mapping with blob-friendly names (no spaces, periods, or special chars)
            category_mappings = {
                "strategy": "01-strategy-document",
                "financial": "02-financial-document", 
                "legal": "03-legal-document",
                "technical": "04-technical-document",
                "marketing": "05-marketing-document",
                "research": "06-research-document",
                "project management": "07-project-management-document",
                "business plan": "01-strategy-document",
                "contract": "03-legal-document",
                "agreement": "03-legal-document",
                "invoice": "02-financial-document",
                "budget": "02-financial-document",
                "proposal": "05-marketing-document",
                "specification": "04-technical-document",
                "manual": "04-technical-document",
                "report": "06-research-document",
                "analysis": "06-research-document"
            }

            # Find matching category
            for keyword, folder in category_mappings.items():
                if keyword in classification_lower:
                    logger.debug(f"Mapped '{ai_classification}' to '{folder}' via keyword '{keyword}'")
                    return folder

            # Default category
            default_category = "39-generic-text-document"
            logger.debug(f"Using default category for '{ai_classification}': {default_category}")
            return default_category

        except Exception as e:
            logger.error(f"Error determining category folder for '{ai_classification}': {e}")
            return "39-generic-text-document"
