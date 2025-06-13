# Images.py
import pytesseract
from PIL import Image as PILImage
from io import BytesIO
import torch
from transformers import BlipProcessor, BlipForConditionalGeneration



class Image:
    def __init__(self, tesseract_path=None):
        if tesseract_path:
            pytesseract.pytesseract.tesseract_cmd = tesseract_path
        
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.blip_processor = BlipProcessor.from_pretrained("Salesforce/blip-image-captioning-base")
        self.blip_model = BlipForConditionalGeneration.from_pretrained("Salesforce/blip-image-captioning-base").to(self.device)


    def process_image(self, path, lang='eng', caption=True):
        try:
            image = PILImage.open(path)
            if image.mode != 'RGB':
                image = image.convert('RGB')
            
            ocr_text = pytesseract.image_to_string(image, lang=lang).strip()
            
            result = {
                'ocr_text': ocr_text
            }
            
            if caption:
                caption_text = self._generate_caption(image)
                result['caption'] = caption_text
                result['combined_text'] = f"OCR Text: {ocr_text}\nImage Caption: {caption_text}"
            
            return result['combined_text']
        except Exception as e:
            print(f"Error processing image: {e}")
            return ""

    def process_image_bytes(self, image_bytes, lang='eng', config='', caption=True):
        try:
            image = PILImage.open(BytesIO(image_bytes))
            # Convert image to RGB if it's not
            if image.mode != 'RGB':
                image = image.convert('RGB')
            
            # Extract text from the image using OCR
            ocr_text = pytesseract.image_to_string(image, lang=lang, config=config).strip()
            
            result = {
                'ocr_text': ocr_text
            }
            
            # Generate image caption using BLIP if requested
            if caption:
                caption_text = self._generate_caption(image)
                result['caption'] = caption_text
                result['combined_text'] = f"OCR Text: {ocr_text}\nImage Caption: {caption_text}"
            
            return result['combined_text']
        except Exception as e:
            print(f"Error processing image: {e}")
            return {"ocr_text": "", "caption": "", "combined_text": ""}


    def _generate_caption(self, image):
        try:
            inputs = self.blip_processor(image, return_tensors="pt").to(self.device)
            out = self.blip_model.generate(**inputs)
            caption = self.blip_processor.decode(out[0], skip_special_tokens=True)
            return caption
        except Exception as e:
            print(f"Error generating caption: {e}")
            return "Caption generation failed"
