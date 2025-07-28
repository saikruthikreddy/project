"""
Document routes for handling document operations.
"""
from typing import Union
import uuid
from flask import Blueprint, request, g
import logging

from giani_pkb.database.database_manager import DatabaseManager
from giani_pkb.services.classification import ClassificationService
from giani_pkb.utils.response_utils import api_success, api_error
from giani_pkb.utils.exceptions import ValidationError, NotFoundError
from giani_pkb.utils.auth_utils import AuthUtils

logger = logging.getLogger(__name__)

def create_document_routes() -> Blueprint:
    """Create document routes blueprint."""
    documents = Blueprint('documents', __name__, url_prefix='/api/v1/documents')

    # Initialize services
    db_manager = DatabaseManager()
    auth_utils = AuthUtils()

    @documents.route('/search', methods=['POST'])
    def search_documents():
        """Search documents by content or metadata."""
        try:
            data = request.get_json()
            if not data:
                return api_error("No search criteria provided", 400)

            search_term = data.get('search_term', '').strip()
            user_id = data.get('user_id')
            project_id = data.get('project_id')

            if not search_term:
                return api_error("Search term is required", 400)

            # Search documents
            documents = db_manager.search_documents(search_term, user_id)

            # Format results
            results = []
            for doc in documents:
                results.append({
                    'id': doc.id,
                    'original_filename': doc.original_filename,
                    'final_category': doc.final_category,
                    'final_purpose': doc.final_purpose,
                    'priority': doc.priority,
                    'text_preview': doc.text_preview[:200] + '...' if doc.text_preview else '',
                    'date_added': doc.date_added_to_giani.isoformat() if doc.date_added_to_giani else None
                })

            return api_success({
                'documents': results,
                'total_count': len(results),
                'search_term': search_term
            }, f"Found {len(results)} documents matching '{search_term}'")

        except Exception as e:
            logger.error(f"Error searching documents: {e}")
            return api_error("Failed to search documents", 500)

    @documents.route('/<document_id>', methods=['GET'])
    def get_document(document_id: Union[str, uuid.UUID]):
        """Get document details by ID."""
        try:
            user_id = g.user_id

            document = db_manager.get_document_by_id(document_id, user_id)
            if not document:
                return api_error("Document not found", 404)

            # Get document chunks and summaries
            chunks = db_manager.get_document_chunks(document_id)
            summaries = db_manager.get_document_summaries(document_id)

            result = {
                'id': document.id,
                'original_filename': document.original_filename,
                'file_size': document.file_size,
                'file_mime_type': document.file_mime_type,
                'final_category': document.final_category,
                'final_purpose': document.final_purpose,
                'priority': document.priority,
                'text_preview': document.text_preview,
                'processed_content': document.processed_content,
                'extracted_text': document.extracted_text,
                # 'metadata': document.metadata or {}, # TODO: Fix this
                'date_added': document.date_added_to_giani.isoformat() if document.date_added_to_giani else None,
                'finalized_at': document.finalized_at.isoformat() if document.finalized_at else None,
                'chunks_count': len(chunks),
                'summaries_count': len(summaries)
            }

            return api_success(result, "Document retrieved successfully")

        except Exception as e:
            logger.error(f"Error getting document {document_id}: {e}")
            return api_error("Failed to get document", 500)

    @documents.route('/<document_id>', methods=['PUT'])
    def update_document(document_id: int):
        """Update document metadata."""
        try:
            data = request.get_json()
            if not data:
                return api_error("No update data provided", 400)

            user_id = data.get('user_id')
            if not user_id:
                return api_error("User ID is required", 400)

            # Validate update fields
            allowed_fields = {
                'final_category', 'final_purpose', 'priority', 'text_preview',
                'processed_content', 'extracted_text', 'metadata'
            }

            update_data = {}
            for key, value in data.items():
                if key in allowed_fields:
                    update_data[key] = value

            if not update_data:
                return api_error("No valid fields to update", 400)

            # Update document
            document = db_manager.update_document(document_id, user_id, **update_data)
            if not document:
                return api_error("Document not found or access denied", 404)

            return api_success({
                'id': document.id,
                'original_filename': document.original_filename,
                'updated_fields': list(update_data.keys())
            }, "Document updated successfully")

        except ValidationError as e:
            return api_error(str(e), 400)
        except NotFoundError as e:
            return api_error(str(e), 404)
        except Exception as e:
            logger.error(f"Error updating document {document_id}: {e}")
            return api_error("Failed to update document", 500)

    @documents.route('/<document_id>', methods=['DELETE'])
    def delete_document(document_id: int):
        """Delete document."""
        try:
            # data = request.get_json()
            # if not data:
            #     return api_error("No data provided", 400)

            user_id = g.user_id
            if not user_id:
                return api_error("User ID is required", 400)

            # Delete document
            success = db_manager.delete_document(document_id, user_id)
            if not success:
                return api_error("Document not found or access denied", 404)

            return api_success({
                'document_id': document_id,
                'deleted': True
            }, "Document deleted successfully")

        except NotFoundError as e:
            return api_error(str(e), 404)
        except Exception as e:
            logger.error(f"Error deleting document {document_id}: {e}")
            return api_error("Failed to delete document", 500)

    @documents.route('/<document_id>/chunks', methods=['GET'])
    def get_document_chunks(document_id: int):
        """Get document chunks."""
        try:
            user_id = g.user_id

            # Verify document access
            document = db_manager.get_document_by_id(document_id, user_id)
            if not document:
                return api_error("Document not found", 404)

            # Get chunks
            chunks = db_manager.get_document_chunks(document_id)

            results = []
            for chunk in chunks:
                results.append({
                    'id': chunk.id,
                    'chunk_id': chunk.chunk_id,
                    'chunk_text': chunk.chunk_text,
                    'source_page_number': chunk.source_page_number,
                    'metadata': chunk.metadata_ or {},
                    'vector_id': chunk.vector_id,
                    'created_at': chunk.created_at.isoformat() if chunk.created_at else None
                })

            return api_success({
                'document_id': document_id,
                'chunks': results,
                'total_count': len(results)
            }, f"Retrieved {len(results)} chunks for document")

        except Exception as e:
            logger.error(f"Error getting document chunks {document_id}: {e}")
            return api_error("Failed to get document chunks", 500)

    @documents.route('/<document_id>/summaries', methods=['GET'])
    def get_document_summaries(document_id: int):
        """Get document summaries."""
        try:
            user_id = g.user_id

            # Verify document access
            document = db_manager.get_document_by_id(document_id, user_id)
            if not document:
                return api_error("Document not found", 404)

            # Get summaries
            summaries = db_manager.get_document_summaries(document_id)

            results = []
            for summary in summaries:
                results.append({
                    'id': summary.id,
                    'narrative_summary': summary.narrative_summary,
                    'llm_used': summary.llm_model_used,
                    'processing_timestamp': summary.processing_timestamp.isoformat() if summary.processing_timestamp else None,
                    # 'summary_metadata': summary.summary_metadata or {},
                    'storage_path': summary.summary_storage_path
                })

            return api_success({
                'document_id': document_id,
                'summaries': results,
                'total_count': len(results)
            }, f"Retrieved {len(results)} summaries for document")

        except Exception as e:
            logger.error(f"Error getting document summaries {document_id}: {e}")
            return api_error("Failed to get document summaries", 500)

    @documents.route('/<document_id>/classify', methods=['POST'])
    def classify_document(document_id: int):
        """Reclassify document using AI."""
        # TODO: Fix this: Getting "source" column error
        try:
            user_id = g.user_id
            if not user_id:
                return api_error("User ID is required", 400)

            # Verify document access
            document = db_manager.get_document_by_id(document_id, user_id)
            if not document:
                return api_error("Document not found", 404)

            # Get classification service
            classification_service = ClassificationService()

            # Classify document
            classification, purpose, prompt_text = classification_service.classify_document(
                document.original_filename,
                document.text_preview or ""
            )

            # Update document with new classification
            updated_document = db_manager.update_document(
                document_id, user_id,
                final_category=classification,
                final_purpose=purpose
            )

            return api_success({
                'document_id': document_id,
                'new_classification': classification,
                'new_purpose': purpose,
                'prompt_used': prompt_text
            }, "Document reclassified successfully")

        except Exception as e:
            logger.error(f"Error classifying document {document_id}: {e}")
            return api_error("Failed to classify document", 500)

    return documents