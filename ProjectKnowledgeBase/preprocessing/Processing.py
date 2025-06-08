import os
from preprocessing.Text import PDF
from preprocessing.Images import Image
from preprocessing.CSV import CSVProcessor
from preprocessing.PPTX import PPTX
from preprocessing.Docx import Docx
import tqdm




class MainProcessing:
    def __init__(self):
        self.PDF = PDF()
        self.Image = Image()
        self.CSV = CSVProcessor(api_key='')
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