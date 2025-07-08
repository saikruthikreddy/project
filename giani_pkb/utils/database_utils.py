"""
Database utilities for managing database operations and table creation.
"""
import logging
from typing import Optional, List, Dict, Any
import uuid

from giani_pkb.database.database_manager import DatabaseManager

logger = logging.getLogger(__name__)

class DatabaseUtils:
    """Database utility class for managing database operations."""

    def __init__(self):
        self.db_manager = DatabaseManager()

    def create_document_tables(self):
        """Create document-related tables if they don't exist."""
        try:
            # DatabaseManager handles table creation automatically
            # This method is kept for backward compatibility
            logger.info("Document tables creation handled by DatabaseManager")
            return True

        except Exception as e:
            logger.error(f"Error creating document tables: {e}")
            raise

    def verify_project_access(self, project_id: str, user_id: str) -> bool:
        """Verify user has access to the project."""
        try:
            project = self.db_manager.get_project(uuid.UUID(project_id) if isinstance(project_id, str) else project_id, uuid.UUID(user_id) if isinstance(user_id, str) else user_id)
            return project is not None
        except Exception as e:
            logger.error(f"Error verifying project access: {e}")
            return False

    def verify_user_exists(self, user_id: str) -> bool:
        """Verify if user exists in database."""
        try:
            user = self.db_manager.get_user(uuid.UUID(user_id) if isinstance(user_id, str) else user_id)
            return user is not None
        except Exception as e:
            logger.error(f"Error verifying user exists: {e}")
            return False

    def update_user_projects_list(self, user_id: str, project_name: str, operation: str = 'add') -> bool:
        """Update the projects list in users table."""
        try:
            if operation == 'add':
                success = self.db_manager.add_user_project(uuid.UUID(user_id) if isinstance(user_id, str) else user_id, project_name)
            elif operation == 'remove':
                success = self.db_manager.remove_user_project(uuid.UUID(user_id) if isinstance(user_id, str) else user_id, project_name)
            else:
                logger.error(f"Invalid operation: {operation}")
                return False

            return success
        except Exception as e:
            logger.error(f"Error updating user projects list: {e}")
            return False

    def get_temp_document(self, temp_document_id: str, project_id: str, user_id: str) -> Optional[Dict[str, Any]]:
        """Get temporary document information."""
        try:
            # TODO: Implement temp_document retrieval in DatabaseManager
            # temp_doc = self.db_manager.get_temp_document(temp_document_id, int(project_id), int(user_id))

            # For now, return None as placeholder
            logger.warning("get_temp_document not yet implemented in DatabaseManager")
            return None
        except Exception as e:
            logger.error(f"Error getting temp document: {e}")
            return None

    def update_temp_document_status(self, temp_document_id: str, status: str) -> bool:
        """Update temporary document status."""
        try:
            # TODO: Implement temp_document status update in DatabaseManager
            # success = self.db_manager.update_temp_document_status(temp_document_id, status)

            # For now, return True as placeholder
            logger.warning("update_temp_document_status not yet implemented in DatabaseManager")
            return True
        except Exception as e:
            logger.error(f"Error updating temp document status: {e}")
            return False

    def create_processing_batch(self, batch_id: str, project_id: str, user_id: str, total_documents: int) -> bool:
        """Create a new processing batch."""
        try:
            # TODO: Implement batch creation in DatabaseManager
            # success = self.db_manager.create_processing_batch(
            #     batch_id, int(project_id), int(user_id), total_documents
            # )

            # For now, return True as placeholder
            logger.warning("create_processing_batch not yet implemented in DatabaseManager")
            return True
        except Exception as e:
            logger.error(f"Error creating processing batch: {e}")
            return False

    def update_batch_status(self, batch_id: str, status: str, processed_documents: int = 0) -> bool:
        """Update batch processing status."""
        try:
            # TODO: Implement batch status update in DatabaseManager
            # success = self.db_manager.update_processing_batch(
            #     batch_id, status=status, processed_documents=processed_documents
            # )

            # For now, return True as placeholder
            logger.warning("update_batch_status not yet implemented in DatabaseManager")
            return True
        except Exception as e:
            logger.error(f"Error updating batch status: {e}")
            return False

    def get_batch_status(self, batch_id: str, user_id: str) -> Optional[Dict[str, Any]]:
        """Get batch processing status."""
        try:
            # TODO: Implement batch status retrieval in DatabaseManager
            # batch_info = self.db_manager.get_processing_batch(batch_id, int(user_id))

            # For now, return None as placeholder
            logger.warning("get_batch_status not yet implemented in DatabaseManager")
            return None
        except Exception as e:
            logger.error(f"Error getting batch status: {e}")
            return None

    def cleanup_temp_document(self, temp_document_id: str) -> bool:
        """Clean up temporary document."""
        try:
            # TODO: Implement temp_document cleanup in DatabaseManager
            # success = self.db_manager.delete_temp_document(temp_document_id)

            # For now, return True as placeholder
            logger.warning("cleanup_temp_document not yet implemented in DatabaseManager")
            return True
        except Exception as e:
            logger.error(f"Error cleaning up temp document: {e}")
            return False

    def get_document_statistics(self, project_id: str) -> Dict[str, Any]:
        """Get document statistics for a project."""
        try:
            stats = self.db_manager.get_project_statistics(uuid.UUID(project_id) if isinstance(project_id, str) else project_id)
            return stats
        except Exception as e:
            logger.error(f"Error getting document statistics: {e}")
            return {}

    def search_documents(self, project_id: str, query: str, category: str = None) -> List[Dict[str, Any]]:
        """Search documents within a project."""
        try:
            documents = self.db_manager.search_documents(
                search_term=query
            )
            return documents
        except Exception as e:
            logger.error(f"Error searching documents: {e}")
            return []

    def get_document_categories(self, project_id: str) -> List[str]:
        """Get unique document categories for a project."""
        try:
            categories = self.db_manager.get_document_categories(uuid.UUID(project_id) if isinstance(project_id, str) else project_id)
            return categories
        except Exception as e:
            logger.error(f"Error getting document categories: {e}")
            return []

    def backup_database(self, backup_path: str) -> bool:
        """Create a backup of the database."""
        try:
            success = self.db_manager.backup_database(backup_path)
            return success
        except Exception as e:
            logger.error(f"Error backing up database: {e}")
            return False

    def restore_database(self, backup_path: str) -> bool:
        """Restore database from backup."""
        try:
            success = self.db_manager.restore_database(backup_path)
            return success
        except Exception as e:
            logger.error(f"Error restoring database: {e}")
            return False

    def get_database_info(self) -> Dict[str, Any]:
        """Get database information and statistics."""
        try:
            info = self.db_manager.get_database_info()
            return info
        except Exception as e:
            logger.error(f"Error getting database info: {e}")
            return {}

    def optimize_database(self) -> bool:
        """Optimize database performance."""
        try:
            success = self.db_manager.optimize_database()
            return success
        except Exception as e:
            logger.error(f"Error optimizing database: {e}")
            return False

# Global instance
db_utils = DatabaseUtils()