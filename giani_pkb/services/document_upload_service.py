"""
Document upload service for handling file uploads and processing.
"""
import os
import shutil
import uuid
import mimetypes
from datetime import datetime
from typing import Dict, List, Any
from pathlib import Path
import logging
from queue import Queue
import threading

from giani_pkb.preprocessing.document_processor import DocumentProcessor
from giani_pkb.services.classification import ClassificationService
from giani_pkb.services.metadata_manager import MetadataManagerService
from giani_pkb.models.document import DocumentMetadata
from giani_pkb.database.database_manager import DatabaseManager
from giani_pkb.utils.config import config
from giani_pkb.utils.constants import DOCUMENT_TYPES
from giani_pkb.utils.exceptions import FileProcessingError, ValidationError

logger = logging.getLogger(__name__)

class DocumentUploadService:
    """
    Service for handling document uploads and processing.
    """

    def __init__(self):
        self.upload_folder = 'temp_uploads'
        self.processed_folder = 'data/uploaded_documents'
        self.max_file_size = 50 * 1024 * 1024  # 50MB
        self.allowed_extensions = {'pdf', 'docx', 'doc', 'txt', 'csv', 'xlsx', 'xls', 'pptx', 'ppt'}

        # Initialize services
        self.db_manager = DatabaseManager()
        self.metadata_manager = MetadataManagerService()
        self.classification_service = ClassificationService()

        # Get API keys from config
        api_keys = {
            'gemini': config.GEMINI_API_KEY,
            'openai': getattr(config, 'OPENAI_API_KEY', None)
        }
        self.document_processor = DocumentProcessor(api_keys=api_keys)

        # Processing queue for async operations
        self.processing_queue = Queue()
        self.batch_status = {}

        # Ensure directories exist
        self._ensure_directories()

        # Start background processing thread
        self._start_background_processor()

    def _ensure_directories(self):
        """Ensure all required directories exist."""
        os.makedirs(self.upload_folder, exist_ok=True)
        os.makedirs(self.processed_folder, exist_ok=True)
        for doc_type in DOCUMENT_TYPES:
            os.makedirs(os.path.join(self.processed_folder, doc_type), exist_ok=True)

    def _start_background_processor(self):
        """Start background thread for processing documents."""
        def process_queue():
            while True:
                try:
                    task = self.processing_queue.get()
                    if task is None:  # Shutdown signal
                        break

                    self._process_document_task(task)
                    self.processing_queue.task_done()
                except Exception as e:
                    logger.error(f"Error in background processing: {e}")

        self.background_thread = threading.Thread(target=process_queue, daemon=True)
        self.background_thread.start()

    def allowed_file(self, filename: str) -> bool:
        """Check if file extension is allowed."""
        return '.' in filename and filename.rsplit('.', 1)[1].lower() in self.allowed_extensions

    def validate_file(self, file_path: str, file_size: int) -> None:
        """Validate uploaded file."""
        if file_size > self.max_file_size:
            raise ValidationError(f"File size {file_size} exceeds maximum allowed size {self.max_file_size}")

        if not self.allowed_file(file_path):
            raise ValidationError(f"File type not allowed: {file_path}")

    def extract_text_preview(self, file_path: str, max_chars: int = 5000) -> str:
        """Extract text preview from file."""
        try:
            # Generate temporary IDs for processing
            temp_doc_id = str(uuid.uuid4())
            temp_proj_id = str(uuid.uuid4())
            
            # Use process_single_file instead of process_files
            parsed_blocks, chunks = self.document_processor.process_single_file(
                file_path=file_path,
                document_id=temp_doc_id,
                project_id=temp_proj_id
            )
            
            if parsed_blocks:
                # Extract text from the first few blocks
                text_content = ""
                for block_text, block_metadata in parsed_blocks:
                    text_content += block_text + "\n"
                    if len(text_content) >= max_chars:
                        break
                return text_content[:max_chars]
            
            return ""
            
        except Exception as e:
            logger.error(f"Error extracting text preview from {file_path}: {e}")
            raise FileProcessingError(f"Error extracting preview from {file_path}: {str(e)}", filepath=file_path)


    def save_temp_document(self, file_path: str, project_id: str, user_id: str) -> Dict[str, Any]:
        """Save uploaded file to temporary location and create database entry."""
        original_filename = os.path.basename(file_path)
        file_size = os.path.getsize(file_path)
        mime_type = mimetypes.guess_type(file_path)[0] or "unknown"

        # Validate file
        self.validate_file(original_filename, file_size)

        # Generate temp document ID
        temp_document_id = str(uuid.uuid4())

        # Extract text preview
        text_preview = self.extract_text_preview(file_path)

        try:
            # Create temp document using database manager
            # Note: This would need to be implemented in DatabaseManager
            # For now, we'll create a simple dict structure
            temp_doc = {
                'temp_document_id': temp_document_id,
                'project_id': project_id,
                'user_id': user_id,
                'original_filename': original_filename,
                'file_path': file_path,
                'file_size': file_size,
                'mime_type': mime_type,
                'text_preview': text_preview,
                'status': 'UPLOADED'
            }

            self.db_manager.create_temp_document(**temp_doc)

            logger.info(f"Saved temp document: {original_filename}")
            return temp_doc

        except Exception as e:
            logger.error(f"Database error saving temp document: {e}")
            raise FileProcessingError(f"Failed to save temp document: {e}", filepath=file_path)

    def get_ai_suggestions(self, temp_document_id: str, project_id: str, user_id: str) -> Dict[str, Any]:
        """Get AI suggestions for document classification."""
        try:
            temp_doc = self.db_manager.get_temp_document(temp_document_id, project_id, user_id)
# 
            # # For now, we'll use a placeholder
            # temp_doc = {
            #     'original_filename': 'placeholder.pdf',
            #     'text_preview': 'Placeholder text preview'
            # }
            print(temp_doc['text_preview'],"SocService",flush=True)
            # Get AI classification
            ai_classification, ai_purpose, gemini_prompt = self.classification_service.classify_document(
                temp_doc['original_filename'], temp_doc['text_preview']
            )

            return {
                'temp_document_id': temp_document_id,
                'original_filename': temp_doc['original_filename'],
                'ai_classification': ai_classification,
                'ai_purpose': ai_purpose,
                'gemini_prompt': gemini_prompt,
                'text_preview': temp_doc['text_preview']
            }

        except Exception as e:
            logger.error(f"Database error getting AI suggestions: {e}")
            raise FileProcessingError(f"Failed to get AI suggestions: {e}")

    def _verify_document_exists(self, temp_document_id: str) -> bool:
        """Verify document exists and is accessible"""
        try:
            file_path = self._get_document_path(temp_document_id)
            exists = os.path.exists(file_path)
            if not exists:
                logger.warning(f"Document verification failed for {temp_document_id}: {file_path}")
            return exists
        except Exception as e:
            logger.error(f"Error verifying document {temp_document_id}: {e}")
            return False


    def process_document_batch(self, project_id: str, user_id: str,
                             document_data: List[Dict[str, Any]]) -> str:
        """Process a batch of documents."""
        batch_id = str(uuid.uuid4())
        print("INside DocUploadService")
        try:
            # Debug document_data structure
            print(f"document_data type: {type(document_data)}")
            print(f"document_data content: {document_data}")
            
            # Convert single dict to list of dicts
            if isinstance(document_data, dict):
                document_data = [document_data]  # Wrap in list
                print(f"Converted to list: {document_data}")
            
            # Ensure document_data is a list
            if not isinstance(document_data, list):
                raise FileProcessingError(f"document_data must be a list, got {type(document_data)}")

            
            valid_documents = 0
            for doc_data in document_data:
                temp_doc_id = doc_data.get('temp_document_id')
                print("Temp Doc ID are : ", temp_doc_id)
                if temp_doc_id and self._verify_document_exists(temp_doc_id):
                    valid_documents += 1
                else:
                    logger.warning(f"Document not found or invalid: {temp_doc_id}")
            if valid_documents == 0:
                raise ValidationError("No valid documents found for processing")
                
            
            # Create batch record using database manager
            self.db_manager.create_processing_batch(batch_id, project_id, user_id, valid_documents)
            print("inside process_doc_batch")

            # Add tasks to processing queue
            for i, doc_data in enumerate(document_data):
                print(f"Processing item {i}: {doc_data} (type: {type(doc_data)})")
                
                # Check if doc_data is a dictionary
                if not isinstance(doc_data, dict):
                    logger.error(f"Expected dict but got {type(doc_data)} at index {i}: {doc_data}")
                    continue
                
                # Now safely extract the data
                task = {
                    'batch_id': batch_id,
                    'project_id': project_id,
                    'user_id': user_id,
                    'temp_document_id': doc_data.get('temp_document_id'),
                    'ai_classification': doc_data.get('ai_classification'),
                    'ai_purpose': doc_data.get('ai_purpose'),
                    'user_purpose_note': doc_data.get('user_purpose_note', ''),
                    'document_priority': doc_data.get('document_priority', 'Medium')
                }
                
                # Validate required fields
                if not task['temp_document_id']:
                    logger.error(f"Missing temp_document_id in item {i}")
                    continue
                    
                print(f"Adding task: {task}")
                self.processing_queue.put(task)

            # Update batch status
            self.batch_status[batch_id] = {
                'status': 'PROCESSING',
                'total_documents': len(document_data),
                'processed_documents': 0,
                'failed_documents': 0
            }

            logger.info(f"Created batch {batch_id} with {len(document_data)} documents")
            return batch_id

        except Exception as e:
            logger.error(f"Database error creating batch: {e}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            raise FileProcessingError(f"Failed to create batch: {e}")



    def _process_document_task(self, task: Dict[str, Any]):
        """Process a single document task."""
        try:
            # Update batch status
            batch_id = task['batch_id']
            self.batch_status[batch_id]['processed_documents'] += 1

            # Process the document
            self._process_single_document(task)

            logger.info(f"Processed document in batch {batch_id}")

        except Exception as e:
            logger.error(f"Error processing document task: {e}")
            batch_id = task['batch_id']
            self.batch_status[batch_id]['failed_documents'] += 1

    def _process_single_document(self, task: Dict[str, Any]):
        """Process a single document."""
        temp_document_id = task['temp_document_id']
        project_id = task['project_id']
        user_id = task['user_id']

        try:
            temp_doc = self.db_manager.get_temp_document(temp_document_id, project_id, user_id)

            if not temp_doc:
                raise FileProcessingError(f"Temp document {temp_document_id} not found")
            
            # Validate file exists
            if not os.path.exists(temp_doc['file_path']):
                raise FileProcessingError(f"File not found:{temp_doc['file_path']}") 

            original_filename = temp_doc['original_filename']
            file_path = temp_doc['file_path']
            file_size = temp_doc['file_size']
            mime_type = temp_doc['mime_type']
            text_preview = temp_doc['text_preview']

            # Determine category folder based on AI classification
            category_folder = self._get_category_folder(task['ai_classification'])

            # Copy file to final location
            dest_dir = os.path.join(self.processed_folder, category_folder)
            dest_path = os.path.join(dest_dir, original_filename)
            shutil.copy2(file_path, dest_path)

            # Create document metadata
            document_id = str(uuid.uuid4())
            metadata_filename = f"{Path(original_filename).stem}_metadata.json"
            metadata_path = os.path.join(dest_dir, metadata_filename)

            # Create DocumentMetadata object
            doc_meta = DocumentMetadata(
                id=document_id,
                originalFilename=original_filename,
                fileSize=file_size,
                fileMimeType=mime_type,
                dateAddedToGiani=datetime.now().isoformat(),
                userID=user_id,
                projectID=project_id,
                textPreview=text_preview,
                finalCategory=task['ai_classification'],
                finalPurpose=task['ai_purpose'],
                priority=task['document_priority'],
                finalizedAt=datetime.now().isoformat(),
                storagePath=dest_path,
                categoryFolder=category_folder,
                storedFilename=metadata_path,
                savedAt=datetime.now().isoformat()
            )

            # Create document using database manager
            document = self.db_manager.create_document(
                original_filename=original_filename,
                file_size=file_size,
                file_mime_type=mime_type,
                storage_path=dest_path,
                category_folder=category_folder,
                stored_filename=metadata_filename,
                final_category=task['ai_classification'],
                final_purpose=task['ai_purpose'],
                priority=task['document_priority'],
                text_preview=text_preview,
                user_id=uuid.UUID(user_id) if isinstance(user_id, str) else user_id,
                project_id=uuid.UUID(project_id) if isinstance(project_id, str) else project_id
            )

            # Update master metadata
            self.metadata_manager.update_master_metadata(doc_meta)

            self.db_manager.delete_temp_document(temp_document_id, user_id)
            logger.info(f"Processed document: {original_filename}")

        except Exception as e:
            logger.error(f"Error processing document {temp_document_id}: {e}")
            raise

    def _get_category_folder(self, ai_classification: str) -> str:
        """Get category folder based on AI classification."""
        # Map AI classification to folder structure
        if "Strategy" in ai_classification:
            return "1. Strategy Document/Deck"
        elif "Financial" in ai_classification:
            return "2. Financial Document"
        elif "Legal" in ai_classification:
            return "3. Legal Document"
        elif "Technical" in ai_classification:
            return "4. Technical Document"
        elif "Marketing" in ai_classification:
            return "5. Marketing Document"
        elif "Research" in ai_classification:
            return "6. Research Document"
        elif "Project Management" in ai_classification:
            return "7. Project Management Document"
        else:
            return "39. Generic Text Document"

    def get_batch_status(self, batch_id: str) -> Dict[str, Any]:
        """Get batch processing status."""
        try:
            batch_info = self.db_manager.get_processing_batch(batch_id)

            # For now, return status from memory
            if batch_id in self.batch_status:
                return {
                    'success': True,
                    'batch_id': batch_id,
                    **self.batch_status[batch_id]
                }
            else:
                return {
                    'success': False,
                    'error': 'Batch not found',
                    'batch_id': batch_id
                }

        except Exception as e:
            logger.error(f"Database error getting batch status: {e}")
            return {
                'success': False,
                'error': f'Database error: {e}',
                'batch_id': batch_id
            }