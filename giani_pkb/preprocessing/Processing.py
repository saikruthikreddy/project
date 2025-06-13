import os
import logging
from giani_pkb.utils.config import GEMINI_API_KEY
from giani_pkb.preprocessing.Text import PDF
from giani_pkb.preprocessing.Images import Image
from giani_pkb.preprocessing.CSV import CSVProcessor
from giani_pkb.preprocessing.PPTX import PPTX
from giani_pkb.preprocessing.Docx import Docx

logger = logging.getLogger(__name__)

class MainProcessing:
    def __init__(self, api_key=None):
        self.PDF = PDF()
        self.Image = Image()
        used_api_key = api_key if api_key else GEMINI_API_KEY
        if not used_api_key:
            # This case should ideally not happen if GEMINI_API_KEY is set in config.
            # Or if the calling code (FileUpload, OldSummary) always passes it.
            logger.warning("MainProcessing initialized for CSVProcessor without a valid API key.")
            # CSVProcessor might fail if used_api_key is None/empty and it strictly needs one for genai.configure
        self.CSV = CSVProcessor(api_key=used_api_key)
        self.PPTX=PPTX()
        self.Docx=Docx()

    def read_files(self, target_folder):
        paths = []
        for dirpath, dirnames, filenames in os.walk(target_folder):
            for filename in filenames:
                file_path  = os.path.join(dirpath, filename)
                paths.append(file_path)
        return paths

    def process_files(self, path):
        if path.endswith('.jpg') or path.endswith('.jpeg') or path.endswith('.png') or path.endswith('.bmp') or path.endswith('.tiff') or path.endswith('.tif'):
            # Process the image
            text = self.Image.process_image(path)
        elif path.endswith('.pdf'):
            # Process the pdf
            text = self.PDF.process_pdf(path)
        elif path.endswith('.csv') or path.endswith('.xlsx') or path.endswith('.xls'):
            # Process the csv
            text = self.CSV.process_csv(path)
        elif path.endswith('.pptx') or path.endswith('.ppt'):
            # Process the pptx
            text = self.PPTX.process_pptx(path)
        elif path.endswith('.docx') or path.endswith('.doc'):
            # Process the pptx
            text = self.Docx.process_docx(path)

        return text

    # Function when the user installs Lexora and runs it for the first time and the below function will be called after that
    def main_processing(self, root_folder):
        paths = self.read_files(root_folder)
        processed_files = self.process_files(paths)
        return processed_files
