"""
Enhanced PowerPoint (PPTX) file processor with complete RAG pipeline integration.
Maintains original interface while adding advanced features and ensuring proper page number handling.
"""
from pptx import Presentation
from pptx.enum.shapes import PP_PLACEHOLDER, MSO_SHAPE_TYPE
from typing import List, Dict, Any, Tuple, Optional, Union
import logging
from pathlib import Path
import io
import base64
from PIL import Image, ImageEnhance, ImageFilter
import tempfile
import os
import cv2
import numpy as np
import re
import pytesseract

# LlamaIndex imports (maintaining original structure)
try:
    from llama_index.core import Document, VectorStoreIndex, ServiceContext
    from llama_index.core.node_parser import SimpleNodeParser
    from llama_index.core.schema import ImageDocument, TextNode, ImageNode
    from llama_index.multi_modal_llms.openai import OpenAIMultiModal
    from llama_index.core.multi_modal_llms.generic_utils import encode_image
    from llama_index.core.program import MultiModalLLMCompletionProgram
    from llama_index.core.output_parsers import PydanticOutputParser
    LLAMAINDEX_AVAILABLE = True
except ImportError:
    LLAMAINDEX_AVAILABLE = False

# Pydantic imports (maintaining original structure)
try:
    from pydantic import BaseModel, Field
    PYDANTIC_AVAILABLE = True
except ImportError:
    PYDANTIC_AVAILABLE = False

# TableTransformer imports (new enhancement)
try:
    from transformers import AutoProcessor, TableTransformerForObjectDetection
    import torch
    TABLE_TRANSFORMER_AVAILABLE = True
except ImportError:
    TABLE_TRANSFORMER_AVAILABLE = False

# RAG Pipeline imports
try:
    from utils.exceptions import ParsingError, FileProcessingError
    from preprocessing.node_converter import NodeConverter
    RAG_IMPORTS_AVAILABLE = True
except ImportError:
    RAG_IMPORTS_AVAILABLE = False
    # Fallback exception classes
    class ParsingError(Exception):
        def __init__(self, message, filename=None):
            super().__init__(message)
            self.filename = filename

    class FileProcessingError(Exception):
        def __init__(self, message, filepath=None):
            super().__init__(message)
            self.filepath = filepath

logger = logging.getLogger(__name__)

# Pydantic models (maintaining original structure)
if PYDANTIC_AVAILABLE:
    class DiagramAnalysis(BaseModel):
        """Pydantic model for structured diagram analysis"""
        diagram_type: str = Field(description="Type of diagram (flowchart, organizational chart, process diagram, etc.)")
        main_elements: List[str] = Field(description="Main elements or components in the diagram")
        relationships: List[str] = Field(description="Relationships between elements")
        text_content: str = Field(description="All text content found in the diagram")
        summary: str = Field(description="Brief summary of what the diagram represents")

    class ImageAnalysis(BaseModel):
        """Pydantic model for structured image analysis"""
        image_type: str = Field(description="Type of image (photograph, screenshot, chart, diagram, etc.)")
        objects_detected: List[str] = Field(description="Objects or elements detected in the image")
        text_content: str = Field(description="Any text content found in the image (OCR)")
        description: str = Field(description="Detailed description of the image content")
        key_insights: List[str] = Field(description="Key insights or important information from the image")
else:
    DiagramAnalysis = None
    ImageAnalysis = None

class EnhancedPptxProcessor:
    """
    Enhanced processor for PowerPoint (PPTX) files with complete RAG pipeline integration.

    Features:
    - Advanced text extraction from slides with metadata
    - Enhanced image extraction with AI-powered analysis
    - Diagram and flowchart understanding
    - Table content extraction with TableTransformer
    - Chart data extraction with AI interpretation
    - Slide-based organization with proper page numbering
    - Shape type classification
    - Multi-modal AI analysis for complex visual content
    - Enhanced OCR with preprocessing
    - Complete RAG pipeline compatibility
    - Proper node conversion with page_numbers handling
    """

    def __init__(self, image_processor=None, openai_api_key=None, document_id=None, project_id=None, node_converter=None):
        """
        Initialize the Enhanced PPTX processor.

        Args:
            image_processor: Optional image processor for OCR
            openai_api_key: OpenAI API key for multi-modal analysis
            document_id: Document ID for RAG pipeline consistency
            project_id: Project ID for RAG pipeline consistency
            node_converter: NodeConverter instance for RAG pipeline integration
        """
        self.supported_extensions = {'.pptx'}

        # RAG Pipeline compatibility attributes
        self.document_id = document_id
        self.project_id = project_id

        # Initialize NodeConverter for RAG pipeline integration
        if node_converter:
            self.node_converter = node_converter
        elif RAG_IMPORTS_AVAILABLE:
            try:
                self.node_converter = NodeConverter()
                logger.info("NodeConverter initialized successfully")
            except Exception as e:
                logger.warning(f"Failed to initialize NodeConverter: {e}")
                self.node_converter = None
        else:
            logger.warning("NodeConverter not available - RAG pipeline integration limited")
            self.node_converter = None

        # Initialize image processor (maintaining original logic)
        if image_processor is None:
            try:
                from preprocessing.image_processor import ImageProcessor
                self.image_processor = ImageProcessor()
                logger.info("PPTX processor initialized with default image processor")
            except ImportError:
                logger.warning("Image processor not available. Basic image extraction will be used.")
                self.image_processor = None
        else:
            self.image_processor = image_processor

        # Initialize LlamaIndex components (maintaining original structure)
        self.openai_api_key = openai_api_key or os.getenv("OPENAI_API_KEY")
        if self.openai_api_key and LLAMAINDEX_AVAILABLE and PYDANTIC_AVAILABLE:
            try:
                self.multi_modal_llm = OpenAIMultiModal(
                    model="gpt-4-vision-preview",
                    api_key=self.openai_api_key,
                    max_new_tokens=1000
                )
                self.diagram_analyzer = MultiModalLLMCompletionProgram.from_defaults(
                    output_parser=PydanticOutputParser(DiagramAnalysis),
                    multi_modal_llm=self.multi_modal_llm,
                    prompt_template_str="""
                    Analyze this diagram/flowchart image and extract structured information.
                    Focus on identifying the type of diagram, main elements, relationships between elements,
                    any text content, and provide a summary of what the diagram represents.

                    Return the analysis in the specified JSON format.
                    """
                )

                self.image_analyzer = MultiModalLLMCompletionProgram.from_defaults(
                    output_parser=PydanticOutputParser(ImageAnalysis),
                    multi_modal_llm=self.multi_modal_llm,
                    prompt_template_str="""
                    Analyze this image and extract comprehensive information.
                    Identify the type of image, detect objects or elements, extract any text content,
                    provide a detailed description, and list key insights.

                    Return the analysis in the specified JSON format.
                    """
                )

                logger.info("LlamaIndex multi-modal components initialized successfully")
                self.ai_analysis_enabled = True
            except Exception as e:
                logger.warning(f"Failed to initialize LlamaIndex multi-modal components: {e}")
                self.ai_analysis_enabled = False
        else:
            logger.warning("OpenAI API key not provided or dependencies missing. AI-powered analysis will be disabled.")
            self.ai_analysis_enabled = False

        # Initialize TableTransformer (new enhancement)
        if TABLE_TRANSFORMER_AVAILABLE:
            try:
                self.table_detection_model = TableTransformerForObjectDetection.from_pretrained(
                    "microsoft/table-transformer-detection"
                )
                self.table_structure_model = TableTransformerForObjectDetection.from_pretrained(
                    "microsoft/table-transformer-structure-recognition"
                )
                self.table_processor = AutoProcessor.from_pretrained("microsoft/table-transformer-detection")
                self.table_transformer_available = True
                logger.info("TableTransformer models loaded successfully")
            except Exception as e:
                logger.warning(f"TableTransformer not available: {e}")
                self.table_transformer_available = False
        else:
            self.table_transformer_available = False

        # Setup enhanced OCR configurations
        self.setup_tesseract()

        # Shape type mapping (maintaining original structure)
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

    def setup_tesseract(self):
        """Configure PyTesseract for better OCR performance"""
        self.ocr_configs = {
            'table': '--oem 3 --psm 6 -c tessedit_char_whitelist=0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz.,()%$-+/= ',
            'chart': '--oem 3 --psm 11 -c tessedit_char_whitelist=0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz.,()%$-+/=:',
            'diagram': '--oem 3 --psm 6',
            'flowchart': '--oem 3 --psm 6 -c tessedit_char_whitelist=0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz.,()%$-+/=→←↑↓',
            'general': '--oem 3 --psm 6',
            'numbers': '--oem 3 --psm 8 -c tessedit_char_whitelist=0123456789.,%$-+'
        }

    def _get_shape_type(self, shape) -> str:
        """Determine the type of a shape for classification."""
        # Check for placeholder types
        if hasattr(shape, 'placeholder_format') and shape.placeholder_format:
            try:
                ph_type = shape.placeholder_format.type
                if ph_type in self.shape_type_mapping:
                    return self.shape_type_mapping[ph_type]
            except (ValueError, AttributeError):
                pass

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

    def preprocess_image_for_ocr(self, image: Image.Image, content_type: str = 'general') -> Image.Image:
        """Enhanced image preprocessing for better OCR accuracy"""
        # Convert to opencv format
        opencv_image = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)

        # Apply different preprocessing based on content type
        if content_type == 'chart':
            opencv_image = cv2.convertScaleAbs(opencv_image, alpha=1.5, beta=10)
            opencv_image = cv2.bilateralFilter(opencv_image, 9, 80, 80)
        elif content_type == 'table':
            kernel = np.array([[-1,-1,-1], [-1,9,-1], [-1,-1,-1]])
            opencv_image = cv2.filter2D(opencv_image, -1, kernel)
        elif content_type in ['diagram', 'flowchart']:
            opencv_image = cv2.convertScaleAbs(opencv_image, alpha=1.3, beta=5)
            opencv_image = cv2.bilateralFilter(opencv_image, 5, 50, 50)

        # Convert to grayscale and apply adaptive thresholding
        gray = cv2.cvtColor(opencv_image, cv2.COLOR_BGR2GRAY)
        binary = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2
        )

        # Morphological operations to clean up
        kernel = np.ones((1, 1), np.uint8)
        cleaned = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)

        return Image.fromarray(cleaned)

    def detect_content_type(self, image: Image.Image) -> str:
        """Detect the type of content in the image"""
        try:
            text = pytesseract.image_to_string(image, config='--psm 6').lower()

            if any(indicator in text for indicator in ['|', 'table', 'row', 'column', 'cell']):
                return 'table'
            elif any(indicator in text for indicator in ['chart', 'graph', '%', 'percentage', 'data', 'axis']):
                return 'chart'
            elif any(indicator in text for indicator in ['flow', 'process', 'step', 'decision', 'start', 'end', '→', '←']):
                return 'flowchart'
            elif any(indicator in text for indicator in ['diagram', 'schema', 'model', 'structure', 'relationship']):
                return 'diagram'
            else:
                return 'general'
        except Exception:
            return 'general'

    def detect_tables_with_transformer(self, image: Image.Image) -> List[Dict]:
        """Use TableTransformer to detect and extract tables"""
        if not self.table_transformer_available:
            return []

        try:
            encoding = self.table_processor(image, return_tensors="pt")

            with torch.no_grad():
                outputs = self.table_detection_model(**encoding)

            target_sizes = torch.tensor([image.size[::-1]])
            results = self.table_processor.post_process_object_detection(
                outputs, threshold=0.7, target_sizes=target_sizes
            )[0]

            tables = []
            for score, label, box in zip(results["scores"], results["labels"], results["boxes"]):
                if score > 0.7:
                    box = [round(i, 2) for i in box.tolist()]
                    x1, y1, x2, y2 = box
                    table_crop = image.crop((x1, y1, x2, y2))
                    table_data = self.extract_table_structure(table_crop)

                    tables.append({
                        "bbox": box,
                        "confidence": score.item(),
                        "table_data": table_data,
                        "image_crop": table_crop
                    })

            return tables
        except Exception as e:
            logger.warning(f"TableTransformer error: {e}")
            return []

    def extract_table_structure(self, table_image: Image.Image) -> Dict:
        """Extract table structure using enhanced methods"""
        processed_img = self.preprocess_image_for_ocr(table_image, 'table')

        try:
            table_text = pytesseract.image_to_string(processed_img, config=self.ocr_configs['table'])
            rows = self.parse_table_text(table_text)

            return {
                "structure_detected": len(rows) > 0,
                "raw_text": table_text,
                "parsed_rows": rows,
                "cell_count": sum(len(row) for row in rows),
                "extraction_method": "enhanced_ocr"
            }
        except Exception as e:
            logger.warning(f"Table structure extraction error: {e}")
            return {
                "structure_detected": False,
                "raw_text": "",
                "parsed_rows": [],
                "cell_count": 0,
                "extraction_method": "fallback"
            }

    def parse_table_text(self, text: str) -> List[List[str]]:
        """Parse OCR text into table structure"""
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        rows = []

        for line in lines:
            cells = re.split(r' {2,}|\t+', line)
            if len(cells) > 1:
                rows.append([cell.strip() for cell in cells])

        return rows

    def _image_to_base64(self, image_bytes: bytes) -> str:
        """Convert image bytes to base64 string for AI analysis."""
        return base64.b64encode(image_bytes).decode('utf-8')

    def _is_diagram_or_flowchart(self, image_bytes: bytes) -> bool:
        """Heuristic to determine if an image might be a diagram or flowchart."""
        try:
            image = Image.open(io.BytesIO(image_bytes))
            gray_image = image.convert('L')

            img_array = np.array(gray_image)
            contrast = img_array.std()

            return contrast > 50

        except Exception as e:
            logger.warning(f"Error in diagram detection heuristic: {e}")
            return False

    def _analyze_image_with_ai(self, image_bytes: bytes, shape_name: str) -> Dict[str, Any]:
        """Analyze image using AI to determine content type."""
        if not self.ai_analysis_enabled:
            # Enhanced fallback analysis
            try:
                pil_image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
                content_type = self.detect_content_type(pil_image)

                if content_type == 'table':
                    detected_tables = self.detect_tables_with_transformer(pil_image)
                    if detected_tables:
                        return {
                            "analysis_type": "table",
                            "structured_content": f"Table detected with {len(detected_tables)} regions",
                            "table_data": detected_tables[0]['table_data'] if detected_tables else {}
                        }

                # Enhanced OCR fallback
                processed_img = self.preprocess_image_for_ocr(pil_image, content_type)
                ocr_text = pytesseract.image_to_string(processed_img, config=self.ocr_configs.get(content_type, self.ocr_configs['general']))

                return {
                    "analysis_type": "enhanced_ocr",
                    "content_type": content_type,
                    "structured_content": f"Content Type: {content_type}\n\nExtracted Text: {ocr_text.strip()}"
                }
            except Exception as e:
                return {"analysis_type": "error", "content": f"Enhanced analysis failed: {str(e)}"}

        try:
            base64_image = self._image_to_base64(image_bytes)
            is_likely_diagram = self._is_diagram_or_flowchart(image_bytes)

            if is_likely_diagram and self.diagram_analyzer:
                analysis = self.diagram_analyzer(image_documents=[base64_image])
                return {
                    "analysis_type": "diagram",
                    "diagram_type": analysis.diagram_type,
                    "main_elements": analysis.main_elements,
                    "relationships": analysis.relationships,
                    "text_content": analysis.text_content,
                    "summary": analysis.summary,
                    "structured_content": f"Diagram Type: {analysis.diagram_type}\n\n"
                                        f"Main Elements: {', '.join(analysis.main_elements)}\n\n"
                                        f"Relationships: {'; '.join(analysis.relationships)}\n\n"
                                        f"Text Content: {analysis.text_content}\n\n"
                                        f"Summary: {analysis.summary}"
                }
            else:
                if self.image_analyzer:
                    analysis = self.image_analyzer(image_documents=[base64_image])
                    return {
                        "analysis_type": "image",
                        "image_type": analysis.image_type,
                        "objects_detected": analysis.objects_detected,
                        "text_content": analysis.text_content,
                        "description": analysis.description,
                        "key_insights": analysis.key_insights,
                        "structured_content": f"Image Type: {analysis.image_type}\n\n"
                                            f"Objects Detected: {', '.join(analysis.objects_detected)}\n\n"
                                            f"Text Content: {analysis.text_content}\n\n"
                                            f"Description: {analysis.description}\n\n"
                                            f"Key Insights: {'; '.join(analysis.key_insights)}"
                    }

        except Exception as e:
            logger.error(f"Error in AI image analysis for {shape_name}: {e}")
            return {"analysis_type": "error", "content": f"AI analysis failed: {str(e)}"}

    def _create_enhanced_metadata(self, slide_num: int, shape_idx: int, shape, base_metadata: Dict) -> Dict[str, Any]:
        """Create enhanced metadata with proper page numbering for RAG pipeline."""
        # Base enhanced metadata
        enhanced_metadata = {
            # Core RAG Pipeline attributes - CRITICAL
            "page_numbers": [slide_num],  # CRITICAL: Must be List[int] for RAG pipeline
            "slide_number": slide_num,  # Legacy compatibility
            "page_number": slide_num,   # Legacy compatibility
            "document_id": self.document_id,
            "project_id": self.project_id,
            "file_type": "pptx",

            # Shape-specific metadata
            "shape_name": shape.name or f"Shape_{shape_idx}",
            "shape_type_raw": shape.shape_type.name if shape.shape_type else "UNKNOWN",
            "shape_idx_on_slide": shape_idx,

            # Enhanced positioning
            "bbox": [int(shape.left), int(shape.top), int(shape.width), int(shape.height)] if hasattr(shape, 'left') else [0, 0, 0, 0],
            "bbox_units": "pptx_emu",
            "page_width": getattr(self, 'slide_width', 0),
            "page_height": getattr(self, 'slide_height', 0),

            # Content classification
            "extraction_confidence": "high",  # Can be overridden by specific extractors
        }

        # Merge with base metadata
        enhanced_metadata.update(base_metadata)

        return enhanced_metadata

    def _extract_text_from_shape(self, shape, slide_num: int, shape_idx: int) -> Optional[Tuple[str, Dict[str, Any]]]:
        """Extract text content from a shape with enhanced metadata."""
        if not shape.has_text_frame:
            return None

        text = shape.text.strip()
        if not text:
            return None

        base_metadata = {
            "block_type": self._get_shape_type(shape),
            "source_type": "text",
        }

        metadata = self._create_enhanced_metadata(slide_num, shape_idx, shape, base_metadata)
        return (text, metadata)

    def _extract_image_from_shape(self, shape, slide_num: int, shape_idx: int) -> Optional[Tuple[str, Dict[str, Any]]]:
        """Extract and process image from a shape with enhanced analysis."""
        if shape.shape_type != MSO_SHAPE_TYPE.PICTURE:
            return None

        try:
            image_bytes = shape.image.blob
            shape_name = shape.name or f"Image_{shape_idx}"

            # Enhanced AI analysis
            ai_analysis = self._analyze_image_with_ai(image_bytes, shape_name)

            # Traditional OCR processing (if available)
            ocr_text = ""
            if self.image_processor:
                try:
                    result = self.image_processor.process_bytes(image_bytes)
                    ocr_text = result.get('combined_text', '').strip()
                except Exception as e:
                    logger.warning(f"OCR processing failed for {shape_name}: {e}")

            # Enhanced OCR fallback
            if not ocr_text:
                try:
                    pil_image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
                    content_type = self.detect_content_type(pil_image)
                    processed_img = self.preprocess_image_for_ocr(pil_image, content_type)
                    ocr_text = pytesseract.image_to_string(processed_img, config=self.ocr_configs.get(content_type, self.ocr_configs['general']))
                except Exception as e:
                    logger.warning(f"Enhanced OCR failed for {shape_name}: {e}")

            # Combine AI analysis with OCR
            combined_content = []

            if ai_analysis.get("structured_content"):
                combined_content.append("=== AI Analysis ===")
                combined_content.append(ai_analysis["structured_content"])

            if ocr_text.strip():
                combined_content.append("=== OCR Text ===")
                combined_content.append(ocr_text.strip())

            if not combined_content:
                return None

            final_content = "\n\n".join(combined_content)

            base_metadata = {
                "block_type": "image_analysis" if ai_analysis.get("analysis_type") in ["diagram", "image"] else "image_text",
                "source_type": "image",
                "ai_analysis_type": ai_analysis.get("analysis_type", "none"),
                "has_ocr": bool(ocr_text.strip()),
                "has_ai_analysis": ai_analysis.get("analysis_type") in ["diagram", "image"],
            }

            # Add specific metadata based on analysis type
            if ai_analysis.get("analysis_type") == "diagram":
                base_metadata.update({
                    "diagram_type": ai_analysis.get("diagram_type", "unknown"),
                    "main_elements_count": len(ai_analysis.get("main_elements", [])),
                    "relationships_count": len(ai_analysis.get("relationships", []))
                })
            elif ai_analysis.get("analysis_type") == "image":
                base_metadata.update({
                    "image_type": ai_analysis.get("image_type", "unknown"),
                    "objects_count": len(ai_analysis.get("objects_detected", [])),
                    "has_insights": len(ai_analysis.get("key_insights", [])) > 0
                })

            metadata = self._create_enhanced_metadata(slide_num, shape_idx, shape, base_metadata)
            return (final_content, metadata)

        except Exception as e:
            logger.error(f"Error processing image in slide {slide_num}, shape {shape.name or shape_idx}: {e}")
            return None

    def _extract_table_from_shape(self, shape, slide_num: int, shape_idx: int) -> Optional[Tuple[str, Dict[str, Any]]]:
        """Extract table content from a shape with enhanced metadata."""
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
                headers = table_lines[0].split(" | ") if table_lines else []

                base_metadata = {
                    "block_type": "table",
                    "source_type": "table",
                    "table_rows": len(table.rows),
                    "table_cols": len(table.columns),
                    "column_names": headers,  # CRITICAL for table-aware processing
                    "extraction_method": "native_pptx"
                }

                metadata = self._create_enhanced_metadata(slide_num, shape_idx, shape, base_metadata)
                return (table_text, metadata)

        except Exception as e:
            logger.error(f"Error extracting table from slide {slide_num}, shape {shape.name or shape_idx}: {e}")

        return None

    def _extract_chart_from_shape(self, shape, slide_num: int, shape_idx: int) -> Optional[Tuple[str, Dict[str, Any]]]:
        """Extract chart data from a shape with enhanced analysis."""
        if shape.shape_type != MSO_SHAPE_TYPE.CHART:
            return None

        if not hasattr(shape, 'chart'):
            return None

        try:
            chart = shape.chart
            if chart is None:
                return None

            chart_info = []

            # Extract chart title with safety checks
            try:
                if hasattr(chart, 'chart_title') and chart.chart_title and hasattr(chart.chart_title, 'text') and chart.chart_title.text:
                    chart_info.append(f"Chart Title: {chart.chart_title.text}")
            except Exception as e:
                logger.debug(f"Could not extract chart title: {e}")

            # Extract series information with safety checks
            try:
                if hasattr(chart, 'series') and chart.series:
                    for i, series in enumerate(chart.series):
                        if hasattr(series, 'name') and series.name:
                            chart_info.append(f"Series {i+1}: {series.name}")
            except Exception as e:
                logger.debug(f"Could not extract chart series: {e}")

            # Extract axis information with safety checks
            try:
                if hasattr(chart, 'category_axis') and chart.category_axis and hasattr(chart.category_axis, 'title') and chart.category_axis.title:
                    chart_info.append(f"X-Axis: {chart.category_axis.title.text}")
            except Exception as e:
                logger.debug(f"Could not extract X-axis info: {e}")

            try:
                if hasattr(chart, 'value_axis') and chart.value_axis and hasattr(chart.value_axis, 'title') and chart.value_axis.title:
                    chart_info.append(f"Y-Axis: {chart.value_axis.title.text}")
            except Exception as e:
                logger.debug(f"Could not extract Y-axis info: {e}")

            # If we couldn't extract any specific info, at least note that a chart exists
            if not chart_info:
                chart_info.append("Chart detected (details not accessible)")

            chart_text = "\n".join(chart_info)

            base_metadata = {
                "block_type": "chart",
                "source_type": "chart",
                "chart_type": chart.chart_type.name if hasattr(chart, 'chart_type') and chart.chart_type else "UNKNOWN",
                "extraction_method": "native_pptx"
            }

            metadata = self._create_enhanced_metadata(slide_num, shape_idx, shape, base_metadata)
            return (chart_text, metadata)

        except Exception as e:
            logger.error(f"Error extracting chart from slide {slide_num}, shape {shape.name or shape_idx}: {e}")
            return None

    def _extract_table_from_image(self, shape, slide_num: int, shape_idx: int) -> Optional[Tuple[str, Dict[str, Any]]]:
        """Enhanced method to extract tables from images using TableTransformer."""
        if shape.shape_type != MSO_SHAPE_TYPE.PICTURE:
            return None

        try:
            image_bytes = shape.image.blob
            pil_image = Image.open(io.BytesIO(image_bytes)).convert("RGB")

            # Detect if this is likely a table
            content_type = self.detect_content_type(pil_image)
            if content_type != 'table':
                return None

            # Try TableTransformer detection
            detected_tables = self.detect_tables_with_transformer(pil_image)

            if detected_tables:
                table_data = detected_tables[0]['table_data']  # Use first detected table

                if table_data.get('parsed_rows'):
                    rows = table_data['parsed_rows']
                    headers = rows[0] if rows else []

                    # Create markdown table
                    markdown = "| " + " | ".join(headers) + " |\n"
                    markdown += "| " + " | ".join(["---"] * len(headers)) + " |\n"

                    for row in rows[1:]:
                        padded_row = row + [''] * (len(headers) - len(row))
                        markdown += "| " + " | ".join(padded_row[:len(headers)]) + " |\n"

                    base_metadata = {
                        "block_type": "table",
                        "source_type": "table",
                        "extraction_method": "table_transformer",
                        "confidence": detected_tables[0]['confidence'],
                        "column_names": headers,  # CRITICAL for table-aware processing
                        "table_rows": len(rows),
                        "table_cols": len(headers)
                    }

                    metadata = self._create_enhanced_metadata(slide_num, shape_idx, shape, base_metadata)
                    return (markdown, metadata)

            # Fallback to enhanced OCR for table-like content
            processed_img = self.preprocess_image_for_ocr(pil_image, 'table')
            ocr_text = pytesseract.image_to_string(processed_img, config=self.ocr_configs['table'])

            if ocr_text.strip():
                rows = self.parse_table_text(ocr_text)
                if rows:
                    headers = rows[0] if rows else []

                    # Create markdown table
                    markdown = "| " + " | ".join(headers) + " |\n"
                    markdown += "| " + " | ".join(["---"] * len(headers)) + " |\n"

                    for row in rows[1:]:
                        padded_row = row + [''] * (len(headers) - len(row))
                        markdown += "| " + " | ".join(padded_row[:len(headers)]) + " |\n"

                    base_metadata = {
                        "block_type": "table",
                        "source_type": "table",
                        "extraction_method": "enhanced_ocr",
                        "column_names": headers,  # CRITICAL for table-aware processing
                        "table_rows": len(rows),
                        "table_cols": len(headers)
                    }

                    metadata = self._create_enhanced_metadata(slide_num, shape_idx, shape, base_metadata)
                    return (markdown, metadata)

        except Exception as e:
            logger.warning(f"Error extracting table from image in slide {slide_num}: {e}")

        return None

    def _process_slide(self, slide, slide_num: int) -> List[Tuple[str, Dict[str, Any]]]:
        """Process a single slide and extract all content with enhanced processing."""
        slide_blocks = []
        shape_idx = 0

        # Process slide title first
        if slide.shapes.title and slide.shapes.title.has_text_frame:
            title_text = slide.shapes.title.text.strip()
            if title_text:
                shape_idx += 1
                base_metadata = {
                    "block_type": "title",
                    "source_type": "text",
                    "shape_type": "title"
                }
                metadata = self._create_enhanced_metadata(slide_num, shape_idx, slide.shapes.title, base_metadata)
                slide_blocks.append((title_text, metadata))

        # Process all other shapes with enhanced detection
        for shape in slide.shapes:
            shape_idx += 1

            # Skip title if already processed
            if shape == slide.shapes.title:
                continue

            try:
                # Enhanced image processing with table detection
                if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
                    # Try enhanced table detection first
                    table_result = self._extract_table_from_image(shape, slide_num, shape_idx)
                    if table_result:
                        slide_blocks.append(table_result)
                        continue

                # Extract text
                text_result = self._extract_text_from_shape(shape, slide_num, shape_idx)
                if text_result:
                    slide_blocks.append(text_result)

                # Extract image content (with enhanced AI analysis)
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

            except Exception as e:
                logger.error(f"Error processing shape {shape_idx} on slide {slide_num}: {e}")
                continue

        return slide_blocks

    def create_llamaindex_documents(self, processed_blocks: List[Tuple[str, Dict[str, Any]]]) -> List[Document]:
        """Create LlamaIndex documents from processed blocks with proper page numbering."""
        if not LLAMAINDEX_AVAILABLE:
            logger.warning("LlamaIndex not available. Returning empty list.")
            return []

        documents = []

        for content, metadata in processed_blocks:
            # Ensure page_numbers is properly set
            if 'page_numbers' not in metadata and 'slide_number' in metadata:
                metadata['page_numbers'] = [metadata['slide_number']]
            elif 'page_numbers' not in metadata and 'page_number' in metadata:
                metadata['page_numbers'] = [metadata['page_number']]

            doc = Document(
                text=content,
                metadata=metadata,
                doc_id=f"slide_{metadata.get('slide_number', metadata.get('page_number', 0))}_shape_{metadata.get('shape_idx_on_slide', 0)}"
            )
            documents.append(doc)

        return documents

    def convert_to_nodes(self, processed_blocks: List[Tuple[str, Dict[str, Any]]]) -> List:
        """Convert processed blocks to RAG pipeline nodes with proper page numbering."""
        if not self.node_converter:
            logger.warning("NodeConverter not available. Cannot convert to nodes.")
            return []

        nodes = []

        for content, metadata in processed_blocks:
            try:
                # Ensure page_numbers is properly formatted as List[int]
                if 'page_numbers' not in metadata:
                    slide_num = metadata.get('slide_number') or metadata.get('page_number', 1)
                    metadata['page_numbers'] = [slide_num]
                elif not isinstance(metadata['page_numbers'], list):
                    metadata['page_numbers'] = [metadata['page_numbers']]

                # Create a chunk-like object for the node converter
                chunk = {
                    'content': content,
                    'metadata': metadata
                }

                # Use the node converter to create the node with proper page numbering
                node = self.node_converter.convert_chunk_to_node(chunk)

                # Double-check that page_numbers is properly set
                if hasattr(node, 'metadata') and 'page_numbers' in metadata:
                    node.metadata['page_numbers'] = metadata['page_numbers']

                nodes.append(node)

            except Exception as e:
                logger.error(f"Error converting block to node: {e}")
                continue

        logger.info(f"Converted {len(nodes)} blocks to RAG pipeline nodes")
        return nodes

    def process_file(self, file_path: Union[str, Path]) -> List[Tuple[str, Dict[str, Any]]]:
        """Process a PPTX file and extract structured content with enhanced features."""
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

            # Store presentation dimensions for processing
            try:
                self.slide_width = int(presentation.slide_width)
                self.slide_height = int(presentation.slide_height)
            except:
                self.slide_width = self.slide_height = 0

            # Process each slide
            for slide_num, slide in enumerate(presentation.slides, 1):
                slide_blocks = self._process_slide(slide, slide_num)
                processed_blocks.extend(slide_blocks)

            if not processed_blocks:
                logger.warning(f"No content blocks extracted from {file_path}")

            logger.info(f"Successfully processed {file_path}: {len(processed_blocks)} blocks from {len(presentation.slides)} slides")

            # Log enhanced analysis statistics
            ai_analyzed = sum(1 for _, metadata in processed_blocks if metadata.get('has_ai_analysis', False))
            diagrams_found = sum(1 for _, metadata in processed_blocks if metadata.get('ai_analysis_type') == 'diagram')
            tables_found = sum(1 for _, metadata in processed_blocks if metadata.get('block_type') == 'table')
            charts_found = sum(1 for _, metadata in processed_blocks if metadata.get('block_type') == 'chart')

            logger.info(f"Enhanced Analysis Statistics: {ai_analyzed} AI analyzed, {diagrams_found} diagrams, {tables_found} tables, {charts_found} charts")

            return processed_blocks

        except Exception as e:
            logger.error(f"Error processing PPTX file {file_path}: {e}")
            raise FileProcessingError(f"Error processing PPTX file {file_path}: {e}", filepath=str(file_path))

    def process_file_to_nodes(self, file_path: Union[str, Path]) -> List:
        """Process PPTX file directly to RAG pipeline nodes with proper page numbering."""
        processed_blocks = self.process_file(file_path)
        return self.convert_to_nodes(processed_blocks)

    def process_pptx(self, file_path: str) -> List[Tuple[str, Dict[str, Any]]]:
        """Legacy method for backward compatibility."""
        return self.process_file(file_path)

    def get_analysis_summary(self, processed_blocks: List[Tuple[str, Dict[str, Any]]]) -> Dict[str, Any]:
        """Get a comprehensive summary of the analysis results."""
        total_blocks = len(processed_blocks)
        slides = set(metadata.get('slide_number') or metadata.get('page_number') for _, metadata in processed_blocks)

        # Count different types of content
        text_blocks = sum(1 for _, metadata in processed_blocks if metadata.get('source_type') == 'text')
        image_blocks = sum(1 for _, metadata in processed_blocks if metadata.get('source_type') == 'image')
        table_blocks = sum(1 for _, metadata in processed_blocks if metadata.get('source_type') == 'table')
        chart_blocks = sum(1 for _, metadata in processed_blocks if metadata.get('source_type') == 'chart')

        # Enhanced analysis statistics
        ai_analyzed = sum(1 for _, metadata in processed_blocks if metadata.get('has_ai_analysis', False))
        diagrams = sum(1 for _, metadata in processed_blocks if metadata.get('ai_analysis_type') == 'diagram')
        tables_with_transformer = sum(1 for _, metadata in processed_blocks
                                    if metadata.get('block_type') == 'table' and metadata.get('extraction_method') == 'table_transformer')

        # Page numbering validation
        page_numbers_valid = all(
            isinstance(metadata.get('page_numbers'), list) and
            len(metadata.get('page_numbers', [])) > 0
            for _, metadata in processed_blocks
        )

        return {
            'total_blocks': total_blocks,
            'total_slides': len(slides),
            'content_breakdown': {
                'text_blocks': text_blocks,
                'image_blocks': image_blocks,
                'table_blocks': table_blocks,
                'chart_blocks': chart_blocks
            },
            'ai_analysis': {
                'blocks_analyzed': ai_analyzed,
                'diagrams_identified': diagrams,
                'analysis_enabled': self.ai_analysis_enabled
            },
            'enhanced_features': {
                'table_transformer_enabled': self.table_transformer_available,
                'tables_with_transformer': tables_with_transformer,
                'enhanced_ocr_enabled': True
            },
            'rag_pipeline_compatibility': {
                'document_id_present': bool(self.document_id),
                'project_id_present': bool(self.project_id),
                'node_converter_available': bool(self.node_converter),
                'page_numbers_valid': page_numbers_valid,
                'table_column_names_present': all(
                    'column_names' in metadata for _, metadata in processed_blocks
                    if metadata.get('block_type') == 'table'
                )
            }
        }

