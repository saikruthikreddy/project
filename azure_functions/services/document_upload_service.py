"""
Document upload service for handling file uploads and processing.
"""
import os
import shutil
import uuid
import mimetypes
from datetime import datetime
from typing import Dict, List, Any, Optional
from pathlib import Path
import logging
from queue import Queue
import threading
import time
import sys
import json
from contextlib import contextmanager
import tempfile

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
    Enhanced service for handling document uploads and processing with improved error handling,
    validation, and resource management.
    """

    def __init__(self):
        self.upload_folder = 'temp_uploads'
        self.processed_folder = 'data/uploaded_documents'
        self.max_file_size = 50 * 1024 * 1024  # 50MB
        self.allowed_extensions = {'pdf', 'docx', 'doc', 'txt', 'csv', 'xlsx', 'xls', 'pptx', 'ppt'}

        # Initialize services with error handling
        try:
            self.db_manager = DatabaseManager()
            self.metadata_manager = MetadataManagerService()
            self.classification_service = ClassificationService()

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

        # Processing queue for async operations with enhanced management
        self.processing_queue = Queue()
        self.batch_status = {}
        self._shutdown_event = threading.Event()
        self._processing_lock = threading.Lock()

        # Ensure directories exist
        self._ensure_directories()

        # Start background processing thread
        self._start_background_processor()

    def _ensure_directories(self):
        """Ensure all required directories exist with proper permissions."""
        try:
            # Create main directories
            os.makedirs(self.upload_folder, exist_ok=True)
            os.makedirs(self.processed_folder, exist_ok=True)
            
            # Create document type subdirectories
            for doc_type in DOCUMENT_TYPES:
                doc_dir = os.path.join(self.processed_folder, doc_type)
                os.makedirs(doc_dir, exist_ok=True)
                
            # Set appropriate permissions (if on Unix-like system)
            try:
                os.chmod(self.upload_folder, 0o755)
                os.chmod(self.processed_folder, 0o755)
            except (OSError, AttributeError):
                # Windows or permission issues
                pass
                
            logger.info("Directory structure created successfully")
            
        except Exception as e:
            logger.error(f"Error creating directories: {e}")
            raise FileProcessingError(f"Failed to create required directories: {e}")

    def _start_background_processor(self):
        """Start background thread for processing documents with enhanced error handling."""
        def process_queue():
            logger.info("Background document processor started")
            
            while not self._shutdown_event.is_set():
                try:
                    # Get task with timeout to allow for shutdown check
                    try:
                        task = self.processing_queue.get(timeout=1.0)
                    except:
                        continue  # Timeout, check shutdown event
                        
                    if task is None:  # Shutdown signal
                        break

                    # Process the task with error isolation
                    try:
                        self._process_document_task(task)
                    except Exception as e:
                        logger.error(f"Error processing task: {e}")
                        # Update batch status for failed task
                        if 'batch_id' in task:
                            self._update_batch_failure(task['batch_id'])
                    finally:
                        self.processing_queue.task_done()
                        
                except Exception as e:
                    logger.error(f"Critical error in background processing: {e}")
                    time.sleep(1)  # Prevent tight loop on persistent errors
                    
            logger.info("Background document processor stopped")

        self.background_thread = threading.Thread(
            target=process_queue, 
            name="DocumentProcessor", 
            daemon=True
        )
        self.background_thread.start()

    def _update_batch_failure(self, batch_id: str):
        """Update batch status for failed document processing."""
        try:
            with self._processing_lock:
                if batch_id in self.batch_status:
                    self.batch_status[batch_id]['failed_documents'] += 1
                    
                # Update database batch status
                self.db_manager.increment_batch_progress(batch_id, success=False)
                
        except Exception as e:
            logger.error(f"Error updating batch failure status: {e}")

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

    def validate_file(self, file_path: str, file_size: int) -> None:
        """Validate uploaded file with comprehensive checks."""
        try:
            # Validate inputs
            if not file_path or not isinstance(file_path, str):
                raise ValidationError("Invalid file path provided")
                
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
            if not self.allowed_file(file_path):
                allowed_exts = ', '.join(sorted(self.allowed_extensions))
                raise ValidationError(
                    f"File type not allowed. Allowed extensions: {allowed_exts}"
                )
                
            # Verify file exists if it's a full path
            if os.path.isabs(file_path) and not os.path.exists(file_path):
                raise ValidationError(f"File does not exist: {file_path}")
                
            logger.debug(f"File validation passed for: {file_path}")
            
        except ValidationError:
            raise  # Re-raise validation errors
        except Exception as e:
            logger.error(f"Error validating file {file_path}: {e}")
            raise ValidationError(f"File validation failed: {e}")

    def extract_text_preview(self, file_path: str, max_chars: int = 5000) -> str:
        """Extract text preview from file with enhanced error handling and safety."""
        try:
            # Input validation
            if not file_path or not os.path.exists(file_path):
                logger.warning(f"File not found for text extraction: {file_path}")
                return "File not found for text extraction"
                
            if max_chars <= 0:
                max_chars = 5000
                
            # Check file size before processing
            file_size = os.path.getsize(file_path)
            if file_size == 0:
                return "Empty file"
                
            if file_size > self.max_file_size:
                return f"File too large for preview extraction ({file_size:,} bytes)"

            logger.info(f"Extracting text preview from: {file_path}")

            # Generate temporary IDs for processing
            temp_doc_id = str(uuid.uuid4())
            temp_proj_id = str(uuid.uuid4())
            
            try:
                # Use process_single_file with timeout protection
                parsed_blocks, chunks = self.document_processor.process_single_file(
                    file_path=file_path,
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
                logger.error(f"Document processor error for {file_path}: {processing_error}")
                
                # Fallback: try basic text extraction for simple file types
                return self._fallback_text_extraction(file_path, max_chars)
            
        except Exception as e:
            logger.error(f"Error extracting text preview from {file_path}: {e}")
            raise FileProcessingError(
                f"Error extracting preview from {os.path.basename(file_path)}: {str(e)}", 
                filepath=file_path
            )

    def _fallback_text_extraction(self, file_path: str, max_chars: int) -> str:
        """Fallback text extraction for simple file types."""
        try:
            file_ext = os.path.splitext(file_path)[1].lower()
            
            # Simple text file extraction
            if file_ext in ['.txt', '.csv']:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read(max_chars)
                    return content if content.strip() else "No readable content"
                    
            return f"Text extraction not available for {file_ext} files"
            
        except Exception as e:
            logger.error(f"Fallback text extraction failed for {file_path}: {e}")
            return "Text extraction failed"

    
    def _get_document_path(self, temp_document_id: str) -> str:
        """Get the file path for a temporary document. FIXED: Now searches by actual filename pattern."""
        try:
            if not temp_document_id:
                raise ValueError("temp_document_id cannot be empty")
                
            # First, try to get the document info from database to get the actual file path
            # This requires querying all temp documents to find the one with matching temp_document_id
            try:
                # Search through temp_uploads directory structure for the file
                # Since files are saved as {original_filename}.pdf, we need to find the right file
                
                for root, dirs, files in os.walk(self.upload_folder):
                    for file in files:
                        file_path = os.path.join(root, file)
                        # Check if this file belongs to our temp_document_id
                        # We'll need to check the database record to match filename to temp_document_id
                        if os.path.isfile(file_path):
                            # Check if this could be our file by examining the directory structure
                            # temp_uploads/{user_id}/{project_id}/{original_filename}.pdf
                            relative_path = os.path.relpath(file_path, self.upload_folder)
                            path_parts = relative_path.split(os.sep)
                            
                            if len(path_parts) >= 3:  # user_id/project_id/filename
                                user_id_dir = path_parts[0]
                                project_id_dir = path_parts[1]
                                filename = path_parts[2]
                                
                                # Try to get temp document from database to verify
                                try:
                                    temp_doc = self.db_manager.get_temp_document(
                                        temp_document_id, project_id_dir, user_id_dir
                                    )
                                    if temp_doc and temp_doc.get('original_filename') == filename:
                                        return file_path
                                except:
                                    continue  # Try next file
                                    
            except Exception as search_error:
                logger.error(f"Error searching for document {temp_document_id}: {search_error}")
                
            logger.warning(f"Document path not found for {temp_document_id}")
            return ""
            
        except Exception as e:
            logger.error(f"Error getting document path for {temp_document_id}: {e}")
            return ""

    def _get_document_path_from_db(self, temp_document_id: str, project_id: str, user_id: str) -> str:
        """Get document path using database information. More efficient alternative."""
        try:
            # Get temp document from database
            temp_doc = self.db_manager.get_temp_document(temp_document_id, project_id, user_id)
            
            if not temp_doc:
                logger.warning(f"Temp document {temp_document_id} not found in database")
                return ""
                
            # Check if file_path is stored in database
            if temp_doc.get('file_path') and os.path.exists(temp_doc['file_path']):
                return temp_doc['file_path']
                
            # Fallback: construct path based on current naming convention
            original_filename = temp_doc.get('original_filename')
            if original_filename:
                # Construct expected path: temp_uploads/{user_id}/{project_id}/{original_filename}
                expected_path = os.path.join(self.upload_folder, user_id, project_id, original_filename)
                
                if os.path.exists(expected_path):
                    return expected_path
                else:
                    logger.warning(f"Expected file not found: {expected_path}")
                    
            return ""
            
        except Exception as e:
            logger.error(f"Error getting document path from database: {e}")
            return ""

    def _verify_document_exists(self, temp_document_id: str, project_id: str = None, user_id: str = None) -> bool:
        """Verify document exists and is accessible. FIXED: Enhanced with better path resolution."""
        try:
            if not temp_document_id or not isinstance(temp_document_id, str):
                logger.warning("Invalid temp_document_id provided for verification")
                return False
                
            # If we have project_id and user_id, use more efficient database lookup
            if project_id and user_id:
                file_path = self._get_document_path_from_db(temp_document_id, project_id, user_id)
            else:
                # Fallback to searching filesystem
                file_path = self._get_document_path(temp_document_id)
            
            if not file_path:
                logger.warning(f"No file path found for document {temp_document_id}")
                return False
                
            # Check if file exists and is readable
            if not os.path.exists(file_path):
                logger.warning(f"Document file does not exist: {file_path}")
                return False
                
            if not os.path.isfile(file_path):
                logger.warning(f"Document path is not a file: {file_path}")
                return False
                
            # Check file is readable and not empty
            try:
                file_size = os.path.getsize(file_path)
                if file_size == 0:
                    logger.warning(f"Document file is empty: {file_path}")
                    return False
                    
                with open(file_path, 'rb') as f:
                    # Try to read first byte to verify readability
                    f.read(1)
                return True
            except Exception as read_error:
                logger.error(f"Cannot read document file {file_path}: {read_error}")
                return False
                
        except Exception as e:
            logger.error(f"Error verifying document {temp_document_id}: {e}")
            return False

    def save_temp_document(self, file_path: str, project_id: str, user_id: str, source:str) -> Dict[str, Any]:
        """Save uploaded file to temporary location and create database entry. FIXED: Consistent file naming."""
        try:
            # Input validation
            if not file_path or not os.path.exists(file_path):
                raise ValidationError(f"File not found: {file_path}")
                
            if not project_id or not isinstance(project_id, str):
                raise ValidationError("Invalid project_id provided")
                
            if not user_id or not isinstance(user_id, str):
                raise ValidationError("Invalid user_id provided")

            # Get file information
            original_filename = os.path.basename(file_path)
            file_size = os.path.getsize(file_path)
            mime_type = mimetypes.guess_type(file_path)[0] or "application/octet-stream"

            # Validate file
            self.validate_file(original_filename, file_size)

            # Generate temp document ID
            temp_document_id = str(uuid.uuid4())

            logger.info(f"Saving temp document: {original_filename} ({file_size:,} bytes)")

            # Extract text preview with error handling
            try:
                text_preview = self.extract_text_preview(file_path)
            except Exception as e:
                logger.warning(f"Failed to extract text preview for {original_filename}: {e}")
                text_preview = f"Text preview unavailable: {str(e)}"

            # Create directory structure
            temp_file_dir = os.path.join(self.upload_folder, user_id, project_id)
            os.makedirs(temp_file_dir, exist_ok=True)
            
            # FIXED: Use original filename directly (no timestamp or temp_document_id prefix)
            # This matches what the user described: files saved as {original_filename}.pdf
            temp_file_path = os.path.join(temp_file_dir, original_filename)
            
            # Handle duplicate filenames by adding a counter if needed
            counter = 1
            base_name = Path(original_filename).stem
            extension = Path(original_filename).suffix
            
            while os.path.exists(temp_file_path):
                new_filename = f"{base_name}_{counter}{extension}"
                temp_file_path = os.path.join(temp_file_dir, new_filename)
                counter += 1
                if counter > 1:  # Update original_filename if we had to modify it
                    original_filename = new_filename
            
            # Copy file to temp location
            shutil.copy2(file_path, temp_file_path)

            # Create temp document structure
            temp_doc = {
                'temp_document_id': temp_document_id,
                'project_id': project_id,
                'user_id': user_id,
                'original_filename': original_filename,
                'source': source,
                'file_path': temp_file_path,  # Store actual path where file is saved
                'file_size': file_size,
                'mime_type': mime_type,
                'text_preview': text_preview,
                'status': 'UPLOADED',
                'upload_timestamp': datetime.utcnow()
            }

            # Save to database
            db_result = self.db_manager.create_temp_document(**temp_doc)
            
            if not db_result:
                # Cleanup temp file if database save failed
                try:
                    os.remove(temp_file_path)
                except:
                    pass
                raise FileProcessingError("Failed to save document to database")

            logger.info(f"Successfully saved temp document: {original_filename} at {temp_file_path}")
            return temp_doc

        except ValidationError:
            raise  # Re-raise validation errors
        except Exception as e:
            logger.error(f"Error saving temp document {file_path}: {e}")
            raise FileProcessingError(f"Failed to save temp document: {e}", filepath=file_path)

    def process_document_batch(self, project_id: str, user_id: str,
                         document_data: List[Dict[str, Any]]) -> str:
        """ 
        Process a batch of documents with comprehensive validation, error handling, and status tracking.
        
        Args:
            project_id: The project ID to associate documents with
            user_id: The user ID who owns the documents
            document_data: List of document dictionaries containing temp_document_id and metadata
            
        Returns:
            str: Batch ID for tracking processing status
            
        Raises:
            ValidationError: If input validation fails
            FileProcessingError: If batch creation or document processing fails
        """
        batch_id = str(uuid.uuid4())
        
        try:
            logger.info(f"Starting batch processing: {batch_id}")
            start_time = time.time()
            
            # === INPUT VALIDATION ===
            if not project_id or not isinstance(project_id, str):
                raise ValidationError("Invalid project_id provided - must be non-empty string")
                
            if not user_id or not isinstance(user_id, str):
                raise ValidationError("Invalid user_id provided - must be non-empty string")
                
            # Validate project_id and user_id formats
            try:
                # Try to convert to expected types for validation
                project_id_int = int(project_id)
                user_id_uuid = uuid.UUID(user_id)
            except (ValueError, TypeError) as e:
                raise ValidationError(f"Invalid ID format - project_id: {project_id}, user_id: {user_id}: {e}")
                
            # === DOCUMENT DATA NORMALIZATION ===
            logger.debug(f"Received document_data type: {type(document_data)}")
            logger.debug(f"Document_data content preview: {str(document_data)[:500]}...")
            
            # Handle single document case - convert dict to list
            if isinstance(document_data, dict):
                document_data = [document_data]
                logger.info("Converted single document to batch format")
            
            # Validate document_data is a list
            if not isinstance(document_data, list):
                raise ValidationError(f"document_data must be a list or dict, got {type(document_data)}")
                
            if not document_data:
                raise ValidationError("No documents provided for processing")
                
            if len(document_data) > 100:  # Reasonable batch size limit
                raise ValidationError(f"Batch size too large: {len(document_data)} documents (max: 100)")

            logger.info(f"Processing batch with {len(document_data)} documents")

            # === DOCUMENT VALIDATION AND FILTERING ===
            valid_documents = []
            invalid_documents = []
            validation_errors = []
            
            for i, doc_data in enumerate(document_data):
                doc_validation_start = time.time()
                
                try:
                    # Check if document data is a dictionary
                    if not isinstance(doc_data, dict):
                        error_msg = f"Document {i} is not a dictionary: {type(doc_data)}"
                        logger.error(error_msg)
                        invalid_documents.append({'index': i, 'error': error_msg, 'data': str(doc_data)})
                        validation_errors.append(error_msg)
                        continue
                    
                    # Extract and validate temp_document_id
                    temp_doc_id = doc_data.get('temp_document_id')
                    if not temp_doc_id or not isinstance(temp_doc_id, str):
                        error_msg = f"Document {i} missing or invalid temp_document_id: {temp_doc_id}"
                        logger.error(error_msg)
                        invalid_documents.append({'index': i, 'error': error_msg, 'data': doc_data})
                        validation_errors.append(error_msg)
                        continue
                    
                    # Validate temp_document_id format (should be UUID)
                    try:
                        uuid.UUID(temp_doc_id)
                    except ValueError:
                        error_msg = f"Document {i} has invalid UUID format for temp_document_id: {temp_doc_id}"
                        logger.error(error_msg)
                        invalid_documents.append({'index': i, 'error': error_msg, 'data': doc_data})
                        validation_errors.append(error_msg)
                        continue
                        
                    # Verify document exists and is accessible
                    logger.debug(f"Verifying document {i}: {temp_doc_id}")
                    if not self._verify_document_exists(temp_doc_id, project_id, user_id):
                        error_msg = f"Document {i} not found or inaccessible: {temp_doc_id}"
                        logger.warning(error_msg)
                        invalid_documents.append({'index': i, 'error': error_msg, 'data': doc_data})
                        validation_errors.append(error_msg)
                        continue
                    
                    # Validate and set default values for optional fields
                    validated_doc = {
                        'temp_document_id': temp_doc_id,
                        'source':str(doc_data.get('source', '')).strip(),
                        'user_purpose_note': str(doc_data.get('user_purpose_note', '')).strip(),
                        'document_priority': doc_data.get('document_priority', 'Medium'),
                        'ai_classification': str(doc_data.get('ai_classification', 'Generic Document')).strip(),
                        'ai_purpose': str(doc_data.get('ai_purpose', 'General purpose document')).strip()
                    }
                    
                    # Validate priority
                    valid_priorities = ['Low', 'Medium', 'High', 'Critical']
                    if validated_doc['document_priority'] not in valid_priorities:
                        logger.warning(f"Invalid priority '{validated_doc['document_priority']}' for document {i}, using 'Medium'")
                        validated_doc['document_priority'] = 'Medium'
                    
                    # Validate classification and purpose are not empty
                    if not validated_doc['ai_classification']:
                        validated_doc['ai_classification'] = 'Generic Document'
                        logger.warning(f"Empty AI classification for document {i}, using default")
                        
                    if not validated_doc['ai_purpose']:
                        validated_doc['ai_purpose'] = 'General purpose document'
                        logger.warning(f"Empty AI purpose for document {i}, using default")
                    
                    # Add validation timestamp
                    validated_doc['validated_at'] = datetime.utcnow().isoformat()
                    validated_doc['original_index'] = i
                    
                    valid_documents.append(validated_doc)
                    
                    logger.debug(f"Document {i} validated successfully in {time.time() - doc_validation_start:.3f}s")
                    
                except Exception as doc_error:
                    error_msg = f"Error validating document {i}: {str(doc_error)}"
                    logger.error(error_msg)
                    invalid_documents.append({'index': i, 'error': error_msg, 'data': doc_data, 'exception': str(doc_error)})
                    validation_errors.append(error_msg)
                    continue

            # === VALIDATION RESULTS ===
            total_documents = len(document_data)
            valid_count = len(valid_documents)
            invalid_count = len(invalid_documents)
            
            logger.info(f"Batch {batch_id} validation complete: {valid_count} valid, {invalid_count} invalid documents")
            
            # Check if we have any valid documents
            if valid_count == 0:
                error_summary = f"No valid documents found for processing. Total provided: {total_documents}, Invalid: {invalid_count}"
                if validation_errors:
                    error_summary += f"\nValidation errors: {'; '.join(validation_errors[:5])}"  # Show first 5 errors
                    if len(validation_errors) > 5:
                        error_summary += f" ... and {len(validation_errors) - 5} more errors"
                
                logger.error(error_summary)
                raise ValidationError(error_summary)

            # Log validation summary
            if invalid_count > 0:
                logger.warning(f"Batch {batch_id}: {invalid_count} documents failed validation and will be skipped")
                for invalid_doc in invalid_documents[:3]:  # Log first 3 invalid documents
                    logger.warning(f"Invalid document {invalid_doc['index']}: {invalid_doc['error']}")

            # === DATABASE BATCH CREATION ===
            try:
                logger.info(f"Creating batch record in database: {batch_id}")
                batch_creation_start = time.time()
                
                batch_result = self.db_manager.create_processing_batch(
                    batch_id=batch_id, 
                    project_id=project_id, 
                    user_id=user_id, 
                    total_documents=valid_count
                )
                
                if not batch_result:
                    raise FileProcessingError("Failed to create batch record in database - no result returned")
                    
                logger.info(f"Batch record created successfully in {time.time() - batch_creation_start:.3f}s")
                    
            except Exception as db_error:
                error_msg = f"Database error creating batch {batch_id}: {str(db_error)}"
                logger.error(error_msg)
                
                # Enhanced error logging
                import traceback
                logger.error(f"Database error traceback: {traceback.format_exc()}")
                
                raise FileProcessingError(f"Failed to create batch record: {db_error}")

            # === INITIALIZE BATCH STATUS ===
            try:
                with self._processing_lock:
                    self.batch_status[batch_id] = {
                        'status': 'PROCESSING',
                        'total_documents': valid_count,
                        'processed_documents': 0,
                        'failed_documents': 0,
                        'created_at': datetime.utcnow().isoformat(),
                        'project_id': project_id,
                        'user_id': user_id,
                        'invalid_documents_count': invalid_count,
                        'validation_time': time.time() - start_time
                    }

                # Update database batch status
                status_update_success = self.db_manager.update_batch_status(
                    batch_id=batch_id, 
                    status='PROCESSING',
                    processed_documents=0,
                    failed_documents=0
                )
                
                if not status_update_success:
                    logger.warning(f"Failed to update batch status in database for {batch_id}")

            except Exception as status_error:
                logger.error(f"Error initializing batch status for {batch_id}: {status_error}")
                # Continue processing even if status initialization fails

            # === CREATE AND QUEUE PROCESSING TASKS ===
            tasks_added = 0
            task_creation_errors = []
            
            logger.info(f"Creating processing tasks for {valid_count} documents")
            task_creation_start = time.time()
            
            for doc_data in valid_documents:
                try:
                    # Create comprehensive task object
                    task = {
                        'batch_id': batch_id,
                        'project_id': project_id,
                        'user_id': user_id,
                        'source': doc_data['source'],
                        'temp_document_id': doc_data['temp_document_id'],
                        'ai_classification': doc_data['ai_classification'],
                        'ai_purpose': doc_data['ai_purpose'],
                        'user_purpose_note': doc_data['user_purpose_note'],
                        'document_priority': doc_data['document_priority'],
                        'created_at': datetime.utcnow().isoformat(),
                        'original_index': doc_data['original_index'],
                        'validated_at': doc_data['validated_at']
                    }
                    
                    # Add task to processing queue
                    self.processing_queue.put(task)
                    tasks_added += 1
                    
                    logger.debug(f"Queued task for document: {doc_data['temp_document_id']} (index: {doc_data['original_index']})")
                    
                except Exception as task_error:
                    error_msg = f"Error creating task for document {doc_data.get('temp_document_id', 'unknown')}: {str(task_error)}"
                    logger.error(error_msg)
                    task_creation_errors.append(error_msg)
                    
                    # Update failure count in batch status
                    try:
                        with self._processing_lock:
                            if batch_id in self.batch_status:
                                self.batch_status[batch_id]['failed_documents'] += 1
                    except:
                        pass

            task_creation_time = time.time() - task_creation_start
            
            # === FINAL VALIDATION ===
            if tasks_added == 0:
                error_msg = f"No tasks could be created for batch {batch_id}"
                if task_creation_errors:
                    error_msg += f". Errors: {'; '.join(task_creation_errors)}"
                
                logger.error(error_msg)
                
                # Cleanup batch status
                try:
                    with self._processing_lock:
                        if batch_id in self.batch_status:
                            del self.batch_status[batch_id]
                    
                    # Update database batch status to failed
                    self.db_manager.update_batch_status(batch_id, 'FAILED', error_details=error_msg)
                except:
                    pass
                    
                raise FileProcessingError(error_msg)

            # === SUCCESS LOGGING ===
            total_time = time.time() - start_time
            
            logger.info(f"Batch {batch_id} created successfully:")
            logger.info(f"  - Total documents processed: {total_documents}")
            logger.info(f"  - Valid documents: {valid_count}")
            logger.info(f"  - Invalid documents: {invalid_count}")
            logger.info(f"  - Tasks queued: {tasks_added}")
            logger.info(f"  - Processing time: {total_time:.3f}s")
            logger.info(f"  - Task creation time: {task_creation_time:.3f}s")


            
            if task_creation_errors:
                logger.warning(f"  - Task creation errors: {len(task_creation_errors)}")

            # === QUEUE STATUS LOGGING ===
            try:
                queue_size = self.processing_queue.qsize()
                logger.info(f"Processing queue size after batch creation: {queue_size}")
            except:
                pass  # qsize() might not be available on all platforms

            return batch_id

        except ValidationError:
            # Re-raise validation errors without modification
            logger.error(f"Validation error in batch creation: {str(sys.exc_info()[1])}")
            raise
            
        except FileProcessingError:
            # Re-raise file processing errors without modification
            logger.error(f"File processing error in batch creation: {str(sys.exc_info()[1])}")
            raise
            
        except Exception as e:
            # Handle unexpected errors
            error_msg = f"Unexpected error creating batch: {str(e)}"
            logger.error(error_msg)
            
            # Enhanced error logging
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            
            # Cleanup batch status if it was created
            try:
                with self._processing_lock:
                    if batch_id in self.batch_status:
                        del self.batch_status[batch_id]
            except:
                pass
                
            # Try to update database batch status to failed
            try:
                self.db_manager.update_batch_status(batch_id, 'FAILED', error_details=error_msg)
            except:
                pass
                
            raise FileProcessingError(error_msg)
        else:
            #delete processed documents
            for i, doc_data in enumerate(document_data):
                    # Extract and validate temp_document_id
                    temp_doc_id = doc_data.get('temp_document_id')
                    self.db_manager.delete_temp_document(temp_doc_id)


    def get_ai_suggestions(self, temp_document_id: str,source: str, project_id: str, user_id: str) -> Dict[str, Any]:
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
                    'text_preview': text_preview[:1000] + ('...' if len(text_preview) > 1000 else ''),  # Limit preview size
                    'confidence': 'medium',  # Could be enhanced with actual confidence scoring
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
            raise  # Re-raise validation errors
        except Exception as e:
            logger.error(f"Error getting AI suggestions for {temp_document_id}: {e}")
            raise FileProcessingError(f"Failed to get AI suggestions: {e}")


    def _process_document_task(self, task: Dict[str, Any]):
        """Process a single document task with enhanced error handling and status tracking."""
        batch_id = task.get('batch_id')
        temp_document_id = task.get('temp_document_id')
        
        try:
            logger.info(f"Processing document task: {temp_document_id} in batch {batch_id}")
            
            # Validate task data
            required_fields = ['batch_id', 'project_id', 'user_id', 'temp_document_id']
            for field in required_fields:
                if not task.get(field):
                    raise ValidationError(f"Missing required field: {field}")

            # Process the document
            self._process_single_document(task)

            # Update batch progress on success
            with self._processing_lock:
                if batch_id in self.batch_status:
                    self.batch_status[batch_id]['processed_documents'] += 1
                    
                    # Check if batch is complete
                    batch = self.batch_status[batch_id]
                    total_processed = batch['processed_documents'] + batch['failed_documents']
                    
                    if total_processed >= batch['total_documents']:
                        batch['status'] = 'COMPLETED'
                        batch['completed_at'] = datetime.utcnow().isoformat()
                        logger.info(f"Batch {batch_id} completed")

            # Update database batch progress
            self.db_manager.increment_batch_progress(batch_id, success=True)

            logger.info(f"Successfully processed document {temp_document_id} in batch {batch_id}")

        except Exception as e:
            logger.error(f"Error processing document task {temp_document_id}: {e}")
            
            # Update batch status for failure
            with self._processing_lock:
                if batch_id in self.batch_status:
                    self.batch_status[batch_id]['failed_documents'] += 1
                    
                    # Check if batch should be marked as failed
                    batch = self.batch_status[batch_id]
                    if batch['failed_documents'] >= batch['total_documents']:
                        batch['status'] = 'FAILED'
                        batch['completed_at'] = datetime.utcnow().isoformat()
                        logger.error(f"Batch {batch_id} failed - all documents failed")

            # Update database batch progress
            self.db_manager.increment_batch_progress(batch_id, success=False)
            
            # Don't re-raise the exception to prevent stopping the processing thread

    def _process_single_document(self, task: Dict[str, Any]):
        """Process a single document with comprehensive error handling and cleanup."""
        temp_document_id = task['temp_document_id']
        project_id = task['project_id']
        user_id = task['user_id']
        batch_id = task['batch_id']

        temp_file_path = None
        dest_path = None

        try:
            logger.info(f"Processing single document: {temp_document_id}")

            # Get temp document from database
            temp_doc = self.db_manager.get_temp_document(temp_document_id, project_id, user_id)

            if not temp_doc:
                raise FileProcessingError(f"Temp document {temp_document_id} not found in database")
            
            # Extract document information
            original_filename = temp_doc['original_filename']
            temp_file_path = temp_doc['file_path']
            file_size = temp_doc.get('file_size', 0)
            mime_type = temp_doc.get('mime_type', 'application/octet-stream')
            text_preview = temp_doc.get('text_preview', '')
            ai_purpose =  temp_doc.get('ai_purpose', task['ai_purpose'])
            source =  task['source']

            # Validate file exists
            if not temp_file_path or not os.path.exists(temp_file_path):
                raise FileProcessingError(f"Temp file not found: {temp_file_path}")

            # Determine category folder based on AI classification
            category_folder = temp_doc.get('ai_classification',task['ai_classification'])

            # Prepare destination
            dest_dir = os.path.join(self.processed_folder, category_folder)
            os.makedirs(dest_dir, exist_ok=True)

            # Create unique destination filename to prevent conflicts
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            base_name = Path(original_filename).stem
            extension = Path(original_filename).suffix
            unique_filename = f"{timestamp}_{base_name}{extension}"
            dest_path = os.path.join(dest_dir, unique_filename)

            # Copy file to final location with verification
            try:
                shutil.copy2(temp_file_path, dest_path)
                
                # Verify copy was successful
                if not os.path.exists(dest_path):
                    raise FileProcessingError("File copy verification failed")
                    
                copied_size = os.path.getsize(dest_path)
                if copied_size != file_size:
                    logger.warning(f"File size mismatch after copy: {copied_size} vs {file_size}")
                    
            except Exception as copy_error:
                raise FileProcessingError(f"Failed to copy file to destination: {copy_error}")

            # Create document metadata
            document_id = uuid.uuid4()
            metadata_filename = f"{Path(unique_filename).stem}_metadata.json"
            metadata_path = os.path.join(dest_dir, metadata_filename)

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
                    storagePath=dest_path,
                    categoryFolder=category_folder,
                    storedFilename=unique_filename,  # Store actual filename, not metadata filename
                    savedAt=datetime.now().isoformat()
                )

                # Convert user_id and project_id to proper types for database
                try:
                    user_uuid = uuid.UUID(user_id) if isinstance(user_id, str) else user_id
                except ValueError:
                    raise FileProcessingError(f"Invalid user_id format: {user_id}")

                try:
                    project_int = int(project_id) if isinstance(project_id, str) else project_id
                except (ValueError, TypeError):
                    raise FileProcessingError(f"Invalid project_id format: {project_id}")

                # Create document in database
                document = self.db_manager.create_document(
                    id=document_id,
                    source=source,
                    original_filename=original_filename,
                    file_size=file_size,
                    file_mime_type=mime_type,
                    storage_path=dest_path,
                    category_folder=category_folder,
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

                # Update master metadata
                self.metadata_manager.update_master_metadata(doc_meta)

                logger.info(f"Successfully processed document: {original_filename}")

            except Exception as db_error:
                logger.error(f"Database/metadata error for {original_filename}: {db_error}")
                
                # Cleanup destination file if database operation failed
                try:
                    if dest_path and os.path.exists(dest_path):
                        os.remove(dest_path)
                        logger.info(f"Cleaned up destination file after database error: {dest_path}")
                except:
                    logger.warning(f"Failed to cleanup destination file: {dest_path}")
                    
                raise FileProcessingError(f"Failed to save document metadata: {db_error}")

            # Clean up temp document and file (only after successful processing)
            try:
                # Remove temp file
                if temp_file_path and os.path.exists(temp_file_path):
                    os.remove(temp_file_path)
                    logger.debug(f"Removed temp file: {temp_file_path}")

                # Remove temp document from database
                self.db_manager.delete_temp_document(temp_document_id, user_id, cleanup_file=False)
                logger.debug(f"Removed temp document from database: {temp_document_id}")

            except Exception as cleanup_error:
                logger.warning(f"Cleanup error for {temp_document_id}: {cleanup_error}")
                # Don't fail the entire process for cleanup errors
            
            # Summarization
            try:
                summarization_service = SummarizationService()
                summary = summarization_service.summarize_document(doc_meta)
                if summary:
                    # Save summary to database
                    self.db_manager.save_summary(
                        document_id=document_id,
                        summary_data=summary,
                    )
                    logger.info(f"Successfully generated and saved summary for document: {original_filename}")
            except Exception as e:
                logger.error(f"Error during summarization for document {original_filename}: {e}")


            # Chunking
            try:
                parsed_blocks, _ = self.document_processor.process_single_file(
                    file_path=dest_path,
                    document_id=document_id,
                    project_id=project_id
                )
                chunks = chunk_document_adaptive(
                    parsed_blocks=parsed_blocks,
                    document_id=document_id,
                    project_id=project_id,
                    document_type=doc_meta.finalCategory,
                    openai_api_key=config.OPENAI_API_KEY
                )
                if chunks:
                    # Save chunks to database
                    self.db_manager.save_chunks(
                        document_id=document_id,
                        chunks=chunks,
                    )
                    logger.info(f"Successfully chunked and saved document: {original_filename}")
            except Exception as e:
                logger.error(f"Error during chunking for document {original_filename}: {e}")


            logger.info(f"Document processing completed successfully: {original_filename}")

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

    def _get_category_folder(self, ai_classification: str) -> str:
        """Get category folder based on AI classification with enhanced mapping and validation."""
        try:
            if not ai_classification or not isinstance(ai_classification, str):
                logger.warning(f"Invalid AI classification: {ai_classification}")
                return "39. Generic Text Document"

            # Normalize classification for comparison
            classification_lower = ai_classification.lower().strip()

            # Enhanced category mapping with more specific patterns
            category_mappings = {
                "strategy": "1. Strategy Document/Deck",
                "financial": "2. Financial Document", 
                "legal": "3. Legal Document",
                "technical": "4. Technical Document",
                "marketing": "5. Marketing Document",
                "research": "6. Research Document",
                "project management": "7. Project Management Document",
                "business plan": "1. Strategy Document/Deck",
                "contract": "3. Legal Document",
                "agreement": "3. Legal Document",
                "invoice": "2. Financial Document",
                "budget": "2. Financial Document",
                "proposal": "5. Marketing Document",
                "specification": "4. Technical Document",
                "manual": "4. Technical Document",
                "report": "6. Research Document",
                "analysis": "6. Research Document"
            }

            # Find matching category
            for keyword, folder in category_mappings.items():
                if keyword in classification_lower:
                    logger.debug(f"Mapped '{ai_classification}' to '{folder}' via keyword '{keyword}'")
                    return folder

            # Default category
            default_category = "39. Generic Text Document"
            logger.debug(f"Using default category for '{ai_classification}': {default_category}")
            return default_category

        except Exception as e:
            logger.error(f"Error determining category folder for '{ai_classification}': {e}")
            return "39. Generic Text Document"

    def get_batch_status(self, batch_id: str, user_id: str = None) -> Dict[str, Any]:
        """Get batch processing status with enhanced information and validation."""
        try:
            # Input validation
            if not batch_id or not isinstance(batch_id, str):
                return {
                    'success': False,
                    'error': 'Invalid batch_id provided',
                    'batch_id': batch_id
                }

            logger.debug(f"Getting batch status for: {batch_id}")

            # Get status from database first
            try:
                batch_info = self.db_manager.get_batch_status(batch_id, user_id)
                
                if batch_info:
                    # Merge with in-memory status if available
                    with self._processing_lock:
                        if batch_id in self.batch_status:
                            memory_status = self.batch_status[batch_id]
                            # Update database info with more current memory info
                            batch_info.update({
                                'processed_documents': memory_status.get('processed_documents', 
                                                                       batch_info.get('processed_documents', 0)),
                                'failed_documents': memory_status.get('failed_documents', 
                                                                    batch_info.get('failed_documents', 0)),
                                'status': memory_status.get('status', batch_info.get('status', 'UNKNOWN'))
                            })
                    
                    # Calculate additional metrics
                    total_docs = batch_info.get('total_documents', 0)
                    processed_docs = batch_info.get('processed_documents', 0)
                    failed_docs = batch_info.get('failed_documents', 0)
                    
                    progress_percentage = 0
                    if total_docs > 0:
                        progress_percentage = ((processed_docs + failed_docs) / total_docs) * 100
                    
                    return {
                        'success': True,
                        'batch_id': batch_id,
                        **batch_info,
                        'progress_percentage': round(progress_percentage, 2),
                        'remaining_documents': max(0, total_docs - processed_docs - failed_docs),
                        'is_complete': (processed_docs + failed_docs) >= total_docs and total_docs > 0,
                        'retrieved_from': 'database'
                    }
                    
            except Exception as db_error:
                logger.warning(f"Database error getting batch status: {db_error}")

            # Fallback to in-memory status
            with self._processing_lock:
                if batch_id in self.batch_status:
                    memory_status = self.batch_status[batch_id].copy()
                    
                    # Calculate progress
                    total_docs = memory_status.get('total_documents', 0)
                    processed_docs = memory_status.get('processed_documents', 0)
                    failed_docs = memory_status.get('failed_documents', 0)
                    
                    progress_percentage = 0
                    if total_docs > 0:
                        progress_percentage = ((processed_docs + failed_docs) / total_docs) * 100
                    
                    return {
                        'success': True,
                        'batch_id': batch_id,
                        **memory_status,
                        'progress_percentage': round(progress_percentage, 2),
                        'remaining_documents': max(0, total_docs - processed_docs - failed_docs),
                        'is_complete': (processed_docs + failed_docs) >= total_docs and total_docs > 0,
                        'retrieved_from': 'memory'
                    }

            # Batch not found
            return {
                'success': False,
                'error': 'Batch not found',
                'batch_id': batch_id,
                'retrieved_from': 'none'
            }

        except Exception as e:
            logger.error(f"Error getting batch status for {batch_id}: {e}")
            return {
                'success': False,
                'error': f'Error retrieving batch status: {e}',
                'batch_id': batch_id
            }

    def cleanup_completed_batches(self, max_age_hours: int = 24) -> int:
        """Clean up old completed batch status entries from memory."""
        try:
            if max_age_hours <= 0:
                max_age_hours = 24
                
            cutoff_time = datetime.utcnow().timestamp() - (max_age_hours * 3600)
            cleaned_count = 0
            
            with self._processing_lock:
                batches_to_remove = []
                
                for batch_id, status in self.batch_status.items():
                    # Check if batch is completed and old enough
                    if status.get('status') in ['COMPLETED', 'FAILED']:
                        created_at = status.get('created_at')
                        if created_at:
                            try:
                                created_timestamp = datetime.fromisoformat(created_at.replace('Z', '+00:00')).timestamp()
                                if created_timestamp < cutoff_time:
                                    batches_to_remove.append(batch_id)
                            except:
                                # If we can't parse the date, remove it anyway
                                batches_to_remove.append(batch_id)
                
                # Remove old batches
                for batch_id in batches_to_remove:
                    del self.batch_status[batch_id]
                    cleaned_count += 1
                    
            if cleaned_count > 0:
                logger.info(f"Cleaned up {cleaned_count} old batch status entries")
                
            return cleaned_count
            
        except Exception as e:
            logger.error(f"Error cleaning up completed batches: {e}")
            return 0

    def shutdown(self):
        """Gracefully shutdown the document upload service."""
        try:
            logger.info("Shutting down DocumentUploadService...")
            
            # Signal background thread to stop
            self._shutdown_event.set()
            
            # Add shutdown signal to queue
            self.processing_queue.put(None)
            
            # Wait for background thread to finish (with timeout)
            if hasattr(self, 'background_thread') and self.background_thread.is_alive():
                self.background_thread.join(timeout=30)
                if self.background_thread.is_alive():
                    logger.warning("Background thread did not shutdown gracefully")
            
            # Clean up any remaining batch statuses
            with self._processing_lock:
                remaining_batches = len(self.batch_status)
                if remaining_batches > 0:
                    logger.info(f"Clearing {remaining_batches} remaining batch status entries")
                self.batch_status.clear()
            
            logger.info("DocumentUploadService shutdown complete")
            
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")

    def __del__(self):
        """Destructor to ensure proper cleanup."""
        try:
            self.shutdown()
        except:
            pass  # Don't raise exceptions in destructor