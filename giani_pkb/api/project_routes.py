"""
API routes for project operations.
"""
from flask import g, Blueprint, request, send_file, abort
import logging
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.utils import secure_filename
import os
import uuid
from giani_pkb.services.project_service import ProjectService
from giani_pkb.services.document_upload_service import DocumentUploadService
from giani_pkb.utils.database_utils import db_utils
from giani_pkb.database.database_manager import DatabaseManager
from giani_pkb.utils.config import config
from giani_pkb.utils.exceptions import ProjectError, ValidationError, FileProcessingError
from giani_pkb.utils.response_utils import (
    api_authorization_error, api_error, api_success, api_validation_error, api_not_found_error,
    api_database_error, api_file_processing_error, api_internal_server_error
)
logger = logging.getLogger(__name__)

def create_project_routes():
    """Create and configure the projects blueprint."""
    projects = Blueprint('projects', __name__, url_prefix='/api/v1/projects')

    # Initialize services
    project_service = ProjectService()
    upload_service = DocumentUploadService()
    db_manager = DatabaseManager()

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

    @projects.route('', methods=['POST'])
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

            user_id = g.user_id

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

    @projects.route('', methods=['GET'])
    def get_user_projects():
        """Get all projects for the current user."""
        try:
            user_id = g.user_id
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

    @projects.route('/<project_id>', methods=['GET'])
    def get_project_details(project_id):
        """Get project details by ID."""
        try:
            user_id = g.user_id

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

    @projects.route('/<project_id>', methods=['PUT'])
    def update_project(project_id):
        """Update project details."""
        try:
            data = request.get_json()
            if not data:
                return api_validation_error('No data provided')

            user_id = g.user_id

            if not db_utils.verify_project_access(project_id, user_id):
                return api_not_found_error('Project not found or access denied')

            # Validate updates
            updates = {}
            if 'projectName' in data:
                project_name = data['projectName'].strip()
                if not project_name:
                    return api_validation_error('Project name cannot be empty')
                updates['name'] = project_name

            if 'projectDescription' in data:
                updates['description'] = data['projectDescription'].strip()

            if 'targetAudience' in data:
                updates['target_audience'] = data['targetAudience'].strip()

            if 'primaryProjectObjectivesSuccessMetrics' in data:
                updates['objectives'] = data['primaryProjectObjectivesSuccessMetrics'].strip()

            if 'keyClientStakeholdersProfiles' in data:
                updates['key_client_stakeholders_profiles'] = data['keyClientStakeholdersProfiles'].strip()

            if 'clientName' in data:
                updates['client_name'] = data['clientName'].strip()

            if 'clientIndustry' in data:
                updates['client_industry'] = data['clientIndustry'].strip()

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

    @projects.route('/<project_id>', methods=['DELETE'])
    def delete_project(project_id):
        """Delete a project."""
        try:
            user_id = g.user_id

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

    @projects.route('/<project_id>/documents/upload', methods=['POST'])
    def upload_documents(project_id):
        """Upload documents to a project."""
        try:
            user_id = g.user_id

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
                        source=''

                        # Save to database
                        temp_doc = upload_service.save_temp_document(temp_path, project_id, user_id, source)
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

    @projects.route('/<project_id>/documents/ai-suggestions', methods=['POST'])
    def get_ai_suggestions(project_id):
        """Get AI suggestions for document classification."""
        try:
            user_id = g.user_id
            data = request.get_json()

            if not data or 'temp_document_id' not in data:
                return api_validation_error('temp_document_id is required')

            temp_document_id = data['temp_document_id']
            source = data['source']

            if not db_utils.verify_project_access(project_id, user_id):
                return api_not_found_error('Project not found or access denied')

            suggestions = upload_service.get_ai_suggestions(temp_document_id, source, project_id, user_id)

            return api_success({
                'suggestions': suggestions
            }, 'AI suggestions retrieved successfully')

        except ValidationError as e:
            return api_validation_error(str(e))
        except Exception as e:
            logger.error(f"Error getting AI suggestions: {e}")
            return api_internal_server_error('Failed to get AI suggestions', str(e))

    @projects.route('/<project_id>/documents/process-batch', methods=['POST'])
    def process_document_batch(project_id):
        """Process a batch of documents."""
        try:
            user_id = g.user_id
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

    @projects.route('/<project_id>/documents', methods=['GET'])
    def get_project_documents(project_id):
        """Get all documents for a project."""
        try:
            user_id = g.user_id

            if not db_utils.verify_project_access(project_id, user_id):
                return api_not_found_error('Project not found or access denied')

            documents = project_service.get_project_documents(project_id, user_id)

            # Convert documents to dictionaries
            documents_dict = [doc.to_dict() for doc in documents]

            return api_success({
                'documents': documents_dict,
                'total': len(documents_dict)
            }, 'Project documents retrieved successfully')

        except ProjectError as e:
            return api_database_error(str(e))
        except Exception as e:
            logger.error(f"Error getting project documents: {e}")
            return api_internal_server_error('Failed to retrieve project documents', str(e))

    @projects.route('/<project_id>/conversations', methods=['POST'])
    def create_conversation(project_id):
        """Create a new conversation."""
        try:
            user_id = g.user_id

            if not db_utils.verify_project_access(project_id, user_id):
                return api_not_found_error('Project not found or access denied')

            conversation = db_manager.create_conversation(project_id, user_id)

            if not conversation:
                return api_database_error('Failed to create conversation')

            return api_success(
                {'conversation_id': str(conversation.id)},
                'Conversation created successfully',
                201
            )

        except Exception as e:
            logger.error(f"Error creating conversation: {e}")
            return api_internal_server_error('Failed to create conversation', str(e))

    @projects.route('/<project_id>/conversations/<conversation_id>', methods=['GET'])
    def get_conversation_history(project_id, conversation_id):
        """Get the chat history for a conversation."""
        try:
            user_id = g.user_id

            if not db_utils.verify_project_access(project_id, user_id):
                return api_not_found_error('Project not found or access denied')

            history = db_manager.get_conversation_history(conversation_id)

            # Convert messages to dictionaries
            history_dict = [
                {
                    'message_id': msg.message_id,
                    'sender_type': msg.sender_type,
                    'content': msg.content,
                    'timestamp': msg.timestamp.isoformat()
                } for msg in history
            ]

            return api_success({
                'history': history_dict,
                'total': len(history_dict)
            }, 'Conversation history retrieved successfully')

        except Exception as e:
            logger.error(f"Error getting conversation history: {e}")
            return api_internal_server_error('Failed to retrieve conversation history', str(e))

    @projects.route('/<project_id>/conversations', methods=['GET'])
    def get_project_conversations(project_id):
        """Get all conversations for a project."""
        try:
            user_id = g.user_id

            if not db_utils.verify_project_access(project_id, user_id):
                return api_not_found_error('Project not found or access denied')

            conversations = db_manager.get_project_conversations(project_id, user_id)

            # Convert conversations to dictionaries
            conversations_dict = [
                {
                    'id': str(conv.id),
                    'title': conv.title,
                    'created_at': conv.created_at.isoformat()
                } for conv in conversations
            ]

            return api_success({
                'conversations': conversations_dict,
                'total': len(conversations_dict)
            }, 'Project conversations retrieved successfully')

        except Exception as e:
            logger.error(f"Error getting project conversations: {e}")
            return api_internal_server_error('Failed to retrieve project conversations', str(e))

    @projects.route('/<int:project_id>/documents/<document_id>', methods=['PUT'])
    def update_document(project_id, document_id):
        """Update a processed document's metadata and properties."""
        try:
            user_id = g.user_id

            # Verify project access
            if not db_utils.verify_project_access(project_id, user_id):
                return api_not_found_error('Project not found or access denied')

            # Get JSON data from request
            data = request.get_json()
            if not data:
                return api_validation_error('No data provided')

            # Convert document_id to UUID if necessary
            try:
                document_uuid = uuid.UUID(document_id)
            except ValueError:
                return api_validation_error('Invalid document ID format')

            # Verify document exists and user has access
            document = db_manager.get_document_by_id(document_uuid, user_id)
            if not document:
                return api_not_found_error('Document not found or access denied')

            # Verify document belongs to the specified project
            if document.project_id != int(project_id):
                return api_authorization_error('Document does not belong to this project')

            # Prepare updates dictionary with validation
            updates = {}

            # Validate and process updatable fields
            if 'final_category' in data:
                category = str(data['final_category']).strip()
                if category:
                    updates['final_category'] = category

            if 'final_purpose' in data:
                purpose = str(data['final_purpose']).strip()
                if purpose:
                    updates['final_purpose'] = purpose

            if 'priority' in data:
                priority = data['priority']
                if isinstance(priority, int) and 1 <= priority <= 10:
                    updates['priority'] = priority
                else:
                    return api_validation_error('Priority must be an integer between 1 and 10')

            if 'processed_content' in data:
                updates['processed_content'] = str(data['processed_content']).strip()

            if 'text_preview' in data:
                updates['text_preview'] = str(data['text_preview']).strip()

            # Handle metadata updates (if applicable)
            if 'metadata' in data and isinstance(data['metadata'], dict):
                updates['metadata'] = data['metadata']

            # Check if there are any valid updates
            if not updates:
                return api_validation_error('No valid updates provided')

            # Update the document
            updated_document = db_manager.update_document(
                document_id=document.id,
                user_id=user_id,
                **updates
            )

            if not updated_document:
                return api_database_error('Failed to update document')

            # Log the update
            logger.info(f"User {user_id} updated document {document_id} in project {project_id}")

            return api_success({
                'document': updated_document.to_dict() if hasattr(updated_document, 'to_dict') else {
                    'id': str(updated_document.id),
                    'original_filename': updated_document.original_filename,
                    'final_category': updated_document.final_category,
                    'final_purpose': updated_document.final_purpose,
                    'priority': updated_document.priority,
                    'updated_at': updated_document.updated_at.isoformat() if updated_document.updated_at else None
                }
            }, 'Document updated successfully')

        except ValidationError as e:
            logger.error(f"Validation error updating document {document_id}: {e}")
            return api_validation_error(str(e))
        except SQLAlchemyError as e:
            logger.error(f"Database error updating document {document_id}: {e}")
            return api_database_error('Failed to update document')
        except Exception as e:
            logger.error(f"Error updating document {document_id}: {e}")
            return api_internal_server_error('Failed to update document', str(e))

    @projects.route('/<int:project_id>/documents/<document_id>', methods=['DELETE'])
    def delete_document(project_id, document_id):
        """Delete a processed document and its associated data."""
        try:
            user_id = g.user_id

            # Verify project access
            if not db_utils.verify_project_access(project_id, user_id):
                return api_not_found_error('Project not found or access denied')

            # Convert document_id to UUID if necessary
            try:
                document_uuid = uuid.UUID(document_id)
            except ValueError:
                return api_validation_error('Invalid document ID format')

            # Verify document exists and user has access
            document = db_manager.get_document_by_id(document_uuid, user_id)
            if not document:
                return api_not_found_error('Document not found or access denied')

            # Verify document belongs to the specified project
            if document.project_id != int(project_id):
                return api_authorization_error('Document does not belong to this project')

            # Store document info for response and logging
            document_info = {
                'id': str(document.id),
                'original_filename': document.original_filename,
                'final_category': document.final_category,
                'storage_path': document.storage_path
            }

            # Optional: Check if force delete is requested
            force_delete = request.args.get('force', 'false').lower() == 'true'

            # Delete the document from database (this also deletes chunks and summaries)
            success = db_manager.delete_document(
                document_id=document.id,
                user_id=user_id
            )

            if not success:
                return api_database_error('Failed to delete document from database')

            # Optional: Delete physical file if requested and it exists
            cleanup_file = request.args.get('cleanup_file', 'false').lower() == 'true'
            file_deleted = False

            if cleanup_file and document.storage_path:
                try:
                    if os.path.exists(document.storage_path):
                        # Additional safety check - ensure file is within expected directories
                        file_path_abs = os.path.abspath(document.storage_path)
                        allowed_dirs = [
                            os.path.abspath("data/uploaded_documents"),
                            os.path.abspath(upload_service.processed_folder)
                        ]

                        is_safe_path = any(file_path_abs.startswith(allowed_dir) for allowed_dir in allowed_dirs)

                        if is_safe_path:
                            os.remove(document.storage_path)
                            file_deleted = True
                            logger.info(f"Deleted physical file: {document.storage_path}")
                        else:
                            logger.warning(f"Refusing to delete file outside allowed directories: {document.storage_path}")
                    else:
                        logger.info(f"Physical file not found (already deleted?): {document.storage_path}")

                except Exception as file_error:
                    logger.warning(f"Failed to delete physical file {document.storage_path}: {file_error}")
                    # Don't fail the entire operation for file cleanup errors

            # Log the deletion
            logger.info(f"User {user_id} deleted document {document_id} ({document_info['original_filename']}) from project {project_id}")

            # Prepare response
            response_data = {
                'deleted_document': document_info,
                'file_deleted': file_deleted
            }

            message = f'Document "{document_info["original_filename"]}" deleted successfully'
            if cleanup_file:
                message += f' (physical file {"deleted" if file_deleted else "cleanup attempted"})'

            return api_success(response_data, message)

        except ValidationError as e:
            logger.error(f"Validation error deleting document {document_id}: {e}")
            return api_validation_error(str(e))
        except SQLAlchemyError as e:
            logger.error(f"Database error deleting document {document_id}: {e}")
            return api_database_error('Failed to delete document')
        except Exception as e:
            logger.error(f"Error deleting document {document_id}: {e}")
            return api_internal_server_error('Failed to delete document', str(e))



    @projects.route('/batches/<batch_id>/status', methods=['GET'])
    def get_batch_status(batch_id):
        """Get batch processing status."""
        try:
            user_id = g.user_id
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

    @projects.route('/<project_id>/documents/temp', methods=['GET'])
    def list_temp_documents(project_id):
        """List temporary documents for a project."""
        try:
            user_id = g.user_id

            # Verify project access
            if not db_utils.verify_project_access(project_id, user_id):
                return api_not_found_error('Project not found or access denied')

            # Get query parameters for filtering and pagination
            status_filter = request.args.get('status')
            limit = request.args.get('limit', type=int)
            offset = request.args.get('offset', type=int, default=0)

            # Validate pagination parameters
            if limit is not None and limit <= 0:
                return api_validation_error('Limit must be greater than 0')
            if offset < 0:
                return api_validation_error('Offset must be non-negative')

            # Get temporary documents from database
            temp_documents = db_manager.list_temp_documents(
                project_id=project_id,
                user_id=user_id,
                status_filter=status_filter,
                limit=limit,
                offset=offset
            )

            # Get total count for pagination metadata
            total_count = db_manager.get_temp_documents_count(
                project_id=project_id,
                user_id=user_id,
                status_filter=status_filter
            )

            # Prepare response data
            response_data = {
                'temp_documents': temp_documents,
                'total_count': total_count,
                'returned_count': len(temp_documents),
                'pagination': {
                    'offset': offset,
                    'limit': limit,
                    'has_more': (offset + len(temp_documents)) < total_count if limit else False
                }
            }

            # Add filter info if applied
            if status_filter:
                response_data['filters'] = {'status': status_filter}

            message = f'Found {len(temp_documents)} temporary documents'
            if status_filter:
                message += f' with status "{status_filter}"'

            return api_success(response_data, message)

        except Exception as e:
            logger.error(f"Error listing temp documents for project {project_id}: {e}")
            return api_internal_server_error('Failed to list temporary documents', str(e))


    @projects.route('/<project_id>/documents/temp/<temp_document_id>', methods=['GET'])
    def get_temp_document(project_id, temp_document_id):
        """Get a specific temporary document."""
        try:
            user_id = g.user_id

            # Verify project access
            if not db_utils.verify_project_access(project_id, user_id):
                return api_not_found_error('Project not found or access denied')

            # Get temporary document from database
            temp_document = db_manager.get_temp_document(
                temp_document_id=temp_document_id,
                project_id=project_id,
                user_id=user_id
            )

            if not temp_document:
                return api_not_found_error('Temporary document not found')

            return api_success({
                'temp_document': temp_document
            }, f'Retrieved temporary document: {temp_document["original_filename"]}')

        except Exception as e:
            logger.error(f"Error getting temp document {temp_document_id} for project {project_id}: {e}")
            return api_internal_server_error('Failed to get temporary document', str(e))


    @projects.route('/<project_id>/documents/temp/<temp_document_id>', methods=['DELETE'])
    def delete_temp_document(project_id, temp_document_id):
        """Delete a specific temporary document."""
        try:
            user_id = g.user_id

            # Verify project access
            if not db_utils.verify_project_access(project_id, user_id):
                return api_not_found_error('Project not found or access denied')

            # Delete the temporary document
            temp_document = db_manager.delete_temp_document(
                temp_document_id=temp_document_id,
                user_id=user_id
            )

            if not temp_document:
                return api_internal_server_error('Failed to delete temporary document')

            return api_success({
                'deleted_document': {
                    'temp_document_id': temp_document_id,
                    'original_filename': temp_document['original_filename']
                }
            }, f'Successfully deleted temporary document: {temp_document["original_filename"]}')

        except Exception as e:
            logger.error(f"Error deleting temp document {temp_document_id} for project {project_id}: {e}")
            return api_internal_server_error('Failed to delete temporary document', str(e))


    @projects.route('/<project_id>/documents/<document_id>/summary', methods=['GET'])
    def get_document_summary(project_id, document_id):
        """Get the summary for a specific document."""
        try:
            user_id = g.user_id

            # Verify project access
            if not db_utils.verify_project_access(project_id, user_id):
                return api_not_found_error('Project not found or access denied')

            # Convert document_id to UUID if necessary
            try:
                document_uuid = uuid.UUID(document_id)
            except ValueError:
                return api_error('Invalid document ID format')

            # Prepare response data
            summary_data = db_manager.get_document_summary(document_id)
            return api_success(summary_data, 'Document summary retrieved successfully')

        except SQLAlchemyError as e:
            logger.error(f"Database error retrieving summary for document {document_id}: {e}")
            return api_database_error('Failed to retrieve document summary')
        except Exception as e:
            logger.error(f"Unexpected error retrieving summary for document {document_id}: {e}")
            return api_internal_server_error('Failed to retrieve document summary', str(e))

    @projects.route('/<project_id>/query', methods=['POST'])  # Changed to POST
    def query_project(project_id):
        """Query a specific project with a user question."""
        try:
            user_id = g.user_id
            data = request.get_json()
            if not data or 'user_question' not in data:
                return api_validation_error('Missing user_question in request body')

            user_question = data['user_question']
            conversation_id = data.get('conversation_id')

            # Verify project access
            if not db_utils.verify_project_access(project_id, user_id):
                return api_not_found_error('Project not found or access denied')

            # If no conversation_id, create a new conversation
            if not conversation_id:
                conversation = db_manager.create_conversation(project_id, user_id, user_question)
                if not conversation:
                    return api_database_error('Failed to create conversation')
                conversation_id = conversation.id

            # Get message index
            history = db_manager.get_conversation_history(conversation_id)
            message_index = len(history) + 1

            # Store user message
            db_manager.add_chat_message(conversation_id, message_index, 'human', user_question)

            # Execute query
            document_content_type = data.get('document_content_type', '')
            top_k = data.get('top_k', 10)
            retrieval_data = db_manager.query_project(
                project_id=project_id,
                user_question=user_question,
                document_content_type=document_content_type,
                top_k=top_k
            )

            # Store AI response
            db_manager.add_chat_message(conversation_id, message_index + 1, 'AI', retrieval_data.get('answer', ''))

            retrieval_data['conversation_id'] = str(conversation_id)

            return api_success(retrieval_data, 'Project query executed successfully')

        except ValueError as e:
            logger.error(f"Invalid input for project query: {e}")
            return api_bad_request_error(f'Invalid input: {str(e)}')
        except SQLAlchemyError as e:
            logger.error(f"Database error during project query: {e}")
            return api_database_error('Failed to execute project query')
        except Exception as e:
            logger.error(f"Unexpected error during project query: {e}")
            return api_internal_server_error('Failed to execute project query', str(e))

    @projects.route('/<project_id>/documents/<document_id>/download', methods=['GET'])
    def download_document(project_id,document_id):
        """
        Download a document by its ID.

        Args:
            document_id (str): UUID of the document to download

        Query Parameters:
            as_attachment (bool): Whether to force download as attachment (default: True)

        Returns:
            File response with appropriate headers or error response
        """
        try:
            user_id = g.user_id

            # Get the document from database
            document = db_manager.get_document_by_id(document_id,user_id)

            if not document:
                return api_not_found_error('Document not found')

            # Verify user has access to this document
            # Check if user owns the document or has access through project
            if document.user_id != user_id:
                # Check if user has access to the project
                if not db_utils.verify_project_access(document.project_id, user_id):
                    return api_authorization_error('Access denied to this document')

            # Get document details
            storage_path = document.storage_path
            original_filename = document.original_filename
            file_mime_type = document.file_mime_type
            file_size = document.file_size

            # Verify file exists on disk
            if not storage_path or not os.path.exists(storage_path):
                logger.error(f"Document file not found at path: {storage_path}")
                return api_not_found_error('Document file not found on server')

            # Verify file size matches (security check)
            actual_file_size = os.path.getsize(storage_path)
            if actual_file_size != file_size:
                logger.warning(f"File size mismatch for document {document_id}. Expected: {file_size}, Actual: {actual_file_size}")

            # Determine if file should be downloaded as attachment
            as_attachment = request.args.get('as_attachment', 'true').lower() == 'true'

            # Secure the filename
            safe_filename = secure_filename(original_filename) or f"document_{document_id}"

            # Set appropriate headers
            headers = {
                'Content-Length': str(actual_file_size),
                'Cache-Control': 'no-cache, no-store, must-revalidate',
                'Pragma': 'no-cache',
                'Expires': '0'
            }

            # Log download activity
            logger.info(f"User {user_id} downloading document {document_id}: {original_filename}")

            # Send file
            return send_file(
                storage_path,
                as_attachment=as_attachment,
                download_name=safe_filename,
                mimetype=file_mime_type,
                conditional=True,  # Enable conditional requests (range requests)
                max_age=0  # Disable caching
            )

        except ValidationError as e:
            logger.error(f"Validation error downloading document {document_id}: {e}")
            return api_validation_error(str(e))

        except PermissionError as e:
            logger.error(f"Permission error accessing file {storage_path}: {e}")
            return api_internal_server_error('File access permission denied')

        except FileNotFoundError as e:
            logger.error(f"File not found {storage_path}: {e}")
            return api_not_found_error('Document file not found')

        except Exception as e:
            logger.error(f"Error downloading document {document_id}: {e}")
            return api_internal_server_error('Failed to download document', str(e))

    return projects
