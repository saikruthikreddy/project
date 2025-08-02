"""
API routes for generating the Project Onboarding Guide.
Enhanced with better error handling and validation using standardized responses.
"""

from flask import Blueprint, request
import logging
from giani_pkb.database.database_manager import DatabaseManager
from giani_pkb.services.onboarding_guide_service import OnboardingGuideGenerator
from giani_pkb.utils.response_utils import (
    api_authorization_error, api_error, api_success, api_validation_error, api_not_found_error,
    api_database_error, api_file_processing_error, api_internal_server_error
)


def create_onboarding_guide_routes():
    """Create a Flask Blueprint for the onboarding guide routes."""
    onboarding_guide_bp = Blueprint("onboarding_guide_api", __name__, url_prefix="/api/v1")
    logger = logging.getLogger(__name__)

    @onboarding_guide_bp.route("/projects/<int:project_id>/onboarding-guide", methods=["GET"])
    def get_onboarding_guide(project_id: int):
        """
        Generates and returns the Project Onboarding Guide for a given project_id.
        
        Returns:
            JSON response containing the onboarding guide or error information
        """
        # Validate project_id
        if project_id <= 0:
            return api_validation_error(
                message="Invalid project_id",
                details="project_id must be a positive integer"
            )

        db_manager = None
        try:
            db_manager = DatabaseManager()
            onboarding_guide_generator = OnboardingGuideGenerator(db_manager)
            
            # Generate the onboarding guide
            onboarding_guide = onboarding_guide_generator.generate_onboarding_guide(project_id)
            
            # Check if the guide contains a fatal error
            if "error" in onboarding_guide and "details" in onboarding_guide:
                logger.error(f"Failed to generate onboarding guide for project {project_id}: {onboarding_guide['details']}")
                return api_internal_server_error(
                    message="Failed to generate onboarding guide",
                    details=onboarding_guide['details']
                )
            
            # Log successful generation
            synthesis_status = onboarding_guide.get("synthesisStatus", {})
            total_time = synthesis_status.get("totalTime", 0)
            errors = synthesis_status.get("errors", {})
            successful_sections = synthesis_status.get("successfulSections", [])
            
            logger.info(f"Onboarding guide generated for project {project_id} in {total_time}s. "
                       f"Successful sections: {len(successful_sections)}, Errors: {len(errors)}")
            
            # Return the guide with appropriate success message
            if errors and successful_sections:
                # Partial success
                return api_success(
                    data=onboarding_guide,
                    message=f"Onboarding guide generated with some warnings. {len(successful_sections)} sections completed successfully.",
                    status_code=200
                )
            elif errors and not successful_sections:
                # Complete failure but with structured response
                return api_internal_server_error(
                    message="Failed to generate any sections of the onboarding guide",
                    details=f"All {len(errors)} attempted sections failed"
                )
            else:
                # Complete success
                return api_success(
                    data=onboarding_guide,
                    message=f"Onboarding guide generated successfully in {total_time}s",
                    status_code=200
                )
                
        except ValueError as ve:
            # Handle configuration errors (e.g., missing API key)
            logger.error(f"Configuration error for project {project_id}: {ve}")
            return api_configuration_error(
                message="Configuration error",
                details=str(ve)
            )
            
        except Exception as e:
            # Handle any other unexpected errors
            logger.exception(f"Unexpected error generating onboarding guide for project {project_id}")
            return api_internal_server_error(
                message="An unexpected error occurred while generating the onboarding guide",
                details=str(e)
            )
            
        finally:
            # Clean up database connection if needed
            if db_manager:
                try:
                    db_manager.close_connection()  # Assuming this method exists
                except AttributeError:
                    pass  # Method doesn't exist, no cleanup needed

    @onboarding_guide_bp.route("/projects/<int:project_id>/onboarding-guide/status", methods=["GET"])
    def get_onboarding_guide_status(project_id: int):
        """
        Returns the status of onboarding guide generation capabilities for a project.
        Useful for checking if a project has the necessary documents before generating.
        """
        if project_id <= 0:
            return api_validation_error(
                message="Invalid project_id",
                details="project_id must be a positive integer"
            )

        db_manager = None
        try:
            db_manager = DatabaseManager()
            
            # Check if project exists
            project = db_manager.get_project(project_id)
            if not project:
                return api_not_found_error(
                    message="Project not found",
                    details=f"No project found with ID {project_id}"
                )
            
            # Check document availability
            documents = db_manager.get_project_documents(project_id)
            document_count = len(documents) if documents else 0
            
            # Check for document summaries
            summaries_available = 0
            if hasattr(db_manager, 'get_all_summaries_for_project'):
                summaries = db_manager.get_all_summaries_for_project(project_id)
                summaries_available = len(summaries) if summaries else 0
            
            status_data = {
                "projectId": project_id,
                "projectName": project.name if hasattr(project, 'name') else "Unknown",
                "documentsAvailable": document_count,
                "summariesAvailable": summaries_available,
                "canGenerateGuide": summaries_available > 0,
                "estimatedGenerationTime": f"{max(10, summaries_available * 2)}s" if summaries_available > 0 else "N/A"
            }
            
            message = "Project status retrieved successfully"
            if not status_data["canGenerateGuide"]:
                message += ". Warning: No document summaries available for guide generation."
            
            return api_success(
                data=status_data,
                message=message,
                status_code=200
            )
            
        except Exception as e:
            logger.exception(f"Error checking status for project {project_id}")
            return api_database_error(
                message="Failed to check project status",
                details=str(e)
            )
            
        finally:
            # Clean up database connection if needed
            if db_manager:
                try:
                    db_manager.close_connection()
                except AttributeError:
                    pass

    return onboarding_guide_bp
