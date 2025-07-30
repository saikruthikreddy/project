"""
PowerPoint (PPTX) file processor for extracting structured content, images, and metadata using LlamaIndex.
"""
from pptx import Presentation
from pptx.enum.shapes import PP_PLACEHOLDER, MSO_SHAPE_TYPE
from typing import List, Dict, Any, Tuple, Optional, Union
import logging
from pathlib import Path
import io
import base64
from PIL import Image
import tempfile
import os

# LlamaIndex imports
from llama_index.core import Document, VectorStoreIndex, ServiceContext
from llama_index.core.node_parser import SimpleNodeParser
from llama_index.core.schema import ImageDocument, TextNode, ImageNode
from llama_index.multi_modal_llms.openai import OpenAIMultiModal
from llama_index.core.multi_modal_llms.generic_utils import encode_image
from llama_index.core.program import MultiModalLLMCompletionProgram
from llama_index.core.output_parsers import PydanticOutputParser
from pydantic import BaseModel, Field

from giani_pkb.utils.exceptions import ParsingError, FileProcessingError

logger = logging.getLogger(__name__)

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

class PptxProcessor:
    """
    Enhanced processor for PowerPoint (PPTX) files that extracts structured content using LlamaIndex.
    
    Features:
    - Advanced text extraction from slides with metadata
    - Enhanced image extraction with AI-powered analysis
    - Diagram and flowchart understanding
    - Table content extraction
    - Chart data extraction with AI interpretation
    - Slide-based organization
    - Shape type classification
    - Multi-modal AI analysis for complex visual content
    """

    def __init__(self, image_processor=None, openai_api_key=None):
        """
        Initialize the PPTX processor with LlamaIndex capabilities.
        
        Args:
            image_processor: Optional image processor for OCR (will create default if None)
            openai_api_key: OpenAI API key for multi-modal analysis
        """
        self.supported_extensions = {'.pptx'}
        
        # Initialize image processor
        if image_processor is None:
            try:
                from giani_pkb.preprocessing.image_processor import ImageProcessor
                self.image_processor = ImageProcessor()
                logger.info("PPTX processor initialized with default image processor")
            except ImportError:
                logger.warning("Image processor not available. Basic image extraction will be used.")
                self.image_processor = None
        else:
            self.image_processor = image_processor

        # Initialize LlamaIndex components
        self.openai_api_key = openai_api_key or os.getenv("OPENAI_API_KEY")
        if self.openai_api_key:
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
            logger.warning("OpenAI API key not provided. AI-powered analysis will be disabled.")
            self.ai_analysis_enabled = False

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

    def _image_to_base64(self, image_bytes: bytes) -> str:
        """Convert image bytes to base64 string for AI analysis."""
        return base64.b64encode(image_bytes).decode('utf-8')

    def _is_diagram_or_flowchart(self, image_bytes: bytes) -> bool:
        """
        Heuristic to determine if an image might be a diagram or flowchart.
        This is a simple check - the AI analysis will provide more accurate classification.
        """
        try:
            image = Image.open(io.BytesIO(image_bytes))
            # Simple heuristics: diagrams often have specific characteristics
            # This is just a preliminary check; AI analysis will be more accurate
            width, height = image.size
            
            # Convert to grayscale for analysis
            gray_image = image.convert('L')
            
            # Check for high contrast (common in diagrams)
            import numpy as np
            img_array = np.array(gray_image)
            contrast = img_array.std()
            
            # Diagrams typically have higher contrast and specific aspect ratios
            return contrast > 50  # Threshold can be adjusted
            
        except Exception as e:
            logger.warning(f"Error in diagram detection heuristic: {e}")
            return False

    def _analyze_image_with_ai(self, image_bytes: bytes, shape_name: str) -> Dict[str, Any]:
        """
        Analyze image using AI to determine if it's a diagram, flowchart, or regular image.
        
        Args:
            image_bytes: Image data as bytes
            shape_name: Name of the shape containing the image
            
        Returns:
            Dictionary containing analysis results
        """
        if not self.ai_analysis_enabled:
            return {"analysis_type": "basic", "content": "AI analysis not available"}

        try:
            # Convert image to base64 for AI analysis
            base64_image = self._image_to_base64(image_bytes)
            
            # First, determine if it's likely a diagram/flowchart
            is_likely_diagram = self._is_diagram_or_flowchart(image_bytes)
            
            if is_likely_diagram:
                # Use diagram analyzer
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
                # Use general image analyzer
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
        Extract and process image from a shape with enhanced AI analysis.
        
        Args:
            shape: PowerPoint shape object
            slide_num: Slide number
            shape_idx: Shape index on slide
            
        Returns:
            (image_content, metadata) tuple or None if processing fails
        """
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
            
            # Combine AI analysis with OCR
            combined_content = []
            
            if ai_analysis.get("structured_content"):
                combined_content.append("=== AI Analysis ===")
                combined_content.append(ai_analysis["structured_content"])
            
            if ocr_text:
                combined_content.append("=== OCR Text ===")
                combined_content.append(ocr_text)
            
            if not combined_content:
                return None
                
            final_content = "\n\n".join(combined_content)
            
            # Enhanced metadata
            metadata = {
                "page_number": slide_num,
                "block_type": "image_analysis" if ai_analysis.get("analysis_type") in ["diagram", "image"] else "image_text",
                "source_type": "image",
                "shape_name": shape_name,
                "shape_idx_on_slide": shape_idx,
                "file_type": "pptx",
                "ai_analysis_type": ai_analysis.get("analysis_type", "none"),
                "has_ocr": bool(ocr_text),
                "has_ai_analysis": ai_analysis.get("analysis_type") in ["diagram", "image"]
            }
            
            # Add specific metadata based on analysis type
            if ai_analysis.get("analysis_type") == "diagram":
                metadata.update({
                    "diagram_type": ai_analysis.get("diagram_type", "unknown"),
                    "main_elements_count": len(ai_analysis.get("main_elements", [])),
                    "relationships_count": len(ai_analysis.get("relationships", []))
                })
            elif ai_analysis.get("analysis_type") == "image":
                metadata.update({
                    "image_type": ai_analysis.get("image_type", "unknown"),
                    "objects_count": len(ai_analysis.get("objects_detected", [])),
                    "has_insights": len(ai_analysis.get("key_insights", [])) > 0
                })

            return (final_content, metadata)
            
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
        Extract chart data from a shape with enhanced analysis.
        
        Args:
            shape: PowerPoint shape object
            slide_num: Slide number
            shape_idx: Shape index on slide
            
        Returns:
            (chart_text, metadata) tuple or None if no chart
        """
        # More robust chart detection
        if shape.shape_type != MSO_SHAPE_TYPE.CHART:
            return None
            
        # Additional safety check
        if not hasattr(shape, 'chart'):
            return None

        try:
            # Try to access chart with proper error handling
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
            metadata = {
                "page_number": slide_num,
                "block_type": "chart",
                "source_type": "chart",
                "shape_name": shape.name or f"Chart_{shape_idx}",
                "shape_idx_on_slide": shape_idx,
                "chart_type": chart.chart_type.name if hasattr(chart, 'chart_type') and chart.chart_type else "UNKNOWN",
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
                
            try:
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
                # Continue processing other shapes even if one fails
                continue

        return slide_blocks

    def create_llamaindex_documents(self, processed_blocks: List[Tuple[str, Dict[str, Any]]]) -> List[Document]:
        """
        Create LlamaIndex documents from processed blocks for further analysis.
        
        Args:
            processed_blocks: List of (content, metadata) tuples
            
        Returns:
            List of LlamaIndex Document objects
        """
        documents = []
        
        for content, metadata in processed_blocks:
            doc = Document(
                text=content,
                metadata=metadata,
                doc_id=f"slide_{metadata['page_number']}_shape_{metadata.get('shape_idx_on_slide', 0)}"
            )
            documents.append(doc)
            
        return documents

    def process_file(self, file_path: Union[str, Path]) -> List[Tuple[str, Dict[str, Any]]]:
        """
        Process a PPTX file and extract structured content with enhanced AI analysis.
        
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
            
            # Log AI analysis statistics
            ai_analyzed = sum(1 for _, metadata in processed_blocks if metadata.get('has_ai_analysis', False))
            diagrams_found = sum(1 for _, metadata in processed_blocks if metadata.get('ai_analysis_type') == 'diagram')
            
            logger.info(f"AI Analysis Statistics: {ai_analyzed} blocks analyzed, {diagrams_found} diagrams/flowcharts identified")

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

    def get_analysis_summary(self, processed_blocks: List[Tuple[str, Dict[str, Any]]]) -> Dict[str, Any]:
        """
        Get a summary of the analysis results.
        
        Args:
            processed_blocks: List of processed content blocks
            
        Returns:
            Dictionary containing analysis summary
        """
        total_blocks = len(processed_blocks)
        slides = set(metadata['page_number'] for _, metadata in processed_blocks)
        
        # Count different types of content
        text_blocks = sum(1 for _, metadata in processed_blocks if metadata.get('source_type') == 'text')
        image_blocks = sum(1 for _, metadata in processed_blocks if metadata.get('source_type') == 'image')
        table_blocks = sum(1 for _, metadata in processed_blocks if metadata.get('source_type') == 'table')
        chart_blocks = sum(1 for _, metadata in processed_blocks if metadata.get('source_type') == 'chart')
        
        # AI analysis statistics
        ai_analyzed = sum(1 for _, metadata in processed_blocks if metadata.get('has_ai_analysis', False))
        diagrams = sum(1 for _, metadata in processed_blocks if metadata.get('ai_analysis_type') == 'diagram')
        
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
            }
        }