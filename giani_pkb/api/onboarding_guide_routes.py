"""
API routes for generating the Project Onboarding Guide.
Enhanced with better error handling and validation.
"""

from flask import Blueprint, jsonify, request
import logging
from giani_pkb.database.database_manager import DatabaseManager
from giani_pkb.services.onboarding_guide_service import OnboardingGuideGenerator

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
            return jsonify({
                "error": "Invalid project_id",
                "details": "project_id must be a positive integer"
            }), 400

        db_manager = None
        try:
            db_manager = DatabaseManager()
            onboarding_guide_generator = OnboardingGuideGenerator(db_manager)
            
            # Generate the onboarding guide
            onboarding_guide = onboarding_guide_generator.generate_onboarding_guide(project_id)
            
            # Check if the guide contains a fatal error
            if "error" in onboarding_guide and "details" in onboarding_guide:
                logger.error(f"Failed to generate onboarding guide for project {project_id}: {onboarding_guide['details']}")
                return jsonify(onboarding_guide), 500
            
            # Log successful generation
            synthesis_status = onboarding_guide.get("synthesisStatus", {})
            total_time = synthesis_status.get("totalTime", 0)
            errors = synthesis_status.get("errors", {})
            successful_sections = synthesis_status.get("successfulSections", [])
            
            logger.info(f"Onboarding guide generated for project {project_id} in {total_time}s. "
                       f"Successful sections: {len(successful_sections)}, Errors: {len(errors)}")
            
            # Return the guide with appropriate status code
            # If there are partial errors but some sections succeeded, return 200 with warnings
            if errors and successful_sections:
                return jsonify(onboarding_guide), 200  # Partial success
            elif errors and not successful_sections:
                return jsonify(onboarding_guide), 500  # Complete failure
            else:
                return jsonify(onboarding_guide), 200  # Complete success
                
        except ValueError as ve:
            # Handle configuration errors (e.g., missing API key)
            error_response = {
                "error": "Configuration error",
                "details": str(ve),
                "projectId": project_id
            }
            logger.error(f"Configuration error for project {project_id}: {ve}")
            return jsonify(error_response), 500
            
        except Exception as e:
            # Handle any other unexpected errors
            error_response = {
                "error": "Internal server error",
                "details": "An unexpected error occurred while generating the onboarding guide",
                "projectId": project_id
            }
            logger.exception(f"Unexpected error generating onboarding guide for project {project_id}")
            return jsonify(error_response), 500
            
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
            return jsonify({
                "error": "Invalid project_id",
                "details": "project_id must be a positive integer"
            }), 400

        try:
            db_manager = DatabaseManager()
            
            # Check if project exists
            project = db_manager.get_project(project_id)
            if not project:
                return jsonify({
                    "error": "Project not found",
                    "projectId": project_id
                }), 404
            
            # Check document availability
            documents = db_manager.get_project_documents(project_id)
            document_count = len(documents) if documents else 0
            
            # Check for document summaries
            summaries_available = 0
            if hasattr(db_manager, 'get_all_summaries_for_project'):
                summaries = db_manager.get_all_summaries_for_project(project_id)
                summaries_available = len(summaries) if summaries else 0
            
            status = {
                "projectId": project_id,
                "projectName": project.name if hasattr(project, 'name') else "Unknown",
                "documentsAvailable": document_count,
                "summariesAvailable": summaries_available,
                "canGenerateGuide": summaries_available > 0,
                "estimatedGenerationTime": f"{max(10, summaries_available * 2)}s" if summaries_available > 0 else "N/A"
            }
            
            return jsonify(status), 200
            
        except Exception as e:
            logger.exception(f"Error checking status for project {project_id}")
            return jsonify({
                "error": "Failed to check project status",
                "details": str(e),
                "projectId": project_id
            }), 500

    return onboarding_guide_bp
