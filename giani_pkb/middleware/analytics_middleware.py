# Create: giani_pkb/middleware/analytics_middleware.py

import time
import logging
from functools import wraps
from flask import request, g, current_app
from typing import Optional, Dict, Any
from giani_pkb.services.analytics_service import AnalyticsService
from giani_pkb.utils.auth_utils import AuthUtils

logger = logging.getLogger(__name__)


class AnalyticsMiddleware:
    """Middleware for automatic analytics tracking."""

    def __init__(self, app=None):
        self.analytics_service = AnalyticsService()
        self.auth_utils = AuthUtils()

        if app is not None:
            self.init_app(app)

    def init_app(self, app):
        """Initialize the middleware with Flask app."""
        app.before_request(self.before_request)
        app.after_request(self.after_request)
        app.teardown_appcontext(self.teardown)

    def before_request(self):
        """Called before each request."""
        # Record start time
        g.start_time = time.time()

        # Extract user information
        g.user_id = self._extract_user_id()
        g.client_type = self._extract_client_type()
        g.session_id = self._extract_session_id() if self._extract_session_id() is not None else self._extract_user_id()
        g.project_id = self._extract_project_id()

        # Store request info for later use
        g.endpoint = request.endpoint
        g.method = request.method
        g.ip_address = self._get_client_ip()
        g.user_agent = request.headers.get("User-Agent", "")

    def after_request(self, response):
        """Called after each request."""
        try:
            # Calculate response time
            response_time_ms = None
            if hasattr(g, "start_time"):
                response_time_ms = (time.time() - g.start_time) * 1000

            # Only log API calls (skip static files, health checks etc.)
            if self._should_log_request():
                self._log_api_call(response, response_time_ms)

        except Exception as e:
            logger.error(f"Error in analytics middleware after_request: {e}")

        return response

    def teardown(self, exception=None):
        """Called when application context is torn down."""
        if exception:
            logger.error(f"Request failed with exception: {exception}")

    def _extract_user_id(self) -> Optional[str]:
        """Extract user ID from request."""
        try:
            # Try to get from cookies first (web app)
            token = request.cookies.get("accessToken")

            # If not in cookies, try Authorization header (API/Add-in)
            if not token:
                auth_header = request.headers.get("Authorization", "")
                if auth_header.startswith("Bearer "):
                    token = auth_header.replace("Bearer ", "")

            # If still no token, try request body for refresh token scenarios
            if not token and request.is_json:
                data = request.get_json(silent=True) or {}
                token = data.get("accessToken")

            if token:
                payload = self.auth_utils.verify_jwt_token(token)
                if payload:
                    return payload.get("user_id")

        except Exception as e:
            logger.debug(f"Could not extract user_id: {e}")

        return None

    def _extract_client_type(self) -> Optional[str]:
        """Extract client type from request headers."""
        # Check explicit header first
        client_type = request.headers.get("X-Client-Type")
        if client_type:
            return client_type

        # Check User-Agent for Office Add-in
        user_agent = request.headers.get("User-Agent", "")
        if "Office" in user_agent or "Microsoft" in user_agent:
            return "addin"

        # Default to web
        return "web"

    def _extract_session_id(self) -> Optional[str]:
        """Extract session ID from request."""
        # This could be from cookies, headers, or generated
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            return auth_header.replace("Bearer ", "")

    def _extract_project_id(self) -> Optional[int]:
        """Extract project ID from request if available."""
        try:
            # Check URL path for project ID
            if "project_id" in request.view_args:
                return request.view_args["project_id"]

            # Check request JSON body
            if request.is_json:
                data = request.get_json(silent=True) or {}
                project_id = data.get("project_id")
                if project_id:
                    return int(project_id)

            # Check query parameters
            project_id = request.args.get("project_id")
            if project_id:
                return int(project_id)

        except (ValueError, TypeError):
            pass

        return None

    def _get_client_ip(self) -> str:
        """Get client IP address handling proxies."""
        # Check for forwarded IP (common in production with load balancers)
        forwarded_ips = request.headers.get("X-Forwarded-For")
        if forwarded_ips:
            return forwarded_ips.split(",")[0].strip()

        # Check other common headers
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip

        # Fallback to remote address
        return request.remote_addr or "unknown"

    def _should_log_request(self) -> bool:
        """Determine if request should be logged."""
        # Skip static files
        if request.endpoint and request.endpoint.startswith("static"):
            return False

        skip_endpoints = {
            "health_check",
            "auth.health_check",
        }

        if request.endpoint in skip_endpoints:
            return False

        # Only log API endpoints
        if request.path.startswith("/api/") or request.path.startswith("/auth/"):
            return True

        return False

    def _determine_feature_used(self) -> Optional[str]:
        """Determine which feature was used based on endpoint."""
        endpoint = getattr(g, "endpoint", "")

        # Map endpoints to features
        feature_map = {
            # Auth features
            "auth.login": "user_login",
            "auth.microsoft_login": "microsoft_sso_login",
            "auth.register": "user_registration",
            "auth.refresh": "token_refresh",
            "auth.logout": "user_logout",
            "auth.get_current_user": "user_profile_access",
            # Project features
            "projects.create_project": "create_project",
            "projects.get_user_projects": "get_user_projects",
            "projects.get_project_details": "get_project_details",
            "projects.update_project": "update_project",
            "projects.delete_project": "delete_project",
            "projects.upload_documents": "upload_documents",
            "projects.get_ai_suggestions": "get_ai_suggestions",
            "projects.process_document_batch": "process_document_batch",
            "projects.get_project_documents": "get_project_documents",
            "projects.get_batch_status": "get_batch_status",
            "projects.get_role_purpose_categories": "get_role_purpose_categories",
            "projects.list_temp_documents": "list_temp_documents",
            "projects.get_temp_document": "get_temp_document",
            "projects.delete_temp_document": "delete_temp_document",
            "projects.get_document_summary": "get_document_summary",
            "projects.query_project": "query_project",
            "projects.download_document": "download_document",
            # Document features
            "documents.upload_document": "document_upload",
            "documents.search_documents": "document_search",
            "documents.get_document": "document_access",
            "documents.delete_document": "document_deletion",
            # PPT features (based on your ppt_routes)
            "ppt.suggest_titles": "suggest_titles",
            "ppt.list_user_projects": "list_user_projects",
            "ppt.refine_title_endpoint": "refine_title_endpoint",
            "ppt.generate_slide_structure_endpoint": "generate_slide_structure_endpoint",
            "ppt.refine_selected_text_endpoint": "refine_selected_text_endpoint",
            "ppt.parallelize_statements_endpoint": "parallelize_statements_endpoint",
            "ppt.review_slide_endpoint": "review_slide_endpoint",
        }

        return feature_map.get(endpoint)

    def _log_api_call(self, response, response_time_ms: float):
        """Log the API call to analytics."""
        try:
            user_id = getattr(g, "user_id", None)

            # Skip logging if no user (for public endpoints, adjust as needed)
            if not user_id:
                return

            feature_used = self._determine_feature_used()

            success = self.analytics_service.log_activity(
                user_id=user_id,
                activity_type="api_call",
                endpoint=getattr(g, "endpoint", ""),
                http_method=getattr(g, "method", ""),
                status_code=response.status_code,
                response_time_ms=response_time_ms,
                user_agent=getattr(g, "user_agent", ""),
                client_type=getattr(g, "client_type", ""),
                ip_address=getattr(g, "ip_address", ""),
                project_id=getattr(g, "project_id", None),
                feature_used=feature_used,
                session_id=getattr(g, "session_id", None),
                additional_data={
                    "path": request.path,
                    "args": dict(request.args) if request.args else None,
                    "content_length": response.content_length,
                },
            )

            if not success:
                logger.warning("Failed to log API call to analytics")
            else:
                logger.debug(f"📔Log saved for {getattr(g,"endpoint", "--endpoint--")}")

        except Exception as e:
            logger.error(f"Error logging API call: {e}")


def log_user_activity(activity_type: str, **kwargs):
    """Decorator for logging specific user activities."""

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **func_kwargs):
            result = f(*args, **func_kwargs)

            try:
                user_id = getattr(g, "user_id", None)
                if user_id:
                    analytics_service = AnalyticsService()
                    analytics_service.log_activity(
                        user_id=user_id,
                        activity_type=activity_type,
                        session_id=getattr(g, "session_id", None),
                        client_type=getattr(g, "client_type", None),
                        ip_address=getattr(g, "ip_address", None),
                        **kwargs,
                    )
            except Exception as e:
                logger.error(f"Error in activity logging decorator: {e}")

            return result

        return decorated_function

    return decorator


# Utility function for manual logging in route handlers
def log_manual_activity(
    activity_type: str, feature_used: str = None, additional_data: Dict[str, Any] = None
):
    """Manually log an activity from within a route handler."""
    try:
        user_id = getattr(g, "user_id", None)
        if user_id:
            analytics_service = AnalyticsService()
            analytics_service.log_activity(
                user_id=user_id,
                activity_type=activity_type,
                feature_used=feature_used,
                session_id=getattr(g, "session_id", None),
                client_type=getattr(g, "client_type", None),
                ip_address=getattr(g, "ip_address", None),
                project_id=getattr(g, "project_id", None),
                additional_data=additional_data,
            )
    except Exception as e:
        logger.error(f"Error in manual activity logging: {e}")
