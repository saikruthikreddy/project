"""
Main application entry point for Giani AI Project Knowledge Base.
"""
from flask import Flask, request, jsonify
from flask_cors import CORS
from giani_pkb.api import (
    create_auth_routes,
    create_project_routes,
    create_document_routes,
    create_user_routes,
    create_health_routes,
    create_ppt_routes
)
from giani_pkb.utils.response_utils import api_success
from giani_pkb.utils.config import config

def create_app():
    """Application factory pattern for creating Flask app."""
    app = Flask(__name__)
    
    # Configure CORS for the combined app - IMPORTANT: No wildcard origins when using credentials
    CORS(app,
         resources={
             r"/api/v1/*": {
                 "origins": config.CORS_ORIGINS,  # Must be specific origins, not '*'
                 "supports_credentials": True,
                 "allow_headers": ["Content-Type", "Authorization", "X-Client-Type"],
                 "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"]
             },
             r"/auth/*": {
                 "origins": config.CORS_ORIGINS,  # Must be specific origins, not '*'
                 "supports_credentials": True,
                 "allow_headers": ["Content-Type", "Authorization", "X-Client-Type"],
                 "methods": ["GET", "POST", "OPTIONS"]
             }
         })
    
    # Global preflight OPTIONS handler
    @app.before_request
    def handle_preflight():
        """Handle preflight OPTIONS requests globally."""
        if request.method == "OPTIONS":
            # Debug logging
            print(f"OPTIONS request received for: {request.path}")
            print(f"Origin: {request.headers.get('Origin')}")
            print(f"Allowed origins: {config.CORS_ORIGINS}")
            
            # Get the origin from the request
            origin = request.headers.get('Origin')
            
            # Check if origin is allowed - FIXED: Ensure no wildcard when credentials are used
            allowed_origins = config.CORS_ORIGINS
            
            # Never allow wildcard '*' for credentialed requests
            if origin and origin in allowed_origins and '*' not in allowed_origins:
                response = jsonify({'status': 'OK'})
                response.headers.add('Access-Control-Allow-Origin', origin)  # Specific origin, not '*'
                response.headers.add('Access-Control-Allow-Headers', 
                                   'Content-Type, Authorization, X-Client-Type, X-Requested-With')
                response.headers.add('Access-Control-Allow-Methods', 
                                   'GET, POST, PUT, DELETE, OPTIONS, PATCH')
                response.headers.add('Access-Control-Allow-Credentials', 'true')
                response.headers.add('Access-Control-Max-Age', '86400')  # 24 hours
                print(f"Returning 200 with CORS headers for origin: {origin}")
                return response
            else:
                # If origin not allowed or wildcard detected, return 403
                print(f"Origin not allowed or wildcard detected: {origin}")
                return jsonify({'error': 'Origin not allowed'}), 403
    
    # Alternative: Route-specific OPTIONS handlers
    @app.route('/api/v1/<path:path>', methods=['OPTIONS'])
    def handle_api_options(path):
        """Handle OPTIONS requests for API v1 routes."""
        origin = request.headers.get('Origin')
        # FIXED: Check for specific origin, not wildcard
        if origin and origin in config.CORS_ORIGINS and '*' not in config.CORS_ORIGINS:
            response = jsonify({'status': 'OK'})
            response.headers.add('Access-Control-Allow-Origin', origin)  # Specific origin
            response.headers.add('Access-Control-Allow-Headers', 
                               'Content-Type, Authorization, X-Client-Type')
            response.headers.add('Access-Control-Allow-Methods', 
                               'GET, POST, PUT, DELETE, OPTIONS')
            response.headers.add('Access-Control-Allow-Credentials', 'true')
            return response
        return jsonify({'error': 'Origin not allowed'}), 403
    
    @app.route('/auth/<path:path>', methods=['OPTIONS'])
    def handle_auth_options(path):
        """Handle OPTIONS requests for auth routes."""
        origin = request.headers.get('Origin')
        # FIXED: Check for specific origin, not wildcard
        if origin and origin in config.CORS_ORIGINS and '*' not in config.CORS_ORIGINS:
            response = jsonify({'status': 'OK'})
            response.headers.add('Access-Control-Allow-Origin', origin)  # Specific origin
            response.headers.add('Access-Control-Allow-Headers', 
                               'Content-Type, Authorization, X-Client-Type')
            response.headers.add('Access-Control-Allow-Methods', 
                               'GET, POST, OPTIONS')
            response.headers.add('Access-Control-Allow-Credentials', 'true')
            return response
        return jsonify({'error': 'Origin not allowed'}), 403
    
    # Add after_request handler to ensure consistent CORS headers
    # @app.after_request
    # def after_request(response):
    #     """Add CORS headers to all responses."""
    #     origin = request.headers.get('Origin')
        
    #     # Only add CORS headers if origin is allowed and not wildcard
    #     if origin and origin in config.CORS_ORIGINS and '*' not in config.CORS_ORIGINS:
    #         response.headers.add('Access-Control-Allow-Origin', origin)
    #         response.headers.add('Access-Control-Allow-Credentials', 'true')
    #         response.headers.add('Access-Control-Allow-Headers', 
    #                            'Content-Type, Authorization, X-Client-Type')
    #         response.headers.add('Access-Control-Allow-Methods', 
    #                            'GET, POST, PUT, DELETE, OPTIONS, PATCH')
        
    #     return response
    
    # Ensure directories exist
    config.ensure_directories_exist()
    
    # Register all route blueprints
    app.register_blueprint(create_auth_routes())
    app.register_blueprint(create_project_routes())
    app.register_blueprint(create_document_routes())
    app.register_blueprint(create_user_routes())
    app.register_blueprint(create_health_routes())
    app.register_blueprint(create_ppt_routes())
    
    @app.route('/')
    def home():
        """Root endpoint with API information."""
        return api_success({
            "service": "Giani AI Project Knowledge Base",
            "version": "1.0.0",
            "endpoints": {
                "auth": "/auth/*",
                "api_v1": "/api/v1/*",
                "health": "/api/v1/health/*"
            },
            "test_endpoints": [
                "/api/v1/health/status",
                "/auth/test",
                "/api/v1/test"
            ],
            "documentation": {
                "api_docs": "/api/v1/docs",
                "health_check": "/api/v1/health/detailed"
            }
        }, "Giani AI Project Knowledge Base API")
    
    @app.route('/api/v1')
    def api_v1_root():
        """API v1 root endpoint."""
        return api_success({
            "version": "1.0.0",
            "endpoints": {
                "projects": "/api/v1/projects/*",
                "documents": "/api/v1/documents/*",
                "users": "/api/v1/users/*",
                "health": "/api/v1/health/*"
            },
            "examples": {
                "get_projects": "GET /api/v1/projects/",
                "create_project": "POST /api/v1/projects/",
                "search_documents": "POST /api/v1/documents/search",
                "get_user_profile": "GET /api/v1/users/profile"
            }
        }, "API v1 Root")
    
    @app.route('/api/v1/test')
    def api_test():
        """Test endpoint for API v1."""
        return api_success({
            "message": "API v1 is working!",
            "endpoints_available": [
                "projects",
                "documents", 
                "users",
                "health"
            ]
        }, "API v1 Test Endpoint")
    
    return app

# Create the Flask application
app = create_app()

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)