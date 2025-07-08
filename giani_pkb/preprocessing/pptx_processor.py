"""
PowerPoint (PPTX) file processor for extracting structured content, images, and metadata.
"""
from pptx import Presentation
from pptx.enum.shapes import PP_PLACEHOLDER, MSO_SHAPE_TYPE
from typing import List, Dict, Any, Tuple, Optional, Union
import logging
from pathlib import Path

from giani_pkb.utils.exceptions import ParsingError, FileProcessingError

logger = logging.getLogger(__name__)

class PptxProcessor:
    """
    Processor for PowerPoint (PPTX) files that extracts structured content.

    Features:
    - Text extraction from slides with metadata
    - Image extraction and OCR processing
    - Table content extraction
    - Chart data extraction
    - Slide-based organization
    - Shape type classification
    """

    def __init__(self, image_processor=None):
        """
        Initialize the PPTX processor.

        Args:
            image_processor: Optional image processor for OCR (will create default if None)
        """
        self.supported_extensions = {'.pptx'}

        # Initialize image processor
        if image_processor is None:
            try:
                from giani_pkb.preprocessing.image_processor import ImageProcessor
                self.image_processor = ImageProcessor()
                logger.info("PPTX processor initialized with default image processor")
            except ImportError:
                logger.warning("Image processor not available. Image extraction will be skipped.")
                self.image_processor = None
        else:
            self.image_processor = image_processor

        # Shape type mapping for better classification
        self.shape_type_mapping = {
            PP_PLACEHOLDER.TITLE: "title",
            PP_PLACEHOLDER.CENTER_TITLE: "title",
            PP_PLACEHOLDER.SUBTITLE: "subtitle",
            PP_PLACEHOLDER.BODY: "body",
            PP_PLACEHOLDER.OBJECT: "object_placeholder",
            PP_PLACEHOLDER.CHART: "chart",
            PP_PLACEHOLDER.TABLE: "table",
            PP_PLACEHOLDER.PICTURE: "picture",
        }

    def _get_shape_type(self, shape) -> str:
        """
        Determine the type of a shape for classification.

        Args:
            shape: PowerPoint shape object

        Returns:
            Shape type string
        """
        # Check for placeholder types
        if hasattr(shape, 'placeholder_format') and shape.placeholder_format.type:
            ph_type = shape.placeholder_format.type
            if ph_type in self.shape_type_mapping:
                return self.shape_type_mapping[ph_type]

        # Check for specific shape types
        if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
            return "picture"
        elif shape.shape_type == MSO_SHAPE_TYPE.TABLE:
            return "table"
        elif shape.shape_type == MSO_SHAPE_TYPE.CHART:
            return "chart"
        elif shape.shape_type == MSO_SHAPE_TYPE.TEXT_BOX:
            return "text_box"

        return "other_shape"

    def _extract_text_from_shape(self, shape, slide_num: int, shape_idx: int) -> Optional[Tuple[str, Dict[str, Any]]]:
        """
        Extract text content from a shape.

        Args:
            shape: PowerPoint shape object
            slide_num: Slide number
            shape_idx: Shape index on slide

        Returns:
            (text, metadata) tuple or None if no text
        """
        if not shape.has_text_frame:
            return None

        text = shape.text.strip()
        if not text:
            return None

        metadata = {
            "page_number": slide_num,
            "block_type": self._get_shape_type(shape),
            "source_type": "text",
            "shape_name": shape.name or f"Shape_{shape_idx}",
            "shape_type_raw": shape.shape_type.name if shape.shape_type else "UNKNOWN",
            "shape_idx_on_slide": shape_idx,
            "file_type": "pptx"
        }

        return (text, metadata)

    def _extract_image_from_shape(self, shape, slide_num: int, shape_idx: int) -> Optional[Tuple[str, Dict[str, Any]]]:
        """
        Extract and process image from a shape.

        Args:
            shape: PowerPoint shape object
            slide_num: Slide number
            shape_idx: Shape index on slide

        Returns:
            (image_text, metadata) tuple or None if processing fails
        """
        if not self.image_processor or shape.shape_type != MSO_SHAPE_TYPE.PICTURE:
            return None

        try:
            image_bytes = shape.image.blob
            result = self.image_processor.process_bytes(image_bytes)

            if result['combined_text'].strip():
                metadata = {
                    "page_number": slide_num,
                    "block_type": "image_text",
                    "source_type": "image",
                    "shape_name": shape.name or f"Image_{shape_idx}",
                    "shape_idx_on_slide": shape_idx,
                    "image_size": result.get('image_size'),
                    "file_type": "pptx"
                }
                return (result['combined_text'].strip(), metadata)

        except Exception as e:
            logger.error(f"Error processing image in slide {slide_num}, shape {shape.name or shape_idx}: {e}")

        return None

    def _extract_table_from_shape(self, shape, slide_num: int, shape_idx: int) -> Optional[Tuple[str, Dict[str, Any]]]:
        """
        Extract table content from a shape.

        Args:
            shape: PowerPoint shape object
            slide_num: Slide number
            shape_idx: Shape index on slide

        Returns:
            (table_text, metadata) tuple or None if no table
        """
        if not hasattr(shape, 'table') or not shape.table:
            return None

        try:
            table = shape.table
            table_lines = []

            # Extract table content
            for row_idx, row in enumerate(table.rows):
                row_cells = []
                for cell in row.cells:
                    cell_text = cell.text.strip()
                    if cell_text:
                        row_cells.append(cell_text)

                if row_cells:
                    table_lines.append(" | ".join(row_cells))

            if table_lines:
                table_text = "\n".join(table_lines)
                metadata = {
                    "page_number": slide_num,
                    "block_type": "table",
                    "source_type": "table",
                    "shape_name": shape.name or f"Table_{shape_idx}",
                    "shape_idx_on_slide": shape_idx,
                    "table_rows": len(table.rows),
                    "table_cols": len(table.columns),
                    "file_type": "pptx"
                }
                return (table_text, metadata)

        except Exception as e:
            logger.error(f"Error extracting table from slide {slide_num}, shape {shape.name or shape_idx}: {e}")

        return None

    def _extract_chart_from_shape(self, shape, slide_num: int, shape_idx: int) -> Optional[Tuple[str, Dict[str, Any]]]:
        """
        Extract chart data from a shape.

        Args:
            shape: PowerPoint shape object
            slide_num: Slide number
            shape_idx: Shape index on slide

        Returns:
            (chart_text, metadata) tuple or None if no chart
        """
        if not hasattr(shape, 'chart') or not shape.chart:
            return None

        try:
            chart = shape.chart
            chart_info = []

            # Extract chart title
            if chart.chart_title and chart.chart_title.text:
                chart_info.append(f"Chart Title: {chart.chart_title.text}")

            # Extract series information
            if hasattr(chart, 'series') and chart.series:
                for i, series in enumerate(chart.series):
                    if hasattr(series, 'name') and series.name:
                        chart_info.append(f"Series {i+1}: {series.name}")

            # Extract axis information
            if hasattr(chart, 'category_axis') and chart.category_axis.title:
                chart_info.append(f"X-Axis: {chart.category_axis.title.text}")

            if hasattr(chart, 'value_axis') and chart.value_axis.title:
                chart_info.append(f"Y-Axis: {chart.value_axis.title.text}")

            if chart_info:
                chart_text = "\n".join(chart_info)
                metadata = {
                    "page_number": slide_num,
                    "block_type": "chart",
                    "source_type": "chart",
                    "shape_name": shape.name or f"Chart_{shape_idx}",
                    "shape_idx_on_slide": shape_idx,
                    "chart_type": chart.chart_type.name if hasattr(chart, 'chart_type') else "UNKNOWN",
                    "file_type": "pptx"
                }
                return (chart_text, metadata)

        except Exception as e:
            logger.error(f"Error extracting chart from slide {slide_num}, shape {shape.name or shape_idx}: {e}")

        return None

    def _process_slide(self, slide, slide_num: int) -> List[Tuple[str, Dict[str, Any]]]:
        """
        Process a single slide and extract all content.

        Args:
            slide: PowerPoint slide object
            slide_num: Slide number (1-based)

        Returns:
            List of (content, metadata) tuples
        """
        slide_blocks = []
        shape_idx = 0

        # Process slide title first
        if slide.shapes.title and slide.shapes.title.has_text_frame:
            title_text = slide.shapes.title.text.strip()
            if title_text:
                shape_idx += 1
                metadata = {
                    "page_number": slide_num,
                    "block_type": "title",
                    "source_type": "text",
                    "shape_type": "title",
                    "shape_idx_on_slide": shape_idx,
                    "file_type": "pptx"
                }
                slide_blocks.append((title_text, metadata))

        # Process all other shapes
        for shape in slide.shapes:
            shape_idx += 1

            # Skip title if already processed
            if shape == slide.shapes.title:
                continue

            # Extract text
            text_result = self._extract_text_from_shape(shape, slide_num, shape_idx)
            if text_result:
                slide_blocks.append(text_result)

            # Extract image content
            image_result = self._extract_image_from_shape(shape, slide_num, shape_idx)
            if image_result:
                slide_blocks.append(image_result)

            # Extract table content
            table_result = self._extract_table_from_shape(shape, slide_num, shape_idx)
            if table_result:
                slide_blocks.append(table_result)

            # Extract chart content
            chart_result = self._extract_chart_from_shape(shape, slide_num, shape_idx)
            if chart_result:
                slide_blocks.append(chart_result)

        return slide_blocks

    def process_file(self, file_path: Union[str, Path]) -> List[Tuple[str, Dict[str, Any]]]:
        """
        Process a PPTX file and extract structured content.

        Args:
            file_path: Path to PPTX file

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
            # Load presentation
            presentation = Presentation(str(file_path))

            # Process each slide
            for slide_num, slide in enumerate(presentation.slides, 1):
                slide_blocks = self._process_slide(slide, slide_num)
                processed_blocks.extend(slide_blocks)

            if not processed_blocks:
                logger.warning(f"No content blocks extracted from {file_path}")

            logger.info(f"Successfully processed {file_path}: {len(processed_blocks)} blocks from {len(presentation.slides)} slides")
            return processed_blocks

        except Exception as e:
            logger.error(f"Error processing PPTX file {file_path}: {e}")
            raise FileProcessingError(f"Error processing PPTX file {file_path}: {e}", filepath=str(file_path))

    def process_pptx(self, file_path: str) -> List[Tuple[str, Dict[str, Any]]]:
        """
        Legacy method for backward compatibility.

        Args:
            file_path: Path to PPTX file

        Returns:
            List of (content_block, metadata) tuples
        """
        return self.process_file(file_path)