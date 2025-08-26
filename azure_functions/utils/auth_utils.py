"""
Authentication utilities for JWT token management and user verification.
"""
import jwt  # type: ignore
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, Union
from functools import wraps
from flask import g, request
import logging
import hashlib
import secrets
import uuid

from utils.response_utils import api_authentication_error
from utils.exceptions import DatabaseError, ValidationError

logger = logging.getLogger(__name__)

def hash_password(password: str) -> str:
    """
    Hash password using SHA-256.

    Args:
        password: Plain text password

    Returns:
        Hashed password string
    """
    if not password:
        raise ValueError("Password cannot be empty")

    return hashlib.sha256(password.encode()).hexdigest()

def verify_password(password: str, hashed_password: str) -> bool:
    """
    Verify a password against its hash.

    Args:
        password: Plain text password to verify
        hashed_password: Stored hash to compare against

    Returns:
        True if password matches hash, False otherwise
    """
    if not password or not hashed_password:
        return False

    try:
        return hash_password(password) == hashed_password
    except Exception as e:
        logger.error(f"Error verifying password: {e}")
        return False

def generate_secure_token(length: int = 32) -> str:
    """
    Generate a secure random token.

    Args:
        length: Length of the token in bytes

    Returns:
        URL-safe base64 encoded token
    """
    return secrets.token_urlsafe(length)

def generate_user_id() -> str:
    """
    Generate a secure user ID.

    Returns:
        URL-safe base64 encoded user ID
    """
    return secrets.token_urlsafe(16)

class AuthUtils:
    """
    Utility class for handling authentication and authorization.
    """

    def __init__(self, jwt_secret: str = 'GIANIAI', jwt_algorithm: str = 'HS256'):
        from database.database_manager import DatabaseManager
        self.jwt_secret = jwt_secret
        self.jwt_algorithm = jwt_algorithm
        self.db_manager = DatabaseManager()

    def extract_token_from_request(self) -> Optional[str]:
        """Extract JWT token from request headers or cookies."""
        # Check Authorization header
        auth_header = request.headers.get('Authorization')
        if auth_header and auth_header.startswith('Bearer '):
            return auth_header[7:]  # Remove 'Bearer ' prefix

        # Check cookies
        access_token = request.cookies.get('accessToken')
        if access_token:
            return access_token

        return None

    def extract_refresh_token_from_request(self) -> Optional[str]:
        """Extract Refresh JWT token from request headers or cookies."""
        # Check cookies
        refresh_token = request.cookies.get('refreshToken')
        if not refresh_token and request.is_json:
            # Check request body
            data = request.get_json() or {}
            refresh_token = data.get('refreshToken')

        return refresh_token

    def verify_jwt_token(self, token: str) -> Optional[Dict[str, Any]]:
        """Verify and decode JWT token."""
        try:
            payload = jwt.decode(token, self.jwt_secret, algorithms=[self.jwt_algorithm])
            return payload
        except jwt.ExpiredSignatureError:
            logger.warning("JWT token expired")
            return None
        except jwt.InvalidTokenError:
            logger.warning("Invalid JWT token")
            return None

    def create_jwt_token(self, user_id: str, email: str, session_id: str, expires_in: int = 3600) -> str:
        """Create a new JWT token."""
        now = datetime.now(timezone.utc)
        payload = {
            'user_id': user_id,
            'email': email,
            'session_id': session_id,
            'exp': now + timedelta(seconds=expires_in),
            'iat': now
        }
        return jwt.encode(payload, self.jwt_secret, algorithm=self.jwt_algorithm)

    def verify_user_exists(self, user_id: Union[str, uuid.UUID]) -> bool:
        """Verify that a user exists in the database."""
        try:
            if isinstance(user_id, str):
                user_id = uuid.UUID(user_id)
            user = self.db_manager.get_user_by_id(user_id)
            return user is not None and user.is_active is True
        except (ValueError, TypeError):
            return False
        except Exception as e:
            logger.error(f"Database error verifying user: {e}")
            return False

    def check_user_permission(self, user_id: str) -> bool:
        """Check if user has basic permissions."""
        return self.verify_user_exists(user_id)

    def auth_required(self, f):
        """Authentication decorator for Flask routes."""
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if request.method == 'OPTIONS':
                return '', 204

            token = self.extract_token_from_request()
            if not token:
                return api_authentication_error("Authentication required")

            payload = self.verify_jwt_token(token)
            if not payload:
                return api_authentication_error("Invalid or expired token")

            # Verify user still exists
            user_id = payload.get('user_id')
            if not user_id or not isinstance(user_id, str) or not self.verify_user_exists(user_id):
                return api_authentication_error("User not found")

            g.current_user = {
                'user_id': user_id,
                'email': payload.get('email')
            }
            return f(*args, **kwargs)

        return decorated_function

    def get_user_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get user details by ID."""
        try:
            if isinstance(user_id, str):
                user_uuid = uuid.UUID(user_id)
            user = self.db_manager.get_user_by_id(user_uuid)
            if user is not None and user.is_active is True:
                return {
                    'id': str(user.id),
                    'username': user.username,
                    'email': user.email,
                    'microsoft_id': user.microsoft_id,
                    'is_active': user.is_active,
                    'is_superuser': user.is_superuser,
                    'created_at': user.created_at.isoformat() if user.created_at is not None else None
                }
            return None
        except (ValueError, TypeError):
            return None
        except Exception as e:
            logger.error(f"Database error getting user: {e}")
            return None

    def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Get user details by email."""
        try:
            user = self.db_manager.get_user_by_email(email)
            if user is not None and user.is_active is True:
                return {
                    'id': str(user.id),
                    'username': user.username,
                    'email': user.email,
                    'hashed_password': user.hashed_password,
                    'microsoft_id': user.microsoft_id,
                    'is_active': user.is_active,
                    'is_superuser': user.is_superuser,
                    'created_at': user.created_at.isoformat() if user.created_at is not None else None
                }
            return None
        except Exception as e:
            logger.error(f"Database error getting user by email: {e}")
            return None

    def create_user(self, username: str, email: str, password: Optional[str],
                    is_superuser: bool = False, microsoft_id: Optional[str] = None) -> Optional[str]:
        """Create a new user. Handles both password and SSO creation."""
        try:
            # Check if user already exists
            existing_user = self.db_manager.get_user_by_email(email)
            if existing_user:
                logger.warning(f"User with email {email} already exists")
                if microsoft_id and not existing_user.get('microsoft_id'):
                    self.link_microsoft_id(existing_user['id'], microsoft_id)
                    return existing_user['id']
                return None

            # Create user using database manager - this may raise ValidationError
            user = self.db_manager.create_user(
                username=username,
                email=email,
                password=password,
                is_superuser=is_superuser,
                microsoft_id=microsoft_id
            )
            if user and 'id' in user:
                logger.info(f"Created user: {username} with ID: {user['id']}")
                return str(user['id'])
            else:
                logger.error(f"User creation failed for {username}, no ID returned.")
                return None

        except ValidationError:
            # Re-raise validation errors to be caught by the route handler
            raise
        except DatabaseError:
            # Re-raise database errors to be caught by the route handler
            raise
        except Exception as e:
            logger.error(f"Unexpected error creating user: {e}")
            raise DatabaseError(f"Failed to create user: {e}")

    def update_user_projects_list(self, user_id: str, project_name: str, operation: str = 'add') -> bool:
        """Update user's projects list."""
        try:
            # This functionality would need to be implemented in DatabaseManager
            # For now, we'll log the operation
            logger.info(f"Project list update: {operation} '{project_name}' for user {user_id}")
            return True
        except Exception as e:
            logger.error(f"Database error updating user projects: {e}")
            return False

    def generate_token(self, length: int = 32) -> str:
        """Generate a secure token."""
        return generate_secure_token(length)

    def generate_user_id(self) -> str:
        """Generate a user ID."""
        return generate_user_id()

    def validate_password_strength(self, password: str) -> tuple[bool, str]:
        """
        Validate password strength.

        Args:
            password: Password to validate

        Returns:
            Tuple of (is_valid, error_message)
        """
        if not password:
            return False, "Password cannot be empty"

        if len(password) < 8:
            return False, "Password must be at least 8 characters long"

        if len(password) > 128:
            return False, "Password must be less than 128 characters"

        # Check for at least one letter and one number
        has_letter = any(c.isalpha() for c in password)
        has_number = any(c.isdigit() for c in password)

        if not has_letter:
            return False, "Password must contain at least one letter"

        if not has_number:
            return False, "Password must contain at least one number"

        return True, "Password is valid"

    def sanitize_username(self, username: str) -> str:
        """
        Sanitize username for safe storage.

        Args:
            username: Raw username

        Returns:
            Sanitized username
        """
        if not username:
            return ""

        # Remove leading/trailing whitespace
        sanitized = username.strip()

        # Convert to lowercase
        sanitized = sanitized.lower()

        # Remove special characters (keep alphanumeric, hyphens, underscores)
        import re
        sanitized = re.sub(r'[^a-z0-9_-]', '', sanitized)

        # Limit length
        if len(sanitized) > 50:
            sanitized = sanitized[:50]

        return sanitized

    def sanitize_email(self, email: str) -> str:
        """
        Sanitize email for safe storage.

        Args:
            email: Raw email

        Returns:
            Sanitized email
        """
        if not email:
            return ""

        # Remove leading/trailing whitespace
        sanitized = email.strip()

        # Convert to lowercase
        sanitized = sanitized.lower()

        # Basic email validation
        import re
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'

        if not re.match(email_pattern, sanitized):
            raise ValueError("Invalid email format")

        return sanitized

    def get_user_by_microsoft_id(self, microsoft_id: str) -> Optional[Dict[str, Any]]:
        """Get user details by their unique Microsoft ID."""
        try:
            user = self.db_manager.get_user_by_microsoft_id(microsoft_id)
            if user is not None and user.is_active is True:
                return self.db_manager._user_to_dict(user)
            return None
        except Exception as e:
            logger.error(f"Database error getting user by Microsoft ID: {e}")
            return None

    def link_microsoft_id(self, user_id: str, microsoft_id: str) -> bool:
        """Links a Microsoft ID to an existing user account."""
        try:
            updated_user = self.db_manager.update_user_microsoft_id(user_id, microsoft_id)
            return updated_user is not None
        except Exception as e:
            logger.error(f"Error linking Microsoft ID to user {user_id}: {e}")
            return False
