"""
API routes for generating the Project Onboarding Guide.
"""

from flask import Blueprint, jsonify
from giani_pkb.database.database_manager import DatabaseManager
from giani_pkb.services.onboarding_guide_service import OnboardingGuideGenerator

def create_onboarding_guide_routes():
    """Create a Flask Blueprint for the onboarding guide routes."""
    onboarding_guide_bp = Blueprint("onboarding_guide_api", __name__, url_prefix="/api/v1")

    @onboarding_guide_bp.route("/projects/<int:project_id>/onboarding-guide", methods=["GET"])
    def get_onboarding_guide(project_id: int):
        """
        Generates and returns the Project Onboarding Guide for a given project_id.
        """
        db_manager = DatabaseManager()
        onboarding_guide_generator = OnboardingGuideGenerator(db_manager)

        try:
            onboarding_guide = onboarding_guide_generator.generate_onboarding_guide(project_id)
            return jsonify(onboarding_guide)
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    return onboarding_guide_bp
