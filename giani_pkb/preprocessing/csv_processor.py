"""
CSV and Excel file processor for extracting structured data and images.
"""
import pandas as pd
import openpyxl
from typing import List, Dict, Any, Tuple, Optional, Iterator
import logging
from pathlib import Path

from giani_pkb.utils.exceptions import ParsingError, FileProcessingError

logger = logging.getLogger(__name__)

class CSVProcessor:
    """
    Processor for CSV and Excel files that extracts structured data and images.

    Features:
    - Multi-encoding CSV support
    - Excel data extraction with image processing
    - Memory-efficient processing for large files
    - Structured output with metadata
    """

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize the CSV processor.

        Args:
            api_key: Optional API key for image processing (if needed)
        """
        self.api_key = api_key
        self.image_processor = self._get_image_processor()

        # Configuration
        self.default_rows_per_block = 10
        self.supported_csv_encodings = ['utf-8', 'latin-1', 'cp1252', 'iso-8859-1']
        self.supported_extensions = {'.csv', '.xlsx', '.xls'}

    def _get_image_processor(self):
        """Get image processor if available."""
        try:
            from giani_pkb.preprocessing.image_processor import ImageProcessor
            return ImageProcessor()
        except ImportError:
            logger.warning("Image processor not available. Image extraction will be skipped.")
            return None

    def _extract_images_from_excel_sheet(self, workbook: openpyxl.Workbook, sheet_name: str) -> List[Tuple[str, Dict[str, Any]]]:
        """
        Extract images from a specific Excel sheet and process them.

        Args:
            workbook: OpenPyXL workbook object
            sheet_name: Name of the sheet to process

        Returns:
            List of (image_text, metadata) tuples
        """
        if not self.image_processor:
            return []

        image_blocks: List[Tuple[str, Dict[str, Any]]] = []

        try:
            sheet = workbook[sheet_name]
            img_idx = 0

            if hasattr(sheet, '_images') and sheet._images:
                for image in sheet._images:
                    img_idx += 1
                    try:
                        image_data = image._data()
                        image_text = self.image_processor.process_image_bytes(image_data)

                        if image_text and image_text.strip():
                            metadata = {
                                "page_number": None,
                                "block_type": "image_text",
                                "source_type": "image",
                                "sheet_name": sheet_name,
                                "image_index_on_sheet": img_idx,
                                "file_type": "excel_image"
                            }
                            image_blocks.append((image_text.strip(), metadata))

                    except Exception as e:
                        logger.error(f"Error processing image {img_idx} in sheet {sheet_name}: {e}")

        except Exception as e:
            logger.error(f"Error accessing images in sheet {sheet_name}: {e}")

        return image_blocks

    def _parse_dataframe_to_blocks(self, df: pd.DataFrame, sheet_name: Optional[str] = None,
                                 rows_per_block: int = None) -> List[Tuple[str, Dict[str, Any]]]:
        """
        Convert a pandas DataFrame into structured text blocks.

        Args:
            df: Pandas DataFrame to process
            sheet_name: Name of the sheet (for Excel files)
            rows_per_block: Number of rows to group together

        Returns:
            List of (text_block, metadata) tuples
        """
        if rows_per_block is None:
            rows_per_block = self.default_rows_per_block

        blocks: List[Tuple[str, Dict[str, Any]]] = []

        if df.empty:
            return blocks

        # Clean the DataFrame
        df = self._clean_dataframe(df)

        for i in range(0, len(df), rows_per_block):
            chunk_df = df.iloc[i:i+rows_per_block]
            block_text_lines = []
            row_numbers = []

            # Process each row in the chunk
            for idx, row in chunk_df.iterrows():
                row_text_parts = []
                for col_name, val in row.items():
                    if pd.notna(val):  # Skip NaN values
                        row_text_parts.append(f"{col_name}: {val}")

                if row_text_parts:  # Only add non-empty rows
                    block_text_lines.append("; ".join(row_text_parts))
                    row_numbers.append(int(idx) + 1)

            if block_text_lines:  # Only create blocks with content
                block_text = "\n".join(block_text_lines)

                metadata = {
                    "page_number": None,
                    "block_type": "row_group_data",
                    "source_type": "tabular_data",
                    "sheet_name": sheet_name,
                    "row_numbers": row_numbers,
                    "column_names": df.columns.tolist(),
                    "total_rows": len(df),
                    "file_type": "excel" if sheet_name else "csv"
                }

                blocks.append((block_text, metadata))

        return blocks

    def _clean_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Clean and prepare DataFrame for processing.

        Args:
            df: Raw DataFrame

        Returns:
            Cleaned DataFrame
        """
        # Clean column names
        df.columns = [str(col).strip() for col in df.columns]

        # Drop completely empty rows and columns
        df = df.dropna(how='all').dropna(axis=1, how='all')

        # Convert all values to strings for consistent processing
        for col in df.columns:
            df[col] = df[col].astype(str).replace('nan', '')

        return df

    def _enhanced_csv_parsing(self, path: str) -> Optional[pd.DataFrame]:
        """
        Enhanced CSV parsing with multiple encoding support.

        Args:
            path: Path to CSV file

        Returns:
            Parsed DataFrame or None if parsing fails
        """
        try:
            for encoding in self.supported_csv_encodings:
                try:
                    df = pd.read_csv(
                        path,
                        encoding=encoding,
                        low_memory=False,
                        skipinitialspace=True,
                        on_bad_lines='skip'  # Skip problematic lines
                    )
                    logger.info(f"Successfully parsed CSV with {encoding} encoding")
                    return df

                except UnicodeDecodeError:
                    continue
                except Exception as e:
                    logger.warning(f"Error with {encoding} encoding: {e}")
                    continue

            logger.error(f"Could not read CSV file {path} with any supported encoding")
            return None

        except Exception as e:
            logger.error(f"Error parsing CSV file {path}: {e}")
            return None

    def _enhanced_excel_parsing_iterative(self, path: str, rows_per_block: int = None) -> Iterator[Tuple[str, Dict[str, Any]]]:
        """
        Enhanced Excel parsing with memory-efficient processing.

        Args:
            path: Path to Excel file
            rows_per_block: Number of rows per block

        Yields:
            (text_block, metadata) tuples
        """
        if rows_per_block is None:
            rows_per_block = self.default_rows_per_block

        try:
            # Get sheet names
            excel_file = pd.ExcelFile(path)

            for sheet_name in excel_file.sheet_names:
                try:
                    # Parse data rows
                    df_sheet = pd.read_excel(
                        path,
                        sheet_name=sheet_name,
                        header=0,
                        na_values=['', 'nan', 'NaN']
                    )

                    if not df_sheet.empty:
                        for block_text, metadata in self._parse_dataframe_to_blocks(
                            df_sheet, sheet_name, rows_per_block
                        ):
                            yield block_text, metadata

                    # Extract images (if processor is available)
                    if self.image_processor:
                        try:
                            img_workbook = openpyxl.load_workbook(path, data_only=False)
                            image_blocks = self._extract_images_from_excel_sheet(img_workbook, sheet_name)

                            for img_block_text, img_metadata in image_blocks:
                                yield img_block_text, img_metadata

                            img_workbook.close()

                        except Exception as e:
                            logger.warning(f"Could not extract images from sheet {sheet_name}: {e}")

                except Exception as e:
                    logger.error(f"Error reading sheet {sheet_name} from {path}: {e}")
                    continue

        except Exception as e:
            logger.error(f"Error parsing Excel file {path}: {e}")
            raise FileProcessingError(f"Failed to parse Excel file: {e}", filepath=path)

    def process_file(self, path: str, rows_per_block: int = None) -> List[Tuple[str, Dict[str, Any]]]:
        """
        Process a CSV or Excel file and extract structured content.

        Args:
            path: Path to the file to process
            rows_per_block: Number of rows to group together (optional)

        Returns:
            List of (text_block, metadata) tuples

        Raises:
            ParsingError: If file format is not supported
            FileProcessingError: If processing fails
        """
        path = Path(path)

        if not path.exists():
            raise FileProcessingError(f"File not found: {path}", filepath=str(path))

        if path.suffix.lower() not in self.supported_extensions:
            raise ParsingError(
                f"Unsupported file format: {path.suffix}. Supported: {', '.join(self.supported_extensions)}",
                filename=str(path)
            )

        processed_blocks: List[Tuple[str, Dict[str, Any]]] = []

        try:
            if path.suffix.lower() == '.csv':
                df = self._enhanced_csv_parsing(str(path))
                if df is not None:
                    processed_blocks.extend(
                        self._parse_dataframe_to_blocks(df, rows_per_block=rows_per_block)
                    )

            elif path.suffix.lower() in {'.xlsx', '.xls'}:
                for block_text, metadata in self._enhanced_excel_parsing_iterative(
                    str(path), rows_per_block=rows_per_block
                ):
                    processed_blocks.append((block_text, metadata))

            if not processed_blocks:
                logger.warning(f"No content blocks extracted from {path}")

            logger.info(f"Successfully processed {path}: {len(processed_blocks)} blocks extracted")
            return processed_blocks

        except (ParsingError, FileProcessingError):
            raise
        except Exception as e:
            logger.error(f"Unexpected error processing file {path}: {e}")
            raise FileProcessingError(f"Error processing file {path}: {e}", filepath=str(path))

    def process_csv(self, path: str, rows_per_block: int = None) -> List[Tuple[str, Dict[str, Any]]]:
        """
        Legacy method for backward compatibility.

        Args:
            path: Path to CSV/Excel file
            rows_per_block: Number of rows per block

        Returns:
            List of (text_block, metadata) tuples
        """
        return self.process_file(path, rows_per_block)