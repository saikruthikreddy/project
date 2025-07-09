"""
API routes for authentication operations.
"""
from flask import Blueprint, request, make_response
import logging
import requests
import base64
import json
import os
from giani_pkb.utils.response_utils import (
    api_success, api_error, api_validation_error, api_authentication_error,
    api_internal_server_error, ApiResponseBuilder
)
from giani_pkb.utils.auth_utils import AuthUtils, hash_password, verify_password
logger = logging.getLogger(__name__)

# Microsoft OAuth configuration
MICROSOFT_CLIENT_ID = os.getenv('MICROSOFT_CLIENT_ID')
MICROSOFT_CLIENT_SECRET = os.getenv('MICROSOFT_CLIENT_SECRET')
MICROSOFT_TENANT_ID = os.getenv('MICROSOFT_TENANT_ID')

def create_auth_routes():
    """Create and configure the authentication blueprint."""
    auth = Blueprint('auth', __name__, url_prefix='/api/v1/auth')

    # Initialize services
    auth_utils = AuthUtils()

    def set_auth_cookies(response, accessToken, refreshToken):
        """Set authentication cookies."""
        response.set_cookie('accessToken', accessToken, httponly=True, secure=True, samesite='None')
        response.set_cookie('refreshToken', refreshToken, httponly=True, secure=True, samesite='None')
        return response

    @auth.route('/test', methods=['GET', 'POST', 'OPTIONS'])
    def test_cors():
        """Test endpoint for CORS"""
        return api_success(
            {'method': request.method},
            'CORS is working for Auth!'
        )

    @auth.route('/login', methods=['POST'])
    def login():
        """Username/password login"""
        try:
            data = request.get_json()
            if not data:
                return api_validation_error('No data provided')

            email = data.get('email')
            password = data.get('password')

            if not email or not password:
                return api_validation_error('Email and password are required')

            # Get user from database using auth_utils
            user = auth_utils.get_user_by_email(email)
            if not user:
                return api_authentication_error('Invalid Username')

            # Verify password using auth_utils
            if not verify_password(password, user['hashed_password']):
                return api_authentication_error('Invalid Password')

            # Generate tokens using auth_utils
            accessToken = auth_utils.create_jwt_token(user['id'], user['email'], 30 * 60)  # 30 minutes
            refreshToken = auth_utils.create_jwt_token(user['id'], user['email'], 7 * 24 * 60 * 60)  # 7 days

            # Determine response format based on User-Agent or explicit header
            is_addin = request.headers.get('X-Client-Type') == 'addin' or 'Office' in request.headers.get('User-Agent', '')

            response_data = {
                'user': {
                    'id': user['id'],
                    'email': user['email'],
                    'name': user['username']
                },
                'tokens': {
                    'accessToken': accessToken,
                    'refreshToken': refreshToken
                }
            }

            if is_addin:
                # For Add-in: return tokens in response body
                response_data['accessToken'] = accessToken
                response_data['refreshToken'] = refreshToken
                return api_success(response_data, 'Login successful')
            else:
                # For Web projects: set cookies
                response = make_response(api_success(response_data, 'Login successful'))
                set_auth_cookies(response, accessToken, refreshToken)
                return response

        except Exception as e:
            logger.error(f"Error during login: {e}")
            return api_internal_server_error('Login failed', str(e))

    @auth.route('/login/microsoft', methods=['POST'])
    def microsoft_login():
        """Microsoft SSO login"""
        try:
            data = request.get_json()
            if not data:
                return api_validation_error('No data provided')

            auth_code = data.get('code')
            redirect_uri = data.get('redirect_uri')

            if not auth_code or not redirect_uri:
                return api_validation_error('Authorization code and redirect URI are required')

            # Exchange authorization code for tokens
            token_url = f'https://login.microsoftonline.com/{MICROSOFT_TENANT_ID}/oauth2/v2.0/token'

            token_data = {
                'client_id': MICROSOFT_CLIENT_ID,
                'client_secret': MICROSOFT_CLIENT_SECRET,
                'code': auth_code,
                'grant_type': 'authorization_code',
                'redirect_uri': redirect_uri,
                'scope': 'openid profile email'
            }

            token_response = requests.post(token_url, data=token_data)

            if token_response.status_code != 200:
                return api_error(ApiResponseBuilder.AUTHENTICATION_ERROR, 'Failed to exchange authorization code')

            tokens = token_response.json()
            id_token = tokens.get('id_token')

            if not id_token:
                return api_error(ApiResponseBuilder.AUTHENTICATION_ERROR, 'No ID token received')

            # Decode ID token (without verification for simplicity - add proper verification in production)
            try:
                # Note: In production, you should verify the token signature
                # Split the token and decode the payload
                token_parts = id_token.split('.')
                payload = token_parts[1]

                # Add padding if necessary
                padding = 4 - len(payload) % 4
                if padding != 4:
                    payload += '=' * padding

                decoded_payload = base64.urlsafe_b64decode(payload)
                user_info = json.loads(decoded_payload)

            except Exception as e:
                logger.error(f"Error decoding ID token: {e}")
                return api_error(ApiResponseBuilder.AUTHENTICATION_ERROR, 'Invalid ID token')

            # Extract user information
            email = user_info.get('email') or user_info.get('preferred_username')
            name = user_info.get('name')
            microsoft_id = user_info.get('sub')

            if not email:
                return api_error(ApiResponseBuilder.AUTHENTICATION_ERROR, 'No email found in token')

            # Create or update user using auth_utils
            user_id = auth_utils.create_user(name or email, email, None, is_superuser=False)
            if not user_id:
                return api_internal_server_error('Failed to create user')

            # Generate our own JWT tokens using auth_utils
            accessToken = auth_utils.create_jwt_token(user_id, email, 3600)  # 1 hour
            refreshToken = auth_utils.create_jwt_token(user_id, email, 604800)  # 7 days

            # Determine response format
            is_addin = request.headers.get('X-Client-Type') == 'addin' or 'Office' in request.headers.get('User-Agent', '')

            response_data = {
                'user': {
                    'id': user_id,
                    'email': email,
                    'name': name
                },
                'tokens': {
                    'access': accessToken,
                    'refresh': refreshToken
                }
            }

            if is_addin:
                # For Add-in: return tokens in response body
                response_data['accessToken'] = accessToken
                response_data['refreshToken'] = refreshToken
                return api_success(response_data, 'Microsoft login successful')
            else:
                # For Web projects: set cookies
                response = make_response(api_success(response_data, 'Microsoft login successful'))
                set_auth_cookies(response, accessToken, refreshToken)
                return response

        except Exception as e:
            logger.error(f"Error during Microsoft login: {e}")
            return api_internal_server_error('Microsoft login failed', str(e))

    @auth.route('/refresh', methods=['POST'])
    def refreshToken():
        """Refresh access token"""
        try:
            # Try to get refresh token from cookie (Web App) or request body (Add-in)
            refreshToken_value = request.cookies.get('refreshToken')

            if not refreshToken_value:
                # Try request body for Add-in
                data = request.get_json() or {}
                refreshToken_value = data.get('refreshToken')

            if not refreshToken_value:
                return api_authentication_error('Refresh token required')

            # Verify refresh token using auth_utils
            payload = auth_utils.verify_jwt_token(refreshToken_value)
            if not payload:
                return api_authentication_error('Invalid refresh token')

            # Generate new access token using auth_utils
            user_id = payload.get('user_id')
            email = payload.get('email')

            new_accessToken = auth_utils.create_jwt_token(user_id, email, 3600)  # 1 hour

            # Determine response format
            is_addin = request.headers.get('X-Client-Type') == 'addin' or 'Office' in request.headers.get('User-Agent', '')

            response_data = {
                'accessToken': new_accessToken
            }

            if is_addin:
                return api_success(response_data, 'Token refreshed successfully')
            else:
                response = make_response(api_success(response_data, 'Token refreshed successfully'))
                response.set_cookie('accessToken', new_accessToken, httponly=True, secure=True, samesite='Strict')
                return response

        except Exception as e:
            logger.error(f"Error refreshing token: {e}")
            return api_internal_server_error('Token refresh failed', str(e))

    @auth.route('/logout', methods=['POST'])
    def logout():
        """Logout user"""
        try:
            response = make_response(api_success({}, 'Logout successful'))
            response.delete_cookie('accessToken')
            response.delete_cookie('refreshToken')
            return response

        except Exception as e:
            logger.error(f"Error during logout: {e}")
            return api_internal_server_error('Logout failed', str(e))

    @auth.route('/me', methods=['GET'])
    def get_current_user():
        """Get current user information"""
        try:
            # Get token from cookie or header
            token = request.cookies.get('accessToken') or request.headers.get('Authorization', '').replace('Bearer ', '')

            if not token:
                return api_authentication_error('Access token required')

            # Verify token using auth_utils
            payload = auth_utils.verify_jwt_token(token)
            if not payload:
                return api_authentication_error('Invalid access token')

            # Get user from database using auth_utils
            user = auth_utils.get_user_by_id(payload.get('user_id'))
            if not user:
                return api_authentication_error('User not found')

            return api_success({
                'user': {
                    'id': user['id'],
                    'email': user['email']
                }
            }, 'User information retrieved successfully')

        except Exception as e:
            logger.error(f"Error getting current user: {e}")
            return api_internal_server_error('Failed to get user information', str(e))

    @auth.route('/register', methods=['POST'])
    def register():
        """Register new user"""
        try:
            data = request.get_json()
            if not data:
                return api_validation_error('No data provided')

            email = data.get('email')
            password = data.get('password')
            name = data.get('name')

            if not email or not password:
                return api_validation_error('Email and password are required')

            # Check if user already exists
            existing_user = auth_utils.get_user_by_email(email)
            if existing_user:
                return api_validation_error('User already exists')

            # Create user
            user_id = auth_utils.create_user(name, email, password, is_superuser=False)
            if not user_id:
                return api_internal_server_error('Failed to create user')

            # Fetch the newly created user
            user = auth_utils.get_user_by_email(email)
            if not user:
                return api_internal_server_error('User creation succeeded but user data fetch failed')

            # Create JWT tokens
            accessToken = auth_utils.create_jwt_token(user_id, email, 30 * 60)  # 30 mins
            refreshToken = auth_utils.create_jwt_token(user_id, email, 7 * 24 * 60 * 60)  # 7 days

            response_data = {
                'user': {
                    'id': user_id,
                    'email': email,
                    'name': name
                },
                'tokens': {
                    'accessToken': accessToken,
                    'refreshToken': refreshToken
                }
            }

            response = make_response(api_success(response_data, 'Login successful'))
            set_auth_cookies(response, accessToken, refreshToken)
            return response
        except Exception as e:
            logger.error(f"Error getting current user: {e}")
            return api_internal_server_error('Failed to get user information', str(e))


    @auth.route('/health', methods=['GET'])
    def health_check():
        """Health check endpoint"""
        return api_success({
            'status': 'healthy',
            'service': 'authentication'
        }, 'Authentication service is healthy')

    return auth