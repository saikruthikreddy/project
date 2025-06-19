import pandas as pd
import openpyxl
from openpyxl.drawing.image import Image as OpenpyxlImage
import zipfile
import os
import tempfile
from io import BytesIO
from giani_pkb.utils.exceptions import ParsingError, APIError, FileProcessingError
from giani_pkb.utils.prompt_loader import load_prompt_template
from giani_pkb.preprocessing.Images import Image as Image_Processor
import google.generativeai as genai
from giani_pkb.utils.config import GEMINI_FLASH_ALIAS

class CSVProcessor:
    def __init__(self, api_key):
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel(GEMINI_FLASH_ALIAS)
        self.image_processor = Image_Processor()
    
    def _extract_images_from_excel(self, path):
        """Extract images from Excel file and process them"""
        extracted_images_text = []
        
        try:
            # Load workbook
            workbook = openpyxl.load_workbook(path, data_only=False)
            
            for sheet_name in workbook.sheetnames:
                print('processing', sheet_name)
                sheet = workbook[sheet_name]
                
                # Check if sheet has images
                if hasattr(sheet, '_images') and sheet._images:
                    for image in sheet._images:
                        try:
                            # Get image data
                            image_data = image._data()
                            
                            # Process image using your Image processor
                            image_text = self.image_processor.process_image_bytes(image_data)
                            if image_text and image_text.strip():
                                extracted_images_text.append(f"Image from sheet '{sheet_name}': {image_text}")
                        except Exception as e:
                            print(f"Error processing image in sheet {sheet_name}: {e}")
                            continue
            
            workbook.close()
            
        except Exception as e:
            print(f"Error extracting images from Excel: {e}")
        
        return extracted_images_text
    
    def _extract_images_from_excel_zip(self, path):
        """Alternative method to extract images by treating Excel as ZIP"""
        extracted_images_text = []
        
        try:
            with zipfile.ZipFile(path, 'r') as zip_file:
                # Look for media files in the Excel structure
                media_files = [f for f in zip_file.namelist() if f.startswith('xl/media/')]
                
                for media_file in media_files:
                    try:
                        # Extract image data
                        image_data = zip_file.read(media_file)
                        image_text = self.image_processor.process_image_bytes(image_data)
                        if image_text and image_text.strip():
                            extracted_images_text.append(f"Image from file '{media_file}': {image_text}")
                    except Exception as e:
                        print(f"Error processing image {media_file}: {e}")
                        continue
                        
        except Exception as e:
            print(f"Error extracting images from Excel ZIP: {e}")
        
        return extracted_images_text
    
    def _enhanced_csv_parsing(self, path):
        """Enhanced CSV parsing with better error handling and data type detection"""
        try:
            # Try different encodings
            encodings = ['utf-8', 'latin-1', 'cp1252', 'iso-8859-1']
            df = None
            
            for encoding in encodings:
                try:
                    df = pd.read_csv(path, encoding=encoding, low_memory=False)
                    break
                except UnicodeDecodeError:
                    continue
            
            if df is None:
                raise ValueError("Could not read CSV file with any supported encoding")
            
            # Handle mixed data types and clean the data
            for col in df.columns:
                # Convert object columns that might contain mixed types
                if df[col].dtype == 'object':
                    # Try to convert to numeric where possible
                    df[col] = pd.to_numeric(df[col], errors='ignore')
            
            return df
            
        except Exception as e:
            raise ValueError(f"Error parsing CSV file: {e}")
    
    def _find_header_row(self, df_raw):
        """Find the actual header row by analyzing the data structure"""
        if df_raw.empty:
            return 0, df_raw.columns.tolist()
        
        # Look for the first row that has the most non-null, non-empty values
        # and appears to be text-based (likely headers)
        best_header_row = 0
        best_score = 0
        
        for i in range(min(10, len(df_raw))):  # Check first 10 rows max
            row = df_raw.iloc[i]
            
            # Count non-null, non-empty values
            non_empty_count = sum(1 for val in row if pd.notna(val) and str(val).strip())
            
            # Count text values (likely headers)
            text_count = sum(1 for val in row if pd.notna(val) and isinstance(val, str) and len(str(val).strip()) > 0)
            
            # Score: prioritize rows with more text values and fewer numeric values
            score = text_count * 2 + non_empty_count
            
            if score > best_score:
                best_score = score
                best_header_row = i
        
        # Extract headers from the best row
        headers = []
        header_row = df_raw.iloc[best_header_row]
        
        for j, val in enumerate(header_row):
            if pd.notna(val) and str(val).strip():
                headers.append(str(val).strip())
            else:
                # Use original column name if header is empty
                headers.append(f"Column_{j}")
        
        return best_header_row, headers
    
    def _clean_merged_headers(self, df_raw, sheet_name):
        """Handle merged headers and multi-row headers"""
        try:
            # Read the sheet without header to get raw data
            workbook = openpyxl.load_workbook(sheet_name, data_only=True)
            if sheet_name in workbook.sheetnames:
                worksheet = workbook[sheet_name]
                
                # Check for merged cells in the first few rows
                merged_ranges = worksheet.merged_cells.ranges
                header_info = {}
                
                # Extract information from merged cells
                for merged_range in merged_ranges:
                    if merged_range.min_row <= 5:  # Only consider first 5 rows as potential headers
                        top_left_cell = worksheet.cell(merged_range.min_row, merged_range.min_col)
                        if top_left_cell.value:
                            for row in range(merged_range.min_row, merged_range.max_row + 1):
                                for col in range(merged_range.min_col, merged_range.max_col + 1):
                                    header_info[(row, col)] = str(top_left_cell.value).strip()
                
                workbook.close()
                return header_info
            else:
                return {}
                
        except Exception as e:
            print(f"Error processing merged headers for sheet {sheet_name}: {e}")
            return {}
    
    def _enhanced_excel_parsing(self, path):
        """Enhanced Excel parsing with intelligent header detection and data cleaning"""
        try:
            # Get all sheet names
            excel_file = pd.ExcelFile(path)
            sheets_data = {}
            
            for sheet_name in excel_file.sheet_names:
                try:
                    # First, read without header to analyze structure
                    df_raw = pd.read_excel(path, sheet_name=sheet_name, header=None, na_values=['', 'N/A', 'NULL', 'null'])
                    
                    if df_raw.empty:
                        continue
                    
                    # Find the best header row
                    header_row_idx, detected_headers = self._find_header_row(df_raw)
                    
                    # Read again with the detected header row
                    df = pd.read_excel(path, sheet_name=sheet_name, header=header_row_idx, na_values=['', 'N/A', 'NULL', 'null'])
                    
                    # Clean column names - handle unnamed columns
                    new_columns = []
                    for i, col in enumerate(df.columns):
                        col_str = str(col)
                        if col_str.startswith('Unnamed:') or col_str == 'nan':
                            # Try to use detected header or create meaningful name
                            if i < len(detected_headers) and not detected_headers[i].startswith('Column_'):
                                new_columns.append(detected_headers[i])
                            else:
                                # Look at the first few non-null values to infer column purpose
                                sample_values = df.iloc[:5, i].dropna().astype(str).tolist()
                                if sample_values:
                                    # Create name based on content pattern
                                    if any(val.replace('.', '').replace('-', '').isdigit() for val in sample_values):
                                        new_columns.append(f"Numeric_Data_{i+1}")
                                    elif any(len(val) > 20 for val in sample_values):
                                        new_columns.append(f"Description_{i+1}")
                                    else:
                                        new_columns.append(f"Data_Column_{i+1}")
                                else:
                                    new_columns.append(f"Empty_Column_{i+1}")
                        else:
                            # Clean existing column names
                            clean_name = col_str.strip().replace('\n', ' ').replace('\r', ' ')
                            new_columns.append(clean_name if clean_name else f"Column_{i+1}")
                    
                    df.columns = new_columns
                    
                    # Remove completely empty rows and columns
                    df = df.dropna(how='all').dropna(axis=1, how='all')
                    
                    # Skip sheets that are still empty after cleaning
                    if not df.empty:
                        # Add metadata about the sheet
                        df.attrs['sheet_name'] = sheet_name
                        df.attrs['original_header_row'] = header_row_idx
                        sheets_data[sheet_name] = df
                        
                except Exception as e:
                    print(f"Error reading sheet {sheet_name}: {e}")
                    continue
            
            # Combine all sheets into one dataframe if multiple sheets exist
            if len(sheets_data) > 1:
                combined_df = pd.DataFrame()
                for sheet_name, df in sheets_data.items():
                    # Add sheet identifier and preserve original info
                    df_copy = df.copy()
                    df_copy['source_sheet'] = sheet_name
                    df_copy['original_header_row'] = df.attrs.get('original_header_row', 0)
                    combined_df = pd.concat([combined_df, df_copy], ignore_index=True, sort=False)
                return combined_df
            elif len(sheets_data) == 1:
                return list(sheets_data.values())[0]
            else:
                raise ValueError("No readable sheets found in Excel file")
                
        except Exception as e:
            raise ValueError(f"Error parsing Excel file: {e}")
    
    def process_csv(self, path):
        try:
            # Enhanced file format detection and parsing
            if path.endswith(".csv"):
                df = self._enhanced_csv_parsing(path)
                extracted_images_text = []  # CSV files don't typically contain images
                
            elif path.endswith(".xlsx") or path.endswith(".xls"):
                df = self._enhanced_excel_parsing(path)
                
                # Extract images from Excel file
                extracted_images_text = self._extract_images_from_excel(path)
                
                # If first method fails, try ZIP method
                if not extracted_images_text:
                    extracted_images_text = self._extract_images_from_excel_zip(path)
                    
            else:
                raise ValueError("Unsupported file format. Please provide a .csv or .xlsx file.")
            
            # Enhanced text extraction
            text_data = df.select_dtypes(include=['object', 'string'])
            all_text = text_data.values.flatten().tolist()
            all_text = [str(text) for text in all_text if pd.notna(text) and str(text).strip()]
            
            # Add statistical summary
            numeric_summary = df.describe(include='all').to_string()
            all_text.append(f"Statistical Summary:\n{numeric_summary}")
            
            # Add detailed column information - ensure all column names are strings
            column_names = [str(col) for col in df.columns.tolist()]
            column_info = f"Detected Columns ({len(column_names)}): {', '.join(column_names)}"
            all_text.append(column_info)
            
            # Add information about data types
            dtype_info = "Column Data Types:\n" + df.dtypes.to_string()
            all_text.append(dtype_info)
            
            # Add data shape information
            shape_info = f"Data shape: {df.shape[0]} rows, {df.shape[1]} columns"
            all_text.append(shape_info)
            
            # Add sample data from first few rows (if available)
            if not df.empty:
                sample_data = f"Sample data (first 3 rows):\n{df.head(3).to_string()}"
                all_text.append(sample_data)
            
            # Add sheet information if this came from Excel
            if 'source_sheet' in df.columns:
                unique_sheets = df['source_sheet'].unique()
                sheet_info = f"Data from sheets: {', '.join(str(sheet) for sheet in unique_sheets)}"
                all_text.append(sheet_info)
            
            # Add extracted image text if any
            if extracted_images_text:
                # Ensure all image text is string
                image_text_strings = [str(img_text) for img_text in extracted_images_text]
                all_text.extend(image_text_strings)
                all_text.append(f"Found {len(extracted_images_text)} images in the file")
            
            # Ensure all items in all_text are strings before joining
            all_text_strings = [str(item) for item in all_text if item is not None]
            
            # Combine all content
            content = ' '.join(all_text_strings)
            
            # Load prompt template and generate content
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
        except Exception as e:
            print(f"Error processing CSV {path}: {e}")
            raise FileProcessingError(f"Error processing file {path}: {e}", filepath=path)