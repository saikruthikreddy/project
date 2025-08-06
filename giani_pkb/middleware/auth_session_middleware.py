from flask import g, request
from giani_pkb.services.auth_service import AuthService
from giani_pkb.utils.auth_utils import AuthUtils
import logging

from giani_pkb.utils.response_utils import api_authentication_error

logger = logging.getLogger(__name__)


class AuthSessionMiddleware:
    "Middleware to validate sessions on each request"

    def __init__(self, app=None):
        self.auth_utils = AuthUtils()
        self.auth_service = AuthService()
        if app is not None:
            self.init_app(app)

    def init_app(self, app):
        """Initialize the middleware with Flask app."""
        app.before_request(self.validate_session)

    def validate_session(self):
        """Validate session on each protected request."""
        if self._should_skip_authentication():
            logger.debug(f"[AuthSessionMiddleware]: skipping auth_session middleware")
            return None

        try:
            access_token = self.auth_utils.extract_token_from_request()
            if not access_token:
                return api_authentication_error("Authentication required")

            payload = self.auth_utils.verify_jwt_token(access_token)
            if not payload:
                return api_authentication_error("Invalid or expired token")

            user_id = payload.get("user_id")
            session_id = payload.get("session_id")

            if not user_id or not session_id:
                return api_authentication_error("Invalid token: no session")

            if not self.auth_utils.verify_user_exists(user_id):
                return api_authentication_error("User not found or ianctive")

            if not self.is_session_active(session_id):
                return api_authentication_error("Session has been terminated")

            g.user_id = user_id
            g.session_id = session_id
            g.current_user = {"user_id": user_id, "email": payload.get("email")}

        except Exception as e:
            logger.error(f"Session validation error: {e}")
            return api_authentication_error("Session validation failed")

    def _should_skip_authentication(self) -> bool:
        """Determine if authentication should be skipped."""
        if request.path.startswith("/api/v1/health/"):
            return True

        if request.method == "OPTIONS":
            return True

        public_endpoints = {
            "auth.login",
            "auth.register",
            "auth.logout",
            "auth.get_microsoft_auth_url",
            "auth.microsoft_login",
            "auth.refresh_token",
            "home",
            "api_v1_root",
            "api_test"
        }
        if request.endpoint in public_endpoints:
            return True

        return False

    def is_session_active(self, session_id: str) -> bool:
        """Check if session is active in database."""
        try:
            with self.auth_service.db_manager.get_session() as db:
                from giani_pkb.models.database_models import UserSession
                from datetime import datetime, timezone

                session = db.query(UserSession).filter(
                    UserSession.session_id == session_id,
                    UserSession.is_active == True
                ).first()

                if not session:
                    return False

                # Manual expiry check to handle timezone issues
                current_time = datetime.now(timezone.utc)
                
                # Check if session has an expiry field
                if hasattr(session, 'expires_at') and session.expires_at:
                    expires_at = session.expires_at
                    
                    # Make expires_at timezone-aware if it's naive
                    if expires_at.tzinfo is None:
                        expires_at = expires_at.replace(tzinfo=timezone.utc)
                    
                    # Check if expired
                    if current_time > expires_at:
                        session.is_active = False
                        session.ended_at = current_time
                        session.end_reason = 'expired'
                        db.flush()
                        return False
                else:
                    # Fallback to original method if no expires_at field
                    try:
                        if session.is_expired():
                            session.is_active = False
                            session.ended_at = current_time
                            session.end_reason = 'expired'
                            db.flush()
                            return False
                    except Exception as tz_error:
                        logger.warning(f"Timezone error in is_expired(): {tz_error}")
                        # If timezone error, assume session is valid for now
                        # You might want to handle this differently based on your security requirements

                return True

        except Exception as e:
            logger.error(f"Error checking session status: {e}")
            return False