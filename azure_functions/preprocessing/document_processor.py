"""
Main document processing orchestrator that coordinates all file processors.
"""

import os
import logging
from pathlib import Path
from typing import List, Tuple, Dict, Any, Optional, Union
from dataclasses import dataclass

from utils.exceptions import ProcessingError, FileProcessingError
from utils.config import config
from services.blob_storage_service import blob_storage_service
from preprocessing.chunking.strategies import chunk_document_adaptive, ChunkMetadata

# Import new processors
from preprocessing.pdf_processor import EnhancedPdfProcessor
from preprocessing.image_processor import ImageProcessor
from preprocessing.csv_processor import CSVProcessor
from preprocessing.pptx_processor import EnhancedPptxProcessor
from preprocessing.docx_processor import DocxProcessor

logger = logging.getLogger(__name__)


@dataclass
class ProcessingResult:
    """Result of processing a single document."""

    blob_name: str
    container_name: str
    document_id: str
    project_id: str
    status: str
    parsed_block_count: int
    chunk_count: int
    chunks_preview: List[Tuple[str, str, str]]  # (text_preview, chunk_id, chunk_type)
    error_message: Optional[str] = None


class DocumentProcessor:
    """
    Main orchestrator for document processing that coordinates all file processors.

    Features:
    - Unified interface for all document types
    - Automatic file type detection and routing
    - Configurable chunking strategies
    - Comprehensive error handling
    - Detailed processing results
    """

    def __init__(self, api_keys: Optional[Dict[str, str]] = None):
        """
        Initialize the document processor with all sub-processors.

        Args:
            api_keys: Dictionary of API keys for various services
        """
        self.api_keys = api_keys or {}

        # Initialize processors
        self._initialize_processors()

        # Supported file extensions
        self.supported_extensions = {
            # Images
            ".jpg",
            ".jpeg",
            ".png",
            ".bmp",
            ".tiff",
            ".tif",
            ".gif",
            # Documents
            ".pdf",
            ".docx",
            ".doc",
            ".pptx",
            ".ppt",
            # Data
            ".csv",
            ".xlsx",
            ".xls",
        }

    def _initialize_processors(self):
        """Initialize all document processors."""
        try:
            # Get API keys
            gemini_key = (
                self.api_keys.get("gemini")
                or os.getenv("GEMINI_API_KEY")
                or getattr(config, "GEMINI_API_KEY", None)
            )
            openai_key = (
                self.api_keys.get("openai")
                or os.getenv("OPENAI_API_KEY")
                or getattr(config, "OPENAI_API_KEY", None)
            )

            # Initialize processors
            self.pdf_processor = EnhancedPdfProcessor()
            self.image_processor = ImageProcessor()
            self.csv_processor = CSVProcessor(api_key=gemini_key)
            self.pptx_processor = EnhancedPptxProcessor(
                image_processor=self.image_processor
            )
            self.docx_processor = DocxProcessor()

            logger.info("All document processors initialized successfully")

        except Exception as e:
            logger.error(f"Error initializing processors: {e}")
            raise ProcessingError(f"Failed to initialize document processors: {e}")

    def _get_file_processor(self, file_extension: str):
        """
        Get the appropriate processor for a file extension.

        Args:
            file_extension: File extension (with dot)

        Returns:
            Appropriate processor instance

        Raises:
            ProcessingError: If file type is not supported
        """
        extension = file_extension.lower()

        if extension in [".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".gif"]:
            return self.image_processor
        elif extension == ".pdf":
            return self.pdf_processor
        elif extension in [".csv", ".xlsx", ".xls"]:
            return self.csv_processor
        elif extension in [".pptx", ".ppt"]:
            return self.pptx_processor
        elif extension in [".docx", ".doc"]:
            return self.docx_processor
        else:
            raise ProcessingError(f"Unsupported file type: {extension}")

    def _create_image_block(self, image_text: str) -> List[Tuple[str, Dict[str, Any]]]:
        """
        Create structured block from image processing result.

        Args:
            image_text: Text extracted from image

        Returns:
            List of structured blocks
        """
        if not image_text or not image_text.strip():
            return []

        return [
            (
                image_text.strip(),
                {
                    "block_type": "image_full_text",
                    "source_type": "image",
                    "page_number": 1,
                    "file_type": "image",
                },
            )
        ]

    def process_single_file(
        self,
        container_name: str,
        blob_name: str,
        document_id: str,
    ) -> Tuple[
        Optional[List[Tuple[str, Dict[str, Any]]]]
    ]:
        """
        Process a single file: parse it into blocks and then chunk those blocks.

        Args:
            container_name:
            blob_name:
            document_id: ID of the document

        Returns:
            Tuple of (parsed_blocks, chunks_with_metadata)

        Raises:
            FileProcessingError: If file processing fails
        """
        file_info = blob_storage_service.get_blob_info(
            {"blob_name": blob_name, "container_name": container_name}
        )

        if not file_info:
            raise FileProcessingError(
                f"File not found: {blob_name} in container: {container_name}"
            )

        try:
            logger.info(f"Processing file: {blob_name} for doc_id: {document_id}")

            # Get file extension and processor
            file_ext = file_info["file_extension"]
            blob_name = file_info["blob_name"]
            container = config.TEMP_DOCUMENTS_CONTAINER
            processor = self._get_file_processor(file_ext)

            # Process file based on type
            parsed_blocks = None

            if file_ext in [".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".gif"]:
                # Handle image processing
                result = processor.process_file(container, blob_name)
                parsed_blocks = self._create_image_block(result["combined_text"])
            else:
                # Handle other file types
                parsed_blocks = processor.process_file(container, blob_name)

            if not parsed_blocks:
                logger.warning(
                    f"No content blocks extracted from {blob_name} for doc_id: {document_id}"
                )
                return None, []

            return parsed_blocks

        except Exception as e:
            logger.error(
                f"Error processing file {blob_name} for doc_id {document_id}: {e}",
                exc_info=True,
            )
            raise FileProcessingError(
                f"Error processing file {blob_name} in {container_name}: {e}"
            )