"""
API routes for project operations.
"""
from flask import Blueprint, request
import logging
from werkzeug.utils import secure_filename
import os
import uuid
from giani_pkb.services.project_service import ProjectService
from giani_pkb.services.document_upload_service import DocumentUploadService
from giani_pkb.utils.auth_utils import AuthUtils
from giani_pkb.utils.database_utils import db_utils
from giani_pkb.utils.config import config
from giani_pkb.utils.exceptions import ProjectError, ValidationError, FileProcessingError
from giani_pkb.utils.response_utils import (
    api_success, api_validation_error, api_not_found_error,
    api_database_error, api_file_processing_error, api_internal_server_error
)

logger = logging.getLogger(__name__)

def create_project_routes():
    """Create and configure the projects blueprint."""
    projects = Blueprint('projects', __name__, url_prefix='/api/v1')

    # Initialize services
    project_service = ProjectService()
    upload_service = DocumentUploadService()
    auth_utils = AuthUtils()

    # Initialize database tables
    db_utils.create_document_tables()

    # Configuration
    MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB

    @projects.route('/test', methods=['GET', 'POST', 'OPTIONS'])
    def test_cors():
        """Test CORS configuration."""
        return api_success(
            {'method': request.method},
            'CORS is working',
            200
        )

    @projects.route('/projects', methods=['POST'])
    @auth_utils.auth_required
    def create_project():
        """Create a new project."""
        try:
            data = request.get_json()
            if not data:
                return api_validation_error('No data provided')

            project_name = data.get('projectName', '').strip()
            description = data.get('projectDescription', '').strip()
            client_name = data.get('clientName', '').strip()
            client_industry = data.get('clientIndustry', '').strip()
            targetAudience = data.get('targetAudience', '').strip()
            stakeholders = data.get('keyClientStakeholdersProfiles', '').strip()
            objectives = data.get('primaryProjectObjectivesSuccessMetrics','').strip()

            if not project_name:
                return api_validation_error('Project name is required')

            user_id = request.current_user['user_id']


            project = project_service.create_project(user_id, project_name,  description, client_name, client_industry, targetAudience, stakeholders, objectives)

            # Update user's projects list
            db_utils.update_user_projects_list(user_id, project_name, 'add')

            return api_success(
                {'project': project.to_dict()},
                'Project created successfully',
                201
            )

        except ValidationError as e:
            return api_validation_error(str(e))
        except ProjectError as e:
            return api_database_error(str(e))
        except Exception as e:
            logger.error(f"Error creating project: {e}")
            return api_internal_server_error('Failed to create project', str(e))

    @projects.route('/projects', methods=['GET'])
    @auth_utils.auth_required
    def get_user_projects():
        """Get all projects for the current user."""
        try:
            user_id = request.current_user['user_id']
            projects_list = project_service.get_user_projects(user_id)
            
            # Convert each project to dictionary
            projects_dict = [project.to_dict() for project in projects_list]
            
            return api_success({
                'projects': projects_dict,
                'total': len(projects_dict)
            }, 'Projects retrieved successfully')
        except ProjectError as e:
            return api_database_error(str(e))
        except Exception as e:
            logger.error(f"Error getting user projects: {e}")
            return api_internal_server_error('Failed to retrieve projects', str(e))

    @projects.route('/projects/<project_id>', methods=['GET'])
    @auth_utils.auth_required
    def get_project_details(project_id):
        """Get project details by ID."""
        try:
            user_id = request.current_user['user_id']

            if not db_utils.verify_project_access(project_id, user_id):
                return api_not_found_error('Project not found or access denied')

            project = project_service.get_project_details(project_id, user_id)
            if not project:
                return api_not_found_error('Project not found')

            # Get project documents count
            documents = project_service.get_project_documents(project_id, user_id)

            return api_success({
                'project': project.to_dict_detailed(),
                'document_count': len(documents)
            }, 'Project details retrieved successfully')

        except ProjectError as e:
            return api_database_error(str(e))
        except Exception as e:
            logger.error(f"Error getting project details: {e}")
            return api_internal_server_error('Failed to retrieve project details', str(e))

    @projects.route('/projects/<project_id>', methods=['PUT'])
    @auth_utils.auth_required
    def update_project(project_id):
        """Update project details."""
        try:
            data = request.get_json()
            if not data:
                return api_validation_error('No data provided')

            user_id = request.current_user['user_id']

            if not db_utils.verify_project_access(project_id, user_id):
                return api_not_found_error('Project not found or access denied')

            # Validate updates
            updates = {}
            if 'project_name' in data:
                project_name = data['project_name'].strip()
                if not project_name:
                    return api_validation_error('Project name cannot be empty')
                updates['name'] = project_name

            if 'description' in data:
                updates['description'] = data['description'].strip()

            if not updates:
                return api_validation_error('No valid updates provided')

            success = project_service.update_project(project_id, user_id, updates)
            if not success:
                return api_database_error('Failed to update project')

            return api_success(
                {'project_id': project_id},
                'Project updated successfully'
            )

        except ValidationError as e:
            return api_validation_error(str(e))
        except ProjectError as e:
            return api_database_error(str(e))
        except Exception as e:
            logger.error(f"Error updating project: {e}")
            return api_internal_server_error('Failed to update project', str(e))

    @projects.route('/projects/<project_id>', methods=['DELETE'])
    @auth_utils.auth_required
    def delete_project(project_id):
        """Delete a project."""
        try:
            user_id = request.current_user['user_id']

            if not db_utils.verify_project_access(project_id, user_id):
                return api_not_found_error('Project not found or access denied')

            success = project_service.delete_project(project_id, user_id)
            if not success:
                return api_database_error('Failed to delete project')

            return api_success(
                {'project_id': project_id},
                'Project deleted successfully'
            )

        except ProjectError as e:
            return api_database_error(str(e))
        except Exception as e:
            logger.error(f"Error deleting project: {e}")
            return api_internal_server_error('Failed to delete project', str(e))

    @projects.route('/projects/<project_id>/documents/upload', methods=['POST'])
    @auth_utils.auth_required
    def upload_documents(project_id):
        """Upload documents to a project."""
        try:
            user_id = request.current_user['user_id']

            if not db_utils.verify_project_access(project_id, user_id):
                return api_not_found_error('Project not found or access denied')

            if 'files' not in request.files:
                return api_validation_error('No files provided')

            files = request.files.getlist('files')
            if not files or all(file.filename == '' for file in files):
                return api_validation_error('No files selected')

            uploaded_docs = []

            for file in files:
                if file and file.filename:
                    try:
                        # Save file temporarily
                        filename = secure_filename(file.filename)
                        temp_path = os.path.join(upload_service.upload_folder, filename)
                        file.save(temp_path)

                        # Save to database
                        temp_doc = upload_service.save_temp_document(temp_path, project_id, user_id)
                        uploaded_docs.append(temp_doc)

                    except Exception as e:
                        logger.error(f"Error uploading file {file.filename}: {e}")
                        continue

            if not uploaded_docs:
                return api_file_processing_error('No files were successfully uploaded')

            return api_success({
                'uploaded_documents': uploaded_docs
            }, f'Successfully uploaded {len(uploaded_docs)} documents', 201)

        except FileProcessingError as e:
            return api_file_processing_error(str(e))
        except Exception as e:
            logger.error(f"Error uploading documents: {e}")
            return api_internal_server_error('Failed to upload documents', str(e))

    @projects.route('/projects/<project_id>/documents/ai-suggestions', methods=['POST'])
    @auth_utils.auth_required
    def get_ai_suggestions(project_id):
        """Get AI suggestions for document classification."""
        try:
            user_id = request.current_user['user_id']
            data = request.get_json()

            if not data or 'temp_document_id' not in data:
                return api_validation_error('temp_document_id is required')

            temp_document_id = data['temp_document_id']

            if not db_utils.verify_project_access(project_id, user_id):
                return api_not_found_error('Project not found or access denied')

            suggestions = upload_service.get_ai_suggestions(temp_document_id, project_id, user_id)

            return api_success({
                'suggestions': suggestions
            }, 'AI suggestions retrieved successfully')

        except ValidationError as e:
            return api_validation_error(str(e))
        except Exception as e:
            logger.error(f"Error getting AI suggestions: {e}")
            return api_internal_server_error('Failed to get AI suggestions', str(e))

    @projects.route('/projects/<project_id>/documents/process-batch', methods=['POST'])
    @auth_utils.auth_required
    def process_document_batch(project_id):
        """Process a batch of documents."""
        try:
            user_id = request.current_user['user_id']
            data = request.get_json()

            if not data or 'documents' not in data:
                return api_validation_error('documents array is required')

            documents = data['documents']
            if not documents:
                return api_validation_error('No documents provided for processing')

            if not db_utils.verify_project_access(project_id, user_id):
                return api_not_found_error('Project not found or access denied')

            batch_id = upload_service.process_document_batch(project_id, user_id, documents)

            return api_success({
                'batch_id': batch_id,
                'total_documents': len(documents)
            }, 'Batch processing started', 202)

        except ValidationError as e:
            return api_validation_error(str(e))
        except FileProcessingError as e:
            return api_file_processing_error(str(e))
        except Exception as e:
            logger.error(f"Error processing batch: {e}")
            return api_internal_server_error('Failed to process batch', str(e))

    @projects.route('/projects/<project_id>/documents', methods=['GET'])
    @auth_utils.auth_required
    def get_project_documents(project_id):
        """Get all documents for a project."""
        try:
            user_id = request.current_user['user_id']

            if not db_utils.verify_project_access(project_id, user_id):
                return api_not_found_error('Project not found or access denied')

            documents = project_service.get_project_documents(project_id, user_id)

            return api_success({
                'documents': documents,
                'total': len(documents)
            }, 'Project documents retrieved successfully')

        except ProjectError as e:
            return api_database_error(str(e))
        except Exception as e:
            logger.error(f"Error getting project documents: {e}")
            return api_internal_server_error('Failed to retrieve project documents', str(e))

    @projects.route('/batches/<batch_id>/status', methods=['GET'])
    @auth_utils.auth_required
    def get_batch_status(batch_id):
        """Get batch processing status."""
        try:
            user_id = request.current_user['user_id']
            status = db_utils.get_batch_status(batch_id, user_id)

            if not status:
                return api_not_found_error('Batch not found')

            return api_success(status, 'Batch status retrieved successfully')

        except Exception as e:
            logger.error(f"Error getting batch status: {e}")
            return api_internal_server_error('Failed to get batch status', str(e))

    @projects.route('/role-purpose-categories', methods=['GET'])
    def get_role_purpose_categories():
        """Get available role/purpose categories."""
        return api_success({
            'categories': config.ROLE_PURPOSE_CATEGORIES
        }, 'Role/purpose categories retrieved successfully')

    return projects