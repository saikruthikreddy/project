# Docx.py
import os
import mammoth
import zipfile
import tempfile
from io import BytesIO
from giani_pkb.preprocessing.Images import Image as Image_Processor

class Docx:
    def __init__(self):
        self.image_processor = Image_Processor()
    
    def _extract_images_from_docx(self, file_path):
        """Extract images from DOCX file and process them"""
        extracted_images_text = []
        
        try:
            with zipfile.ZipFile(file_path, 'r') as zip_file:
                # Look for media files in the DOCX structure
                media_files = [f for f in zip_file.namelist() if f.startswith('word/media/')]
                
                for media_file in media_files:
                    try:
                        # Extract image data
                        image_data = zip_file.read(media_file)
                        
                        # Process image using your Image processor
                        image_text = self.image_processor.process_image_bytes(image_data)
                        if image_text and image_text.strip():
                            image_filename = os.path.basename(media_file)
                            extracted_images_text.append(f"Image '{image_filename}': {image_text}")
                    except Exception as e:
                        print(f"Error processing image {media_file}: {e}")
                        continue
                        
        except Exception as e:
            print(f"Error extracting images from DOCX: {e}")
        
        return extracted_images_text
    
    def _extract_images_with_mammoth(self, file_path):
        """Alternative method using mammoth's image extraction"""
        extracted_images_text = []
        
        try:
            def convert_image(image):
                """Custom image converter for mammoth"""
                try:
                    # Get image data
                    image_bytes = image.open().read()
                    
                    # Process with your Image processor
                    image_text = self.image_processor.process_image_bytes(image_bytes)
                    
                    if image_text and image_text.strip():
                        # Store the processed text
                        image_info = {
                            'alt_text': getattr(image, 'alt_text', ''),
                            'content_type': getattr(image, 'content_type', ''),
                            'processed_text': image_text
                        }
                        extracted_images_text.append(image_info)
                    
                    # Return markdown representation
                    alt_text = getattr(image, 'alt_text', 'Image')
                    return f"![{alt_text}](processed_image)\n\n**Image Content:** {image_text}\n\n"
                    
                except Exception as e:
                    print(f"Error processing image with mammoth: {e}")
                    return f"![Image processing failed]({str(e)})"
            
            # Configure mammoth to use custom image converter
            with open(file_path, "rb") as docx_file:
                result = mammoth.convert_to_markdown(
                    docx_file,
                    convert_image=mammoth.images.img_element(convert_image)
                )
                return result, extracted_images_text
                
        except Exception as e:
            print(f"Error with mammoth image extraction: {e}")
            return None, []
    
    def process_docx(self, file_path):
        try:
            # First, extract images using ZIP method
            zip_extracted_images = self._extract_images_from_docx(file_path)
            
            # Then, try mammoth with custom image converter
            mammoth_result, mammoth_images = self._extract_images_with_mammoth(file_path)
            
            if mammoth_result:
                # Use mammoth result if available (it includes inline image processing)
                md_content = f"# Document: {os.path.basename(file_path)}\n\n"
                md_content += mammoth_result.value
                
                # Add conversion messages if any
                if mammoth_result.messages:
                    md_content += "\n\n## Conversion Notes\n\n"
                    for message in mammoth_result.messages:
                        md_content += f"- {message.message}\n"
                
                # Add ZIP-extracted images that weren't processed by mammoth
                if zip_extracted_images:
                    md_content += "\n\n## Additional Images Found\n\n"
                    for img_text in zip_extracted_images:
                        md_content += f"- {img_text}\n"
                
            else:
                # Fallback to basic mammoth conversion
                with open(file_path, "rb") as docx_file:
                    result = mammoth.convert_to_markdown(docx_file)
                    md_content = f"# Document: {os.path.basename(file_path)}\n\n"
                    md_content += result.value
                    
                    if result.messages:
                        md_content += "\n\n## Conversion Notes\n\n"
                        for message in result.messages:
                            md_content += f"- {message.message}\n"
                    
                    # Add extracted images
                    if zip_extracted_images:
                        md_content += "\n\n## Images Found in Document\n\n"
                        for img_text in zip_extracted_images:
                            md_content += f"- {img_text}\n"
            
            # Add summary of image processing
            total_images = len(zip_extracted_images) + len(mammoth_images)
            if total_images > 0:
                md_content += f"\n\n## Image Processing Summary\n\n"
                md_content += f"Total images processed: {total_images}\n"
            
            return md_content
            
        except Exception as e:
            error_msg = f"# Error Processing {os.path.basename(file_path)}\n\nAn error occurred: {str(e)}"
            
            # Try to extract images even if main conversion fails
            try:
                zip_extracted_images = self._extract_images_from_docx(file_path)
                if zip_extracted_images:
                    error_msg += "\n\n## Images Found Despite Error\n\n"
                    for img_text in zip_extracted_images:
                        error_msg += f"- {img_text}\n"
            except:
                pass
            
            return error_msg