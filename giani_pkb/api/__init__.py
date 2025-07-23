"""
API routes package for Giani AI Project Knowledge Base.
"""
from .auth_routes import create_auth_routes
from .project_routes import create_project_routes
from .document_routes import create_document_routes
from .user_routes import create_user_routes
from .health_routes import create_health_routes
from .ppt_addin_routes import create_ppt_routes
from .analytics_routes import create_analytics_routes


__all__ = [
    'create_auth_routes',
    'create_project_routes',
    'create_document_routes',
    'create_user_routes',
    'create_health_routes',
    'create_analytics_routes'
]