"""
Unified database manager using SQLAlchemy ORM for all database operations.
"""
import logging
from typing import Optional, List, Dict, Any, Union
from datetime import datetime, timezone
from contextlib import contextmanager
from sqlalchemy import and_, or_, desc
from sqlalchemy.exc import SQLAlchemyError
import uuid
import os
from utils.database import SessionLocal, engine
from models.database_models import (
    OnboardingGuide, User, Project, Document, DocumentChunk, DocumentSummary
)
from utils.exceptions import DatabaseError, ValidationError, NotFoundError

logger = logging.getLogger(__name__)

class DatabaseManager:
    """
    Unified database manager using SQLAlchemy ORM for efficient database operations.

    Features:
    - Connection pooling and session management
    - Optimized queries with eager loading
    - Transaction management
    - Error handling and logging
    - Type safety and validation
    """

    def __init__(self):
        self.engine = engine

    @contextmanager
    def get_session(self):
        """Get database session with automatic cleanup and improved error handling."""
        session = SessionLocal()
        try:
            yield session
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"Session error: {e}")
            raise
        finally:
            session.close()

    # Project Operations
    def create_processing_batch(self, batch_id: str, project_id: Union[int, str],
                          user_id: Union[str, uuid.UUID], total_documents: int) -> Optional[Dict[str, Any]]:
        """Create a new processing batch record with enhanced validation and error handling."""
        try:
            # Input validation
            if not batch_id or not batch_id.strip():
                raise ValidationError("Batch ID cannot be empty")

            if total_documents < 0:
                raise ValidationError("Total documents cannot be negative")

            with self.get_session() as session:
                from models.database_models import ProcessingBatch

                # Convert user_id to UUID if it's a string
                if isinstance(user_id, str):
                    try:
                        user_id = uuid.UUID(user_id)
                    except ValueError as e:
                        logger.error(f"Invalid UUID format for user_id: {user_id}")
                        raise ValidationError(f"Invalid user_id format: {user_id}")

                # Ensure project_id is an integer
                if isinstance(project_id, str):
                    try:
                        project_id = int(project_id)
                    except ValueError as e:
                        logger.error(f"Invalid project_id format: {project_id}")
                        raise ValidationError(f"Invalid project_id format: {project_id}")

                # Check for duplicate batch_id
                existing_batch = session.query(ProcessingBatch).filter(
                    ProcessingBatch.batch_id == batch_id.strip()
                ).first()

                if existing_batch:
                    raise ValidationError(f"Batch with ID {batch_id} already exists")

                # Verify user exists and is active
                user = session.query(User).filter(
                    and_(User.id == user_id, User.is_active == True)
                ).first()
                if not user:
                    raise ValidationError(f"User with ID {user_id} not found or inactive")

                # Verify project exists and is active
                project = session.query(Project).filter(
                    and_(Project.id == project_id, Project.is_active == True)
                ).first()
                if not project:
                    raise ValidationError(f"Project with ID {project_id} not found or inactive")

                # Verify user has access to the project
                if project.owner_id != user_id:
                    raise ValidationError(f"User {user_id} does not have access to project {project_id}")

                # Create batch with actual valid document count
                processing_batch = ProcessingBatch(
                    batch_id=batch_id.strip(),
                    project_id=project_id,
                    user_id=user_id,
                    total_documents=total_documents,
                    status='QUEUED',
                    created_at=datetime.now(timezone.utc)
                )

                session.add(processing_batch)
                session.flush()  # Get the ID

                # Convert to dictionary for return
                batch_dict = {
                    'id': processing_batch.id,
                    'batch_id': processing_batch.batch_id,
                    'project_id': processing_batch.project_id,
                    'user_id': str(processing_batch.user_id),  # Convert UUID to string
                    'status': processing_batch.status,
                    'created_at': processing_batch.created_at.isoformat() if processing_batch.created_at else None,
                    'started_at': processing_batch.started_at.isoformat() if processing_batch.started_at else None,
                    'completed_at': processing_batch.completed_at.isoformat() if processing_batch.completed_at else None,
                    'total_documents': processing_batch.total_documents,
                    'processed_documents': processing_batch.processed_documents or 0,
                    'failed_documents': processing_batch.failed_documents or 0,
                    'error_details': processing_batch.error_details
                }

                logger.info(f"Created processing batch: {batch_id} with {total_documents} documents for user: {user.username}")
                return batch_dict

        except ValidationError:
            raise  # Re-raise validation errors
        except SQLAlchemyError as e:
            logger.error(f"Database error creating processing batch: {e}")
            raise DatabaseError(f"Failed to create processing batch: {e}")
        except Exception as e:
            logger.error(f"Unexpected error creating processing batch: {e}")
            raise DatabaseError(f"Unexpected error creating processing batch: {e}")

    def delete_temp_document(self, temp_document_id: str, user_id: Union[str, uuid.UUID] = None,
                        cleanup_file: bool = True) -> bool:
        """
        Delete a temporary document and optionally clean up the file with enhanced error handling.

        Args:
            temp_document_id: The temporary document ID to delete
            user_id: Optional user ID for access control (can be string UUID or UUID object)
            cleanup_file: Whether to also delete the physical file

        Returns:
            bool: True if deletion was successful, False otherwise
        """
        try:
            # Enhanced input validation
            if not temp_document_id or not isinstance(temp_document_id, str) or not temp_document_id.strip():
                logger.error("Temp document ID must be a non-empty string")
                return False

            # Validate temp_document_id is a valid UUID format
            try:
                uuid.UUID(temp_document_id.strip())
            except ValueError:
                logger.error(f"Invalid UUID format for temp_document_id: {temp_document_id}")
                return False

            with self.get_session() as session:
                from models.database_models import TempDocument

                # Convert user_id to UUID if provided and is string
                if user_id:
                    if isinstance(user_id, str):
                        try:
                            user_id = uuid.UUID(user_id)
                        except ValueError as e:
                            logger.error(f"Invalid UUID format for user_id: {user_id}")
                            return False
                    elif not isinstance(user_id, uuid.UUID):
                        logger.error(f"user_id must be string or UUID, got {type(user_id)}")
                        return False

                # Build query with optional user access control
                query = session.query(TempDocument).filter(
                    TempDocument.temp_document_id == temp_document_id.strip()
                )

                if user_id:
                    query = query.filter(TempDocument.user_id == user_id)

                temp_document = query.first()

                if not temp_document:
                    logger.warning(f"Temp document {temp_document_id} not found" +
                                (f" for user {user_id}" if user_id else ""))
                    return False

                # Store info for logging and file cleanup
                filename = temp_document.original_filename or "unknown_file"
                file_path = temp_document.file_path
                user_info = f"user {temp_document.user_id}" if temp_document.user_id else "unknown user"
                project_info = f"project {temp_document.project_id}" if temp_document.project_id else "unknown project"

                # Validate file path before attempting cleanup
                file_cleanup_success = True
                if cleanup_file and file_path:
                    if os.path.exists(file_path):
                        try:
                            # Additional safety check - ensure file is within expected directories
                            file_path_abs = os.path.abspath(file_path)

                            # Check if file is in temp_uploads or other allowed directories
                            # TODO: Update this to use blob storage
                            allowed_dirs = [
                                # os.path.abspath("temp_uploads"),
                                # os.path.abspath("data/uploaded_documents")
                            ]

                            is_safe_path = any(file_path_abs.startswith(allowed_dir) for allowed_dir in allowed_dirs)

                            if is_safe_path:
                                # Get file info before deletion
                                file_size = os.path.getsize(file_path)

                                os.remove(file_path)
                                logger.info(f"Deleted file: {file_path} ({file_size:,} bytes)")

                                # Try to remove empty parent directories
                                try:
                                    parent_dir = os.path.dirname(file_path)
                                    if os.path.exists(parent_dir) and not os.listdir(parent_dir):
                                        os.rmdir(parent_dir)
                                        logger.debug(f"Removed empty directory: {parent_dir}")

                                        # Try to remove grandparent if also empty (project directory)
                                        grandparent_dir = os.path.dirname(parent_dir)
                                        if os.path.exists(grandparent_dir) and not os.listdir(grandparent_dir):
                                            os.rmdir(grandparent_dir)
                                            logger.debug(f"Removed empty directory: {grandparent_dir}")
                                except OSError:
                                    # Directory not empty or other issue - this is fine
                                    pass

                            else:
                                logger.error(f"Refusing to delete file outside allowed directories: {file_path}")
                                file_cleanup_success = False

                        except OSError as e:
                            logger.warning(f"Failed to delete file {file_path}: {e}")
                            file_cleanup_success = False

                        except Exception as e:
                            logger.error(f"Unexpected error deleting file {file_path}: {e}")
                            file_cleanup_success = False
                    else:
                        logger.warning(f"File not found for cleanup: {file_path}")
                        # Don't consider this a failure if the file doesn't exist

                # Delete the database record
                session.delete(temp_document)
                session.flush()

                # Log success with details
                status_msg = f"Deleted temp document: {filename} (ID: {temp_document_id}) for {user_info} in {project_info}"
                if cleanup_file:
                    if file_cleanup_success:
                        status_msg += " [file cleaned up]"
                    else:
                        status_msg += " [file cleanup failed]"
                else:
                    status_msg += " [file cleanup skipped]"

                logger.info(status_msg)
                return True

        except SQLAlchemyError as e:
            logger.error(f"Database error deleting temp document {temp_document_id}: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error deleting temp document {temp_document_id}: {e}")
            import traceback
            logger.debug(f"Full traceback: {traceback.format_exc()}")
            return False

    def update_batch_status(self, batch_id: str, status: str, **kwargs) -> bool:
        """Update processing batch status and related fields with enhanced validation."""
        try:
            if not batch_id or not batch_id.strip():
                logger.error("Batch ID cannot be empty")
                return False

            valid_statuses = {'QUEUED', 'PROCESSING', 'COMPLETED', 'FAILED', 'CANCELLED'}
            if status not in valid_statuses:
                logger.error(f"Invalid status: {status}. Must be one of {valid_statuses}")
                return False

            with self.get_session() as session:
                from models.database_models import ProcessingBatch

                batch = session.query(ProcessingBatch).filter(
                    ProcessingBatch.batch_id == batch_id.strip()
                ).first()

                if not batch:
                    logger.warning(f"Processing batch {batch_id} not found")
                    return False

                # Update status
                batch.status = status

                # Update timestamps based on status
                if status == 'PROCESSING' and not batch.started_at:
                    batch.started_at = datetime.now(timezone.utc)
                elif status in ['COMPLETED', 'FAILED', 'CANCELLED'] and not batch.completed_at:
                    batch.completed_at = datetime.now(timezone.utc)

                # Update other fields if provided with validation
                allowed_fields = {'processed_documents', 'failed_documents', 'error_details'}
                for key, value in kwargs.items():
                    if key in allowed_fields and hasattr(batch, key):
                        if key in ['processed_documents', 'failed_documents'] and value is not None:
                            if not isinstance(value, int) or value < 0:
                                logger.warning(f"Invalid value for {key}: {value}")
                                continue
                        setattr(batch, key, value)

                session.flush()
                logger.info(f"Updated batch {batch_id} status to {status}")
                return True

        except SQLAlchemyError as e:
            logger.error(f"Database error updating batch status: {e}")
            return False

    def get_processing_batch(self, batch_id: str) -> Optional[Dict[str, Any]]:
        """Get processing batch by ID with enhanced validation."""
        try:
            if not batch_id or not batch_id.strip():
                logger.error("Batch ID cannot be empty")
                return None

            with self.get_session() as session:
                from models.database_models import ProcessingBatch

                batch = session.query(ProcessingBatch).filter(
                    ProcessingBatch.batch_id == batch_id.strip()
                ).first()

                if not batch:
                    return None

                return {
                    'id': batch.id,
                    'batch_id': batch.batch_id,
                    'project_id': batch.project_id,
                    'user_id': str(batch.user_id),
                    'status': batch.status,
                    'created_at': batch.created_at.isoformat() if batch.created_at else None,
                    'started_at': batch.started_at.isoformat() if batch.started_at else None,
                    'completed_at': batch.completed_at.isoformat() if batch.completed_at else None,
                    'total_documents': batch.total_documents,
                    'processed_documents': batch.processed_documents or 0,
                    'failed_documents': batch.failed_documents or 0,
                    'error_details': batch.error_details
                }

        except SQLAlchemyError as e:
            logger.error(f"Database error getting processing batch: {e}")
            return None

    def get_batch_status(self, batch_id: str, user_id: Union[str, uuid.UUID] = None) -> Optional[Dict[str, Any]]:
        """Get the current status of a processing batch with enhanced validation and calculations."""
        try:
            if not batch_id or not batch_id.strip():
                logger.error("Batch ID cannot be empty")
                return None

            with self.get_session() as session:
                from models.database_models import ProcessingBatch

                # Convert user_id to UUID if provided and is string
                if user_id and isinstance(user_id, str):
                    try:
                        user_id = uuid.UUID(user_id)
                    except ValueError as e:
                        logger.error(f"Invalid UUID format for user_id: {user_id}")
                        return None

                # Build query with optional user access control
                query = session.query(ProcessingBatch).filter(
                    ProcessingBatch.batch_id == batch_id.strip()
                )

                if user_id:
                    query = query.filter(ProcessingBatch.user_id == user_id)

                batch = query.first()

                if not batch:
                    logger.warning(f"Batch {batch_id} not found" +
                                (f" for user {user_id}" if user_id else ""))
                    return None

                # Calculate progress percentage with safe division
                total_docs = batch.total_documents or 0
                processed_docs = batch.processed_documents or 0
                failed_docs = batch.failed_documents or 0

                progress_percentage = 0
                if total_docs > 0:
                    progress_percentage = ((processed_docs + failed_docs) / total_docs) * 100

                # Determine if batch is complete
                is_complete = (processed_docs + failed_docs) >= total_docs and total_docs > 0

                # Build status dictionary
                status_dict = {
                    'id': batch.id,
                    'batch_id': batch.batch_id,
                    'project_id': batch.project_id,
                    'user_id': str(batch.user_id),
                    'status': batch.status,
                    'created_at': batch.created_at.isoformat() if batch.created_at else None,
                    'started_at': batch.started_at.isoformat() if batch.started_at else None,
                    'completed_at': batch.completed_at.isoformat() if batch.completed_at else None,
                    'total_documents': batch.total_documents,
                    'processed_documents': batch.processed_documents or 0,
                    'failed_documents': batch.failed_documents or 0,
                    'progress_percentage': round(progress_percentage, 2),
                    'is_complete': is_complete,
                    'error_details': batch.error_details
                }

                logger.info(f"Retrieved batch status for {batch_id}: {batch.status}")
                return status_dict

        except SQLAlchemyError as e:
            logger.error(f"Database error getting batch status: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error getting batch status: {e}")
            return None

    def increment_batch_progress(self, batch_id: str, success: bool = True) -> bool:
        """Increment batch progress counters with enhanced validation and atomic operations."""
        try:
            if not batch_id or not batch_id.strip():
                logger.error("Batch ID cannot be empty")
                return False

            with self.get_session() as session:
                from models.database_models import ProcessingBatch

                batch = session.query(ProcessingBatch).filter(
                    ProcessingBatch.batch_id == batch_id.strip()
                ).first()

                if not batch:
                    logger.warning(f"Processing batch {batch_id} not found")
                    return False

                if not batch.started_at:
                    batch.started_at = datetime.now(timezone.utc)

                # Increment counters atomically
                if success:
                    batch.processed_documents = (batch.processed_documents or 0) + 1
                else:
                    batch.failed_documents = (batch.failed_documents or 0) + 1

                # Check if batch is complete
                total_processed = (batch.processed_documents or 0) + (batch.failed_documents or 0)
                total_documents = batch.total_documents or 0

                if total_processed >= total_documents and total_documents > 0:
                    batch.status = 'COMPLETED'
                    if not batch.completed_at:
                        batch.completed_at = datetime.now(timezone.utc)

                session.flush()
                logger.info(f"Updated batch {batch_id} progress: {total_processed}/{total_documents}")
                return True

        except SQLAlchemyError as e:
            logger.error(f"Database error updating batch progress: {e}")
            return False

    def create_temp_document(self, **kwargs) -> Optional[Dict[str, Any]]:
        """Create a new temporary document with comprehensive validation."""
        try:
            # Input validation
            required_fields = ['temp_document_id', 'project_id', 'user_id', 'original_filename']
            for field in required_fields:
                if not kwargs.get(field):
                    raise ValidationError(f"Required field '{field}' is missing or empty")

            with self.get_session() as session:
                from models.database_models import TempDocument

                # Convert user_id to UUID if it's a string
                user_id = kwargs.get('user_id')
                if isinstance(user_id, str):
                    try:
                        user_id = uuid.UUID(user_id)
                        kwargs['user_id'] = user_id
                    except ValueError as e:
                        logger.error(f"Invalid UUID format for user_id: {user_id}")
                        raise ValidationError(f"Invalid user_id format: {user_id}")

                # Ensure project_id is an integer
                project_id = kwargs.get('project_id')
                if isinstance(project_id, str):
                    try:
                        project_id = int(project_id)
                        kwargs['project_id'] = project_id
                    except ValueError as e:
                        logger.error(f"Invalid project_id format: {project_id}")
                        raise ValidationError(f"Invalid project_id format: {project_id}")

                # Check for duplicate temp_document_id
                temp_doc_id = kwargs.get('temp_document_id', '').strip()
                if not temp_doc_id:
                    raise ValidationError("Temp document ID cannot be empty")

                existing_temp_doc = session.query(TempDocument).filter(
                    TempDocument.temp_document_id == temp_doc_id
                ).first()

                if existing_temp_doc:
                    raise ValidationError(f"Temporary document with ID {temp_doc_id} already exists")

                # Verify user exists and is active
                user = session.query(User).filter(
                    and_(User.id == user_id, User.is_active == True)
                ).first()
                if not user:
                    raise ValidationError(f"User with ID {user_id} not found or inactive")

                # Verify project exists and is active
                project = session.query(Project).filter(
                    and_(Project.id == project_id, Project.is_active == True)
                ).first()
                if not project:
                    raise ValidationError(f"Project with ID {project_id} not found or inactive")

                # Verify user has access to the project
                if project.owner_id != user_id:
                    raise ValidationError(f"User {user_id} does not have access to project {project_id}")

                # Set default values and clean up data
                print('Kwargs in db manager is :',kwargs)
                cleaned_kwargs = {}
                for key, value in kwargs.items():
                    if key == 'original_filename' and value:
                        cleaned_kwargs[key] = value.strip()
                    elif key == 'temp_document_id' and value:
                        cleaned_kwargs[key] = value.strip()
                    elif key == 'file_size':
                        cleaned_kwargs[key] = max(0, int(value)) if value is not None else 0
                    elif key == 'status':
                        valid_statuses = {'UPLOADED', 'PROCESSING', 'PROCESSED', 'FAILED'}
                        cleaned_kwargs[key] = value if value in valid_statuses else 'UPLOADED'
                    else:
                        cleaned_kwargs[key] = value

                # Set upload timestamp if not provided
                if 'upload_timestamp' not in cleaned_kwargs:
                    cleaned_kwargs['upload_timestamp'] = datetime.now(timezone.utc)

                # Create the temporary document
                temp_document = TempDocument(**cleaned_kwargs)
                session.add(temp_document)
                session.flush()  # Get the ID

                # Convert to dictionary for return
                temp_doc_dict = {
                    'id': temp_document.id,
                    'temp_document_id': temp_document.temp_document_id,
                    'project_id': temp_document.project_id,
                    'user_id': str(temp_document.user_id),  # Convert UUID to string
                    'original_filename': temp_document.original_filename,
                    'file_path': temp_document.file_path,
                    'source': temp_document.source,
                    'file_size': temp_document.file_size,
                    'mime_type': temp_document.mime_type,
                    'upload_timestamp': temp_document.upload_timestamp.isoformat() if temp_document.upload_timestamp else None,
                    'status': temp_document.status,
                    'text_preview': temp_document.text_preview
                }

                logger.info(f"Created temp document: {temp_document.original_filename} for user: {user.username}")
                return temp_doc_dict

        except ValidationError:
            raise  # Re-raise validation errors
        except SQLAlchemyError as e:
            logger.error(f"Database error creating temp document: {e}")
            raise DatabaseError(f"Failed to create temp document: {e}")
        except Exception as e:
            logger.error(f"Unexpected error creating temp document: {e}")
            raise DatabaseError(f"Unexpected error creating temp document: {e}")

    def get_temp_document(self, temp_document_id: str, project_id: Union[int, str],
                         user_id: Union[str, uuid.UUID]) -> Optional[Dict[str, Any]]:
        """Get temporary document by ID with project and user access verification and enhanced validation."""
        try:
            # Input validation
            if not temp_document_id or not temp_document_id.strip():
                logger.error("Temp document ID cannot be empty")
                return None

            with self.get_session() as session:
                from models.database_models import TempDocument

                # Convert user_id to UUID if it's a string
                if isinstance(user_id, str):
                    try:
                        user_id = uuid.UUID(user_id)
                    except ValueError as e:
                        logger.error(f"Invalid UUID format for user_id: {user_id}")
                        return None

                # Ensure project_id is an integer
                if isinstance(project_id, str):
                    try:
                        project_id = int(project_id)
                    except ValueError as e:
                        logger.error(f"Invalid project_id format: {project_id}")
                        return None

                # Query for temporary document with access control
                temp_document = session.query(TempDocument).filter(
                    and_(
                        TempDocument.temp_document_id == temp_document_id.strip(),
                        TempDocument.project_id == project_id,
                        TempDocument.user_id == user_id
                    )
                ).first()

                if not temp_document:
                    logger.warning(f"Temp document lookup failed - ID: {temp_document_id}, "
                                f"Project: {project_id}, User: {user_id}")

                    # Check if document exists without access control for debugging
                    exists = session.query(TempDocument).filter(
                        TempDocument.temp_document_id == temp_document_id.strip()
                    ).first()

                    if exists:
                        logger.warning(f"Document exists but access denied - "
                                    f"Expected user: {user_id}, Actual user: {exists.user_id}, "
                                    f"Expected project: {project_id}, Actual project: {exists.project_id}")
                    else:
                        logger.warning(f"Document {temp_document_id} does not exist in database")

                    return None

                # Convert to dictionary format
                temp_doc = {
                    'id': temp_document.id,
                    'temp_document_id': temp_document.temp_document_id,
                    'original_filename': temp_document.original_filename,
                    'text_preview': temp_document.text_preview or 'No preview available',
                    'file_path': temp_document.file_path,
                    'blob_name': temp_document.blob_name,
                    'source': temp_document.source,
                    'file_size': temp_document.file_size or 0,
                    'mime_type': temp_document.mime_type,
                    'upload_timestamp': temp_document.upload_timestamp,
                    'status': temp_document.status or 'UPLOADED',
                    'project_id': temp_document.project_id,
                    'user_id': str(temp_document.user_id)  # Convert UUID back to string
                }

                logger.info(f"Retrieved temp document: {temp_document.original_filename}")
                return temp_doc

        except SQLAlchemyError as e:
            logger.error(f"Database error getting temp document: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error getting temp document: {e}")
            return None

    def list_temp_documents(self, project_id: Union[int, str],
                            user_id: Union[str, uuid.UUID],
                            status_filter: Optional[str] = None,
                            limit: Optional[int] = None,
                            offset: Optional[int] = 0) -> List[Dict[str, Any]]:
        """List all temporary documents for a given project and user with optional filtering."""
        try:
            with self.get_session() as session:
                from models.database_models import TempDocument

                # Convert user_id to UUID if it's a string
                if isinstance(user_id, str):
                    try:
                        user_id = uuid.UUID(user_id)
                    except ValueError as e:
                        logger.error(f"Invalid UUID format for user_id: {user_id}")
                        return []

                # Ensure project_id is an integer
                if isinstance(project_id, str):
                    try:
                        project_id = int(project_id)
                    except ValueError as e:
                        logger.error(f"Invalid project_id format: {project_id}")
                        return []

                # Build query with base filters
                query = session.query(TempDocument).filter(
                    and_(
                        TempDocument.project_id == project_id,
                        TempDocument.user_id == user_id
                    )
                )

                # Add optional status filter
                if status_filter:
                    query = query.filter(TempDocument.status == status_filter)

                # Add ordering (most recent first)
                query = query.order_by(TempDocument.upload_timestamp.desc())

                # Add pagination
                if offset:
                    query = query.offset(offset)
                if limit:
                    query = query.limit(limit)

                # Execute query
                temp_documents = query.all()

                if not temp_documents:
                    logger.info(f"No temp documents found for project {project_id} and user {user_id}")
                    return []

                # Convert to dictionary format
                temp_docs_list = []
                for temp_document in temp_documents:
                    temp_doc = {
                        'id': temp_document.id,
                        'temp_document_id': temp_document.temp_document_id,
                        'original_filename': temp_document.original_filename,
                        'text_preview': temp_document.text_preview or 'No preview available',
                        'file_path': temp_document.file_path,
                        'file_size': temp_document.file_size or 0,
                        'mime_type': temp_document.mime_type,
                        'source': temp_document.source,
                        'upload_timestamp': temp_document.upload_timestamp,
                        'status': temp_document.status or 'UPLOADED',
                        'project_id': temp_document.project_id,
                        'user_id': str(temp_document.user_id)  # Convert UUID back to string
                    }
                    temp_docs_list.append(temp_doc)

                logger.info(f"Retrieved {len(temp_docs_list)} temp documents for project {project_id} and user {user_id}")
                return temp_docs_list

        except SQLAlchemyError as e:
            logger.error(f"Database error listing temp documents: {e}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error listing temp documents: {e}")
            return []

    def get_project(self, project_id: Union[int, str]) -> Optional[Project]:
        """Get project by ID with optional user access check and improved type handling."""
        try:
            # Convert project_id to int if needed
            if isinstance(project_id, str):
                try:
                    project_id = int(project_id)
                except ValueError:
                    logger.error(f"Invalid project_id format: {project_id}")
                    return None

            with self.get_session() as session:
                query = session.query(Project).filter(
                    and_(Project.id == project_id, Project.is_active == True)
                )

                project = query.first()

                if project:
                    session.expunge(project)

                return project

        except Exception as e:
            logger.error(f"Database error getting project: {e}")
            return None

    def get_temp_documents_count(self, project_id: Union[int, str],
                                user_id: Union[str, uuid.UUID],
                                status_filter: Optional[str] = None) -> int:
        """Get count of temporary documents for a given project and user."""
        try:
            with self.get_session() as session:
                from models.database_models import TempDocument

                # Convert user_id to UUID if it's a string
                if isinstance(user_id, str):
                    try:
                        user_id = uuid.UUID(user_id)
                    except ValueError as e:
                        logger.error(f"Invalid UUID format for user_id: {user_id}")
                        return 0

                # Ensure project_id is an integer
                if isinstance(project_id, str):
                    try:
                        project_id = int(project_id)
                    except ValueError as e:
                        logger.error(f"Invalid project_id format: {project_id}")
                        return 0

                # Build query with base filters
                query = session.query(TempDocument).filter(
                    and_(
                        TempDocument.project_id == project_id,
                        TempDocument.user_id == user_id
                    )
                )

                # Add optional status filter
                if status_filter:
                    query = query.filter(TempDocument.status == status_filter)

                # Get count
                count = query.count()

                logger.info(f"Found {count} temp documents for project {project_id} and user {user_id}")
                return count

        except SQLAlchemyError as e:
            logger.error(f"Database error counting temp documents: {e}")
            return 0
        except Exception as e:
            logger.error(f"Unexpected error counting temp documents: {e}")
            return 0



    # Document Operations (Enhanced)
    def create_document(self, **kwargs) -> Document:
        """Create a new document with enhanced validation."""
        try:
            # Input validation
            required_fields = ['user_id', 'project_id', 'original_filename']
            for field in required_fields:
                if not kwargs.get(field):
                    raise ValidationError(f"Required field '{field}' is missing")

            with self.get_session() as session:
                # Convert user_id to UUID if it's a string
                user_id = kwargs.get('user_id')
                if isinstance(user_id, str):
                    try:
                        user_id = uuid.UUID(user_id)
                        kwargs['user_id'] = user_id
                    except ValueError:
                        raise ValidationError(f"Invalid UUID format for user_id: {user_id}")

                # Verify user and project exist
                user = session.query(User).filter(
                    and_(User.id == user_id, User.is_active == True)
                ).first()
                if not user:
                    raise ValidationError(f"User with ID {user_id} not found")

                project = session.query(Project).filter(
                    and_(Project.id == kwargs.get('project_id'), Project.is_active == True)
                ).first()
                if not project:
                    raise ValidationError(f"Project with ID {kwargs.get('project_id')} not found")

                # Verify user has access to the project
                if project.owner_id != user_id:
                    raise ValidationError(f"User does not have access to project")

                # Set default timestamp if not provided
                if 'date_added_to_giani' not in kwargs:
                    kwargs['date_added_to_giani'] = datetime.now(timezone.utc)

                document = Document(**kwargs)
                session.add(document)
                session.flush()

                # Detach from session
                session.expunge(document)

                logger.info(f"Created document: {document.original_filename}")
                return document

        except ValidationError:
            raise  # Re-raise validation errors
        except SQLAlchemyError as e:
            logger.error(f"Database error creating document: {e}")
            raise DatabaseError(f"Failed to create document: {e}")

    def get_document_by_id(self, document_id: Union[str, uuid.UUID], user_id: Union[str, uuid.UUID] = None) -> Optional[Document]:
        """Get document by ID with optional user access check and enhanced type handling."""
        try:
            # Convert document_id to UUID if it's a string
            if isinstance(document_id, str):
                try:
                    document_id = uuid.UUID(document_id)
                except ValueError:
                    logger.error(f"Invalid UUID format for document_id: {document_id}")
                    return None

            # Convert user_id to UUID if provided and is string
            if user_id and isinstance(user_id, str):
                try:
                    user_id = uuid.UUID(user_id)
                except ValueError:
                    logger.error(f"Invalid UUID format for user_id: {user_id}")
                    return None

            with self.get_session() as session:
                query = session.query(Document).filter(Document.id == document_id)
                if user_id:
                    query = query.filter(Document.user_id == user_id)

                document = query.first()
                if document:
                    session.expunge(document)
                return document

        except SQLAlchemyError as e:
            logger.error(f"Database error getting document: {e}")
            return None

    def get_project_documents(self, project_id: Union[int, str], user_id: Union[str, uuid.UUID] = None) -> List[Document]:
        """Get all documents for a project with optimized query and enhanced type handling."""
        try:
            # Convert project_id to int if needed
            if isinstance(project_id, str):
                try:
                    project_id = int(project_id)
                except ValueError:
                    logger.error(f"Invalid project_id format: {project_id}")
                    return []

            # Convert user_id to UUID if provided and is string
            if user_id and isinstance(user_id, str):
                try:
                    user_id = uuid.UUID(user_id)
                except ValueError:
                    logger.error(f"Invalid UUID format for user_id: {user_id}")
                    return []

            with self.get_session() as session:
                query = session.query(Document).filter(Document.project_id == project_id)

                if user_id:
                    query = query.filter(Document.user_id == user_id)

                documents = query.order_by(desc(Document.date_added_to_giani)).all()

                # Detach all documents from session
                for document in documents:
                    session.expunge(document)

                return documents

        except SQLAlchemyError as e:
            logger.error(f"Database error getting project documents: {e}")
            return []

    def search_documents(self, search_term: str, user_id: Union[str, uuid.UUID] = None) -> List[Document]:
        """Search documents with optimized full-text search and enhanced validation."""
        try:
            if not search_term or not search_term.strip():
                logger.warning("Empty search term provided")
                return []

            # Convert user_id to UUID if provided and is string
            if user_id and isinstance(user_id, str):
                try:
                    user_id = uuid.UUID(user_id)
                except ValueError:
                    logger.error(f"Invalid UUID format for user_id: {user_id}")
                    return []

            search_term = search_term.strip()

            with self.get_session() as session:
                query = session.query(Document).filter(
                    or_(
                        Document.original_filename.contains(search_term),
                        Document.text_preview.contains(search_term),
                        Document.final_purpose.contains(search_term)
                    )
                )

                if user_id:
                    query = query.filter(Document.user_id == user_id)

                documents = query.order_by(desc(Document.date_added_to_giani)).all()

                # Detach all documents from session
                for document in documents:
                    session.expunge(document)

                return documents

        except SQLAlchemyError as e:
            logger.error(f"Database error searching documents: {e}")
            return []

    def update_document(self, document_id: int, user_id: Union[str, uuid.UUID], **kwargs) -> Optional[Document]:
        """Update document fields with ownership verification and enhanced validation."""
        try:
            # Convert user_id to UUID if it's a string
            if isinstance(user_id, str):
                try:
                    user_id = uuid.UUID(user_id)
                except ValueError:
                    raise ValidationError(f"Invalid UUID format for user_id: {user_id}")

            with self.get_session() as session:
                document = session.query(Document).filter(
                    and_(Document.id == document_id, Document.user_id == user_id)
                ).first()

                if not document:
                    raise NotFoundError(f"Document with ID {document_id} not found or access denied")

                # Update allowed fields with validation
                allowed_fields = {
                    'final_category', 'final_purpose', 'priority', 'text_preview',
                    'processed_content', 'extracted_text', 'metadata'
                }
                for key, value in kwargs.items():
                    if key in allowed_fields and hasattr(document, key):
                        # Validate specific fields
                        if key == 'priority' and value is not None:
                            if not isinstance(value, int) or value < 1 or value > 10:
                                raise ValidationError("Priority must be an integer between 1 and 10")
                        elif key in ['final_category', 'final_purpose'] and value:
                            value = value.strip()

                        setattr(document, key, value)

                document.updated_at = datetime.now(timezone.utc)
                session.flush()

                # Detach from session
                session.expunge(document)

                logger.info(f"Updated document: {document.original_filename}")
                return document

        except ValidationError:
            raise  # Re-raise validation errors
        except SQLAlchemyError as e:
            logger.error(f"Database error updating document: {e}")
            raise DatabaseError(f"Failed to update document: {e}")

    def delete_document(self, document_id: int, user_id: Union[str, uuid.UUID]) -> bool:
        """Delete document with ownership verification and enhanced type handling."""
        try:
            # Convert user_id to UUID if it's a string
            if isinstance(user_id, str):
                try:
                    user_id = uuid.UUID(user_id)
                except ValueError:
                    raise ValidationError(f"Invalid UUID format for user_id: {user_id}")

            with self.get_session() as session:
                document = session.query(Document).filter(
                    and_(Document.id == document_id, Document.user_id == user_id)
                ).first()

                if not document:
                    raise NotFoundError(f"Document with ID {document_id} not found or access denied")

                # Store filename for logging
                filename = document.original_filename

                # Delete related chunks and summaries first
                chunks_deleted = session.query(DocumentChunk).filter(
                    DocumentChunk.document_id == document_id
                ).delete()

                summaries_deleted = session.query(DocumentSummary).filter(
                    DocumentSummary.document_id == document_id
                ).delete()

                # Delete document
                session.delete(document)

                logger.info(f"Deleted document: {filename} (with {chunks_deleted} chunks and {summaries_deleted} summaries)")
                return True

        except ValidationError:
            raise  # Re-raise validation errors
        except SQLAlchemyError as e:
            logger.error(f"Database error deleting document: {e}")
            raise DatabaseError(f"Failed to delete document: {e}")

    # Document Chunk Operations (Enhanced)
    def create_document_chunk(self, **kwargs) -> DocumentChunk:
        """Create a new document chunk with UUID conversion for SQLite."""
        try:
            # Convert UUID fields to strings for SQLite compatibility
            if 'chunk_id' in kwargs and kwargs['chunk_id']:
                if isinstance(kwargs['chunk_id'], uuid.UUID):
                    kwargs['chunk_id'] = str(kwargs['chunk_id'])

            if 'vector_id' in kwargs and kwargs['vector_id']:
                if isinstance(kwargs['vector_id'], uuid.UUID):
                    kwargs['vector_id'] = str(kwargs['vector_id'])

            if 'metadata_' in kwargs and kwargs['metadata_']:
                kwargs['metadata_'] = self._serialize_metadata(kwargs['metadata_'])

            # Rest of your existing validation code...
            required_fields = ['document_id', 'chunk_text']
            for field in required_fields:
                if not kwargs.get(field):
                    raise ValidationError(f"Required field '{field}' is missing")

            with self.get_session() as session:
                chunk = DocumentChunk(**kwargs)
                session.add(chunk)
                session.flush()

                # Detach from session
                logger.info(f"Created document chunk for document ID: {kwargs.get('document_id')}")
                session.expunge(chunk)
                return chunk

        except ValidationError:
            raise
        except SQLAlchemyError as e:
            logger.error(f"Database error creating document chunk: {e}")
            raise DatabaseError(f"Failed to create document chunk: {e}")

    # Document Summary Operations (Enhanced)
    def create_document_summary(self, **kwargs) -> DocumentSummary:
        """Create a new document summary with enhanced validation."""
        try:
            # Input validation
            required_fields = ['document_id', 'summary_text']
            for field in required_fields:
                if not kwargs.get(field):
                    raise ValidationError(f"Required field '{field}' is missing")

            document_id = kwargs.get('document_id')
            if isinstance(document_id, str):
                try:
                    document_id = UUID(document_id)
                    kwargs['document_id'] = document_id  # update the value
                except ValueError:
                    raise ValidationError("Invalid UUID format for 'document_id'")


            with self.get_session() as session:
                # Verify document exists
                document = session.query(Document).filter(
                    Document.id == document_id
                ).first()
                if not document:
                    raise ValidationError(f"Document with ID {document_id} not found")

                # Set processing timestamp if not provided
                if 'processing_timestamp' not in kwargs:
                    kwargs['processing_timestamp'] = datetime.now(timezone.utc)

                summary = DocumentSummary(**kwargs)
                session.add(summary)
                session.flush()

                # Detach from session
                session.expunge(summary)

                logger.info(f"Created document summary for document ID: {document_id}")
                return summary

        except ValidationError:
            raise  # Re-raise validation errors
        except SQLAlchemyError as e:
            logger.error(f"Database error creating document summary: {e}")
            raise DatabaseError(f"Failed to create document summary: {e}")

    def _verify_document_exists(self, document_id) -> bool:
        """Verify that a document exists in the database."""
        try:
            with self.get_session() as session:  # type: Session
                try:
                    if isinstance(document_id, str):
                        document_id = UUID(document_id)
                except ValueError:
                    logger.error(f"Invalid UUID format: {document_id}")
                    return False

                result = session.query(Document).filter_by(id=document_id).first()
                return result is not None

        except SQLAlchemyError as e:
            logger.error(f"Error verifying document existence: {e}")
            return False

    def get_document_summaries(self, document_id: Union[str, uuid.UUID]) -> List[DocumentSummary]:
        """Get all summaries for a document with enhanced validation."""
        try:
            if isinstance(document_id, str):
                try:
                    document_id = uuid.UUID(document_id)
                except ValueError:
                    logger.error(f"Invalid UUID format for document_id: {document_id}")
                    return False

            with self.get_session() as session:
                summaries = session.query(DocumentSummary).filter(
                    DocumentSummary.document_id == document_id
                ).order_by(desc(DocumentSummary.processing_timestamp)).all()

                # Detach all summaries from session
                for summary in summaries:
                    session.expunge(summary)

                return summaries

        except SQLAlchemyError as e:
            logger.error(f"Database error getting document summaries: {e}")
            return []

    def get_project_summaries(self, project_id: int) -> List[DocumentSummary]:
        """Gets all the documents summaries for a given project """
        try:
            if isinstance(project_id, str):
                try:
                    project_id = int(project_id)
                except ValueError:
                    logger.error(f"Invalid format for project_id: {project_id}")
                    raise

            with self.get_session() as session:
                summaries = (
                    session.query(DocumentSummary)
                    .join(Document, DocumentSummary.document_id == Document.id)
                    .filter(Document.project_id == project_id)
                    .order_by(DocumentSummary.processing_timestamp.desc())
                ).all()

                # Detach all summaries from session
                for summary in summaries:
                    session.expunge(summary)

                return summaries

        except SQLAlchemyError as e:
            logger.error(f"Database error getting summaries for the project: {project_id}")

    def create_or_update_onboarding_guide(self, project_id: int, guide: dict[str, Any]):
        """Create or update an onboarding guide for a given project id"""
        try:
            with self.get_session() as session:
                existing_guide = session.query(OnboardingGuide).filter(
                    OnboardingGuide.project_id == project_id
                ).first()

                if existing_guide:
                    existing_guide.content = guide
                    session.flush()

                    logger.info(f"Updated onboarding_guide: {existing_guide.id} for project: {project_id}")
                    return existing_guide.id
                else:
                    onboarding_guide = OnboardingGuide(project_id=project_id, content=guide)
                    session.add(onboarding_guide)
                    session.flush()

                    logger.info(f"Created onboarding_guide: {onboarding_guide.id} for project: {project_id}")
                    return onboarding_guide.id

        except Exception as e:
            logger.error(f"Unexpected error creating/updating onboarding guide: {e}")
            raise DatabaseError(f"Unexpected error creating/updating onboarding guide: {e}")


    # Statistics and Analytics (Enhanced)
    def save_summary(self, document_id: str, summary_data: Dict[str, Any]) -> bool:
        """Save a document summary to the database."""
        try:
            # Convert string to UUID if necessary
            if isinstance(document_id, str):
                try:
                    document_uuid = uuid.UUID(document_id)
                except ValueError:
                    logger.error(f"Invalid UUID format for document_id: {document_id}")
                    return False
            else:
                document_uuid = document_id

            # Verify the document exists before saving summary
            if not self._verify_document_exists(document_uuid):
                logger.error(f"Cannot save summary: document_id {document_id} does not exist")
                return False

            # Extract llm_analysis for easier access
            llm_analysis = summary_data.get("llm_analysis", {})
            extracted_metadata = llm_analysis.get("extracted_metadata", {})

            with self.get_session() as session:
                summary = DocumentSummary(
                    document_id=document_uuid,
                    # llm_analysis=llm_analysis,
                    summarization_analysis=summary_data.get("summarization_analysis"),
                    metadata_analysis=summary_data.get("metadata_analysis"),

                    # Document context
                    document_filename=summary_data.get("document_filename"),
                    document_category=summary_data.get("document_category"),
                    document_group=summary_data.get("document_group"),
                    user_note_purpose=summary_data.get("user_note_purpose"),
                    source=summary_data.get("source"),

                    # Processing metadata
                    processing_timestamp=datetime.now(timezone.utc),
                    summarization_llm_model=summary_data.get("summarization_llm_model", ""),
                    summary_storage_path=summary_data.get("summaryStoragePath"),

                    # Extracted fields for easy querying
                    narrative_summary=summary_data.get("ai_high_level_narrative_summary"),
                    key_themes=summary_data.get("ai_overall_key_themes_list"),
                    key_takeaways=summary_data.get("ai_key_takeaways_bullets"),
                    extracted_keywords=summary_data.get("extracted_keywords"),

                    # Metadata for search and filtering
                    document_sentiment=extracted_metadata.get("document_overall_sentiment"),
                    suggested_title=extracted_metadata.get("suggested_document_title"),
                    implied_audience=extracted_metadata.get("implied_audience"),
                    geographical_focus=extracted_metadata.get("primary_geographical_focus"),

                    # Key entities
                    key_people_mentioned=extracted_metadata.get("key_people_or_roles_mentioned"),
                    key_organizations_mentioned=extracted_metadata.get("key_companies_organizations_mentioned"),
                    key_dates_mentioned=extracted_metadata.get("key_dates_mentioned"),
                )
                session.add(summary)
                session.commit()
                logger.info(f"Successfully saved summary for document {document_id}")
                return True

        except SQLAlchemyError as e:
            logger.error(f"Database error saving summary: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error saving summary: {e}")
            return False

    def _normalize_document_id(self, document_id: Union[str, uuid.UUID]) -> str:
        """Normalize document ID to string format for database storage."""
        if isinstance(document_id, str):
            try:
                uuid_obj = uuid.UUID(document_id)
                return str(uuid_obj).replace('-', '')
            except ValueError:
                raise ValueError(f"Invalid UUID format: {document_id}")
        return str(document_id).replace('-', '')

    def _convert_uuids_to_strings(self, data_dict: Dict[str, Any]) -> Dict[str, Any]:
        """Convert UUID objects to strings for SQLite compatibility, handling nested structures."""
        import uuid
        import json

        converted = {}
        for key, value in data_dict.items():
            if isinstance(value, uuid.UUID):
                converted[key] = str(value)
            elif isinstance(value, dict):
                # Recursively convert nested dictionaries
                converted[key] = self._convert_dict_uuids_to_strings(value)
            elif isinstance(value, list):
                # Handle lists that might contain UUIDs
                converted[key] = self._convert_list_uuids_to_strings(value)
            elif hasattr(value, 'to_dict'):
                # Handle objects with to_dict method
                dict_value = value.to_dict()
                converted[key] = self._convert_dict_uuids_to_strings(dict_value)
            else:
                # For metadata_, ensure it's JSON serializable
                if key == 'metadata_' and value is not None:
                    try:
                        # Try to serialize to ensure it's JSON compatible
                        json.dumps(value)
                        converted[key] = value
                    except (TypeError, ValueError):
                        # If not serializable, convert to string
                        converted[key] = str(value)
                else:
                    converted[key] = value
        return converted

    def _convert_dict_uuids_to_strings(self, data_dict: Dict[str, Any]) -> Dict[str, Any]:
        """Recursively convert UUIDs in nested dictionaries."""
        import uuid

        converted = {}
        for key, value in data_dict.items():
            if isinstance(value, uuid.UUID):
                converted[key] = str(value)
            elif isinstance(value, dict):
                converted[key] = self._convert_dict_uuids_to_strings(value)
            elif isinstance(value, list):
                converted[key] = self._convert_list_uuids_to_strings(value)
            else:
                converted[key] = value
        return converted

    def _convert_list_uuids_to_strings(self, data_list: List[Any]) -> List[Any]:
        """Convert UUIDs in lists to strings."""
        import uuid

        converted = []
        for item in data_list:
            if isinstance(item, uuid.UUID):
                converted.append(str(item))
            elif isinstance(item, dict):
                converted.append(self._convert_dict_uuids_to_strings(item))
            elif isinstance(item, list):
                converted.append(self._convert_list_uuids_to_strings(item))
            else:
                converted.append(item)
        return converted

    def save_chunks(self, document_id: Union[str, uuid.UUID], chunks: List[Any]) -> bool:
        """Save document chunks to the database with UUID conversion."""
        logger.debug(f"Attempting to save {len(chunks)} chunks for document_id: {document_id}")

        try:
            # Normalize document_id to string format (remove dashes for SQLite)
            if isinstance(document_id, str):
                document_id = uuid.UUID(document_id)

            # Verify the document exists
            if not self._verify_document_exists(document_id):
                logger.error(f"Document validation failed: document_id {document_id} does not exist in documents table")
                return False

            logger.debug(f"Document {document_id} exists, proceeding with chunk save")

            with self.get_session() as session:
                session.begin()

                try:
                    for i, chunk_data in enumerate(chunks):
                        # Initialize variables with defaults
                        chunk_text = ""
                        chunk_metadata = {}
                        chunk_id = str(uuid.uuid4())
                        vector_id = None
                        embedding_checksum = None

                        # Handle different chunk_data formats
                        if isinstance(chunk_data, tuple):
                            chunk_text = chunk_data[0] if len(chunk_data) > 0 else ""
                            chunk_metadata = chunk_data[1] if len(chunk_data) > 1 else {}
                            chunk_id = chunk_data[2] if len(chunk_data) > 2 else str(uuid.uuid4())
                            vector_id = chunk_data[3] if len(chunk_data) > 3 else None
                            embedding_checksum = chunk_data[4] if len(chunk_data) > 4 else None
                        elif isinstance(chunk_data, dict):
                            chunk_text = chunk_data.get('text', chunk_data.get('chunk_text', ''))
                            chunk_metadata = chunk_data.get('metadata', {})
                            chunk_id = chunk_data.get('chunk_id', str(uuid.uuid4()))
                            vector_id = chunk_data.get('vector_id')
                            embedding_checksum = chunk_data.get('embedding_checksum')
                        else:
                            logger.error(f"Unexpected chunk_data type: {type(chunk_data)}")
                            continue

                        # Ensure chunk_text is a string
                        if not isinstance(chunk_text, str):
                            chunk_text = str(chunk_text) if chunk_text is not None else ""

                        # Ensure chunk_id is a string
                        if isinstance(chunk_id, uuid.UUID):
                            chunk_id = str(chunk_id)
                        elif chunk_id is None:
                            chunk_id = str(uuid.uuid4())

                        # Ensure vector_id is a string if it's a UUID
                        if isinstance(vector_id, uuid.UUID):
                            vector_id = str(vector_id)

                        # Process metadata - ensure it's JSON serializable
                        if chunk_metadata:
                            if hasattr(chunk_metadata, 'to_dict'):
                                metadata_dict = chunk_metadata.to_dict()
                            else:
                                metadata_dict = chunk_metadata

                            # Convert any UUIDs in metadata to strings
                            if isinstance(metadata_dict, dict):
                                metadata_json = self._convert_dict_uuids_to_strings(metadata_dict)
                            else:
                                metadata_json = str(metadata_dict)
                        else:
                            metadata_json = {}

                        # Ensure metadata_json is a dict
                        if not isinstance(metadata_json, dict):
                            metadata_json = {}

                        chunk_dict = {
                            'document_id': document_id,  # Use normalized string format
                            'chunk_index': i,
                            'chunk_text': chunk_text,
                            'metadata_': metadata_json,
                            'chunk_id': chunk_id,
                            'vector_id': vector_id,
                            'embedding_checksum': embedding_checksum
                        }

                        # Convert any remaining UUIDs to strings (except document_id which is already normalized)
                        chunk_dict_converted = self._convert_uuids_to_strings(chunk_dict)
                        # Keep document_id as normalized string (don't convert back to UUID)
                        chunk_dict_converted['document_id'] = document_id

                        # Additional safety check - ensure all values are JSON serializable
                        try:
                            import json
                            json.dumps(chunk_dict_converted['metadata_'])
                        except (TypeError, ValueError) as e:
                            logger.warning(f"Metadata not JSON serializable, converting to string: {e}")
                            chunk_dict_converted['metadata_'] = str(chunk_dict_converted['metadata_'])

                        chunk = DocumentChunk(**chunk_dict_converted)
                        session.add(chunk)

                    session.commit()
                    return True

                except Exception as e:
                    session.rollback()
                    raise e

        except SQLAlchemyError as e:
            logger.error(f"Database error saving chunks: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error saving chunks: {e}")
            return False