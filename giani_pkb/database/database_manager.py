"""
Unified database manager using SQLAlchemy ORM for all database operations.
"""
import logging
from typing import Optional, List, Dict, Any
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

    def update_user(self, user_id: int, **kwargs) -> Optional[User]:
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
    def create_project(self, name: str, owner_id: int, description: str = None) -> Project:
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
                    project_id = uuid.UUID(project_id)
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