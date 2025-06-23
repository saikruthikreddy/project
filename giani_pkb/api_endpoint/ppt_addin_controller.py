# api/ppt_addin_controller.py (API Controller)
# ================================
from flask import Blueprint, request, jsonify
from core.ppt_title_service import generate_titles
from core.ppt_title_refine_service import refine_title
from core.project_service import get_projects_for_user, get_project_purpose

ppt_bp = Blueprint("ppt", __name__)

# ✅ Endpoint to generate slide titles
@ppt_bp.route("/ppt/suggest-titles", methods=["POST"])
def suggest_titles():
    try:
        payload = request.get_json()
        
        # Validate required fields
        if not payload:
            return jsonify({"error": "No JSON payload provided"}), 400
            
        # Generate titles using the service
        result = generate_titles(payload)
        return jsonify(result)
        
    except Exception as e:
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500

# ✅ Endpoint to fetch all projects for a given user
@ppt_bp.route("/projects/list-by-user", methods=["POST"])
def list_user_projects():
    try:
        payload = request.get_json()
        
        if not payload:
            return jsonify({"error": "No JSON payload provided"}), 400
            
        user_id = payload.get("userID")
        
        if not user_id:
            return jsonify({"error": "Missing userID"}), 400

        projects = get_projects_for_user(user_id)
        return jsonify({"projects": projects})
        
    except Exception as e:
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500

# ✅ Endpoint to refine slide titles
@ppt_bp.route("/ppt/refine-title", methods=["POST"])
def refine_title_endpoint():
    try:
        payload = request.get_json()
        
        if not payload:
            return jsonify({"error": "No JSON payload provided"}), 400
            
        project_id = payload.get("projectID", "")

        # Get project purpose from CSV DB and inject into payload
        if project_id:
            project_purpose = get_project_purpose(project_id)
            payload["projectPurpose"] = project_purpose

        result = refine_title(payload)
        return jsonify(result)
        
    except Exception as e:
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500
