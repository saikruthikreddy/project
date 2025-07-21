from flask import Blueprint, request
from giani_pkb.services.ppt_title_service import generate_titles
from giani_pkb.services.ppt_title_refine_service import refine_title
from giani_pkb.services.project_service import get_projects_for_user, get_project_purpose
from giani_pkb.services.ppt_slide_structure import generate_slide_structure
from giani_pkb.services.ppt_improve_selected_text_service import refine_selected_text
from giani_pkb.services.ppt_parallelize_content_service import parallelize_statements
from giani_pkb.services.slide_review_service import review_slide
from giani_pkb.utils.response_utils import (
    api_success,
    api_validation_error,
    api_internal_server_error
)

def create_ppt_routes():
    ppt_bp = Blueprint("ppt", __name__, url_prefix="/api/v1")

    @ppt_bp.route("/ppt/suggest-titles", methods=["POST"])
    def suggest_titles():
        try:
            payload = request.get_json()
            if not payload:
                return api_validation_error("No JSON payload provided")

            result = generate_titles(payload)

            return api_success(
                {
                    "refinedSuggestions": result.get("refinedSuggestions"),
                    "contextUsed": result.get("contextUsed")
                }
            )
        except Exception as e:
            return api_internal_server_error("Failed to generate slide titles", str(e))

    @ppt_bp.route("/projects/list-by-user", methods=["POST"])
    def list_user_projects():
        try:
            payload = request.get_json()
            if not payload:
                return api_validation_error("No JSON payload provided")

            user_id = payload.get("userID")
            if not user_id:
                return api_validation_error("Missing userID")

            projects = get_projects_for_user(user_id)

            return api_success({"projects": projects}, "Projects fetched")

        except Exception as e:
            return api_internal_server_error("Failed to fetch projects", str(e))

    @ppt_bp.route("/ppt/refine-title", methods=["POST"])
    def refine_title_endpoint():
        try:
            payload = request.get_json()
            if not payload:
                return api_validation_error("No JSON payload provided")

            project_id = payload.get("projectID", "")
            if project_id:
                payload["projectPurpose"] = get_project_purpose(project_id)

            result = refine_title(payload)

            return api_success(
                {
                    "refinedSuggestions": result.get("refinedSuggestions"),
                    "contextUsed": result.get("contextUsed")
                }
            )

        except Exception as e:
            return api_internal_server_error("Failed to refine title", str(e))

    @ppt_bp.route("/ppt/generate-slide-structure", methods=["POST"])
    def generate_slide_structure_endpoint():
        try:
            payload = request.get_json()
            if not payload:
                return api_validation_error("No JSON payload provided")

            result = generate_slide_structure(payload)

            return api_success(
                {
                    "structuredSlides": result.get("structuredSlideOutput"),
                    "contextUsed": result.get("contextUsed")
                }
            )

        except Exception as e:
            return api_internal_server_error("Failed to generate slide structure", str(e))

    @ppt_bp.route("/ppt/refine-selected-text", methods=["POST"])
    def refine_selected_text_endpoint():
        try:
            payload = request.get_json()
            if not payload:
                return api_validation_error("No JSON payload provided")

            project_id = payload.get("projectID", "")
            if project_id and not payload.get("currentProjectPurpose"):
                payload["currentProjectPurpose"] = get_project_purpose(project_id)

            result = refine_selected_text(payload)

            return api_success(
                {
                    "refinedText": result.get("refinedText"),
                    "contextUsed": result.get("contextUsed")
                }
            )

        except Exception as e:
            return api_internal_server_error("Failed to refine selected text", str(e))

    @ppt_bp.route("/ppt/parallelize-statements", methods=["POST"])
    def parallelize_statements_endpoint():
        try:
            payload = request.get_json()
            if not payload:
                return api_validation_error("No JSON payload provided")

            result = parallelize_statements(payload)

            return api_success(
                {
                    "parallelizedStatements": result.get("parallelizedStatements"),
                    "contextUsed": result.get("contextUsed")
                }
            )

        except Exception as e:
            return api_internal_server_error("Failed to parallelize statements", str(e))

    @ppt_bp.route("/ppt/review-slide", methods=["POST"])
    def review_slide_endpoint():
        try:
            payload = request.get_json()
            if not payload:
                return api_validation_error("No JSON payload provided")

            project_id = payload.get("projectID", "")
            if project_id and not payload.get("currentProjectPurpose"):
                payload["currentProjectPurpose"] = get_project_purpose(project_id)

            result = review_slide(payload)

            return api_success(
                {
                    "reviewSuggestions": result.get("reviewSuggestions"),
                    "contextUsed": result.get("contextUsed")
                }
            )

        except Exception as e:
            return api_internal_server_error("Failed to review slide", str(e))

    return ppt_bp
