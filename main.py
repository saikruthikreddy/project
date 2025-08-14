"""
Main application entry point for Giani AI Project Knowledge Base.
Updated with Analytics Middleware integration.
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from flask import Flask
from flask_cors import CORS

from giani_pkb.api import (
    create_auth_routes,
    create_project_routes,
    create_document_routes,
    create_user_routes,
    create_health_routes,
    create_ppt_routes,
    create_analytics_routes,
    create_onboarding_guide_routes
)
from giani_pkb.middleware.auth_session_middleware import AuthSessionMiddleware
from giani_pkb.utils.response_utils import api_success
from giani_pkb.utils.config import config
from giani_pkb.middleware.analytics_middleware import AnalyticsMiddleware


def create_app():
    """Application factory pattern for creating Flask app."""
    app = Flask(__name__)

    # Configure CORS for the combined app - IMPORTANT: No wildcard origins when using credentials
    CORS(
        app,
        resources={
            r"/api/v1/*": {
                "origins": config.CORS_ORIGINS,  # Must be specific origins, not '*'
                "supports_credentials": True,
                "allow_headers": [
                    "Content-Type",
                    "Authorization",
                    "X-Client-Type",
                    "X-Session-ID",
                ],
                "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
            },
            r"/auth/*": {
                "origins": config.CORS_ORIGINS,  # Must be specific origins, not '*'
                "supports_credentials": True,
                "allow_headers": [
                    "Content-Type",
                    "Authorization",
                    "X-Client-Type",
                    "X-Session-ID",
                ],
                "methods": ["GET", "POST", "OPTIONS"],
            },
        },
    )

    config.ensure_directories_exist()

    auth_session_middleware = AuthSessionMiddleware(app)
    analytics_middleware = AnalyticsMiddleware(app)

    # Register all route blueprints
    app.register_blueprint(create_auth_routes())
    app.register_blueprint(create_project_routes())
    app.register_blueprint(create_document_routes())
    app.register_blueprint(create_user_routes())
    app.register_blueprint(create_health_routes())
    app.register_blueprint(create_ppt_routes())
    app.register_blueprint(create_analytics_routes())
    app.register_blueprint(create_onboarding_guide_routes())

    @app.route("/")
    def home():
        """Root endpoint with API information."""
        return api_success(
            {
                "service": "Giani AI Project Knowledge Base",
                "version": "1.0.0",
                "endpoints": {
                    "auth": "/auth/*",
                    "api_v1": "/api/v1/*",
                    "health": "/api/v1/health/*",
                    "analytics": "/api/v1/analytics/*",  # Added analytics endpoint
                },
                "test_endpoints": [
                    "/api/v1/health/status",
                    "/auth/test",
                    "/api/v1/test",
                ],
                "documentation": {
                    "api_docs": "/api/v1/docs",
                    "health_check": "/api/v1/health/detailed",
                },
            },
            "Giani AI Project Knowledge Base API",
        )

    @app.route("/api/v1")
    def api_v1_root():
        """API v1 root endpoint."""
        return api_success(
            {
                "version": "1.0.0",
                "endpoints": {
                    "projects": "/api/v1/projects/*",
                    "documents": "/api/v1/documents/*",
                    "users": "/api/v1/users/*",
                    "health": "/api/v1/health/*",
                    "analytics": "/api/v1/analytics/*",  # Added analytics endpoint
                },
                "examples": {
                    "get_projects": "GET /api/v1/projects/",
                    "create_project": "POST /api/v1/projects/",
                    "search_documents": "POST /api/v1/documents/search",
                    "get_user_profile": "GET /api/v1/users/profile",
                    "get_user_analytics": "GET /api/v1/analytics/user/summary",
                },
            },
            "API v1 Root",
        )

    @app.route("/api/v1/test")
    def api_test():
        """Test endpoint for API v1."""
        return api_success(
            {
                "message": "API v1 is working!",
                "endpoints_available": [
                    "projects",
                    "documents",
                    "users",
                    "health",
                    "analytics",
                ],
            },
            "API v1 Test Endpoint",
        )

    return app


# Create the Flask application
app = create_app()

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
