# CSV.py
import pandas as pd
import google.generativeai as genai


class CSVProcessor:
    def __init__(self, api_key):
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel("gemini-2.0-flash")  # Initialize model once


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
        
            prompt = f"""
            Blindly Rewrite the Dataset in md file format and
            Analyze the following dataset and provide a comprehensive summary of the data:
            {content}
            """
        
            response = self.model.generate_content(prompt)
            description = response.parts[0].text.strip()
            return description
        except Exception as e:
            print(f"Error processing CSV {path}: {e}")
            return ""