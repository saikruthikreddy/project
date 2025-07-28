"""
API routes for authentication operations.
"""

from flask import Blueprint, request, make_response, g
from datetime import datetime
import logging
import os
import msal
from giani_pkb.middleware.analytics_middleware import log_user_activity
from giani_pkb.utils.response_utils import (
    api_success,
    api_validation_error,
    api_authentication_error,
    api_internal_server_error,
)
from giani_pkb.utils.auth_utils import AuthUtils, verify_password
from giani_pkb.utils.exceptions import DatabaseError, ValidationError

logger = logging.getLogger(__name__)

# Microsoft SSO Configuration
MICROSOFT_CLIENT_ID = os.getenv("MICROSOFT_CLIENT_ID")
MICROSOFT_CLIENT_SECRET = os.getenv("MICROSOFT_CLIENT_SECRET")
MICROSOFT_TENANT_ID = os.getenv(
    "MICROSOFT_TENANT_ID", "common"
)  # 'common' for multi-tenant

# MSAL Configuration
AUTHORITY = f"https://login.microsoftonline.com/{MICROSOFT_TENANT_ID}"
SCOPE = ["User.Read"]


def create_msal_app():
    return msal.ConfidentialClientApplication(
        client_id=MICROSOFT_CLIENT_ID,
        authority=AUTHORITY,
        client_credential=MICROSOFT_CLIENT_SECRET,
    )


def create_auth_routes():
    """Create and configure the authentication blueprint."""
    auth = Blueprint("auth", __name__, url_prefix="/api/v1/auth")

    # Initialize services
    auth_utils = AuthUtils()

    def set_auth_cookies(response, accessToken, refreshToken):
        """Set authentication cookies."""
        response.set_cookie(
            "accessToken", accessToken, httponly=True, secure=True, samesite="None"
        )
        response.set_cookie(
            "refreshToken", refreshToken, httponly=True, secure=True, samesite="None"
        )
        return response

    @auth.route("/test", methods=["GET", "POST", "OPTIONS"])
    def test_cors():
        """Test endpoint for CORS"""
        return api_success({"method": request.method}, "CORS is working for Auth!")

    @auth.route("/login", methods=["POST"])
    @log_user_activity("login")
    def login():
        """Username/password login"""
        try:
            data = request.get_json()
            if not data:
                return api_validation_error("No data provided")

            email = data.get("email")
            password = data.get("password")

            if not email or not password:
                return api_validation_error("Email and password are required")

            # Get user from database using auth_utils
            user = auth_utils.get_user_by_email(email)
            if not user:
                return api_authentication_error("Invalid Username")

            if user["hashed_password"] is None and user["microsoft_id"] is not None:
                return api_authentication_error(
                    "User has registered using microsoft account. Login using the same."
                )

            # Verify password using auth_utils
            if not verify_password(password, user["hashed_password"]):
                return api_authentication_error("Invalid Password")

            # Create session and tokens using AuthService
            from giani_pkb.services.auth_service import AuthService
            auth_service = AuthService()

            client_type = g.client_type
            user_agent = g.user_agent
            ip_address = g.ip_address

            # Create session
            session_id = auth_service.create_session(
                user_id=user["id"],
                client_type=client_type,
                user_agent=user_agent,
                ip_address=ip_address
            )

            # Create tokens
            tokens = auth_service.create_tokens(
                user_id=user["id"],
                email=email,
                session_id=session_id,
                client_type=client_type,
                user_agent=user_agent,
                ip_address=ip_address
            )

            setattr(g, "user_id", user["id"])
            setattr(g, "session_id", session_id)

            response_data = {
                "user": {
                    "id": user["id"],
                    "email": user["email"],
                    "name": user["username"],
                },
                "tokens": {
                    "accessToken": tokens["access_token"],
                    "refreshToken": tokens["refresh_token"]
                },
                "session": {
                    "session_id": session_id,
                    "expires_in": tokens["expires_in"]
                }
            }

            # Handle response format (cookies vs JSON)
            is_addin = g.client_type == "addin"

            if is_addin:
                return api_success(response_data, "Login successful")
            else:
                response = make_response(api_success(response_data, "Login successful"))
                set_auth_cookies(response, tokens["access_token"], tokens["refresh_token"])
                return response

        except Exception as e:
            logger.error(f"Error during login: {e}")
            return api_internal_server_error("Login failed", str(e))

    @auth.route("/microsoft/url", methods=["GET"])
    def get_microsoft_auth_url():
        """Generate Microsoft OAuth URL for frontend"""
        try:
            redirect_uri = request.args.get("redirect_uri")
            if not redirect_uri:
                return api_validation_error("Redirect URI are required")
            msal_app = create_msal_app()

            # Generate auth URL
            auth_url = msal_app.get_authorization_request_url(
                SCOPE,
                redirect_uri=redirect_uri,
                state=request.args.get("state", "default_state"),
            )

            return api_success({"auth_url": auth_url})
        except Exception as e:
            return api_internal_server_error("Failed to generate auth url", str(e))

    @auth.route("/login/microsoft", methods=["POST"])
    @log_user_activity("microsoft_login")
    def microsoft_login():
        """Handle Microsoft SSO login"""
        try:
            data = request.get_json()
            if not data:
                return api_validation_error("No data provided")

            auth_code = data.get("code")
            redirect_uri = data.get("redirect_uri")
            if not auth_code or not redirect_uri:
                return api_validation_error(
                    "Authorization code and redirect URI are required"
                )

            msal_app = create_msal_app()

            # Exchange code for token
            result = msal_app.acquire_token_by_authorization_code(
                code=auth_code, scopes=SCOPE, redirect_uri=redirect_uri
            )

            if "error" in result:
                logger.error(
                    f"MSAL token acquisition error: {result.get('error_description')}"
                )
                return api_authentication_error(
                    f"Token exchange failed: {result.get('error_description', result.get('error'))}"
                )

            # The id_token contains user information
            id_token_claims = result.get("id_token_claims", {})
            email = id_token_claims.get("email") or id_token_claims.get(
                "preferred_username"
            )
            name = id_token_claims.get("name")
            microsoft_id = id_token_claims.get("sub")

            if not email or not microsoft_id:
                return api_authentication_error(
                    "Required user information (email, sub) not found in Microsoft token"
                )

            user = auth_utils.get_user_by_microsoft_id(microsoft_id)

            if not user:
                # If not found by Microsoft ID, check if an account with that email already exists.
                user = auth_utils.get_user_by_email(email)
                if user:
                    logger.info(f"Existing user {email} found. Linking Microsoft ID.")
                    auth_utils.link_microsoft_id(user["id"], microsoft_id)
                else:
                    # No user exists, creating a new one.
                    logger.info(
                        f"New user from Microsoft SSO, email: {email}, name: {name}. Creating account."
                    )
                    user_id = auth_utils.create_user(
                        username=name or email.split("@")[0],
                        email=email,
                        password=None,
                        microsoft_id=microsoft_id,
                        is_superuser=False,
                    )
                    if not user_id:
                        return api_internal_server_error(
                            "Failed to create new user account"
                        )
                    user = auth_utils.get_user_by_id(user_id)

            if not user:
                return api_internal_server_error("User creation/retrieval failed")

            # User exists, generate auth tokens
            from giani_pkb.services.auth_service import AuthService
            auth_service = AuthService()

            client_type = g.client_type
            user_agent = g.user_agent
            ip_address = g.ip_address

            # Create session
            session_id = auth_service.create_session(
                user_id=user["id"],
                client_type=client_type,
                user_agent=user_agent,
                ip_address=ip_address
            )

            # Create tokens
            tokens = auth_service.create_tokens(
                user_id=user["id"],
                email=email,
                session_id=session_id,
                client_type=client_type,
                user_agent=user_agent,
                ip_address=ip_address
            )

            setattr(g, "user_id", user["id"])
            setattr(g, "session_id", session_id)

            response_data = {
                "user": {
                    "id": user["id"],
                    "email": user["email"],
                    "name": user["username"],
                },
                "tokens": {
                    "accessToken": tokens["access_token"],
                    "refreshToken": tokens["refresh_token"]
                },
                "session": {
                    "session_id": session_id,
                    "expires_in": tokens["expires_in"]
                }
            }

            # Determine response format based on User-Agent or explicit header
            is_addin = g.client_type == "addin"

            if is_addin:
                return api_success(response_data, "Microsoft login successful")
            else:
                # For Web projects: set cookies
                response = make_response(
                    api_success(response_data, "Microsoft login successful")
                )
                set_auth_cookies(response, tokens["access_token"], tokens["refresh_token"])
                return response

        except Exception as e:
            logger.error(f"Error during Microsoft login: {e}", exc_info=True)
            return api_internal_server_error(
                "An unexpected error occurred during Microsoft login", str(e)
            )

    @auth.route("/refresh", methods=["POST"])
    def refresh_token():
        """Refresh access token"""
        try:
            from giani_pkb.services.auth_service import AuthService
            auth_service = AuthService()

            # Extract refresh token
            refresh_token_value = auth_utils.extract_refresh_token_from_request()
            if not refresh_token_value:
                return api_authentication_error("Refresh token required")

            # Refresh with rotation
            new_tokens = auth_service.refresh_access_token(
                refresh_token=refresh_token_value,
                ip_address=g.ip_address
            )

            if not new_tokens:
                return api_authentication_error("Invalid or expired refresh token")

            response_data = {
                "accessToken": new_tokens["access_token"],
                "refreshToken": new_tokens["refresh_token"],
                "expires_in": new_tokens["expires_in"]
            }

            # Handle response format
            is_addin = g.client_type == "addin"

            if is_addin:
                return api_success(response_data, "Token refreshed successfully")
            else:
                response = make_response(api_success(response_data, "Token refreshed successfully"))
                set_auth_cookies(response, new_tokens["access_token"], new_tokens["refresh_token"])
                return response

        except Exception as e:
            logger.error(f"Error refreshing token: {e}")
            return api_internal_server_error("Token refresh failed", str(e))

    @auth.route("/logout", methods=["POST"])
    @log_user_activity("logout")
    def logout():
        """Logout user"""
        try:
            from giani_pkb.services.auth_service import AuthService
            auth_service = AuthService()

            # Get tokens
            access_token = auth_utils.extract_token_from_request()
            refresh_token_value = auth_utils.extract_refresh_token_from_request()

            if access_token:
                payload = auth_utils.verify_jwt_token(access_token)
                if payload:
                    session_id = payload.get('session_id')

                    # Revoke session and all its tokens
                    auth_service.revoke_session(session_id, 'logout')

            # Revoke specific refresh token if provided
            if refresh_token_value:
                auth_service.revoke_refresh_token(refresh_token_value, 'logout')

            response = make_response(api_success({}, "Logout successful"))
            response.delete_cookie(key="accessToken", httponly=True, secure=True, samesite="None")
            response.delete_cookie(key="refreshToken", httponly=True, secure=True, samesite="None")

            return response

        except Exception as e:
            logger.error(f"Error during logout: {e}")
            return api_internal_server_error("Logout failed", str(e))

    @auth.route("/me", methods=["GET"])
    def get_current_user():
        """Get current user information"""
        try:
            # Get token from cookie or header
            token = request.cookies.get("accessToken") or request.headers.get(
                "Authorization", ""
            ).replace("Bearer ", "")

            if not token:
                return api_authentication_error("Access token required")

            # Verify token using auth_utils
            payload = auth_utils.verify_jwt_token(token)
            if not payload:
                return api_authentication_error("Invalid access token")

            user_id = payload.get("user_id")
            if not user_id:
                return api_authentication_error("Unable to get user_id")

            # Get user from database using auth_utils
            user = auth_utils.get_user_by_id(user_id)
            if not user:
                return api_authentication_error("User not found")

            return api_success(
                {
                    "user": {
                        "id": user["id"],
                        "email": user["email"],
                        "name": user["username"],
                    }
                },
                "User information retrieved successfully",
            )

        except Exception as e:
            logger.error(f"Error getting current user: {e}")
            return api_internal_server_error("Failed to get user information", str(e))

    @auth.route("/register", methods=["POST"])
    @log_user_activity("register")
    def register():
        """Register new user with enhanced session management."""
        try:
            data = request.get_json()
            if not data:
                return api_validation_error("No data provided")

            email = data.get("email")
            password = data.get("password")
            name = data.get("name")

            # Basic validation
            if not email or not password:
                return api_validation_error("Email and password are required")

            if not name:
                return api_validation_error("Name is required")

            # Check if user already exists
            existing_user = auth_utils.get_user_by_email(email)
            if existing_user:
                if existing_user["microsoft_id"]:
                    return api_validation_error(
                        "User has already registered through microsoft. Login using Microsoft account."
                    )
                else:
                    return api_validation_error("User already exists")

            # Create user - this will raise ValidationError if validation fails
            user_id = auth_utils.create_user(name, email, password, is_superuser=False)

            if not user_id:
                return api_internal_server_error("Failed to create user")

            setattr(g, "user_id", user_id)

            # Fetch the newly created user
            user = auth_utils.get_user_by_email(email)
            if not user:
                return api_internal_server_error(
                    "User creation succeeded but user data fetch failed"
                )

            # Create session and tokens using AuthService
            from giani_pkb.services.auth_service import AuthService
            auth_service = AuthService()

            client_type = g.client_type
            user_agent = g.user_agent
            ip_address = g.ip_address

            # Create session
            session_id = auth_service.create_session(
                user_id=user["id"],
                client_type=client_type,
                user_agent=user_agent,
                ip_address=ip_address
            )

            # Create tokens
            tokens = auth_service.create_tokens(
                user_id=user["id"],
                email=email,
                session_id=session_id,
                client_type=client_type,
                user_agent=user_agent,
                ip_address=ip_address
            )

            setattr(g, "user_id", user["id"])
            setattr(g, "session_id", session_id)

            response_data = {
                "user": {"id": user_id, "email": email, "name": name},
                "tokens": {
                    "accessToken": tokens["access_token"],
                    "refreshToken": tokens["refresh_token"]
                },
                "session": {
                    "session_id": session_id,
                    "expires_in": tokens["expires_in"]
                }
            }

            # Handle response format (cookies vs JSON)
            is_addin = g.client_type == "addin"

            if is_addin:
                return api_success(response_data, "Registration successful")
            else:
                response = make_response(api_success(response_data, "Registration successful"))
            set_auth_cookies(response, tokens["access_token"], tokens["refresh_token"])
            return response

        except ValidationError as e:
            # Handle validation errors from the database layer
            logger.warning(f"Validation error during registration: {e}")
            return api_validation_error(str(e))

        except DatabaseError as e:
            # Handle database errors
            logger.error(f"Database error during registration: {e}")
            return api_internal_server_error(
                "Database error occurred during registration"
            )

        except Exception as e:
            logger.error(f"Unexpected error during registration: {e}")
            return api_internal_server_error("Failed to register user", str(e))

    @auth.route("/health", methods=["GET"])
    def health_check():
        """Health check endpoint"""
        return api_success(
            {"status": "healthy", "service": "authentication"},
            "Authentication service is healthy",
        )

    @auth.route("/sessions", methods=["GET"])
    def get_user_sessions():
        """Get all active sessions for current user."""
        try:
            token = auth_utils.extract_token_from_request()
            if not token:
                return api_authentication_error("Access token required")

            payload = auth_utils.verify_jwt_token(token)
            if not payload:
                return api_authentication_error("Invalid access token")

            user_id = payload.get("user_id")

            from giani_pkb.services.auth_service import AuthService
            auth_service = AuthService()

            sessions = auth_service.get_user_sessions(user_id)

            return api_success({"sessions": sessions}, "Sessions retrieved successfully")

        except Exception as e:
            logger.error(f"Error getting user sessions: {e}")
            return api_internal_server_error("Failed to get sessions", str(e))

    @auth.route("/sessions/<session_id>", methods=["DELETE"])
    def revoke_session(session_id):
        """Revoke a specific session."""
        try:
            token = auth_utils.extract_token_from_request()
            if not token:
                return api_authentication_error("Access token required")

            payload = auth_utils.verify_jwt_token(token)
            if not payload:
                return api_authentication_error("Invalid access token")

            from giani_pkb.services.auth_service import AuthService
            auth_service = AuthService()

            success = auth_service.revoke_session(session_id, 'manual_revocation')

            if success:
                return api_success({}, "Session revoked successfully")
            else:
                return api_validation_error("Session not found or already revoked")

        except Exception as e:
            logger.error(f"Error revoking session: {e}")
            return api_internal_server_error("Failed to revoke session", str(e))

    return auth
