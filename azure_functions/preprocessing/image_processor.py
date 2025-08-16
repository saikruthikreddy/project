"""
Image processor for OCR text extraction and AI-powered image captioning.
"""
import pytesseract
from PIL import Image as PILImage
from io import BytesIO
from typing import Dict, Any, Optional, Union
import logging
from pathlib import Path

from utils.exceptions import ProcessingError, DependencyError

logger = logging.getLogger(__name__)

# Optional dependencies
try:
    # import torch
    # from transformers import BlipProcessor, BlipForConditionalGeneration
    TRANSFORMERS_AVAILABLE = False
except ImportError:
    TRANSFORMERS_AVAILABLE = False
    BlipProcessor = None
    BlipForConditionalGeneration = None
    torch = None

class ImageProcessor:
    """
    Processor for images that extracts text via OCR and generates captions using AI.

    Features:
    - OCR text extraction using Tesseract
    - AI-powered image captioning using BLIP model
    - Support for multiple languages
    - GPU acceleration when available
    - Graceful fallback when dependencies are missing
    """

    def __init__(self, tesseract_path: Optional[str] = None, enable_captioning: bool = True):
        """
        Initialize the image processor.

        Args:
            tesseract_path: Optional path to Tesseract executable
            enable_captioning: Whether to enable AI captioning (requires transformers)
        """
        self.enable_captioning = enable_captioning
        self.supported_formats = {'.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.gif'}

        # Configure Tesseract
        if tesseract_path:
            pytesseract.pytesseract.tesseract_cmd = tesseract_path

        # Initialize AI models
        self.blip_processor = None
        self.blip_model = None
        self.device = "cpu"

        if enable_captioning and TRANSFORMERS_AVAILABLE:
            self._initialize_ai_models()
        elif enable_captioning and not TRANSFORMERS_AVAILABLE:
            logger.warning("Captioning requested but transformers not available. Install with: pip install transformers torch")

    def _initialize_ai_models(self):
        """Initialize BLIP models for image captioning."""
        try:
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
            logger.info(f"Initializing BLIP models on device: {self.device}")

            self.blip_processor = BlipProcessor.from_pretrained("Salesforce/blip-image-captioning-base")
            self.blip_model = BlipForConditionalGeneration.from_pretrained(
                "Salesforce/blip-image-captioning-base"
            ).to(self.device)

            logger.info("BLIP models initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize BLIP models: {e}")
            self.blip_processor = None
            self.blip_model = None
            raise DependencyError(f"Failed to initialize AI models: {e}")

    def _load_image(self, image_source: Union[str, Path, bytes]) -> PILImage.Image:
        """
        Load image from various sources.

        Args:
            image_source: File path, Path object, or image bytes

        Returns:
            PIL Image object

        Raises:
            ProcessingError: If image cannot be loaded
        """
        try:
            if isinstance(image_source, (str, Path)):
                image = PILImage.open(str(image_source))
            elif isinstance(image_source, bytes):
                image = PILImage.open(BytesIO(image_source))
            else:
                raise ProcessingError(f"Unsupported image source type: {type(image_source)}")

            # Convert to RGB if necessary
            if image.mode != 'RGB':
                image = image.convert('RGB')

            return image

        except Exception as e:
            raise ProcessingError(f"Failed to load image: {e}")

    def _extract_ocr_text(self, image: PILImage.Image, lang: str = 'eng', config: str = '') -> str:
        """
        Extract text from image using OCR.

        Args:
            image: PIL Image object
            lang: Language code for OCR
            config: Tesseract configuration string

        Returns:
            Extracted text string
        """
        try:
            ocr_text = pytesseract.image_to_string(image, lang=lang, config=config).strip()
            return ocr_text

        except Exception as e:
            logger.error(f"OCR extraction failed: {e}")
            return ""

    def _generate_caption(self, image: PILImage.Image) -> str:
        """
        Generate AI caption for image.

        Args:
            image: PIL Image object

        Returns:
            Generated caption string
        """
        if not self.blip_processor or not self.blip_model:
            return "Captioning not available (models not initialized)"

        try:
            inputs = self.blip_processor(image, return_tensors="pt").to(self.device)
            outputs = self.blip_model.generate(**inputs)
            caption = self.blip_processor.decode(outputs[0], skip_special_tokens=True)
            return caption

        except Exception as e:
            logger.error(f"Caption generation failed: {e}")
            return "Caption generation failed"

    def _format_result(self, ocr_text: str, caption: str, include_ocr: bool = True, include_caption: bool = True) -> str:
        """
        Format the processing result as a combined string.

        Args:
            ocr_text: Extracted OCR text
            caption: Generated caption
            include_ocr: Whether to include OCR text in output
            include_caption: Whether to include caption in output

        Returns:
            Formatted result string
        """
        parts = []

        if include_ocr and ocr_text:
            parts.append(f"OCR Text: {ocr_text}")
        elif include_ocr:
            parts.append("OCR Text: (no text detected)")

        if include_caption and caption:
            parts.append(f"Image Caption: {caption}")
        elif include_caption:
            parts.append("Image Caption: (no caption generated)")

        return "\n".join(parts) if parts else "No content extracted"

    def process_file(self, file_path: Union[str, Path], lang: str = 'eng', config: str = '',
                    include_ocr: bool = True, include_caption: bool = True) -> Dict[str, Any]:
        """
        Process an image file and extract text and caption.

        Args:
            file_path: Path to image file
            lang: Language code for OCR
            config: Tesseract configuration string
            include_ocr: Whether to include OCR text in output
            include_caption: Whether to include caption in output

        Returns:
            Dictionary with processing results

        Raises:
            ProcessingError: If processing fails
        """
        file_path = Path(file_path)

        if not file_path.exists():
            raise ProcessingError(f"Image file not found: {file_path}", filepath=str(file_path))

        if file_path.suffix.lower() not in self.supported_formats:
            raise ProcessingError(
                f"Unsupported image format: {file_path.suffix}. "
                f"Supported: {', '.join(self.supported_formats)}",
                filename=str(file_path)
            )

        try:
            # Load and process image
            image = self._load_image(file_path)

            # Extract OCR text
            ocr_text = ""
            if include_ocr:
                ocr_text = self._extract_ocr_text(image, lang, config)

            # Generate caption
            caption = ""
            if include_caption and self.enable_captioning:
                caption = self._generate_caption(image)

            # Format result
            combined_text = self._format_result(ocr_text, caption, include_ocr, include_caption)

            result = {
                'ocr_text': ocr_text,
                'caption': caption,
                'combined_text': combined_text,
                'file_path': str(file_path),
                'file_size': file_path.stat().st_size,
                'image_format': image.format,
                'image_size': image.size,
                'processing_successful': True
            }

            logger.info(f"Successfully processed image {file_path}: {len(ocr_text)} chars OCR, {len(caption)} chars caption")
            return result

        except Exception as e:
            logger.error(f"Error processing image {file_path}: {e}")
            raise ProcessingError(f"Error processing image {file_path}: {e}", filepath=str(file_path))

    def process_bytes(self, image_bytes: bytes, lang: str = 'eng', config: str = '',
                     include_ocr: bool = True, include_caption: bool = True) -> Dict[str, Any]:
        """
        Process image bytes and extract text and caption.

        Args:
            image_bytes: Raw image bytes
            lang: Language code for OCR
            config: Tesseract configuration string
            include_ocr: Whether to include OCR text in output
            include_caption: Whether to include caption in output

        Returns:
            Dictionary with processing results

        Raises:
            ProcessingError: If processing fails
        """
        try:
            # Load and process image
            image = self._load_image(image_bytes)

            # Extract OCR text
            ocr_text = ""
            if include_ocr:
                ocr_text = self._extract_ocr_text(image, lang, config)

            # Generate caption
            caption = ""
            if include_caption and self.enable_captioning:
                caption = self._generate_caption(image)

            # Format result
            combined_text = self._format_result(ocr_text, caption, include_ocr, include_caption)

            result = {
                'ocr_text': ocr_text,
                'caption': caption,
                'combined_text': combined_text,
                'file_size': len(image_bytes),
                'image_format': image.format,
                'image_size': image.size,
                'processing_successful': True
            }

            logger.info(f"Successfully processed image bytes: {len(ocr_text)} chars OCR, {len(caption)} chars caption")
            return result

        except Exception as e:
            logger.error(f"Error processing image bytes: {e}")
            raise ProcessingError(f"Error processing image bytes: {e}")

    def process_image(self, path: Union[str, Path], lang: str = 'eng', caption: bool = True) -> str:
        """
        Legacy method for backward compatibility.

        Args:
            path: Path to image file
            lang: Language code for OCR
            caption: Whether to generate caption

        Returns:
            Combined text string
        """
        result = self.process_file(path, lang=lang, include_caption=caption)
        return result['combined_text']

    def process_image_bytes(self, image_bytes: bytes, lang: str = 'eng', config: str = '', caption: bool = True) -> str:
        """
        Legacy method for backward compatibility.

        Args:
            image_bytes: Raw image bytes
            lang: Language code for OCR
            config: Tesseract configuration string
            caption: Whether to generate caption

        Returns:
            Combined text string
        """
        result = self.process_bytes(image_bytes, lang=lang, config=config, include_caption=caption)
        return result['combined_text']