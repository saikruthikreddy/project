"""
Enhanced PDF file processor with Azure Blob Storage integration and complete RAG pipeline compatibility.
Modified to work with container and blob_name parameters like the DOCX processor.
"""
from __future__ import annotations

import fitz  # PyMuPDF
import logging
import re
import io
import uuid
import json
import base64
import tempfile
import os
from pathlib import Path
from typing import List, Dict, Any, Tuple, Union, Optional
from datetime import datetime
import mimetypes

import numpy as np
import cv2
import pytesseract
import torch
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

# Optional dependencies with graceful fallbacks
try:
    from transformers import AutoProcessor, TableTransformerForObjectDetection
    TABLE_TRANSFORMER_AVAILABLE = True
except ImportError:
    TABLE_TRANSFORMER_AVAILABLE = False

try:
    from llama_index.core import download_loader, Document, VectorStoreIndex, ServiceContext
    from llama_index.core.node_parser import SimpleNodeParser
    from llama_index.core.schema import TextNode, Document as LlamaDocument
    LLAMAINDEX_AVAILABLE = True
except ImportError:
    LLAMAINDEX_AVAILABLE = False

try:
    from pydantic import BaseModel, Field
    PYDANTIC_AVAILABLE = True
except ImportError:
    PYDANTIC_AVAILABLE = False

# Import Azure blob storage service and exceptions
from services.blob_storage_service import blob_storage_service
from utils.exceptions import ParsingError, FileProcessingError

logger = logging.getLogger(__name__)


class EnhancedPdfProcessor:
    """
    Enhanced processor for PDF files with Azure Blob Storage integration.
    
    Features:
    - Text extraction with block-level metadata using LlamaIndex
    - Enhanced image text extraction and OCR processing  
    - Table detection using TableTransformer
    - Chart/diagram recognition
    - Font analysis for heading detection
    - Contextual text extraction around images
    - Page-based organization with normalized page_numbers
    - Complete RAG pipeline compatibility
    - Azure Blob Storage integration
    """

    # Class constants
    SUPPORTED_EXTENSIONS = {'.pdf'}
    HEADING_FONT_SIZE_THRESHOLD = 14.0
    SUBHEADING_FONT_SIZE_THRESHOLD = 12.0
    MIN_IMAGE_SIZE = (30, 30)
    DEFAULT_OCR_CONFIDENCE_THRESHOLD = 30
    CONTEXTUAL_TEXT_DISTANCE = 50
    CONTEXTUAL_TEXT_MAX_WORDS = 20
    TABLE_DETECTION_THRESHOLD = 0.7
    STRUCTURE_RECOGNITION_THRESHOLD = 0.5
    MAX_IMAGE_SIZE_FOR_TRANSFORMER = 1024

    # Pattern constants for visual classification
    CHART_PATTERNS = {
        'chart', 'graph', 'plot', 'axis', 'legend', 'data', 'figure',
        'bar', 'line', 'pie', 'scatter', 'histogram', 'trend', 'scale'
    }
    
    TABLE_PATTERNS = {
        'table', 'row', 'column', 'cell', 'header', 'data',
        'record', 'entry', 'field', 'value', 'total', 'sum'
    }

    def __init__(self, image_processor=None, use_llamaindex: bool = True, api_key: Optional[str] = None):
        """
        Initialize the Enhanced PDF processor.
        
        Args:
            image_processor: Optional image processor for OCR
            use_llamaindex: Whether to use LlamaIndex for text extraction
            api_key: Optional API key for enhanced processing
        """
        self.supported_extensions = self.SUPPORTED_EXTENSIONS
        self.api_key = api_key
        self._initialize_llamaindex(use_llamaindex)
        self._initialize_image_processor(image_processor)
        self._initialize_table_transformer()
        self._setup_ocr_configurations()

    def _initialize_llamaindex(self, use_llamaindex: bool) -> None:
        """Initialize LlamaIndex components with proper error handling."""
        self.use_llamaindex = use_llamaindex and LLAMAINDEX_AVAILABLE

        if self.use_llamaindex and not LLAMAINDEX_AVAILABLE:
            logger.warning("LlamaIndex not available. Falling back to PyMuPDF extraction.")
            self.use_llamaindex = False

        if self.use_llamaindex:
            try:
                PDFReader = download_loader("PDFReader")
                self.pdf_loader = PDFReader()
                self.node_parser = SimpleNodeParser.from_defaults()
                logger.info("PDF processor initialized with LlamaIndex support")
            except Exception as e:
                logger.error(f"Error initializing LlamaIndex components: {e}")
                self.use_llamaindex = False

    def _initialize_image_processor(self, image_processor) -> None:
        """Initialize image processor with fallback to enhanced OCR."""
        if image_processor is None:
            try:
                from preprocessing.image_processor import ImageProcessor
                self.image_processor = ImageProcessor()
                logger.info("PDF processor initialized with default image processor")
            except ImportError:
                logger.warning("Image processor not available. Using enhanced OCR instead.")
                self.image_processor = None
        else:
            self.image_processor = image_processor

    def _initialize_table_transformer(self) -> None:
        """Initialize TableTransformer models with proper error handling."""
        self.table_transformer_available = False
        
        if not TABLE_TRANSFORMER_AVAILABLE:
            return

        try:
            self.table_detection_model = TableTransformerForObjectDetection.from_pretrained(
                "microsoft/table-transformer-detection"
            )
            self.table_structure_model = TableTransformerForObjectDetection.from_pretrained(
                "microsoft/table-transformer-structure-recognition"
            )
            self.table_processor = AutoProcessor.from_pretrained(
                "microsoft/table-transformer-detection",
                use_fast=True
            )
            self.table_transformer_available = True
            logger.info("TableTransformer models loaded successfully")
        except Exception as e:
            logger.warning(f"Could not load TableTransformer models: {e}")

    def _setup_ocr_configurations(self) -> None:
        """Setup OCR configurations for different content types."""
        self.ocr_configs = {
            'table': '--oem 3 --psm 6 -c tessedit_char_whitelist=0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz.,()%$-+/= ',
            'chart': '--oem 3 --psm 11 -c tessedit_char_whitelist=0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz.,()%$-+/=:',
            'general': '--oem 3 --psm 6',
            'numbers': '--oem 3 --psm 8 -c tessedit_char_whitelist=0123456789.,%$-+'
        }

    @staticmethod
    def _ensure_rgb_image(image: Image.Image) -> Image.Image:
        """Ensure image is in RGB format for model processing."""
        if image.mode == 'RGB':
            return image
        
        if image.mode == 'RGBA':
            background = Image.new('RGB', image.size, (255, 255, 255))
            background.paste(image, mask=image.split()[-1])
            return background
        
        return image.convert('RGB')

    def _preprocess_image_for_ocr(self, image: Image.Image, content_type: str = 'general') -> Image.Image:
        """Enhanced image preprocessing for better OCR accuracy."""
        image = self._ensure_rgb_image(image)
        opencv_image = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
        
        # Content-specific preprocessing
        if content_type == 'chart':
            opencv_image = cv2.convertScaleAbs(opencv_image, alpha=1.5, beta=10)
            opencv_image = cv2.bilateralFilter(opencv_image, 9, 80, 80)
        elif content_type == 'table':
            kernel = np.array([[-1, -1, -1], [-1, 9, -1], [-1, -1, -1]])
            opencv_image = cv2.filter2D(opencv_image, -1, kernel)
        
        # Convert to grayscale and apply adaptive thresholding
        gray = cv2.cvtColor(opencv_image, cv2.COLOR_BGR2GRAY)
        binary = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2
        )
        
        # Clean up with morphological operations
        kernel = np.ones((1, 1), np.uint8)
        cleaned = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)
        
        return Image.fromarray(cv2.cvtColor(cleaned, cv2.COLOR_GRAY2RGB))

    def _detect_tables_with_transformer(self, image: Image.Image) -> List[Dict[str, Any]]:
        """Use TableTransformer to detect and extract tables."""
        if not self.table_transformer_available:
            return self._detect_tables_fallback(image)
        
        try:
            image = self._ensure_rgb_image(image)
            
            # Resize image if too large
            if max(image.size) > self.MAX_IMAGE_SIZE_FOR_TRANSFORMER:
                ratio = self.MAX_IMAGE_SIZE_FOR_TRANSFORMER / max(image.size)
                new_size = tuple(int(dim * ratio) for dim in image.size)
                image = image.resize(new_size, Image.Resampling.LANCZOS)
            
            encoding = self.table_processor(image, return_tensors="pt")
            
            with torch.no_grad():
                outputs = self.table_detection_model(**encoding)
            
            target_sizes = torch.tensor([image.size[::-1]])
            results = self.table_processor.post_process_object_detection(
                outputs, 
                threshold=self.TABLE_DETECTION_THRESHOLD, 
                target_sizes=target_sizes
            )[0]
            
            tables = []
            for score, label, box in zip(results["scores"], results["labels"], results["boxes"]):
                if score > self.TABLE_DETECTION_THRESHOLD:
                    box_coords = [round(coord, 2) for coord in box.tolist()]
                    x1, y1, x2, y2 = box_coords
                    
                    table_crop = image.crop((x1, y1, x2, y2))
                    table_data = self._extract_table_structure(table_crop)
                    
                    tables.append({
                        "bbox": box_coords,
                        "confidence": score.item(),
                        "table_data": table_data,
                        "image_crop": table_crop
                    })
            
            return tables
            
        except Exception as e:
            logger.warning(f"TableTransformer detection failed: {e}, falling back to OCR")
            return self._detect_tables_fallback(image)

    def _detect_tables_fallback(self, image: Image.Image) -> List[Dict[str, Any]]:
        """Fallback table detection using OCR and heuristics."""
        try:
            processed_img = self._preprocess_image_for_ocr(image, 'table')
            
            ocr_data = pytesseract.image_to_data(
                processed_img, 
                config=self.ocr_configs['table'],
                output_type=pytesseract.Output.DICT
            )
            
            # Extract text with position information
            text_items = self._extract_positioned_text(ocr_data)
            
            # Group text into rows
            rows = self._group_text_into_rows(text_items)
            
            # Check if it looks like a table
            if self._is_table_structure(rows):
                table_text = self._format_fallback_table(rows)
                return [{
                    "bbox": [0, 0, image.width, image.height],
                    "confidence": 0.6,
                    "table_data": {
                        "structure_detected": True,
                        "raw_text": table_text,
                        "parsed_rows": self._parse_table_text(table_text),
                        "cell_count": len(text_items)
                    },
                    "image_crop": image
                }]
            
            return []
            
        except Exception as e:
            logger.error(f"Fallback table detection failed: {e}")
            return []

    def _extract_positioned_text(self, ocr_data: Dict[str, List]) -> List[Dict[str, Any]]:
        """Extract text with position information from OCR data."""
        text_items = []
        
        for word, conf, top, left in zip(
            ocr_data['text'], ocr_data['conf'], ocr_data['top'], ocr_data['left']
        ):
            if conf > self.DEFAULT_OCR_CONFIDENCE_THRESHOLD and word.strip():
                text_items.append({
                    'text': word.strip(),
                    'top': top,
                    'left': left,
                    'confidence': conf
                })
        
        return text_items

    def _group_text_into_rows(self, text_items: List[Dict[str, Any]]) -> Dict[int, List[Dict[str, Any]]]:
        """Group text items into rows based on vertical position."""
        rows = {}
        
        for item in text_items:
            row_key = item['top'] // 20 * 20  # Group by 20-pixel ranges
            if row_key not in rows:
                rows[row_key] = []
            rows[row_key].append(item)
        
        return rows

    def _is_table_structure(self, rows: Dict[int, List[Dict[str, Any]]]) -> bool:
        """Determine if the grouped text resembles a table structure."""
        if len(rows) < 2:
            return False
        
        avg_cols_per_row = sum(len(row) for row in rows.values()) / len(rows)
        return avg_cols_per_row >= 2

    def _format_fallback_table(self, rows: Dict[int, List[Dict[str, Any]]]) -> str:
        """Format detected text into table structure."""
        formatted_rows = []
        
        for top in sorted(rows.keys()):
            row_items = sorted(rows[top], key=lambda x: x['left'])
            row_text = " | ".join(item['text'] for item in row_items)
            formatted_rows.append(row_text)
        
        return "\n".join(formatted_rows)

    def _extract_table_structure(self, table_image: Image.Image) -> Dict[str, Any]:
        """Extract table structure with enhanced error handling."""
        try:
            table_image = self._ensure_rgb_image(table_image)
            processed_img = self._preprocess_image_for_ocr(table_image, 'table')
            
            # Try TableTransformer structure recognition if available
            structure_detected, cell_count = self._detect_table_structure_with_transformer(processed_img)
            
            # Extract text content
            table_text = pytesseract.image_to_string(
                processed_img, 
                config=self.ocr_configs['table']
            )
            
            rows = self._parse_table_text(table_text)
            
            return {
                "structure_detected": structure_detected,
                "raw_text": table_text,
                "parsed_rows": rows,
                "cell_count": cell_count if cell_count > 0 else self._calculate_cell_count(rows)
            }
            
        except Exception as e:
            logger.error(f"Table structure extraction failed: {e}")
            return self._create_fallback_table_data(table_image)

    def _detect_table_structure_with_transformer(self, processed_img: Image.Image) -> Tuple[bool, int]:
        """Detect table structure using TableTransformer if available."""
        if not self.table_transformer_available:
            return False, 0

        try:
            encoding = self.table_processor(processed_img, return_tensors="pt")
            
            with torch.no_grad():
                outputs = self.table_structure_model(**encoding)
            
            target_sizes = torch.tensor([processed_img.size[::-1]])
            results = self.table_processor.post_process_object_detection(
                outputs, 
                threshold=self.STRUCTURE_RECOGNITION_THRESHOLD, 
                target_sizes=target_sizes
            )[0]
            
            return len(results["boxes"]) > 0, len(results["boxes"])
            
        except Exception as e:
            logger.debug(f"Structure recognition failed: {e}")
            return False, 0

    def _calculate_cell_count(self, rows: List[List[str]]) -> int:
        """Calculate estimated cell count from parsed rows."""
        if not rows:
            return 0
        return len(rows) * (len(rows[0]) if rows[0] else 0)

    def _create_fallback_table_data(self, table_image: Image.Image) -> Dict[str, Any]:
        """Create fallback table data when extraction fails."""
        try:
            table_text = pytesseract.image_to_string(
                self._ensure_rgb_image(table_image), 
                config=self.ocr_configs['general']
            )
            return {
                "structure_detected": False,
                "raw_text": table_text,
                "parsed_rows": [],
                "cell_count": 0
            }
        except Exception as fallback_e:
            logger.error(f"Fallback OCR also failed: {fallback_e}")
            return {
                "structure_detected": False,
                "raw_text": "",
                "parsed_rows": [],
                "cell_count": 0
            }

    def _parse_table_text(self, text: str) -> List[List[str]]:
        """Parse OCR text into table structure."""
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        rows = []
        
        for line in lines:
            # Split on multiple spaces or tabs
            cells = re.split(r' {2,}|\t+', line)
            if len(cells) > 1:
                rows.append([cell.strip() for cell in cells])
        
        return rows

    def _extract_chart_data_advanced(self, image: Image.Image) -> Dict[str, Any]:
        """Enhanced chart data extraction with comprehensive analysis."""
        try:
            image = self._ensure_rgb_image(image)
            processed_img = self._preprocess_image_for_ocr(image, 'chart')
            
            # Extract structured OCR data
            ocr_data = pytesseract.image_to_data(
                processed_img, 
                config=self.ocr_configs['chart'],
                output_type=pytesseract.Output.DICT
            )
            
            chart_elements = self._parse_chart_elements(ocr_data)
            
            # Extract general text
            general_text = pytesseract.image_to_string(
                processed_img, 
                config=self.ocr_configs['general']
            )
            
            chart_type = self._detect_chart_type(general_text)
            confidence = self._calculate_chart_confidence(chart_elements, general_text)
            
            return {
                "chart_type": chart_type,
                "structured_data": chart_elements,
                "raw_text": general_text,
                "confidence_score": confidence
            }
            
        except Exception as e:
            logger.error(f"Chart data extraction failed: {e}")
            return {
                "chart_type": "unknown",
                "structured_data": [],
                "raw_text": "",
                "confidence_score": 0.0
            }

    def _parse_chart_elements(self, ocr_data: Dict[str, List]) -> List[Dict[str, Any]]:
        """Parse OCR data to extract chart elements."""
        elements = []
        
        words = ocr_data['text']
        confidences = ocr_data['conf']
        boxes = list(zip(
            ocr_data['left'], ocr_data['top'], 
            ocr_data['width'], ocr_data['height']
        ))
        
        for word, conf, box in zip(words, confidences, boxes):
            if conf < self.DEFAULT_OCR_CONFIDENCE_THRESHOLD or not word.strip():
                continue
                
            word = word.strip()
            
            if re.match(r'^\d+(?:\.\d+)?%?$', word):
                elements.append({
                    "type": "value",
                    "text": word,
                    "confidence": conf,
                    "bbox": box,
                    "is_percentage": '%' in word
                })
            elif len(word) > 2 and not word.isdigit():
                elements.append({
                    "type": "label",
                    "text": word,
                    "confidence": conf,
                    "bbox": box
                })
        
        return elements

    def _detect_chart_type(self, text: str) -> str:
        """Detect chart type based on text content."""
        text_lower = text.lower()
        
        chart_type_mapping = {
            'pie_chart': ['pie', 'slice', 'sector'],
            'bar_chart': ['bar', 'column', 'histogram'],
            'line_chart': ['line', 'trend', 'time series'],
            'scatter_plot': ['scatter', 'plot', 'correlation']
        }
        
        for chart_type, keywords in chart_type_mapping.items():
            if any(keyword in text_lower for keyword in keywords):
                return chart_type
        
        return 'unknown'

    def _calculate_chart_confidence(self, elements: List[Dict[str, Any]], text: str) -> float:
        """Calculate confidence score for chart data extraction."""
        if not elements:
            return 0.0
        
        avg_confidence = sum(elem['confidence'] for elem in elements) / len(elements)
        
        # Boost confidence if both labels and values are present
        has_labels = any(elem['type'] == 'label' for elem in elements)
        has_values = any(elem['type'] == 'value' for elem in elements)
        
        if has_labels and has_values:
            avg_confidence *= 1.2
        
        return min(avg_confidence / 100.0, 1.0)

    def _get_pdf_from_blob(self, container: str, blob_name: str) -> fitz.Document:
        """Get PDF document from Azure blob storage."""
        try:
            pdf_bytes = blob_storage_service.download_blob_bytes(container, blob_name)
            return fitz.open(stream=pdf_bytes, filetype="pdf")
        except Exception as e:
            logger.error(f"Error loading PDF from blob {blob_name}: {e}")
            raise FileProcessingError(f"Error loading PDF from blob {blob_name}: {e}", filepath=blob_name)

    def _extract_with_llamaindex_blob(self, container: str, blob_name: str) -> List[Tuple[str, Dict[str, Any]]]:
        """
        Extract text using LlamaIndex with blob storage and normalized page_numbers.

        Args:
            container: Name of the blob container
            blob_name: Blob name

        Returns:
            List of (content_block, metadata) tuples with normalized page_numbers
        """
        try:
            # Download PDF to temporary file for LlamaIndex processing
            pdf_bytes = blob_storage_service.download_blob_bytes(container, blob_name)
            
            with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp_file:
                tmp_file.write(pdf_bytes)
                tmp_file_path = tmp_file.name
            
            try:
                # Load PDF using LlamaIndex
                docs = self.pdf_loader.load_data(tmp_file_path)
                
                # Parse into nodes (text chunks)
                nodes = self.node_parser.get_nodes_from_documents(docs)
                
                processed_blocks = []
                
                for i, node in enumerate(nodes):
                    if not node.text.strip():
                        continue
                    
                    # Extract and normalize page number
                    page_number = self._extract_page_number_from_node(node, default=1)
                    
                    # Create normalized page_numbers list
                    page_numbers = [page_number] if isinstance(page_number, int) else page_number
                    
                    metadata = {
                        "page_number": page_number,  # Keep for backward compatibility
                        "page_numbers": page_numbers,  # New normalized field
                        "block_type": "prose",
                        "source_type": "text",
                        "node_id": getattr(node, 'node_id', f"node_{i}"),
                        "chunk_index": i,
                        "extraction_method": "llamaindex",
                        "file_type": "pdf"
                    }
                    
                    processed_blocks.append((node.text.strip(), metadata))
                
                logger.info(f"LlamaIndex extracted {len(processed_blocks)} text blocks")
                return processed_blocks
                
            finally:
                os.unlink(tmp_file_path)
            
        except Exception as e:
            logger.error(f"Error extracting with LlamaIndex: {e}")
            raise

    def _extract_page_number_from_node(self, node, default: int = 1) -> int:
        """Extract page number from LlamaIndex node with proper handling."""
        if not hasattr(node, 'metadata') or not node.metadata:
            return default
        
        page_label = node.metadata.get('page_label', default)
        
        if isinstance(page_label, str):
            try:
                return int(page_label)
            except ValueError:
                return default
        
        return page_label if isinstance(page_label, int) else default

    def _get_block_type(self, block: Dict[str, Any]) -> str:
        """Determine block type based on font analysis."""
        try:
            lines = block.get("lines", [])
            if not lines:
                return "paragraph"

            spans = lines[0].get("spans", [])
            if not spans:
                return "paragraph"

            # Analyze font properties
            span = spans[0]
            font_size = span.get("size", 10)
            font_flags = span.get("flags", 0)
            font_name = span.get("font", "").lower()

            # Check for bold and italic flags
            is_bold = bool(font_flags & (1 << 4))  # Bold flag
            is_italic = bool(font_flags & (1 << 1))  # Italic flag

            # Determine block type based on font properties
            if font_size > self.HEADING_FONT_SIZE_THRESHOLD or is_bold:
                return "heading"
            elif font_size > self.SUBHEADING_FONT_SIZE_THRESHOLD:
                return "subheading"
            elif "italic" in font_name or is_italic:
                return "emphasis"
            else:
                return "paragraph"

        except Exception as e:
            logger.debug(f"Error analyzing block type: {e}")
            return "paragraph"

    def _extract_text_near_image(self, page: fitz.Page, image_bbox: fitz.Rect, 
                                max_words: int = None) -> str:
        """Extract text appearing near an image for context."""
        if max_words is None:
            max_words = self.CONTEXTUAL_TEXT_MAX_WORDS
            
        try:
            words = page.get_text("words")
            nearby_text = []

            # Check for text above the image first
            nearby_text = self._find_text_above_image(words, image_bbox)
            
            # If no text above, check below
            if not nearby_text:
                nearby_text = self._find_text_below_image(words, image_bbox)

            return " ".join(nearby_text[:max_words])

        except Exception as e:
            logger.debug(f"Error extracting text near image: {e}")
            return ""

    def _find_text_above_image(self, words: List, image_bbox: fitz.Rect) -> List[str]:
        """Find text above the image within specified distance."""
        nearby_text = []
        
        # Sort by y1 (bottom), then x0 (left)
        for word in sorted(words, key=lambda w: (w[3], w[0])):
            word_bbox = fitz.Rect(word[:4])

            # Check if word is within distance above and horizontally aligned
            if (word_bbox.y1 < image_bbox.y0 and
                image_bbox.y0 - word_bbox.y1 < self.CONTEXTUAL_TEXT_DISTANCE and
                self._is_horizontally_aligned(word_bbox, image_bbox)):
                nearby_text.append(word[4])
        
        return nearby_text

    def _find_text_below_image(self, words: List, image_bbox: fitz.Rect) -> List[str]:
        """Find text below the image within specified distance."""
        nearby_text = []
        
        # Sort by y0 (top), then x0 (left)
        for word in sorted(words, key=lambda w: (w[1], w[0])):
            word_bbox = fitz.Rect(word[:4])

            # Check if word is within distance below and horizontally aligned
            if (word_bbox.y0 > image_bbox.y1 and
                word_bbox.y0 - image_bbox.y1 < self.CONTEXTUAL_TEXT_DISTANCE and
                self._is_horizontally_aligned(word_bbox, image_bbox)):
                nearby_text.append(word[4])
        
        return nearby_text

    def _is_horizontally_aligned(self, word_bbox: fitz.Rect, image_bbox: fitz.Rect) -> bool:
        """Check if word is horizontally aligned with image."""
        alignment_threshold = 100
        return (abs(word_bbox.x0 - image_bbox.x0) < alignment_threshold or
                abs(word_bbox.x1 - image_bbox.x1) < alignment_threshold)

    def _extract_text_blocks_pymupdf(self, page: fitz.Page, page_num: int) -> List[Tuple[str, Dict[str, Any]]]:
        """Extract text blocks from a PDF page using PyMuPDF (fallback method)."""
        text_blocks = []

        try:
            # Extract structured text with font information
            text_flags = (fitz.TEXTFLAGS_DICT & 
                         ~fitz.TEXT_PRESERVE_LIGATURES & 
                         ~fitz.TEXT_PRESERVE_WHITESPACE)
            page_dict = page.get_text("dict", flags=text_flags)

            for block in page_dict.get("blocks", []):
                if block.get("type") != 0:  # Skip non-text blocks
                    continue
                
                block_text = self._extract_block_text(block)
                
                if block_text:
                    metadata = {
                        "page_number": page_num,  # Keep for backward compatibility
                        "page_numbers": [page_num],  # New normalized field
                        "block_type": self._get_block_type(block),
                        "bbox": list(block.get("bbox", [])),
                        "source_type": "text",
                        "extraction_method": "pymupdf",
                        "file_type": "pdf"
                    }
                    text_blocks.append((block_text, metadata))

        except Exception as e:
            logger.error(f"Error extracting text from page {page_num}: {e}")

        return text_blocks

    def _extract_block_text(self, block: Dict[str, Any]) -> str:
        """Extract text from a block, preserving line breaks."""
        block_text = ""
        
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                block_text += span.get("text", "") + " "
            block_text += "\n"  # Preserve line breaks
        
        return block_text.strip()

    def _bytes_to_pil_image(self, image_bytes: bytes) -> Image.Image:
        """Convert image bytes to PIL Image."""
        nparr = np.frombuffer(image_bytes, np.uint8)
        cv_image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        cv_image = cv2.cvtColor(cv_image, cv2.COLOR_BGR2RGB)
        return Image.fromarray(cv_image)

    def _is_image_size_valid(self, image: Image.Image) -> bool:
        """Check if image meets minimum size requirements."""
        return (image.size[0] >= self.MIN_IMAGE_SIZE[0] and 
                image.size[1] >= self.MIN_IMAGE_SIZE[1])

    def _process_image_with_enhanced_ocr(self, image_bytes: bytes, page_num: int, 
                                       img_index: int, img_bbox_on_page: List = None, 
                                       contextual_text: str = "") -> List[Tuple[str, Dict[str, Any]]]:
        """Process image using enhanced OCR with comprehensive analysis."""
        try:
            # Convert bytes to PIL Image
            pil_image = self._bytes_to_pil_image(image_bytes)
            
            if not self._is_image_size_valid(pil_image):
                return []
            
            processed_blocks = []
            
            # Try table detection first
            detected_tables = self._detect_tables_with_transformer(pil_image)
            
            if detected_tables:
                processed_blocks.extend(
                    self._process_detected_tables(detected_tables, page_num, img_index, 
                                                img_bbox_on_page, contextual_text)
                )
            else:
                # Process as chart/diagram
                processed_blocks.extend(
                    self._process_as_chart_or_diagram(pil_image, page_num, img_index, 
                                                    img_bbox_on_page, contextual_text)
                )
            
            return processed_blocks
            
        except Exception as e:
            logger.error(f"Error processing image with enhanced OCR: {e}")
            return []

    def _process_detected_tables(self, detected_tables: List[Dict[str, Any]], 
                               page_num: int, img_index: int, 
                               img_bbox_on_page: List, contextual_text: str) -> List[Tuple[str, Dict[str, Any]]]:
        """Process detected tables and create metadata blocks."""
        processed_blocks = []
        
        for j, table_data in enumerate(detected_tables):
            table_text = self._format_table_data(table_data['table_data'])
            
            if table_text and table_text.strip():
                metadata = {
                    "page_number": page_num,  # Keep for backward compatibility
                    "page_numbers": [page_num],  # New normalized field
                    "block_type": "image_text",
                    "bbox": img_bbox_on_page,
                    "source_type": "table",
                    "image_context": contextual_text,
                    "original_image_xref": f"img_{img_index}",
                    "image_size": table_data.get('image_crop', {}).size if hasattr(table_data.get('image_crop', {}), 'size') else None,
                    "file_type": "pdf",
                    "table_confidence": table_data['confidence'],
                    "extraction_method": "table_transformer"
                }
                processed_blocks.append((table_text.strip(), metadata))
        
        return processed_blocks

    def _process_as_chart_or_diagram(self, pil_image: Image.Image, page_num: int, 
                                   img_index: int, img_bbox_on_page: List, 
                                   contextual_text: str) -> List[Tuple[str, Dict[str, Any]]]:
        """Process image as chart or diagram."""
        processed_blocks = []
        
        # Process as chart/diagram
        chart_data = self._extract_chart_data_advanced(pil_image)
        
        if chart_data['raw_text'] and chart_data['raw_text'].strip():
            source_type = self._determine_source_type(chart_data)
            
            metadata = {
                "page_number": page_num,  # Keep for backward compatibility
                "page_numbers": [page_num],  # New normalized field
                "block_type": "image_text",
                "bbox": img_bbox_on_page,
                "source_type": source_type,
                "image_context": contextual_text,
                "original_image_xref": f"img_{img_index}",
                "image_size": pil_image.size,
                "file_type": "pdf",
                "chart_type": chart_data.get('chart_type'),
                "confidence": chart_data.get('confidence_score', 0.0),
                "extraction_method": "enhanced_ocr"
            }
            processed_blocks.append((chart_data['raw_text'].strip(), metadata))
        
        return processed_blocks

    def _determine_source_type(self, chart_data: Dict[str, Any]) -> str:
        """Determine the source type based on chart data analysis."""
        if chart_data['chart_type'] != 'unknown':
            return "chart"
        
        raw_text_lower = chart_data['raw_text'].lower()
        
        if any(pattern in raw_text_lower for pattern in self.CHART_PATTERNS):
            return "chart"
        elif any(pattern in raw_text_lower for pattern in self.TABLE_PATTERNS):
            return "table"
        else:
            return "image"

    def _format_table_data(self, table_data: Dict[str, Any]) -> str:
        """Format extracted table data into readable text."""
        if table_data.get('parsed_rows'):
            return self._format_as_markdown_table(table_data['parsed_rows'])
        else:
            return table_data.get('raw_text', '')

    def _format_as_markdown_table(self, rows: List[List[str]]) -> str:
        """Format parsed rows as markdown table."""
        if not rows:
            return ""
        
        headers = rows[0]
        if not headers:
            return ""
            
        # Create markdown table
        markdown = "| " + " | ".join(headers) + " |\n"
        markdown += "| " + " | ".join(["---"] * len(headers)) + " |\n"
        
        for row in rows[1:]:
            # Pad row to match header length
            padded_row = row + [''] * (len(headers) - len(row))
            markdown += "| " + " | ".join(padded_row[:len(headers)]) + " |\n"
        
        return markdown

    def _extract_images(self, page: fitz.Page, page_num: int, 
                       pdf_document: fitz.Document) -> List[Tuple[str, Dict[str, Any]]]:
        """Extract images from a PDF page and process them with enhanced OCR."""
        image_blocks = []

        try:
            # Get images from page
            image_list = page.get_images(full=True)

            for img_index, img_info in enumerate(image_list):
                xref = img_info[0]

                try:
                    processed_blocks = self._process_single_image(
                        page, pdf_document, xref, img_index, page_num
                    )
                    image_blocks.extend(processed_blocks)

                except Exception as e:
                    logger.error(f"Error processing image xref {xref} on page {page_num}: {e}")

        except Exception as e:
            logger.error(f"Error extracting images from page {page_num}: {e}")

        return image_blocks

    def _process_single_image(self, page: fitz.Page, pdf_document: fitz.Document, 
                            xref: int, img_index: int, page_num: int) -> List[Tuple[str, Dict[str, Any]]]:
        """Process a single image from the PDF page."""
        # Extract image data
        base_image = pdf_document.extract_image(xref)
        if not base_image:
            return []

        image_bytes = base_image["image"]

        # Get image bounding box
        img_rects = page.get_image_rects(xref, transform=True)
        img_bbox_on_page = list(img_rects[0]) if img_rects else []

        # Extract contextual text
        contextual_text = ""
        if img_bbox_on_page:
            contextual_text = self._extract_text_near_image(page, fitz.Rect(img_bbox_on_page))

        # Process image with appropriate method
        if self.image_processor:
            return self._process_with_image_processor(
                image_bytes, page_num, xref, img_bbox_on_page, contextual_text
            )
        else:
            return self._process_image_with_enhanced_ocr(
                image_bytes, page_num, img_index, img_bbox_on_page, contextual_text
            )

    def _process_with_image_processor(self, image_bytes: bytes, page_num: int, 
                                    xref: int, img_bbox_on_page: List, 
                                    contextual_text: str) -> List[Tuple[str, Dict[str, Any]]]:
        """Process image using the existing image processor (backward compatibility)."""
        result = self.image_processor.process_bytes(image_bytes)
        image_text = result['combined_text']

        if image_text and image_text.strip():
            metadata = {
                "page_number": page_num,  # Keep for backward compatibility
                "page_numbers": [page_num],  # New normalized field
                "block_type": "image_text",
                "bbox": img_bbox_on_page,
                "source_type": "image",
                "image_context": contextual_text,
                "original_image_xref": xref,
                "image_size": result.get('image_size'),
                "file_type": "pdf",
                "extraction_method": "image_processor"
            }
            return [(image_text.strip(), metadata)]
        
        return []

    def _normalize_blocks_input(self, blocks_input: Any) -> List[Dict[str, Any]]:
        """Normalize different types of blocks input to standard format."""
        normalized_blocks = []

        if not blocks_input:
            return normalized_blocks

        # Handle list input
        if isinstance(blocks_input, list):
            for item in blocks_input:
                if isinstance(item, dict) and 'text' in item:
                    normalized_blocks.append(item)
                elif isinstance(item, str):
                    normalized_blocks.append({"text": item, "type": "text"})
                elif hasattr(item, 'text'):  # Object with text attribute
                    normalized_blocks.append({
                        "text": str(item.text),
                        "type": getattr(item, 'type', 'text')
                    })

        # Handle single object input
        elif hasattr(blocks_input, '__iter__') and not isinstance(blocks_input, (str, dict)):
            try:
                for item in blocks_input:
                    if isinstance(item, dict) and 'text' in item:
                        normalized_blocks.append(item)
                    elif hasattr(item, 'text'):
                        normalized_blocks.append({
                            "text": str(item.text),
                            "type": getattr(item, 'type', 'text')
                        })
            except Exception as e:
                logger.warning(f"Error normalizing blocks input: {e}")

        # Handle ProcessingResult or similar objects
        elif hasattr(blocks_input, 'chunks_preview'):
            try:
                # Extract from chunks_preview if available
                for chunk_info in blocks_input.chunks_preview[:2]:
                    if len(chunk_info) >= 1:
                        normalized_blocks.append({
                            "text": str(chunk_info[0]),
                            "type": "prose"
                        })
            except Exception as e:
                logger.warning(f"Error extracting from ProcessingResult: {e}")

        return normalized_blocks

    def create_llamaindex_nodes(self, blocks: List[Dict[str, Any]]) -> List[Any]:
        """Create LlamaIndex nodes from parsed blocks."""
        if not self.use_llamaindex:
            logger.warning("LlamaIndex not available or disabled")
            return []

        try:
            # Convert blocks to LlamaIndex Documents
            documents = [LlamaDocument(text=block["text"]) for block in blocks if block.get("text")]

            # Parse documents into nodes
            if self.node_parser:
                nodes = self.node_parser.get_nodes_from_documents(documents)
                return nodes
            else:
                logger.warning("Node parser not available")
                return []
        except Exception as e:
            logger.error(f"Error creating LlamaIndex nodes: {e}")
            return []

    def generate_metadata_with_llamaindex(self, container: str, blob_name: str, blocks: Any,
                                        nodes: List[Any] = None) -> Dict[str, Any]:
        """Generate comprehensive metadata using LlamaIndex integration."""
        document_id = str(uuid.uuid4())
        now_iso = datetime.now().isoformat()

        # Normalize blocks input to standard format
        actual_blocks = self._normalize_blocks_input(blocks)

        # Create preview from nodes or blocks
        preview_entries = []

        # Generate preview from nodes first (preferred)
        if nodes and len(nodes) > 0:
            for i, node in enumerate(nodes[:2]):
                try:
                    if hasattr(node, 'text'):
                        snippet = str(node.text).replace('\n', ' ')[:100].strip()
                        node_id = getattr(node, 'node_id', str(uuid.uuid4()))
                        preview_entries.append({
                            "snippet": snippet,
                            "node_id": node_id,
                            "type": "prose"
                        })
                except Exception as e:
                    logger.warning(f"Error processing node {i}: {e}")

        # Fallback to blocks if no valid nodes
        if not preview_entries and actual_blocks:
            for i, block in enumerate(actual_blocks[:2]):
                try:
                    text_content = block.get("text", "")
                    if text_content:
                        snippet = str(text_content).replace('\n', ' ')[:100].strip()
                        preview_entries.append({
                            "snippet": snippet,
                            "node_id": str(uuid.uuid4()),
                            "type": block.get("type", "prose")
                        })
                except Exception as e:
                    logger.warning(f"Error processing block {i}: {e}")

        # Final fallback - create a basic preview
        if not preview_entries:
            preview_entries = [{
                "snippet": "Document content available - preview generation failed",
                "node_id": str(uuid.uuid4()),
                "type": "prose"
            }]

        preview_str = json.dumps(preview_entries, ensure_ascii=False, indent=2)

        # Generate full text
        full_text = ""
        if nodes:
            try:
                full_text = "\n\n".join(str(node.text) for node in nodes if hasattr(node, 'text'))
            except Exception as e:
                logger.warning(f"Error generating full text from nodes: {e}")

        if not full_text and actual_blocks:
            try:
                full_text = "\n\n".join(block["text"] for block in actual_blocks if block.get("text"))
            except Exception as e:
                logger.warning(f"Error generating full text from blocks: {e}")
                full_text = "Content available - text generation failed"

        # File information
        file_info = blob_storage_service.get_blob_info(container, blob_name)
        file_size = file_info["size_human"]
        mime_type = mimetypes.guess_type(blob_name)[0] or "application/pdf"

        metadata = {
            "document_id": document_id,
            "dateAddedToGiani": now_iso,
            "originalFilename": file_info["file_name"],
            "storagePath": file_info["blob_name"],
            "fileSize": file_size,
            "fileMimeType": mime_type,
            "userID": "user_001",
            "projectID": "project_001",
            "categoryFolder": "Client-Provided Material",
            "finalCategory": "4. Document Material",
            "finalPurpose": f"\"{blob_name}\" likely contains structured document content with text, images, charts, and tables for business analysis.",
            "priority": "Medium",
            "geminiPrompt": (
                "You are an AI assistant helping classify documents for a management consulting project.\n\n"
                f"This is the document source \"<user_input>preview</user_input>\".\n\n"
                f"Based on the filename \"<user_input>{blob_name}</user_input>\" and this text preview:\n"
                f"\"<user_input>{preview_str}</user_input>\"\n\nPlease classify this document..."
            ),
            "textPreview": preview_str,
            "storedFilename": f"data/uploaded_documents/Client-Provided Material/{blob_name}",
            "finalizedAt": now_iso,
            "savedAt": now_iso,
            "fullText": full_text,
            "parsedBlocksCount": len(actual_blocks),
            "llamaIndexNodesCount": len(nodes) if nodes else 0,
            "enhancedParsing": self.use_llamaindex
        }

        return metadata

    def process_file(self, container: str, blob_name: str, use_enhanced_parsing: bool = None) -> List[Tuple[str, Dict[str, Any]]]:
        """
        Process a PDF file and extract structured content using blob storage.

        Args:
            container: Name of the blob container
            blob_name: Blob name
            use_enhanced_parsing: Override for using enhanced parsing

        Returns:
            List of (text_block, metadata) tuples

        Raises:
            ParsingError: If file format is not supported
            FileProcessingError: If processing fails
        """
        # Determine parsing method
        enhanced_parsing = use_enhanced_parsing if use_enhanced_parsing is not None else self.use_llamaindex

        try:
            if enhanced_parsing:
                return self._process_file_enhanced(container, blob_name)
            else:
                return self._process_file_legacy(container, blob_name)
        except Exception as e:
            logger.error(f"Error processing PDF file {blob_name}: {e}")
            raise FileProcessingError(f"Error processing PDF file {blob_name}: {e}", filepath=str(blob_name))

    def _process_file_enhanced(self, container: str, blob_name: str) -> List[Tuple[str, Dict[str, Any]]]:
        """Process file using enhanced LlamaIndex logic with blob storage."""
        processed_blocks = []

        try:
            # Extract text content using LlamaIndex
            text_blocks = self._extract_with_llamaindex_blob(container, blob_name)
            processed_blocks.extend(text_blocks)
            
            # Extract image content
            image_blocks = self._extract_image_content_blob(container, blob_name)
            processed_blocks.extend(image_blocks)
            
            logger.info(f"Successfully processed {blob_name} (enhanced): {len(processed_blocks)} blocks extracted")
            return processed_blocks

        except Exception as e:
            logger.error(f"Enhanced processing failed for {blob_name}: {e}")
            # Fallback to legacy processing
            return self._process_file_legacy(container, blob_name)

    def _process_file_legacy(self, container: str, blob_name: str) -> List[Tuple[str, Dict[str, Any]]]:
        """Process file using legacy PyMuPDF logic with blob storage."""
        processed_blocks = []

        # Load PDF from blob storage
        pdf_document = self._get_pdf_from_blob(container, blob_name)
        
        try:
            # Process each page
            for page_num in range(1, len(pdf_document) + 1):
                page = pdf_document.load_page(page_num - 1)  # fitz is 0-indexed
                
                # Extract text blocks
                text_blocks = self._extract_text_blocks_pymupdf(page, page_num)
                processed_blocks.extend(text_blocks)
                
                # Extract image blocks
                image_blocks = self._extract_images(page, page_num, pdf_document)
                processed_blocks.extend(image_blocks)
        finally:
            pdf_document.close()

        logger.info(f"Successfully processed {blob_name} (legacy): {len(processed_blocks)} blocks extracted")
        return processed_blocks

    def _extract_image_content_blob(self, container: str, blob_name: str) -> List[Tuple[str, Dict[str, Any]]]:
        """Extract image content with enhanced processing from blob storage."""
        processed_blocks = []
        
        pdf_document = self._get_pdf_from_blob(container, blob_name)
        try:
            for page_num in range(1, len(pdf_document) + 1):
                page = pdf_document.load_page(page_num - 1)
                image_blocks = self._extract_images(page, page_num, pdf_document)
                processed_blocks.extend(image_blocks)
        finally:
            pdf_document.close()
        
        return processed_blocks

    def save_metadata_and_blocks(self, container: str, blob_name: str, output_dir: str,
                                blocks_input: Any = None) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        Process file and save metadata and blocks (similar to DOCX functionality).

        Args:
            container: Name of the blob container
            blob_name: Blob name
            output_dir: Output directory for saved files
            blocks_input: Optional pre-parsed blocks (can handle various formats)

        Returns:
            Tuple of (blocks, metadata)
        """
        # Process file if blocks not provided
        if blocks_input is None:
            processed_blocks = self.process_file(container, blob_name)
            # Convert to block format
            blocks = []
            for text, metadata in processed_blocks:
                blocks.append({
                    "text": text,
                    "type": metadata.get("block_type", "text"),
                    **metadata
                })
        else:
            # Use provided blocks and normalize them
            blocks = self._normalize_blocks_input(blocks_input)

        # Create LlamaIndex nodes if available
        nodes = self.create_llamaindex_nodes(blocks) if self.use_llamaindex else []

        # Generate comprehensive metadata
        metadata = self.generate_metadata_with_llamaindex(container, blob_name, blocks, nodes)

        return blocks, metadata

    def process_pdf(self, container: str, blob_name: str) -> List[Tuple[str, Dict[str, Any]]]:
        """
        Legacy method for backward compatibility with blob storage.

        Args:
            container: Name of the blob container
            blob_name: Blob name

        Returns:
            List of (text_block, metadata) tuples
        """
        return self.process_file(container, blob_name)

    def get_analysis_summary(self, processed_blocks: List[Tuple[str, Dict[str, Any]]]) -> Dict[str, Any]:
        """Get a comprehensive summary of the analysis results."""
        total_blocks = len(processed_blocks)
        pages = set(metadata.get('page_number') for _, metadata in processed_blocks)
        
        # Count different types of content
        text_blocks = sum(1 for _, metadata in processed_blocks if metadata.get('source_type') == 'text')
        image_blocks = sum(1 for _, metadata in processed_blocks if metadata.get('source_type') == 'image')
        table_blocks = sum(1 for _, metadata in processed_blocks if metadata.get('source_type') == 'table')
        chart_blocks = sum(1 for _, metadata in processed_blocks if metadata.get('source_type') == 'chart')
        
        # Enhanced analysis statistics
        tables_with_transformer = sum(1 for _, metadata in processed_blocks 
                                    if metadata.get('extraction_method') == 'table_transformer')
        
        # Page numbering validation
        page_numbers_valid = all(
            isinstance(metadata.get('page_numbers'), list) and 
            len(metadata.get('page_numbers', [])) > 0
            for _, metadata in processed_blocks
        )
        
        return {
            'total_blocks': total_blocks,
            'total_pages': len(pages),
            'content_breakdown': {
                'text_blocks': text_blocks,
                'image_blocks': image_blocks,
                'table_blocks': table_blocks,
                'chart_blocks': chart_blocks
            },
            'enhanced_features': {
                'table_transformer_enabled': self.table_transformer_available,
                'tables_with_transformer': tables_with_transformer,
                'enhanced_ocr_enabled': True,
                'llamaindex_enabled': self.use_llamaindex
            },
            'rag_pipeline_compatibility': {
                'blob_storage_integrated': True,
                'page_numbers_valid': page_numbers_valid,
                'metadata_complete': True
            }
        }