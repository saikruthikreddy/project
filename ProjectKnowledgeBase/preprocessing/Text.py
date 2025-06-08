# Text.py
from PyPDF2 import PdfReader
import pdfplumber
from PIL import Image
from io import BytesIO
import fitz
from preprocessing.Images import Image as Image_Processor


class PDF:
    def __init__(self):
        self.image_processor = Image_Processor()
    
    def extract_text_near_image(self, pdf_page, image_rect, max_length=100):
        text_blocks = pdf_page.get_text("blocks")
        relevant_text = ""
        for block in text_blocks:
            block_rect = fitz.Rect(block[:4])
            if block_rect.y1 >= image_rect.y0:
                relevant_text += block[4] + " "
                if len(relevant_text) >= max_length:
                    relevant_text = relevant_text[:max_length]
                    break
        return relevant_text.strip()
        
    def process_pdf(self, path):
        text = ""
        try:
            pdf_document = fitz.open(path)
            
            for page_num in range(len(pdf_document)):
                page = pdf_document.load_page(page_num)
                page_content = page.get_text()
                text += page_content
                
                # Extract images from the page
                image_list = page.get_images(full=True)
                for img_index, img in enumerate(image_list):
                    xref = img[0]
                    base_image = pdf_document.extract_image(xref)
                    image_bytes = base_image["image"]
                    image_rect = fitz.Rect(img[1:5])
                    
                    # Extract relevant text near the image
                    descriptive_text = self.extract_text_near_image(page, image_rect)
                    
                    # Process the image - note the way we handle the result
                    image_result = self.image_processor.process_image_bytes(image_bytes)
                    
                    # The result is already a string based on the Image class implementation
                    # Append it to our text output
                    text += f"\n\n--- Image on {self.ordinal(page_num + 1)} page ---\n"
                    text += f"Context: {descriptive_text}\n"
                    text += f"{image_result}\n\n"
                    
            return text
        except Exception as e:
            return f"Error processing {path}: {str(e)}"
            
    def ordinal(self, n):
        return "%d%s" % (n, "tsnrhtdd"[(n//10%10!=1)*(n%10<4)*n%10::4])