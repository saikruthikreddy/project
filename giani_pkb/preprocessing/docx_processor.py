"""
DOCX file processor for extracting structured content, tables, and images.
"""
import os
import docx
import zipfile
from typing import List, Dict, Any, Tuple, Optional
import logging
from pathlib import Path

from giani_pkb.utils.exceptions import ParsingError, FileProcessingError

logger = logging.getLogger(__name__)

class DocxProcessor:
    """
    Processor for DOCX files that extracts structured content, tables, and images.

    Features:
    - Text extraction with style-based block classification
    - Table conversion to Markdown format
    - Image extraction and processing
    - Structured output with metadata
    """

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize the DOCX processor.

        Args:
            api_key: Optional API key for image processing (if needed)
        """
        self.api_key = api_key
        self.image_processor = self._get_image_processor()

        # Configuration
        self.supported_extensions = {'.docx'}

        # Style mapping for better block classification
        self.style_mapping = {
            'heading 1': 'heading_1',
            'heading 2': 'heading_2',
            'heading 3': 'heading_3',
            'heading 4': 'heading_4',
            'heading 5': 'heading_5',
            'heading 6': 'heading_6',
            'list paragraph': 'list_item',
            'caption': 'caption',
            'quote': 'quote',
            'title': 'title',
            'subtitle': 'subtitle'
        }

    def _get_image_processor(self):
        """Get image processor if available."""
        try:
            from giani_pkb.preprocessing.image_processor import ImageProcessor
            return ImageProcessor()
        except ImportError:
            logger.warning("Image processor not available. Image extraction will be skipped.")
            return None

    def _get_paragraph_style_type(self, paragraph: docx.text.paragraph.Paragraph) -> str:
        """
        Determine block type based on paragraph style.

        Args:
            paragraph: DOCX paragraph object

        Returns:
            Block type string
        """
        style_name = paragraph.style.name.lower()

        # Check for list items by content
        if paragraph.text.strip().startswith(("* ", "- ", "• ", "1. ", "2. ")):
            return "list_item"

        # Check style mapping
        for style_key, block_type in self.style_mapping.items():
            if style_key in style_name:
                return block_type

        # Check for generic headings
        if 'heading' in style_name:
            return "heading"

        return "paragraph"

    def _table_to_markdown(self, table: docx.table.Table) -> str:
        """
        Convert a DOCX table to Markdown format.

        Args:
            table: DOCX table object

        Returns:
            Markdown table string
        """
        if not table.rows:
            return ""

        try:
            markdown_lines = []

            # Process header row
            header_cells = []
            for cell in table.rows[0].cells:
                cell_text = cell.text.strip().replace("|", "\\|")
                header_cells.append(cell_text)

            markdown_lines.append("| " + " | ".join(header_cells) + " |")

            # Add separator row
            separator = "| " + " | ".join(["---"] * len(header_cells)) + " |"
            markdown_lines.append(separator)

            # Process data rows
            for row in table.rows[1:]:
                data_cells = []
                for cell in row.cells:
                    cell_text = cell.text.strip().replace("|", "\\|")
                    data_cells.append(cell_text)
                markdown_lines.append("| " + " | ".join(data_cells) + " |")

            return "\n".join(markdown_lines)

        except Exception as e:
            logger.error(f"Error converting table to markdown: {e}")
            # Fallback: simple text extraction
            return self._table_to_simple_text(table)

    def _table_to_simple_text(self, table: docx.table.Table) -> str:
        """
        Convert table to simple text format as fallback.

        Args:
            table: DOCX table object

        Returns:
            Simple text representation
        """
        text_lines = []
        for row in table.rows:
            row_texts = []
            for cell in row.cells:
                cell_text = cell.text.strip()
                if cell_text:
                    row_texts.append(cell_text)
            if row_texts:
                text_lines.append(" | ".join(row_texts))

        return "\n".join(text_lines)

    def _extract_images_from_docx(self, file_path: str) -> List[Tuple[str, Dict[str, Any]]]:
        """
        Extract images from DOCX file and process them.

        Args:
            file_path: Path to DOCX file

        Returns:
            List of (image_text, metadata) tuples
        """
        if not self.image_processor:
            return []

        image_blocks: List[Tuple[str, Dict[str, Any]]] = []

        try:
            with zipfile.ZipFile(file_path, 'r') as docx_zip:
                # Get list of media files
                media_files = [
                    item for item in docx_zip.infolist()
                    if item.filename.startswith('word/media/')
                ]

                for media_file in media_files:
                    try:
                        image_bytes = docx_zip.read(media_file.filename)
                        image_text = self.image_processor.process_image_bytes(image_bytes)

                        if image_text and image_text.strip():
                            metadata = {
                                "page_number": None,
                                "block_type": "image_text",
                                "source_type": "image",
                                "image_filename": os.path.basename(media_file.filename),
                                "file_type": "docx_image"
                            }
                            image_blocks.append((image_text.strip(), metadata))

                    except Exception as e:
                        logger.error(f"Error processing image {media_file.filename}: {e}")

        except Exception as e:
            logger.error(f"Error extracting images from DOCX {file_path}: {e}")

        return image_blocks

    def _process_paragraph(self, paragraph: docx.text.paragraph.Paragraph, element_order: int) -> Optional[Tuple[str, Dict[str, Any]]]:
        """
        Process a single paragraph and return structured data.

        Args:
            paragraph: DOCX paragraph object
            element_order: Order of element in document

        Returns:
            (text, metadata) tuple or None if paragraph is empty
        """
        para_text = paragraph.text.strip()
        if not para_text:
            return None

        metadata = {
            "page_number": None,
            "block_type": self._get_paragraph_style_type(paragraph),
            "source_type": "text",
            "style_name": paragraph.style.name,
            "doc_element_order": element_order,
            "file_type": "docx"
        }

        return (para_text, metadata)

    def _process_table(self, table: docx.table.Table, element_order: int) -> Optional[Tuple[str, Dict[str, Any]]]:
        """
        Process a single table and return structured data.

        Args:
            table: DOCX table object
            element_order: Order of element in document

        Returns:
            (text, metadata) tuple or None if table is empty
        """
        if not table.rows:
            return None

        table_text = self._table_to_markdown(table)
        if not table_text.strip():
            return None

        metadata = {
            "page_number": None,
            "block_type": "table",
            "source_type": "table",
            "num_rows": len(table.rows),
            "num_cols": len(table.columns),
            "doc_element_order": element_order,
            "file_type": "docx"
        }

        return (table_text, metadata)

    def process_file(self, file_path: str) -> List[Tuple[str, Dict[str, Any]]]:
        """
        Process a DOCX file and extract structured content.

        Args:
            file_path: Path to DOCX file

        Returns:
            List of (text_block, metadata) tuples

        Raises:
            ParsingError: If file format is not supported
            FileProcessingError: If processing fails
        """
        file_path = Path(file_path)

        if not file_path.exists():
            raise FileProcessingError(f"File not found: {file_path}", filepath=str(file_path))

        if file_path.suffix.lower() not in self.supported_extensions:
            raise ParsingError(
                f"Unsupported file format: {file_path.suffix}. Supported: {', '.join(self.supported_extensions)}",
                filename=str(file_path)
            )

        processed_blocks: List[Tuple[str, Dict[str, Any]]] = []
        element_order = 0

        try:
            # Load document
            document = docx.Document(str(file_path))

            # Process document elements in order
            for element in document.element.body:
                element_order += 1

                # Process paragraphs
                if isinstance(element, docx.oxml.text.paragraph.CT_P):
                    paragraph = docx.text.paragraph.Paragraph(element, document)
                    result = self._process_paragraph(paragraph, element_order)
                    if result:
                        processed_blocks.append(result)

                # Process tables
                elif isinstance(element, docx.oxml.table.CT_Tbl):
                    table = docx.table.Table(element, document)
                    result = self._process_table(table, element_order)
                    if result:
                        processed_blocks.append(result)

            # Extract and process images
            image_blocks = self._extract_images_from_docx(str(file_path))
            for i, (img_text, img_metadata) in enumerate(image_blocks):
                img_metadata["doc_element_order"] = element_order + 1 + i
                processed_blocks.append((img_text, img_metadata))

            if not processed_blocks:
                logger.warning(f"No content blocks extracted from {file_path}")

            logger.info(f"Successfully processed {file_path}: {len(processed_blocks)} blocks extracted")
            return processed_blocks

        except Exception as e:
            logger.error(f"Error processing DOCX file {file_path}: {e}")
            raise FileProcessingError(f"Error processing DOCX file {file_path}: {e}", filepath=str(file_path))

    def process_docx(self, file_path: str) -> List[Tuple[str, Dict[str, Any]]]:
        """
        Legacy method for backward compatibility.

        Args:
            file_path: Path to DOCX file

        Returns:
            List of (text_block, metadata) tuples
        """
        return self.process_file(file_path)