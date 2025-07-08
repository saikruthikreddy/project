"""
Project service for handling project-related business logic.
"""

from datetime import datetime
from typing import Dict, List, Optional, Any
import logging
import uuid

from giani_pkb.services.metadata_manager import MetadataManagerService
from giani_pkb.services.classification import ClassificationService
from giani_pkb.database.database_manager import DatabaseManager
from giani_pkb.utils.exceptions import ProjectError, ValidationError

logger = logging.getLogger(__name__)


class ProjectService:
    """
    Service for handling project-related operations.
    """

    def __init__(self):
        self.db_manager = DatabaseManager()
        self.metadata_manager = MetadataManagerService()
        self.classification_service = ClassificationService()

    def create_project(
        self, user_id: str, project_name: str, description: str = None
    ) -> Dict[str, Any]:
        """Create a new project."""
        if not project_name.strip():
            raise ValidationError("Project name cannot be empty")

        try:
            project = self.db_manager.create_project(
                user_id=uuid.UUID(user_id) if isinstance(user_id, str) else user_id,
                project_name=project_name,
                description=description,
            )

            logger.info(f"Created project: {project_name} for user: {user_id}")
            return project

        except Exception as e:
            logger.error(f"Database error creating project: {e}")
            raise ProjectError(f"Failed to create project: {e}")

    def get_user_projects(self, user_id: str) -> List[Dict[str, Any]]:
        """Get all projects for a user."""
        try:
            projects = self.db_manager.get_user_projects(
                uuid.UUID(user_id) if isinstance(user_id, str) else user_id
            )
            return projects

        except Exception as e:
            logger.error(f"Database error getting projects: {e}")
            raise ProjectError(f"Failed to get projects: {e}")

    def get_project_details(
        self, project_id: str, user_id: str
    ) -> Optional[Dict[str, Any]]:
        """Get project details by ID."""
        try:
            project = self.db_manager.get_project(
                project_id, uuid.UUID(user_id) if isinstance(user_id, str) else user_id
            )
            return project

        except Exception as e:
            logger.error(f"Database error getting project details: {e}")
            raise ProjectError(f"Failed to get project details: {e}")

    def update_project(
        self, project_id: str, user_id: str, updates: Dict[str, Any]
    ) -> bool:
        """Update project details."""
        try:
            # Validate project access
            if not self.verify_project_access(project_id, user_id):
                raise ValidationError("Project not found or access denied")

            # Update project using database manager
            success = self.db_manager.update_project(
                project_id=project_id,
                user_id=uuid.UUID(user_id) if isinstance(user_id, str) else user_id,
                **updates,
            )

            if success:
                logger.info(f"Updated project: {project_id}")
                return True
            else:
                logger.error(f"Failed to update project: {project_id}")
                return False

        except Exception as e:
            logger.error(f"Database error updating project: {e}")
            raise ProjectError(f"Failed to update project: {e}")

    def delete_project(self, project_id: str, user_id: str) -> bool:
        """Delete a project (soft delete)."""
        try:
            # Validate project access
            if not self.verify_project_access(project_id, user_id):
                raise ValidationError("Project not found or access denied")

            # Soft delete project using database manager
            success = self.db_manager.delete_project(
                project_id, uuid.UUID(user_id) if isinstance(user_id, str) else user_id
            )

            if success:
                logger.info(f"Deleted project: {project_id}")
                return True
            else:
                logger.error(f"Failed to delete project: {project_id}")
                return False

        except Exception as e:
            logger.error(f"Database error deleting project: {e}")
            raise ProjectError(f"Failed to delete project: {e}")

    def verify_project_access(self, project_id: str, user_id: str) -> bool:
        """Verify if user has access to the project."""
        try:
            project = self.db_manager.get_project(
                project_id, uuid.UUID(user_id) if isinstance(user_id, str) else user_id
            )
            return project is not None

        except Exception as e:
            logger.error(f"Database error verifying project access: {e}")
            return False

    def get_project_documents(
        self, project_id: str, user_id: str
    ) -> List[Dict[str, Any]]:
        """Get all documents for a project."""
        try:
            # Verify project access
            if not self.verify_project_access(project_id, user_id):
                raise ValidationError("Project not found or access denied")

            # Get documents using database manager
            documents = self.db_manager.get_project_documents(project_id)

            return documents

        except Exception as e:
            logger.error(f"Database error getting project documents: {e}")
            raise ProjectError(f"Failed to get project documents: {e}")

    def get_project_statistics(self, project_id: str, user_id: str) -> Dict[str, Any]:
        """Get project statistics."""
        try:
            # Verify project access
            if not self.verify_project_access(project_id, user_id):
                raise ValidationError("Project not found or access denied")

            # Get project statistics using database manager
            stats = self.db_manager.get_project_statistics(project_id)

            return stats

        except Exception as e:
            logger.error(f"Database error getting project statistics: {e}")
            raise ProjectError(f"Failed to get project statistics: {e}")

    def search_project_documents(
        self, project_id: str, user_id: str, query: str, category: str = None
    ) -> List[Dict[str, Any]]:
        """Search documents within a project."""
        try:
            # Verify project access
            if not self.verify_project_access(project_id, user_id):
                raise ValidationError("Project not found or access denied")

            # Search documents using database manager
            documents = self.db_manager.search_documents(
                project_id=project_id, query=query, category=category
            )

            return documents

        except Exception as e:
            logger.error(f"Database error searching project documents: {e}")
            raise ProjectError(f"Failed to search project documents: {e}")

    def get_document_categories(self, project_id: str, user_id: str) -> List[str]:
        """Get unique document categories for a project."""
        try:
            # Verify project access
            if not self.verify_project_access(project_id, user_id):
                raise ValidationError("Project not found or access denied")

            # Get categories using database manager
            categories = self.db_manager.get_document_categories(project_id)

            return categories

        except Exception as e:
            logger.error(f"Database error getting document categories: {e}")
            raise ProjectError(f"Failed to get document categories: {e}")

    def export_project_data(self, project_id: str, user_id: str) -> Dict[str, Any]:
        """Export all project data."""
        try:
            # Verify project access
            if not self.verify_project_access(project_id, user_id):
                raise ValidationError("Project not found or access denied")

            # Get project details
            project = self.get_project_details(project_id, user_id)

            # Get project documents
            documents = self.get_project_documents(project_id, user_id)

            # Get project statistics
            statistics = self.get_project_statistics(project_id, user_id)

            export_data = {
                "project": project,
                "documents": documents,
                "statistics": statistics,
                "exported_at": datetime.now().isoformat(),
            }

            logger.info(f"Exported project data: {project_id}")
            return export_data

        except Exception as e:
            logger.error(f"Database error exporting project data: {e}")
            raise ProjectError(f"Failed to export project data: {e}")


def get_project_purpose(project_id: str) -> str:
    print("TODO: Implement this function", project_id)
    return project_id


def get_projects_for_user(user_id):
    print("TODO: Implement this function", user_id)
    return user_id
