"""
User routes for handling user operations.
"""
from flask import Blueprint, request, g
import logging

from giani_pkb.database.database_manager import DatabaseManager
from giani_pkb.utils.response_utils import api_success, api_error
from giani_pkb.utils.exceptions import ValidationError, NotFoundError
from giani_pkb.utils.auth_utils import AuthUtils, hash_password

logger = logging.getLogger(__name__)

def create_user_routes() -> Blueprint:
    """Create user routes blueprint."""
    users = Blueprint('users', __name__, url_prefix='/api/v1/users')

    # Initialize services
    db_manager = DatabaseManager()
    auth_utils = AuthUtils()

    @users.route('/profile', methods=['GET'])
    def get_user_profile():
        """Get current user profile."""
        try:
            user_id = g.user_id

            if not user_id:
                return api_error("User ID is required", 400)

            user = db_manager.get_user_by_id(user_id)
            if not user:
                return api_error("User not found", 404)

            # Get user projects
            projects = db_manager.get_user_projects(user_id)

            result = {
                'id': user.id,
                'username': user.username,
                'email': user.email,
                'is_active': user.is_active,
                'is_superuser': user.is_superuser,
                'created_at': user.created_at.isoformat() if user.created_at else None,
                'updated_at': user.updated_at.isoformat() if user.updated_at else None,
                'projects_count': len(projects),
                'projects': [
                    {
                        'id': project.id,
                        'name': project.name,
                        'description': project.description,
                        'created_at': project.created_at.isoformat() if project.created_at else None
                    }
                    for project in projects[:5]  # Limit to 5 most recent
                ]
            }

            return api_success(result, "User profile retrieved successfully")

        except Exception as e:
            logger.error(f"Error getting user profile: {e}")
            return api_error("Failed to get user profile", 500)

    @users.route('/profile', methods=['PUT'])
    def update_user_profile():
        """Update user profile."""
        try:
            data = request.get_json()
            if not data:
                return api_error("No update data provided", 400)

            user_id = g.user_id
            if not user_id:
                return api_error("User ID is required", 400)

            # Validate update fields
            allowed_fields = {'username'}
            update_data = {}

            for key, value in data.items():
                if key in allowed_fields and value:
                    update_data[key] = value

            if not update_data:
                return api_error("No valid fields to update", 400)

            # Update user
            user = db_manager.update_user(user_id, **update_data)
            if not user:
                return api_error("User not found", 404)

            return api_success({
                'id': user.id,
                'username': user.username,
                'email': user.email,
                'updated_fields': list(update_data.keys())
            }, "User profile updated successfully")

        except ValidationError as e:
            return api_error(str(e), 400)
        except NotFoundError as e:
            return api_error(str(e), 404)
        except Exception as e:
            logger.error(f"Error updating user profile: {e}")
            return api_error("Failed to update user profile", 500)

    @users.route('/change-password', methods=['POST'])
    def change_password():
        """Change user password."""
        try:
            data = request.get_json()
            if not data:
                return api_error("No password data provided", 400)

            current_password = data.get('current_password')
            new_password = data.get('new_password')
            user_id = g.user_id

            if not all([user_id, current_password, new_password]):
                return api_error("User ID, current password, and new password are required", 400)

            # Verify current password
            user = db_manager.get_user_by_id(user_id)
            if not user:
                return api_error("User not found", 404)

            if not auth_utils.verify_password(current_password, user.hashed_password):
                return api_error("Current password is incorrect", 401)

            # Update password
            hashed_new_password = hash_password(new_password)
            updated_user = db_manager.update_user(user_id, hashed_password=hashed_new_password)

            return api_success({
                'id': updated_user.id,
                'username': updated_user.username,
                'password_changed': True
            }, "Password changed successfully")

        except NotFoundError as e:
            return api_error(str(e), 404)
        except Exception as e:
            logger.error(f"Error changing password: {e}")
            return api_error("Failed to change password", 500)

    @users.route('/documents', methods=['GET'])
    def get_user_documents():
        """Get all documents for a user."""
        try:
            user_id = g.user_id

            if not user_id:
                return api_error("User ID is required", 400)

            # Verify user exists
            user = db_manager.get_user_by_id(user_id)
            if not user:
                return api_error("User not found", 404)

            # Get user's documents (this would need to be implemented in DatabaseManager)
            # For now, we'll get documents through projects
            projects = db_manager.get_user_projects(user_id)

            all_documents = []
            for project in projects:
                project_documents = db_manager.get_project_documents(project.id, user_id)
                for doc in project_documents:
                    all_documents.append({
                        'id': doc.id,
                        'original_filename': doc.original_filename,
                        'final_category': doc.final_category,
                        'final_purpose': doc.final_purpose,
                        'priority': doc.priority,
                        'project_id': doc.project_id,
                        'project_name': project.name,
                        'date_added': doc.date_added_to_giani.isoformat() if doc.date_added_to_giani else None
                    })

            # Sort by date added (newest first)
            all_documents.sort(key=lambda x: x['date_added'] or '', reverse=True)

            return api_success({
                'user_id': user_id,
                'documents': all_documents,
                'total_count': len(all_documents)
            }, f"Retrieved {len(all_documents)} documents for user")

        except Exception as e:
            logger.error(f"Error getting user documents: {e}")
            return api_error("Failed to get user documents", 500)

    @users.route('/statistics', methods=['GET'])
    def get_user_statistics():
        """Get user statistics."""
        try:
            user_id = g.user_id

            if not user_id:
                return api_error("User ID is required", 400)

            # Verify user exists
            user = db_manager.get_user_by_id(user_id)
            if not user:
                return api_error("User not found", 404)

            # Get user projects
            projects = db_manager.get_user_projects(user_id)

            # Calculate statistics
            total_documents = 0
            total_chunks = 0
            total_summaries = 0

            for project in projects:
                project_documents = db_manager.get_project_documents(project.id, user_id)
                total_documents += len(project_documents)

                for doc in project_documents:
                    chunks = db_manager.get_document_chunks(doc.id)
                    summaries = db_manager.get_document_summaries(doc.id)
                    total_chunks += len(chunks)
                    total_summaries += len(summaries)

            # Get category distribution
            category_counts = {}
            for project in projects:
                project_documents = db_manager.get_project_documents(project.id, user_id)
                for doc in project_documents:
                    category = doc.final_category or 'Unknown'
                    category_counts[category] = category_counts.get(category, 0) + 1

            result = {
                'user_id': user_id,
                'username': user.username,
                'email': user.email,
                'statistics': {
                    'total_projects': len(projects),
                    'total_documents': total_documents,
                    'total_chunks': total_chunks,
                    'total_summaries': total_summaries,
                    'category_distribution': category_counts
                },
                'account_info': {
                    'created_at': user.created_at.isoformat() if user.created_at else None,
                    'is_active': user.is_active,
                    'is_superuser': user.is_superuser
                }
            }

            return api_success(result, "User statistics retrieved successfully")

        except Exception as e:
            logger.error(f"Error getting user statistics: {e}")
            return api_error("Failed to get user statistics", 500)

    @users.route('/register', methods=['POST'])
    def register_user():
        """Register a new user."""
        try:
            data = request.get_json()
            if not data:
                return api_error("No registration data provided", 400)

            username = data.get('username', '').strip()
            email = data.get('email', '').strip()
            password = data.get('password', '')

            if not all([username, email, password]):
                return api_error("Username, email, and password are required", 400)

            if len(password) < 8:
                return api_error("Password must be at least 8 characters long", 400)

            # Create user
            user = db_manager.create_user(username, email, password)

            return api_success({
                'id': user['id'],
                'username': user['username'],
                'email': user['email'],
                'created_at': user['created_at'] if user['created_at'] else None
            }, "User registered successfully")

        except ValidationError as e:
            return api_error(str(e), 400)
        except Exception as e:
            logger.error(f"Error registering user: {e}")
            return api_error("Failed to register user", 500)

    return users