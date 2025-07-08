"""
Unified database manager using SQLAlchemy ORM for all database operations.
"""
import logging
from typing import Optional, List, Dict, Any, Union
from datetime import datetime
from contextlib import contextmanager
from sqlalchemy import and_, or_, func, desc, asc
from sqlalchemy.exc import SQLAlchemyError
import uuid

from giani_pkb.utils.database import SessionLocal, engine
from giani_pkb.models.database_models import (
    User, Project, Document, DocumentChunk, DocumentSummary, APICallLog
)
from giani_pkb.utils.exceptions import DatabaseError, ValidationError, NotFoundError
from giani_pkb.utils.auth_utils import hash_password, verify_password

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
        """Get database session with automatic cleanup."""
        session = SessionLocal()
        try:
            yield session
            session.commit()
        except Exception as e:
            session.rollback()
            raise
        finally:
            session.close()

    def _user_to_dict(self, user: User) -> Dict[str, Any]:
        """Convert User object to dictionary."""
        return {
            'id': user.id,
            'username': user.username,
            'email': user.email,
            'hashed_password': user.hashed_password,
            'is_active': user.is_active,
            'is_superuser': user.is_superuser,
            'created_at': user.created_at,
            'updated_at': user.updated_at
        }

    # User Operations
    def create_user(self, username: str, email: str, password: str,
                   is_superuser: bool = False) -> Optional[Dict[str, Any]]:
        """Create a new user with proper password hashing and return user data as dict."""
        try:
            with self.get_session() as session:
                # Check if user already exists
                existing_user = session.query(User).filter(
                    or_(User.email == email, User.username == username)
                ).first()

                if existing_user:
                    raise ValidationError(f"User with email {email} or username {username} already exists")

                # Create new user
                hashed_password = hash_password(password)
                user = User(
                    username=username,
                    email=email,
                    hashed_password=hashed_password,
                    is_superuser=is_superuser,
                    is_active=True
                )

                session.add(user)
                session.flush()  # Get the user ID

                # Return user data as dict
                return self._user_to_dict(user)

        except SQLAlchemyError as e:
            logger.error(f"Database error creating user: {e}")
            raise DatabaseError(f"Failed to create user: {e}")

    def get_user_by_id(self, user_id) -> Optional[User]:
        """Get user by ID with optimized query. Returns detached User object."""
        try:
            with self.get_session() as session:
                user = session.query(User).filter(
                    and_(User.id == user_id, User.is_active == True)
                ).first()
                
                if user:
                    # Detach from session to prevent lazy loading issues
                    session.expunge(user)
                    
                return user
                
        except SQLAlchemyError as e:
            logger.error(f"Database error getting user by ID: {e}")
            return None

    def get_user_by_email(self, email: str) -> Optional[User]:
        """Get user by email with optimized query. Returns detached User object."""
        try:
            with self.get_session() as session:
                user = session.query(User).filter(
                    and_(User.email == email, User.is_active == True)
                ).first()

                if user:
                    # Detach from session to prevent lazy loading issues
                    session.expunge(user)
                    
                return user

        except SQLAlchemyError as e:
            logger.error(f"Database error getting user by email: {e}")
            return None

    def get_user_by_username(self, username: str) -> Optional[User]:
        """Get user by username with optimized query. Returns detached User object."""
        try:
            with self.get_session() as session:
                user = session.query(User).filter(
                    and_(User.username == username, User.is_active == True)
                ).first()
                
                if user:
                    # Detach from session to prevent lazy loading issues
                    session.expunge(user)
                    
                return user
                
        except SQLAlchemyError as e:
            logger.error(f"Database error getting user by username: {e}")
            return None

    def verify_user_credentials(self, email: str, password: str) -> Optional[User]:
        """Verify user credentials and return user if valid. Returns detached User object."""
        try:
            with self.get_session() as session:
                user = session.query(User).filter(
                    and_(User.email == email, User.is_active == True)
                ).first()

                if user and verify_password(password, user.hashed_password):
                    # Detach from session to prevent lazy loading issues
                    session.expunge(user)
                    return user
                return None

        except SQLAlchemyError as e:
            logger.error(f"Database error verifying credentials: {e}")
            return None

    # Alternative methods that return dictionaries (for APIs)
    def get_user_dict_by_id(self, user_id) -> Optional[Dict[str, Any]]:
        """Get user by ID as dictionary."""
        user = self.get_user_by_id(user_id)
        return self._user_to_dict(user) if user else None

    def get_user_dict_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Get user by email as dictionary."""
        user = self.get_user_by_email(email)
        return self._user_to_dict(user) if user else None

    def verify_user_credentials_dict(self, email: str, password: str) -> Optional[Dict[str, Any]]:
        """Verify user credentials and return user data as dict."""
        user = self.verify_user_credentials(email, password)
        return self._user_to_dict(user) if user else None

    def update_user(self, user_id: uuid.UUID, **kwargs) -> Optional[User]:
        """Update user fields."""
        try:
            with self.get_session() as session:
                user = session.query(User).filter(User.id == user_id).first()
                if not user:
                    raise NotFoundError(f"User with ID {user_id} not found")

                # Update allowed fields
                allowed_fields = {'username', 'email', 'is_active', 'is_superuser'}
                for key, value in kwargs.items():
                    if key in allowed_fields and hasattr(user, key):
                        setattr(user, key, value)

                user.updated_at = datetime.utcnow()
                session.flush()

                # Detach from session
                session.expunge(user)

                logger.info(f"Updated user: {user.username}")
                return user

        except SQLAlchemyError as e:
            logger.error(f"Database error updating user: {e}")
            raise DatabaseError(f"Failed to update user: {e}")

    def delete_user(self, user_id: int) -> bool:
        """Soft delete user by setting is_active to False."""
        try:
            with self.get_session() as session:
                user = session.query(User).filter(User.id == user_id).first()
                if not user:
                    raise NotFoundError(f"User with ID {user_id} not found")

                user.is_active = False
                user.updated_at = datetime.utcnow()

                logger.info(f"Deleted user: {user.username}")
                return True

        except SQLAlchemyError as e:
            logger.error(f"Database error deleting user: {e}")
            raise DatabaseError(f"Failed to delete user: {e}")

    # Project Operations
    def create_project(self, name: str, owner_id: uuid.UUID, description: str = None) -> Project:
        """Create a new project."""
        try:
            with self.get_session() as session:
                # Verify owner exists
                owner = session.query(User).filter(
                    and_(User.id == owner_id, User.is_active == True)
                ).first()
                if not owner:
                    raise ValidationError(f"User with ID {owner_id} not found")

                project = Project(
                    name=name,
                    description=description,
                    owner_id=owner_id,
                    is_active=True
                )

                session.add(project)
                session.flush()

                # Detach from session
                session.expunge(project)

                logger.info(f"Created project: {name} for user: {owner.username}")
                return project

        except SQLAlchemyError as e:
            logger.error(f"Database error creating project: {e}")
            raise DatabaseError(f"Failed to create project: {e}")

    def get_project(self, project_id, user_id=None):
        """
        Get project by ID with optional user access check.
        project_id: int or str (convert to int if needed)
        user_id: UUID or None
        """
        try:
            with self.get_session() as session:
                if isinstance(project_id, str):
                    project_id = int(project_id)
                query = session.query(Project).filter(Project.id == project_id)
                if user_id:
                    query = query.filter(Project.owner_id == user_id)
                project = query.first()
                
                if project:
                    session.expunge(project)
                    
                return project
                
        except Exception as e:
            logger.error(f"Database error getting project: {e}")
            return None

    def get_user_projects(self, user_id: int) -> List[Project]:
        """Get all projects for a user with optimized query."""
        try:
            with self.get_session() as session:
                projects = session.query(Project).filter(
                    and_(Project.owner_id == user_id, Project.is_active == True)
                ).order_by(desc(Project.updated_at)).all()
                
                # Detach all projects from session
                for project in projects:
                    session.expunge(project)
                    
                return projects

        except SQLAlchemyError as e:
            logger.error(f"Database error getting user projects: {e}")
            return []

    def update_project(self, project_id: int, user_id: int, **kwargs) -> Optional[Project]:
        """Update project fields with ownership verification."""
        try:
            print('inside update_project in db manager')
            with self.get_session() as session:
                project = session.query(Project).filter(
                    and_(Project.id == project_id, Project.owner_id == user_id, Project.is_active == True)
                ).first()

                if not project:
                    raise NotFoundError(f"Project with ID {project_id} not found or access denied")

                # Update allowed fields
                allowed_fields = {'name', 'description'}
                for key, value in kwargs.items():
                    if key in allowed_fields and hasattr(project, key):
                        setattr(project, key, value)

                project.updated_at = datetime.utcnow()
                session.flush()

                # Detach from session
                session.expunge(project)

                logger.info(f"Updated project: {project.name}")
                return project

        except SQLAlchemyError as e:
            logger.error(f"Database error updating project: {e}")
            raise DatabaseError(f"Failed to update project: {e}")

    def delete_project(self, project_id: int, user_id: int) -> bool:
        """Soft delete project with ownership verification."""
        try:
            with self.get_session() as session:
                project = session.query(Project).filter(
                    and_(Project.id == project_id, Project.owner_id == user_id, Project.is_active == True)
                ).first()

                if not project:
                    raise NotFoundError(f"Project with ID {project_id} not found or access denied")

                project.is_active = False
                project.updated_at = datetime.utcnow()

                logger.info(f"Deleted project: {project.name}")
                return True

        except SQLAlchemyError as e:
            logger.error(f"Database error deleting project: {e}")
            raise DatabaseError(f"Failed to delete project: {e}")

    def create_processing_batch(self, batch_id: str, project_id: int, user_id: Union[str, uuid.UUID], 
                          total_documents: int) -> Optional[Dict[str, Any]]:
        """
        Create a new processing batch record.
        
        Args:
            batch_id: Unique batch identifier
            project_id: ID of the project
            user_id: ID of the user (string or UUID)
            total_documents: Total number of documents in the batch
            
        Returns:
            Dictionary containing created batch data or None if failed
        """
        try:
            with self.get_session() as session:
                from giani_pkb.models.database_models import ProcessingBatch
                
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

                # Create the processing batch
                processing_batch = ProcessingBatch(
                    batch_id=batch_id,
                    project_id=project_id,
                    user_id=user_id,
                    total_documents=total_documents,
                    status='QUEUED'
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
                    'processed_documents': processing_batch.processed_documents,
                    'failed_documents': processing_batch.failed_documents,
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
        Delete a temporary document and optionally clean up the file.
        
        Args:
            temp_document_id: ID of the temporary document to delete
            user_id: Optional user ID for access control
            cleanup_file: Whether to delete the physical file as well
            
        Returns:
            True if deleted successfully, False otherwise
        """
        try:
            with self.get_session() as session:
                from giani_pkb.models.database_models import TempDocument
                import os
                
                # Convert user_id to UUID if provided and is string
                if user_id and isinstance(user_id, str):
                    try:
                        user_id = uuid.UUID(user_id)
                    except ValueError as e:
                        logger.error(f"Invalid UUID format for user_id: {user_id}")
                        return False
                
                # Build query with optional user access control
                query = session.query(TempDocument).filter(
                    TempDocument.temp_document_id == temp_document_id
                )
                
                if user_id:
                    query = query.filter(TempDocument.user_id == user_id)
                
                temp_document = query.first()
                
                if not temp_document:
                    logger.warning(f"Temp document {temp_document_id} not found" + 
                                (f" for user {user_id}" if user_id else ""))
                    return False
                
                # Store info for logging and file cleanup
                filename = temp_document.original_filename
                file_path = temp_document.file_path
                
                # Delete the database record
                session.delete(temp_document)
                session.flush()
                
                # Clean up physical file if requested
                if cleanup_file and file_path and os.path.exists(file_path):
                    try:
                        os.remove(file_path)
                        logger.info(f"Deleted file: {file_path}")
                    except OSError as e:
                        logger.warning(f"Failed to delete file {file_path}: {e}")
                
                logger.info(f"Deleted temp document: {filename} (ID: {temp_document_id})")
                return True
                
        except SQLAlchemyError as e:
            logger.error(f"Database error deleting temp document: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error deleting temp document: {e}")
            return False


    def update_batch_status(self, batch_id: str, status: str, **kwargs) -> bool:
        """Update processing batch status and related fields."""
        try:
            with self.get_session() as session:
                from giani_pkb.models.database_models import ProcessingBatch
                
                batch = session.query(ProcessingBatch).filter(
                    ProcessingBatch.batch_id == batch_id
                ).first()
                
                if not batch:
                    logger.warning(f"Processing batch {batch_id} not found")
                    return False
                
                # Update status
                batch.status = status
                
                # Update timestamps based on status
                if status == 'PROCESSING' and not batch.started_at:
                    batch.started_at = datetime.utcnow()
                elif status in ['COMPLETED', 'FAILED'] and not batch.completed_at:
                    batch.completed_at = datetime.utcnow()
                
                # Update other fields if provided
                allowed_fields = {'processed_documents', 'failed_documents', 'error_details'}
                for key, value in kwargs.items():
                    if key in allowed_fields and hasattr(batch, key):
                        setattr(batch, key, value)
                
                session.flush()
                logger.info(f"Updated batch {batch_id} status to {status}")
                return True
                
        except SQLAlchemyError as e:
            logger.error(f"Database error updating batch status: {e}")
            return False

    def get_processing_batch(self, batch_id: str) -> Optional[Dict[str, Any]]:
        """Get processing batch by ID."""
        try:
            with self.get_session() as session:
                from giani_pkb.models.database_models import ProcessingBatch
                
                batch = session.query(ProcessingBatch).filter(
                    ProcessingBatch.batch_id == batch_id
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
                    'processed_documents': batch.processed_documents,
                    'failed_documents': batch.failed_documents,
                    'error_details': batch.error_details
                }
                
        except SQLAlchemyError as e:
            logger.error(f"Database error getting processing batch: {e}")
            return None

    def get_batch_status(self, batch_id: str, user_id: Union[str, uuid.UUID] = None) -> Optional[Dict[str, Any]]:
        """
        Get the current status of a processing batch.
        
        Args:
            batch_id: ID of the batch to check
            user_id: Optional user ID for access control
            
        Returns:
            Dictionary containing batch status information or None if not found
        """
        try:
            with self.get_session() as session:
                from giani_pkb.models.database_models import ProcessingBatch
                
                # Convert user_id to UUID if provided and is string
                if user_id and isinstance(user_id, str):
                    try:
                        user_id = uuid.UUID(user_id)
                    except ValueError as e:
                        logger.error(f"Invalid UUID format for user_id: {user_id}")
                        return None
                
                # Build query with optional user access control
                query = session.query(ProcessingBatch).filter(
                    ProcessingBatch.batch_id == batch_id
                )
                
                if user_id:
                    query = query.filter(ProcessingBatch.user_id == user_id)
                
                batch = query.first()
                
                if not batch:
                    logger.warning(f"Batch {batch_id} not found" + 
                                (f" for user {user_id}" if user_id else ""))
                    return None
                
                # Calculate progress percentage
                total_docs = batch.total_documents
                processed_docs = batch.processed_documents
                failed_docs = batch.failed_documents
                
                progress_percentage = 0
                if total_docs > 0:
                    progress_percentage = ((processed_docs + failed_docs) / total_docs) * 100
                
                # Determine if batch is complete
                is_complete = (processed_docs + failed_docs) >= total_docs
                
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
                    'processed_documents': batch.processed_documents,
                    'failed_documents': batch.failed_documents,
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
        """Increment batch progress counters."""
        try:
            with self.get_session() as session:
                from giani_pkb.models.database_models import ProcessingBatch
                
                batch = session.query(ProcessingBatch).filter(
                    ProcessingBatch.batch_id == batch_id
                ).first()
                
                if not batch:
                    logger.warning(f"Processing batch {batch_id} not found")
                    return False
                
                if success:
                    batch.processed_documents += 1
                else:
                    batch.failed_documents += 1
                
                # Check if batch is complete
                total_processed = batch.processed_documents + batch.failed_documents
                if total_processed >= batch.total_documents:
                    batch.status = 'COMPLETED'
                    if not batch.completed_at:
                        batch.completed_at = datetime.utcnow()
                
                session.flush()
                logger.info(f"Updated batch {batch_id} progress: {total_processed}/{batch.total_documents}")
                return True
                
        except SQLAlchemyError as e:
            logger.error(f"Database error updating batch progress: {e}")
            return False


    
    def create_temp_document(self, **kwargs) -> Optional[Dict[str, Any]]:
        """
        Create a new temporary document.
        
        Args:
            **kwargs: Document data including temp_document_id, project_id, user_id, 
                    original_filename, file_path, file_size, mime_type, text_preview, status
            
        Returns:
            Dictionary containing created document data or None if failed
        """
        try:
            with self.get_session() as session:
                from giani_pkb.models.database_models import TempDocument
                
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

                # Create the temporary document
                temp_document = TempDocument(**kwargs)
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


    def get_temp_document(self, temp_document_id: str, project_id: int, user_id: Union[str, uuid.UUID]) -> Optional[Dict[str, Any]]:
        """
        Get temporary document by ID with project and user access verification.
        
        Args:
            temp_document_id: ID of the temporary document (string)
            project_id: Project ID for access control
            user_id: User ID for access control (string or UUID)
            
        Returns:
            Dictionary containing document data or None if not found
        """
        try:
            with self.get_session() as session:
                # Import TempDocument here to avoid circular imports
                from giani_pkb.models.database_models import TempDocument
                
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
                        TempDocument.temp_document_id == temp_document_id,
                        TempDocument.project_id == project_id,
                        TempDocument.user_id == user_id
                    )
                ).first()
                
                if not temp_document:
                    logger.warning(f"Temp document {temp_document_id} not found or access denied for user {user_id}")
                    return None
                
                # Convert to dictionary format expected by your application
                temp_doc = {
                    'id': temp_document.id,
                    'temp_document_id': temp_document.temp_document_id,
                    'original_filename': temp_document.original_filename,
                    'text_preview': temp_document.text_preview or 'No preview available',
                    'file_path': temp_document.file_path,
                    'file_size': temp_document.file_size,
                    'mime_type': temp_document.mime_type,
                    'upload_timestamp': temp_document.upload_timestamp,
                    'status': temp_document.status,
                    'project_id': temp_document.project_id,
                    'user_id': str(temp_document.user_id)  # Convert UUID back to string for JSON serialization
                }
                
                logger.info(f"Retrieved temp document: {temp_document.original_filename}")
                return temp_doc
                
        except SQLAlchemyError as e:
            logger.error(f"Database error getting temp document: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error getting temp document: {e}")
            return None




    # Document Operations
    def create_document(self, **kwargs) -> Document:
        """Create a new document with validation."""
        try:
            with self.get_session() as session:
                # Verify user and project exist
                user = session.query(User).filter(
                    and_(User.id == kwargs.get('user_id'), User.is_active == True)
                ).first()
                if not user:
                    raise ValidationError(f"User with ID {kwargs.get('user_id')} not found")

                project = session.query(Project).filter(
                    and_(Project.id == kwargs.get('project_id'), Project.is_active == True)
                ).first()
                if not project:
                    raise ValidationError(f"Project with ID {kwargs.get('project_id')} not found")

                document = Document(**kwargs)
                session.add(document)
                session.flush()

                # Detach from session
                session.expunge(document)

                logger.info(f"Created document: {document.original_filename}")
                return document

        except SQLAlchemyError as e:
            logger.error(f"Database error creating document: {e}")
            raise DatabaseError(f"Failed to create document: {e}")

    def get_document_by_id(self, document_id: int, user_id: int = None) -> Optional[Document]:
        """Get document by ID with optional user access check."""
        try:
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

    def get_project_documents(self, project_id: int, user_id: int = None) -> List[Document]:
        """Get all documents for a project with optimized query."""
        try:
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

    def search_documents(self, search_term: str, user_id: int = None) -> List[Document]:
        """Search documents with optimized full-text search."""
        try:
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

    def update_document(self, document_id: int, user_id: int, **kwargs) -> Optional[Document]:
        """Update document fields with ownership verification."""
        try:
            with self.get_session() as session:
                document = session.query(Document).filter(
                    and_(Document.id == document_id, Document.user_id == user_id)
                ).first()

                if not document:
                    raise NotFoundError(f"Document with ID {document_id} not found or access denied")

                # Update allowed fields
                allowed_fields = {
                    'final_category', 'final_purpose', 'priority', 'text_preview',
                    'processed_content', 'extracted_text', 'metadata'
                }
                for key, value in kwargs.items():
                    if key in allowed_fields and hasattr(document, key):
                        setattr(document, key, value)

                document.updated_at = datetime.utcnow()
                session.flush()

                # Detach from session
                session.expunge(document)

                logger.info(f"Updated document: {document.original_filename}")
                return document

        except SQLAlchemyError as e:
            logger.error(f"Database error updating document: {e}")
            raise DatabaseError(f"Failed to update document: {e}")

    def delete_document(self, document_id: int, user_id: int) -> bool:
        """Delete document with ownership verification."""
        try:
            with self.get_session() as session:
                document = session.query(Document).filter(
                    and_(Document.id == document_id, Document.user_id == user_id)
                ).first()

                if not document:
                    raise NotFoundError(f"Document with ID {document_id} not found or access denied")

                # Delete related chunks and summaries
                session.query(DocumentChunk).filter(DocumentChunk.document_id == document_id).delete()
                session.query(DocumentSummary).filter(DocumentSummary.document_id == document_id).delete()

                # Delete document
                session.delete(document)

                logger.info(f"Deleted document: {document.original_filename}")
                return True

        except SQLAlchemyError as e:
            logger.error(f"Database error deleting document: {e}")
            raise DatabaseError(f"Failed to delete document: {e}")

    # Document Chunk Operations
    def create_document_chunk(self, **kwargs) -> DocumentChunk:
        """Create a new document chunk."""
        try:
            with self.get_session() as session:
                chunk = DocumentChunk(**kwargs)
                session.add(chunk)
                session.flush()
                
                # Detach from session
                session.expunge(chunk)
                
                return chunk

        except SQLAlchemyError as e:
            logger.error(f"Database error creating document chunk: {e}")
            raise DatabaseError(f"Failed to create document chunk: {e}")

    def get_document_chunks(self, document_id: int) -> List[DocumentChunk]:
        """Get all chunks for a document."""
        try:
            with self.get_session() as session:
                chunks = session.query(DocumentChunk).filter(
                    DocumentChunk.document_id == document_id
                ).order_by(asc(DocumentChunk.id)).all()
                
                # Detach all chunks from session
                for chunk in chunks:
                    session.expunge(chunk)
                    
                return chunks

        except SQLAlchemyError as e:
            logger.error(f"Database error getting document chunks: {e}")
            return []

    # Document Summary Operations
    def create_document_summary(self, **kwargs) -> DocumentSummary:
        """Create a new document summary."""
        try:
            with self.get_session() as session:
                summary = DocumentSummary(**kwargs)
                session.add(summary)
                session.flush()
                
                # Detach from session
                session.expunge(summary)
                
                return summary

        except SQLAlchemyError as e:
            logger.error(f"Database error creating document summary: {e}")
            raise DatabaseError(f"Failed to create document summary: {e}")

    def get_document_summaries(self, document_id: int) -> List[DocumentSummary]:
        """Get all summaries for a document."""
        try:
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

    # API Call Logging
    def log_api_call(self, **kwargs) -> APICallLog:
        """Log an API call for monitoring and debugging."""
        try:
            with self.get_session() as session:
                # Get next call number
                last_call = session.query(APICallLog).order_by(desc(APICallLog.call_number)).first()
                call_number = (last_call.call_number + 1) if last_call else 1

                api_log = APICallLog(call_number=call_number, **kwargs)
                session.add(api_log)
                session.flush()
                
                # Detach from session
                session.expunge(api_log)
                
                return api_log

        except SQLAlchemyError as e:
            logger.error(f"Database error logging API call: {e}")
            raise DatabaseError(f"Failed to log API call: {e}")

    def get_api_call_logs(self, limit: int = 100) -> List[APICallLog]:
        """Get recent API call logs."""
        try:
            with self.get_session() as session:
                logs = session.query(APICallLog).order_by(
                    desc(APICallLog.timestamp)
                ).limit(limit).all()
                
                # Detach all logs from session
                for log in logs:
                    session.expunge(log)
                    
                return logs

        except SQLAlchemyError as e:
            logger.error(f"Database error getting API call logs: {e}")
            return []

    # Statistics and Analytics
    def get_database_statistics(self) -> Dict[str, Any]:
        """Get comprehensive database statistics."""
        try:
            with self.get_session() as session:
                stats = {
                    'users': session.query(func.count(User.id)).filter(User.is_active == True).scalar(),
                    'projects': session.query(func.count(Project.id)).filter(Project.is_active == True).scalar(),
                    'documents': session.query(func.count(Document.id)).scalar(),
                    'document_chunks': session.query(func.count(DocumentChunk.id)).scalar(),
                    'document_summaries': session.query(func.count(DocumentSummary.id)).scalar(),
                    'api_call_logs': session.query(func.count(APICallLog.id)).scalar()
                }

                # Get recent activity
                recent_documents = session.query(func.count(Document.id)).filter(
                    Document.date_added_to_giani >= datetime.utcnow().date()
                ).scalar()
                stats['documents_today'] = recent_documents

                return stats

        except SQLAlchemyError as e:
            logger.error(f"Database error getting statistics: {e}")
            return {}

    def verify_database_integrity(self) -> bool:
        """Verify database integrity and relationships."""
        try:
            with self.get_session() as session:
                # Check for orphaned records
                orphaned_documents = session.query(Document).filter(
                    ~Document.user_id.in_(session.query(User.id))
                ).count()

                orphaned_projects = session.query(Project).filter(
                    ~Project.owner_id.in_(session.query(User.id))
                ).count()

                if orphaned_documents > 0 or orphaned_projects > 0:
                    logger.warning(f"Found orphaned records: {orphaned_documents} documents, {orphaned_projects} projects")
                    return False

                return True

        except SQLAlchemyError as e:
            logger.error(f"Database integrity check failed: {e}")
            return False
