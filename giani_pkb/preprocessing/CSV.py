import pandas as pd
from giani_pkb.utils.exceptions import ParsingError, APIError, FileProcessingError
from giani_pkb.utils.prompt_loader import load_prompt_template
import google.generativeai as genai
from giani_pkb.utils.config import GEMINI_FLASH_ALIAS 


class CSVProcessor:
    def __init__(self, api_key):
        genai.configure(api_key=api_key) 
        self.model = genai.GenerativeModel(GEMINI_FLASH_ALIAS)  


    def process_csv(self, path):
        try:
            if path.endswith(".csv"):
                df = pd.read_csv(path)
            elif path.endswith(".xlsx") or path.endswith(".xls"):
                df = pd.read_excel(path)
            else:
                raise ValueError("Unsupported file format. Please provide a .csv or .xlsx file.")

            text_data = df.select_dtypes(include=['object'])
            all_text = text_data.values.flatten().tolist()
            all_text = [str(text) for text in all_text if pd.notna(text)]
            all_text.append(df.describe().to_string())
            content = ' '.join(all_text)

            prompt_template = load_prompt_template("csv_analysis_prompt.txt")
            prompt = prompt_template.format(content=content)

            response = self.model.generate_content(prompt)
            description = response.parts[0].text.strip()
            return description
        except ValueError as e: 
            raise ParsingError(str(e), filename=path)
        except APIError as e: 
            print(f"API Error processing CSV {path}: {e}")
            raise 
        except Exception as e: #
            print(f"Error processing CSV {path}: {e}") 
            raise FileProcessingError(f"Error processing file {path}: {e}", filepath=path)
