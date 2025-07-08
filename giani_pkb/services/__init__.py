"""
Services package for Giani AI system.

This package contains all business logic services including:
- Document upload and processing
- Project management
- Classification and summarization
- Metadata management
- Database operations
"""

from .document_upload_service import DocumentUploadService
from .project_service import ProjectService
from .classification import ClassificationService
from .summarization import SummarizationService
from .metadata_manager import MetadataManagerService

__all__ = [
    'DocumentUploadService',
    'ProjectService',
    'ClassificationService',
    'SummarizationService',
    'MetadataManagerService'
]