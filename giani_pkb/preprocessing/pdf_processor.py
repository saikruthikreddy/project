"""
PDF file processor for extracting structured content, text, and images.
"""
import fitz  # PyMuPDF
from typing import List, Dict, Any, Tuple, Union
import logging
from pathlib import Path

from giani_pkb.utils.exceptions import ParsingError, FileProcessingError

logger = logging.getLogger(__name__)

class PdfProcessor:
    """
    Processor for PDF files that extracts structured content, text, and images.

    Features:
    - Text extraction with block-level metadata
    - Image extraction and OCR processing
    - Font analysis for heading detection
    - Contextual text extraction around images
    - Page-based organization
    - Bounding box preservation
    """

    def __init__(self, image_processor=None):
        """
        Initialize the PDF processor.

        Args:
            image_processor: Optional image processor for OCR (will create default if None)
        """
        self.supported_extensions = {'.pdf'}

        # Initialize image processor
        if image_processor is None:
            try:
                from giani_pkb.preprocessing.image_processor import ImageProcessor
                self.image_processor = ImageProcessor()
                logger.info("PDF processor initialized with default image processor")
            except ImportError:
                logger.warning("Image processor not available. Image extraction will be skipped.")
                self.image_processor = None
        else:
            self.image_processor = image_processor

        # Font size thresholds for heading detection
        self.heading_font_size_threshold = 14.0
        self.subheading_font_size_threshold = 12.0

    def _get_block_type(self, block: Dict[str, Any]) -> str:
        """
        Determine block type based on font analysis.

        Args:
            block: PDF text block dictionary

        Returns:
            Block type string
        """
        try:
            lines = block.get("lines", [])
            if not lines:
                return "paragraph"

            spans = lines[0].get("spans", [])
            if not spans:
                return "paragraph"

            # Analyze font properties
            font_size = spans[0].get("size", 10)
            font_flags = spans[0].get("flags", 0)
            font_name = spans[0].get("font", "").lower()

            # Check for bold text
            is_bold = bool(font_flags & 2**4)  # Bold flag

            # Determine block type based on font properties
            if font_size > self.heading_font_size_threshold or is_bold:
                return "heading"
            elif font_size > self.subheading_font_size_threshold:
                return "subheading"
            elif "italic" in font_name or bool(font_flags & 2**1):  # Italic flag
                return "emphasis"
            else:
                return "paragraph"

        except Exception as e:
            logger.debug(f"Error analyzing block type: {e}")
            return "paragraph"

    def _extract_text_near_image(self, page: fitz.Page, image_bbox: fitz.Rect, max_words: int = 20) -> str:
        """
        Extract text appearing near an image for context.

        Args:
            page: PDF page object
            image_bbox: Image bounding box
            max_words: Maximum words to extract

        Returns:
            Contextual text string
        """
        try:
            words = page.get_text("words")
            nearby_text = []

            # Check for text above the image
            for word in sorted(words, key=lambda w: (w[3], w[0])):  # Sort by y1 (bottom), then x0 (left)
                word_bbox = fitz.Rect(word[:4])

                # Check if word is within 50 units above and horizontally aligned
                if (word_bbox.y1 < image_bbox.y0 and
                    image_bbox.y0 - word_bbox.y1 < 50 and
                    (abs(word_bbox.x0 - image_bbox.x0) < 100 or
                     abs(word_bbox.x1 - image_bbox.x1) < 100)):
                    nearby_text.append(word[4])

            # If no text above, check below
            if not nearby_text:
                for word in sorted(words, key=lambda w: (w[1], w[0])):  # Sort by y0 (top), then x0 (left)
                    word_bbox = fitz.Rect(word[:4])

                    # Check if word is within 50 units below and horizontally aligned
                    if (word_bbox.y0 > image_bbox.y1 and
                        word_bbox.y0 - image_bbox.y1 < 50 and
                        (abs(word_bbox.x0 - image_bbox.x0) < 100 or
                         abs(word_bbox.x1 - image_bbox.x1) < 100)):
                        nearby_text.append(word[4])

            return " ".join(nearby_text[:max_words])

        except Exception as e:
            logger.debug(f"Error extracting text near image: {e}")
            return ""

    def _extract_text_blocks(self, page: fitz.Page, page_num: int) -> List[Tuple[str, Dict[str, Any]]]:
        """
        Extract text blocks from a PDF page.

        Args:
            page: PDF page object
            page_num: Page number (1-based)

        Returns:
            List of (text, metadata) tuples
        """
        text_blocks = []

        try:
            # Extract structured text with font information
            page_dict = page.get_text("dict", flags=fitz.TEXTFLAGS_DICT & ~fitz.TEXT_PRESERVE_LIGATURES & ~fitz.TEXT_PRESERVE_WHITESPACE)

            for block in page_dict.get("blocks", []):
                if block.get("type") == 0:  # Text block
                    block_text = ""

                    # Extract text from spans
                    for line in block.get("lines", []):
                        for span in line.get("spans", []):
                            block_text += span.get("text", "") + " "
                        block_text += "\n"  # Preserve line breaks

                    block_text = block_text.strip()
                    if block_text:
                        metadata = {
                            "page_number": page_num,
                            "block_type": self._get_block_type(block),
                            "bbox": list(block.get("bbox", [])),
                            "source_type": "text",
                            "file_type": "pdf"
                        }
                        text_blocks.append((block_text, metadata))

        except Exception as e:
            logger.error(f"Error extracting text from page {page_num}: {e}")

        return text_blocks

    def _extract_images(self, page: fitz.Page, page_num: int, pdf_document: fitz.Document) -> List[Tuple[str, Dict[str, Any]]]:
        """
        Extract images from a PDF page and process them.

        Args:
            page: PDF page object
            page_num: Page number (1-based)
            pdf_document: PDF document object

        Returns:
            List of (image_text, metadata) tuples
        """
        if not self.image_processor:
            return []

        image_blocks = []

        try:
            # Get images from page
            image_list = page.get_images(full=True)

            for img_index, img_info in enumerate(image_list):
                xref = img_info[0]

                try:
                    # Extract image data
                    base_image = pdf_document.extract_image(xref)
                    if not base_image:
                        continue

                    image_bytes = base_image["image"]

                    # Get image bounding box
                    img_rects = page.get_image_rects(xref, transform=True)
                    img_bbox_on_page = list(img_rects[0]) if img_rects else []

                    # Extract contextual text
                    contextual_text = ""
                    if img_bbox_on_page:
                        contextual_text = self._extract_text_near_image(page, fitz.Rect(img_bbox_on_page))

                    # Process image with OCR
                    result = self.image_processor.process_bytes(image_bytes)
                    image_text = result['combined_text']

                    if image_text and image_text.strip():
                        metadata = {
                            "page_number": page_num,
                            "block_type": "image_text",
                            "bbox": img_bbox_on_page,
                            "source_type": "image",
                            "image_context": contextual_text,
                            "original_image_xref": xref,
                            "image_size": result.get('image_size'),
                            "file_type": "pdf"
                        }
                        image_blocks.append((image_text.strip(), metadata))

                except Exception as e:
                    logger.error(f"Error processing image xref {xref} on page {page_num}: {e}")

        except Exception as e:
            logger.error(f"Error extracting images from page {page_num}: {e}")

        return image_blocks

    def process_file(self, file_path: Union[str, Path]) -> List[Tuple[str, Dict[str, Any]]]:
        """
        Process a PDF file and extract structured content.

        Args:
            file_path: Path to PDF file

        Returns:
            List of (content_block, metadata) tuples

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

        processed_blocks = []

        try:
            # Open PDF document
            pdf_document = fitz.open(str(file_path))

            # Process each page
            for page_num in range(1, len(pdf_document) + 1):
                page = pdf_document.load_page(page_num - 1)  # fitz is 0-indexed

                # Extract text blocks
                text_blocks = self._extract_text_blocks(page, page_num)
                processed_blocks.extend(text_blocks)

                # Extract images
                image_blocks = self._extract_images(page, page_num, pdf_document)
                processed_blocks.extend(image_blocks)

            # Close document
            num_pages = len(pdf_document)
            pdf_document.close()
            

            if not processed_blocks:
                logger.warning(f"No content blocks extracted from {file_path}")

            logger.info(f"Successfully processed {file_path}: {len(processed_blocks)} blocks from {num_pages} pages")
            return processed_blocks

        except Exception as e:
            logger.error(f"Error processing PDF file {file_path}: {e}")
            raise FileProcessingError(f"Error processing PDF file {file_path}: {e}", filepath=str(file_path))

    def process_pdf(self, file_path: str) -> List[Tuple[str, Dict[str, Any]]]:
        """
        Legacy method for backward compatibility.

        Args:
            file_path: Path to PDF file

        Returns:
            List of (content_block, metadata) tuples
        """
        return self.process_file(file_path)