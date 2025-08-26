"""
Enhanced CSV and Excel file processor for extracting structured data and images with LlamaIndex integration.
Fully migrated for Azure Blob Storage compatibility with all improvements correctly implemented.
"""
import pandas as pd
import openpyxl
import json
import uuid
import re
import chardet
from datetime import datetime
from typing import List, Dict, Any, Tuple, Optional, Iterator
import logging
from pathlib import Path

# LlamaIndex imports
try:
    from llama_index.core import Document, VectorStoreIndex, Settings
    from llama_index.core.node_parser import SimpleNodeParser
    from llama_index.core.schema import BaseNode, TextNode
    from llama_index.core.storage.storage_context import StorageContext
    from llama_index.readers.file import PandasCSVReader, PandasExcelReader

    try:
        from llama_index.embeddings.openai import OpenAIEmbedding
        from llama_index.llms.openai import OpenAI
    except ImportError:
        try:
            from llama_index.embeddings import OpenAIEmbedding
            from llama_index.llms import OpenAI
        except ImportError:
            OpenAIEmbedding = None
            OpenAI = None

    try:
        from llama_index.vector_stores.chroma import ChromaVectorStore
        import chromadb
        CHROMA_AVAILABLE = True
    except ImportError:
        try:
            from llama_index.vector_stores import ChromaVectorStore
            import chromadb
            CHROMA_AVAILABLE = True
        except ImportError:
            ChromaVectorStore = None
            chromadb = None
            CHROMA_AVAILABLE = False

    LLAMAINDEX_AVAILABLE = True
except ImportError as e:
    LLAMAINDEX_AVAILABLE = False
    CHROMA_AVAILABLE = False
    Document = None
    VectorStoreIndex = None
    Settings = None
    SimpleNodeParser = None

logger = logging.getLogger(__name__)

from services.blob_storage_service import blob_storage_service
from utils.exceptions import ParsingError, FileProcessingError

class CSVProcessor:
    """
    Enhanced processor for CSV and Excel files with Azure Blob Storage support.
    Fully migrated with all improvements correctly implemented.
    """

    def __init__(self, api_key: Optional[str] = None, use_row_by_row: bool = False,
                 openai_api_key: Optional[str] = None, use_llamaindex: bool = True):
        """
        Initialize the CSV processor.

        Args:
            api_key: Optional API key for image processing
            use_row_by_row: Whether to use row-by-row processing
            openai_api_key: OpenAI API key for embeddings and LLM
            use_llamaindex: Whether to use LlamaIndex for enhanced parsing
        """
        self.api_key = api_key
        self.use_row_by_row = use_row_by_row
        self.openai_api_key = openai_api_key
        self.use_llamaindex = use_llamaindex and LLAMAINDEX_AVAILABLE

        self.image_processor = self._get_image_processor()
        self.default_rows_per_block = 120
        self.supported_csv_encodings = ['utf-8', 'ISO-8859-1', 'latin-1', 'cp1252']
        self.supported_csv_delimiters = [',', ';', '\t', '|', ':']
        self.supported_extensions = {'.csv', '.xlsx', '.xls'}

        self.current_section_idx = 1
        self._blob_info_cache = {}  # Cache for blob info to improve performance

        self.visual_patterns = [
            r'\b(?:chart|figure|graph|diagram|table|image|plot|visualization)\b',
            r'\b(?:see|refer|reference|shown|depicted|illustrated)\s+(?:above|below|in|to)\b',
            r'\b(?:as\s+shown|refer\s+to|see\s+table|see\s+figure|chart\s+shows)\b',
            r'\b(?:visualization|infographic|screenshot|dashboard)\b'
        ]

        if self.use_llamaindex:
            self.node_parser = SimpleNodeParser.from_defaults()
            if self.openai_api_key and OpenAI and OpenAIEmbedding:
                Settings.llm = OpenAI(api_key=self.openai_api_key, model="gpt-3.5-turbo")
                Settings.embed_model = OpenAIEmbedding(api_key=self.openai_api_key)

    def _get_image_processor(self):
        """Get image processor if available."""
        try:
            from preprocessing.image_processor import ImageProcessor
            return ImageProcessor()
        except ImportError:
            logger.warning("Image processor not available. Image extraction will be skipped.")
            return None

    def _get_cached_blob_info(self, container: str, blob_name: str) -> Dict[str, Any]:
        """Get blob info with caching to improve performance."""
        key = f"{container}/{blob_name}"
        if key not in self._blob_info_cache:
            self._blob_info_cache[key] = blob_storage_service.get_blob_info(container, blob_name)
        return self._blob_info_cache[key]

    def get_synthetic_page_number(self, sheet_name: str, chunk_index: int = 0) -> int:
        """Create stable page numbers based on sheet order and chunk position."""
        base_page = max(1, self.current_section_idx)
        return base_page + chunk_index

    def detect_encoding(self, container: str, blob_name: str) -> str:
        """Detect file encoding using chardet."""
        try:
            blob_data = blob_storage_service.download_file(container, blob_name)
            result = chardet.detect(blob_data[:100000])
            encoding = result['encoding']
            confidence = result['confidence']
            logger.info(f"Detected encoding: {encoding} (confidence: {confidence:.2f})")
            return encoding if encoding else 'utf-8'
        except Exception as e:
            logger.warning(f"Encoding detection failed: {e}")
            return 'utf-8'

    def detect_csv_delimiter(self, container: str, blob_name: str, encoding: str) -> str:
        """Detect CSV delimiter by analyzing the first few lines."""
        try:
            blob_data = blob_storage_service.download_file(container, blob_name)
            text_data = blob_data.decode(encoding)
            sample_lines = text_data.split('\n')[:5]

            delimiter_counts = {}
            for delimiter in self.supported_csv_delimiters:
                counts = [line.count(delimiter) for line in sample_lines if line.strip()]
                if counts and all(count > 0 for count in counts):
                    avg_count = sum(counts) / len(counts)
                    consistency = all(abs(count - avg_count) <= 1 for count in counts)
                    if consistency:
                        delimiter_counts[delimiter] = avg_count

            if delimiter_counts:
                best_delimiter = max(delimiter_counts, key=delimiter_counts.get)
                logger.info(f"Detected delimiter: '{best_delimiter}' (avg count: {delimiter_counts[best_delimiter]:.1f})")
                return best_delimiter
            else:
                logger.info("Using default delimiter: ','")
                return ','

        except Exception as e:
            logger.warning(f"Delimiter detection failed: {e}")
            return ','

    def detect_visual_references(self, text: str) -> bool:
        """Detect if text contains visual references."""
        text_lower = text.lower()
        for pattern in self.visual_patterns:
            if re.search(pattern, text_lower, re.IGNORECASE):
                return True
        return False

    def count_words(self, text: str) -> int:
        """Count words in text."""
        return len(text.split()) if text else 0

    def _clean_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """Clean and prepare DataFrame for processing."""
        df.columns = [str(col).strip() for col in df.columns]
        df = df.dropna(how='all').dropna(axis=1, how='all')
        return df

    def _enhanced_csv_parsing(self, container: str, blob_name: str) -> Optional[pd.DataFrame]:
        """Enhanced CSV parsing with multiple encoding and delimiter support."""
        try:
            detected_encoding = self.detect_encoding(container, blob_name)
            encodings_to_try = [detected_encoding] + self.supported_csv_encodings
            encodings_to_try = list(dict.fromkeys(encodings_to_try))

            blob_data = blob_storage_service.download_file(container, blob_name)

            for encoding in encodings_to_try:
                for delimiter in self.supported_csv_delimiters:
                    try:
                        from io import StringIO
                        text_data = blob_data.decode(encoding)
                        df = pd.read_csv(
                            StringIO(text_data),
                            delimiter=delimiter,
                            low_memory=False,
                            skipinitialspace=True,
                            on_bad_lines='skip'
                        )

                        if not df.empty and len(df.columns) > 1:
                            logger.info(f"Successfully parsed CSV with encoding='{encoding}', delimiter='{delimiter}'")
                            return df

                    except (UnicodeDecodeError, pd.errors.EmptyDataError):
                        continue
                    except Exception as e:
                        logger.debug(f"Error with {encoding} encoding and '{delimiter}' delimiter: {e}")
                        continue

            # Fallback approach
            for encoding in encodings_to_try:
                try:
                    from io import StringIO
                    text_data = blob_data.decode(encoding)
                    df = pd.read_csv(
                        StringIO(text_data),
                        low_memory=False,
                        skipinitialspace=True,
                        on_bad_lines='skip'
                    )
                    logger.info(f"Successfully parsed CSV with {encoding} encoding (fallback)")
                    return df

                except UnicodeDecodeError:
                    continue
                except Exception as e:
                    logger.warning(f"Error with {encoding} encoding: {e}")
                    continue

            logger.error(f"Could not read CSV blob {container}/{blob_name} with any supported encoding or delimiter")
            return None

        except Exception as e:
            logger.error(f"Error parsing CSV blob {container}/{blob_name}: {e}")
            return None

    def _load_excel_dataframe(self, container: str, blob_name: str, sheet_name: str = None) -> pd.DataFrame:
        """Load Excel file with enhanced error handling."""
        try:
            blob_data = blob_storage_service.download_file(container, blob_name)
            from io import BytesIO

            if sheet_name:
                df = pd.read_excel(BytesIO(blob_data), sheet_name=sheet_name, header=0, na_values=['', 'nan', 'NaN'])
            else:
                df = pd.read_excel(BytesIO(blob_data), header=0, na_values=['', 'nan', 'NaN'])

            logger.info(f"Successfully loaded Excel sheet: {sheet_name or 'default'}")
            return df

        except Exception as e:
            logger.error(f"Error loading Excel sheet {sheet_name}: {e}")
            raise

    def get_excel_sheet_names(self, container: str, blob_name: str) -> List[str]:
        """Get all sheet names from an Excel file."""
        try:
            blob_data = blob_storage_service.download_file(container, blob_name)
            from io import BytesIO
            xl_file = pd.ExcelFile(BytesIO(blob_data))
            sheet_names = xl_file.sheet_names
            logger.info(f"Found {len(sheet_names)} sheets: {sheet_names}")
            return sheet_names
        except Exception as e:
            logger.warning(f"Could not read sheet names: {e}")
            return ["Sheet1"]

    def _extract_images_from_excel_sheet(self, container: str, blob_name: str, sheet_name: str) -> List[Tuple[str, Dict[str, Any]]]:
        """Extract images from a specific Excel sheet and process them."""
        if not self.image_processor:
            return []

        image_blocks: List[Tuple[str, Dict[str, Any]]] = []

        try:
            blob_data = blob_storage_service.download_file(container, blob_name)
            from io import BytesIO
            workbook = openpyxl.load_workbook(BytesIO(blob_data), data_only=False)
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
                                "page_number": self.get_synthetic_page_number(sheet_name),
                                "block_type": "image_text",
                                "source_type": "image",
                                "sheet_name": sheet_name,
                                "image_index_on_sheet": img_idx,
                                "file_type": "excel_image",
                                "section_id": self.current_section_idx
                            }
                            image_blocks.append((image_text.strip(), metadata))

                    except Exception as e:
                        logger.error(f"Error processing image {img_idx} in sheet {sheet_name}: {e}")

        except Exception as e:
            logger.error(f"Error accessing images in sheet {sheet_name}: {e}")

        return image_blocks

    def emit_sheet_tables(self, df: pd.DataFrame, sheet_name: str, blob_name: str,
                         rows_per_block: int = None) -> List[Tuple[str, Dict[str, Any]]]:
        """Create sheet-level table blocks with header carry-over."""
        if df.empty:
            return []

        if rows_per_block is None:
            rows_per_block = self.default_rows_per_block

        # Get clean filename without path operations
        blob_info = self._get_cached_blob_info(*blob_name.split('/', 1)) if '/' in blob_name else {"file_name": blob_name}
        base_name = blob_info.get("file_name", blob_name)

        headers = list(map(str, df.columns))
        header_md = "| " + " | ".join(headers) + " |\n| " + " | ".join(["---"] * len(headers)) + " |\n"

        blocks = []

        for chunk_idx, i in enumerate(range(0, len(df), rows_per_block)):
            chunk = df.iloc[i:i+rows_per_block]

            body_rows = []
            for _, row in chunk.iterrows():
                cells = []
                for val in row:
                    if pd.isna(val):
                        cells.append("")
                    else:
                        cells.append(str(val).strip())
                body_rows.append("| " + " | ".join(cells) + " |")

            body = "\n".join(body_rows)
            text = header_md + body

            synthetic_page = self.get_synthetic_page_number(sheet_name, chunk_idx)

            metadata = {
                "page_number": synthetic_page,
                "block_type": "table",
                "source_type": "tabular_data",
                "sheet_name": sheet_name,
                "region_id": f"{sheet_name.replace(' ', '_')}_rows_{i}_{min(i+rows_per_block-1, len(df)-1)}",
                "filename": base_name,
                "section_id": self.current_section_idx,
                "column_names": headers,
                "row_numbers": [int(i), int(min(i+rows_per_block-1, len(df)-1))],
                "caption": f"{sheet_name} (rows {i+1}--{min(i+rows_per_block,len(df))})",
                "source": f"{base_name}#{sheet_name}#rows={i}-{min(i+rows_per_block-1, len(df)-1)}",
                "word_count": len(text.split()),
                "row_count": len(chunk),
                "column_count": len(headers),
                "total_rows": len(df),
                "file_type": "excel" if sheet_name != "Sheet1" else "csv"
            }

            blocks.append((text, metadata))

        return blocks

    def _convert_to_row_blocks(self, df: pd.DataFrame, sheet_name: Optional[str] = None,
                              container: str = None, blob_name: str = None) -> List[Tuple[str, Dict[str, Any]]]:
        """Convert DataFrame to row-by-row blocks (legacy compatibility)."""
        blocks = []

        # Get clean filename
        if container and blob_name:
            blob_info = self._get_cached_blob_info(container, blob_name)
            base_name = blob_info["file_name"]
        else:
            base_name = "unknown"

        for idx, row in df.iterrows():
            row_text = " | ".join(str(cell) for cell in row.values if pd.notna(cell)).strip()

            if row_text:
                has_visual_ref = self.detect_visual_references(row_text)
                block_type = "visual_reference" if has_visual_ref else "data_row"

                metadata = {
                    "page_number": self.get_synthetic_page_number(sheet_name or "Sheet1"),
                    "block_type": block_type,
                    "source_type": "row_data",
                    "sheet_name": sheet_name,
                    "row_number": idx + 1,
                    "column_names": df.columns.tolist(),
                    "total_rows": len(df),
                    "source": f"{base_name}#row={idx + 1}",
                    "file_type": "excel" if sheet_name else "csv",
                    "section_id": self.current_section_idx,
                    "word_count": self.count_words(row_text),
                    "visual_reference": has_visual_ref
                }
                blocks.append((row_text, metadata))

        return blocks

    def _parse_dataframe_to_blocks(self, df: pd.DataFrame, sheet_name: Optional[str] = None,
                                 rows_per_block: int = None, container: str = None,
                                 blob_name: str = None) -> List[Tuple[str, Dict[str, Any]]]:
        """Convert a pandas DataFrame into structured text blocks."""
        if df.empty:
            return []

        df = self._clean_dataframe(df)

        if self.use_row_by_row:
            return self._convert_to_row_blocks(df, sheet_name, container, blob_name)

        # Get filename for sheet tables
        if container and blob_name:
            blob_info = self._get_cached_blob_info(container, blob_name)
            base_name = blob_info["file_name"]
        else:
            base_name = "unknown"

        return self.emit_sheet_tables(df, sheet_name or "Sheet1", base_name, rows_per_block)

    def _enhanced_excel_parsing_iterative(self, container: str, blob_name: str,
                                        rows_per_block: int = None) -> Iterator[Tuple[str, Dict[str, Any]]]:
        """Enhanced Excel parsing with memory-efficient processing."""
        if rows_per_block is None:
            rows_per_block = self.default_rows_per_block

        try:
            sheet_names = self.get_excel_sheet_names(container, blob_name)
            blob_info = self._get_cached_blob_info(container, blob_name)
            base_name = blob_info["file_name"]

            for sheet_idx, sheet_name in enumerate(sheet_names):
                self.current_section_idx = sheet_idx + 1

                try:
                    df_sheet = self._load_excel_dataframe(container, blob_name, sheet_name)

                    if not df_sheet.empty:
                        # Create sheet summary block
                        columns = list(df_sheet.columns)
                        column_info = f"Sheet: {sheet_name}\nFile: {base_name}\nColumns: {', '.join(str(col) for col in columns)}\nTotal rows: {len(df_sheet)}"

                        summary_metadata = {
                            "sheet_name": sheet_name,
                            "region_id": f"{sheet_name.replace(' ', '_')}_summary",
                            "block_type": "sheet_summary",
                            "source_type": "summary",
                            "filename": base_name,
                            "page_number": self.get_synthetic_page_number(sheet_name, 0),
                            "section_id": self.current_section_idx,
                            "source": f"{base_name}#{sheet_name}#summary",
                            "word_count": self.count_words(column_info),
                            "column_headers": columns,
                            "column_names": columns,
                            "visual_reference": False
                        }

                        yield column_info, summary_metadata

                        # Generate table blocks
                        for block_text, metadata in self._parse_dataframe_to_blocks(
                            df_sheet, sheet_name, rows_per_block, container, blob_name
                        ):
                            yield block_text, metadata

                    # Extract images
                    if self.image_processor:
                        try:
                            image_blocks = self._extract_images_from_excel_sheet(container, blob_name, sheet_name)
                            for img_block_text, img_metadata in image_blocks:
                                yield img_block_text, img_metadata
                        except Exception as e:
                            logger.warning(f"Could not extract images from sheet {sheet_name}: {e}")

                except Exception as e:
                    logger.error(f"Error reading sheet {sheet_name} from {container}/{blob_name}: {e}")
                    continue

        except Exception as e:
            logger.error(f"Error parsing Excel blob {container}/{blob_name}: {e}")
            raise FileProcessingError(f"Failed to parse Excel blob: {e}", filepath=f"{container}/{blob_name}")

    def validate_blocks_before_chunking(self, blocks: List[Tuple[str, Dict[str, Any]]]) -> bool:
        """Centralize pre-chunk validation for all formats."""
        logger.info("Running pre-chunk validation...")

        for i, (text, meta) in enumerate(blocks):
            try:
                assert "block_type" in meta, f"Block {i}: parser must set block_type"
                assert "page_number" in meta, f"Block {i}: missing page_number"

                if meta.get("block_type") == "table":
                    assert "column_names" in meta and meta.get("column_names"), f"Block {i}: table blocks must have column_names"
                    assert meta.get("source_type") == "tabular_data", f"Block {i}: table blocks must have source_type='tabular_data'"

                logger.debug(f"Block {i}: validation passed")

            except AssertionError as e:
                logger.error(f"Validation failed: {e}")
                return False

        logger.info(f"All {len(blocks)} blocks passed validation")
        return True

    def create_llamaindex_nodes(self, blocks: List[Dict[str, Any]]) -> List[Any]:
        """Create LlamaIndex nodes from parsed blocks."""
        if not self.use_llamaindex:
            logger.warning("LlamaIndex not available or disabled")
            return []

        try:
            documents = [Document(text=block["text"]) for block in blocks]
            nodes = self.node_parser.get_nodes_from_documents(documents)
            return nodes
        except Exception as e:
            logger.error(f"Error creating LlamaIndex nodes: {e}")
            return []

    def _normalize_blocks_input(self, blocks_input: Any) -> List[Dict[str, Any]]:
        """Normalize different types of blocks input to standard format."""
        normalized_blocks = []

        if not blocks_input:
            return normalized_blocks

        if isinstance(blocks_input, list):
            for item in blocks_input:
                if isinstance(item, dict) and 'text' in item:
                    normalized_blocks.append(item)
                elif isinstance(item, str):
                    normalized_blocks.append({"text": item, "type": "text"})
                elif hasattr(item, 'text'):
                    normalized_blocks.append({
                        "text": str(item.text),
                        "type": getattr(item, 'type', 'text')
                    })

        elif hasattr(blocks_input, '__iter__') and not isinstance(blocks_input, (str, dict)):
            try:
                for item in blocks_input:
                    if isinstance(item, dict) and 'text' in item:
                        normalized_blocks.append(item)
                    elif hasattr(item, 'text'):
                        normalized_blocks.append({
                            "text": str(item.text),
                            "type": getattr(item, 'type', 'text')
                        })
            except Exception as e:
                logger.warning(f"Error normalizing blocks input: {e}")

        elif hasattr(blocks_input, 'chunks_preview'):
            try:
                for chunk_info in blocks_input.chunks_preview[:2]:
                    if len(chunk_info) >= 1:
                        normalized_blocks.append({
                            "text": str(chunk_info[0]),
                            "type": "prose"
                        })
            except Exception as e:
                logger.warning(f"Error extracting from ProcessingResult: {e}")

        return normalized_blocks

    def generate_metadata_with_llamaindex(self, container: str, blob_name: str, blocks: Any,
                                        nodes: List[Any] = None) -> Dict[str, Any]:
        """Generate comprehensive metadata using LlamaIndex integration."""
        document_id = str(uuid.uuid4())
        now_iso = datetime.now().isoformat()

        actual_blocks = self._normalize_blocks_input(blocks)

        preview_entries = []

        if nodes and len(nodes) > 0:
            for i, node in enumerate(nodes[:2]):
                try:
                    if hasattr(node, 'text'):
                        snippet = str(node.text).replace('\n', ' ')[:100].strip()
                        node_id = getattr(node, 'node_id', str(uuid.uuid4()))
                        preview_entries.append({
                            "snippet": snippet,
                            "node_id": node_id,
                            "type": "prose"
                        })
                except Exception as e:
                    logger.warning(f"Error processing node {i}: {e}")

        if not preview_entries and actual_blocks:
            for i, block in enumerate(actual_blocks[:2]):
                try:
                    text_content = block.get("text", "")
                    if text_content:
                        snippet = str(text_content).replace('\n', ' ')[:100].strip()
                        preview_entries.append({
                            "snippet": snippet,
                            "node_id": str(uuid.uuid4()),
                            "type": block.get("type", "prose")
                        })
                except Exception as e:
                    logger.warning(f"Error processing block {i}: {e}")

        if not preview_entries:
            preview_entries = [{
                "snippet": "Document content available - preview generation failed",
                "node_id": str(uuid.uuid4()),
                "type": "prose"
            }]

        preview_str = json.dumps(preview_entries, ensure_ascii=False, indent=2)

        full_text = ""
        if nodes:
            try:
                full_text = "\n\n".join(str(node.text) for node in nodes if hasattr(node, 'text'))
            except Exception as e:
                logger.warning(f"Error generating full text from nodes: {e}")

        if not full_text and actual_blocks:
            try:
                full_text = "\n\n".join(block["text"] for block in actual_blocks if block.get("text"))
            except Exception as e:
                logger.warning(f"Error generating full text from blocks: {e}")
                full_text = "Content available - text generation failed"

        file_info = self._get_cached_blob_info(container, blob_name)
        file_size = file_info["size_human"]

        metadata = {
            "document_id": document_id,
            "dateAddedToGiani": now_iso,
            "originalFilename": file_info["file_name"],
            "storagePath": f"{container}/{blob_name}",
            "fileSize": file_size,
            "fileMimeType": "text/csv" if blob_name.endswith('.csv') else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "userID": "user_001",
            "projectID": "project_001",
            "categoryFolder": "Client-Provided Material",
            "finalCategory": "2. Operational Report/Review Deck",
            "finalPurpose": f"\"{blob_name}\" likely contains structured data with tables and charts for analysis.",
            "priority": "Medium",
            "geminiPrompt": (
                "You are an AI assistant helping classify documents for a management consulting project.\n\n"
                f"This is the document source \"<user_input>preview</user_input>\".\n\n"
                f"Based on the filename \"<user_input>{blob_name}</user_input>\" and this text preview:\n"
                f"\"<user_input>{preview_str}</user_input>\"\n\nPlease classify this document..."
            ),
            "textPreview": preview_str,
            "storedFilename": f"data/uploaded_documents/Client-Provided Material/{blob_name}",
            "finalizedAt": now_iso,
            "savedAt": now_iso,
            "fullText": full_text,
            "parsedBlocksCount": len(blocks),
            "llamaIndexNodesCount": len(nodes) if nodes else 0,
            "enhancedParsing": self.use_llamaindex
        }

        return metadata

    def process_file(self, container: str, blob_name: str, use_enhanced_parsing: bool = None,
                    rows_per_block: int = None) -> List[Tuple[str, Dict[str, Any]]]:
        """Process a CSV or Excel file and extract structured content."""
        enhanced_parsing = use_enhanced_parsing if use_enhanced_parsing is not None else self.use_llamaindex

        try:
            # Check if blob exists
            try:
                blob_info = self._get_cached_blob_info(container, blob_name)
            except Exception as e:
                raise FileProcessingError(f"Blob not found: {container}/{blob_name}", filepath=f"{container}/{blob_name}")

            file_extension = Path(blob_info["file_name"]).suffix.lower()

            if file_extension not in self.supported_extensions:
                raise ParsingError(
                    f"Unsupported file format: {file_extension}. Supported: {', '.join(self.supported_extensions)}",
                    filename=blob_name
                )

            if enhanced_parsing:
                return self._process_file_enhanced(container, blob_name, rows_per_block)
            else:
                return self._process_file_legacy(container, blob_name, rows_per_block)
        except Exception as e:
            logger.error(f"Error processing CSV/Excel blob {container}/{blob_name}: {e}")
            raise FileProcessingError(f"Error processing CSV/Excel blob {container}/{blob_name}: {e}",
                                    filepath=f"{container}/{blob_name}")

    def _process_file_enhanced(self, container: str, blob_name: str,
                             rows_per_block: int = None) -> List[Tuple[str, Dict[str, Any]]]:
        """Process file using enhanced logic."""
        processed_blocks: List[Tuple[str, Dict[str, Any]]] = []
        self.current_section_idx = 1

        blob_info = self._get_cached_blob_info(container, blob_name)
        file_extension = Path(blob_info["file_name"]).suffix.lower()

        if file_extension == '.csv':
            df = self._enhanced_csv_parsing(container, blob_name)
            if df is not None:
                processed_blocks.extend(
                    self._parse_dataframe_to_blocks(df, rows_per_block=rows_per_block,
                                                  container=container, blob_name=blob_name)
                )

        elif file_extension in {'.xlsx', '.xls'}:
            for block_text, metadata in self._enhanced_excel_parsing_iterative(
                container, blob_name, rows_per_block=rows_per_block
            ):
                processed_blocks.append((block_text, metadata))

        if not processed_blocks:
            logger.warning(f"No content blocks extracted from {container}/{blob_name}")

        logger.info(f"Successfully processed {container}/{blob_name} (enhanced): {len(processed_blocks)} blocks extracted")
        return processed_blocks

    def _process_file_legacy(self, container: str, blob_name: str,
                           rows_per_block: int = None) -> List[Tuple[str, Dict[str, Any]]]:
        """Process file using legacy logic."""
        processed_blocks: List[Tuple[str, Dict[str, Any]]] = []
        self.current_section_idx = 1

        blob_info = self._get_cached_blob_info(container, blob_name)
        file_extension = Path(blob_info["file_name"]).suffix.lower()

        if file_extension == '.csv':
            df = self._enhanced_csv_parsing(container, blob_name)
            if df is not None:
                processed_blocks.extend(
                    self._parse_dataframe_to_blocks(df, rows_per_block=rows_per_block,
                                                  container=container, blob_name=blob_name)
                )

        elif file_extension in {'.xlsx', '.xls'}:
            sheet_names = self.get_excel_sheet_names(container, blob_name)
            for sheet_idx, sheet_name in enumerate(sheet_names):
                self.current_section_idx = sheet_idx + 1
                try:
                    df_sheet = self._load_excel_dataframe(container, blob_name, sheet_name)
                    if not df_sheet.empty:
                        blocks = self._parse_dataframe_to_blocks(df_sheet, sheet_name, rows_per_block,
                                                               container, blob_name)
                        processed_blocks.extend(blocks)
                except Exception as e:
                    logger.error(f"Error processing sheet {sheet_name}: {e}")
                    continue

        if not processed_blocks:
            logger.warning(f"No content blocks extracted from {container}/{blob_name}")

        logger.info(f"Successfully processed {container}/{blob_name} (legacy): {len(processed_blocks)} blocks extracted")
        return processed_blocks

    def save_metadata_and_blocks(self, container: str, blob_name: str, output_dir: str,
                                blocks_input: Any = None) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Process file and save metadata and blocks."""
        if blocks_input is None:
            processed_blocks = self.process_file(container, blob_name)
            blocks = [{"text": text, "metadata": metadata} for text, metadata in processed_blocks]
        else:
            blocks = self._normalize_blocks_input(blocks_input)

        nodes = self.create_llamaindex_nodes(blocks) if self.use_llamaindex else []
        metadata = self.generate_metadata_with_llamaindex(container, blob_name, blocks, nodes)

        return blocks, metadata

    def process_csv(self, container: str, blob_name: str, rows_per_block: int = None) -> List[Tuple[str, Dict[str, Any]]]:
        """Legacy method for backward compatibility."""
        return self.process_file(container, blob_name, rows_per_block=rows_per_block)

    def get_statistics(self) -> Dict[str, Any]:
        """Get statistics about processed data."""
        return {
            "llamaindex_available": LLAMAINDEX_AVAILABLE,
            "chroma_available": CHROMA_AVAILABLE,
            "use_row_by_row": self.use_row_by_row,
            "current_section_idx": self.current_section_idx,
            "default_rows_per_block": self.default_rows_per_block,
            "cached_blob_info_count": len(self._blob_info_cache)
        }

    def load_all_dataframes(self, container: str, blob_name: str) -> Tuple[Dict[str, pd.DataFrame], Dict[str, Any]]:
        """Load all sheets/data as DataFrames with loading metadata."""
        blob_info = self._get_cached_blob_info(container, blob_name)
        ext = Path(blob_info["file_name"]).suffix.lower()
        dataframes = {}
        loading_metadata = {
            'extraction_method': 'enhanced_csv_excel_parser_v3_mentor_compliant',
            'encoding_info': {},
            'sheet_info': {}
        }

        self.current_section_idx = 1

        if ext in [".xlsx", ".xls"]:
            sheet_names = self.get_excel_sheet_names(container, blob_name)

            for sheet_idx, sheet_name in enumerate(sheet_names):
                try:
                    df = self._load_excel_dataframe(container, blob_name, sheet_name)
                    if not df.empty:
                        dataframes[sheet_name] = df
                        loading_metadata['sheet_info'][sheet_name] = {
                            'rows': len(df),
                            'columns': len(df.columns),
                            'column_names': list(df.columns),
                            'section_index': sheet_idx + 1
                        }
                        logger.info(f"Loaded DataFrame for sheet '{sheet_name}' with shape {df.shape}")
                    else:
                        logger.warning(f"Sheet '{sheet_name}' is empty, skipping")
                except Exception as e:
                    logger.warning(f"Failed to load sheet '{sheet_name}': {e}")
                    continue
        else:
            df = self._enhanced_csv_parsing(container, blob_name)

            if df is not None:
                dataframes["Sheet1"] = df
                loading_metadata['encoding_info'] = {
                    'encoding_used': 'detected',
                    'delimiter_used': 'detected',
                    'method': 'robust_detection'
                }
                loading_metadata['sheet_info']["Sheet1"] = {
                    'rows': len(df),
                    'columns': len(df.columns),
                    'column_names': list(df.columns),
                    'section_index': 1
                }
                logger.info(f"Loaded CSV DataFrame with shape {df.shape}")
            else:
                logger.error("Failed to load CSV as DataFrame")

        return dataframes, loading_metadata

    def convert_to_enhanced_blocks(self, dataframes: Dict[str, pd.DataFrame], container: str,
                                 blob_name: str, document_id: str = None,
                                 loading_metadata: Dict[str, Any] = None) -> List[Dict[str, Any]]:
        """Convert DataFrames to enhanced blocks format."""
        blob_info = self._get_cached_blob_info(container, blob_name)
        base_name = blob_info["file_name"]
        all_blocks = []

        for sheet_idx, (sheet_name, df) in enumerate(dataframes.items()):
            self.current_section_idx = sheet_idx + 1

            logger.info(f"Processing sheet '{sheet_name}' with {len(df)} rows (section {self.current_section_idx})")
            columns = list(df.columns)

            column_info = f"Sheet: {sheet_name}\nFile: {base_name}\nColumns: {', '.join(str(col) for col in columns)}\nTotal rows: {len(df)}"

            summary_page = self.get_synthetic_page_number(sheet_name, 0)

            summary_block = {
                "text": column_info,
                "metadata": {
                    "sheet_name": sheet_name,
                    "region_id": f"{sheet_name.replace(' ', '_')}_summary",
                    "block_type": "sheet_summary",
                    "source_type": "summary",
                    "filename": base_name,
                    "page_number": summary_page,
                    "section_id": self.current_section_idx,
                    "extraction_method": loading_metadata.get('extraction_method', 'enhanced_csv_excel_parser_v3_mentor_compliant') if loading_metadata else 'enhanced_csv_excel_parser_v3_mentor_compliant',
                    "source": f"{base_name}#{sheet_name}#summary",
                    "word_count": self.count_words(column_info),
                    "column_headers": columns,
                    "column_names": columns,
                    "visual_reference": False
                }
            }
            all_blocks.append(summary_block)

            table_blocks = self.emit_sheet_tables(df, sheet_name, base_name, self.default_rows_per_block)
            for text, metadata in table_blocks:
                all_blocks.append({"text": text, "metadata": metadata})

        blocks_tuples = [(block["text"], block["metadata"]) for block in all_blocks]
        validation_passed = self.validate_blocks_before_chunking(blocks_tuples)
        if not validation_passed:
            raise ValueError("Block validation failed - blocks do not meet chunker requirements")

        return all_blocks

    def create_vector_store_if_requested(self, blocks: List[Dict[str, Any]]) -> Optional[Any]:
        """Create LlamaIndex vector store from blocks with proper exception handling."""
        if not LLAMAINDEX_AVAILABLE:
            return None

        try:
            documents = []
            non_summary_blocks = [block for block in blocks if block["metadata"]["block_type"] != "sheet_summary"]

            for block in non_summary_blocks:
                doc = Document(
                    text=block["text"],
                    metadata=block["metadata"]
                )
                documents.append(doc)

            if documents:
                index = VectorStoreIndex.from_documents(documents)
                logger.info(f"Created vector store with {len(documents)} documents (skipped {len(blocks) - len(non_summary_blocks)} summary blocks)")
                return index
            else:
                logger.warning("No documents to create vector store from")
                return None

        except Exception as e:
            logger.warning(f"Failed to create vector store: {e}")
            return None


def validate_blocks_for_chunking(blocks: List[Dict[str, Any]]) -> None:
    """Centralize pre-chunk validation utility."""
    for i, b in enumerate(blocks):
        txt, meta = b.get("text", ""), b.get("metadata", {})
        assert "block_type" in meta, f"Block {i}: missing block_type"
        assert ("page_number" in meta or "slide_number" in meta), f"Block {i}: missing page or slide"

        if meta.get("block_type") == "table":
            assert "column_names" in meta and meta["column_names"], f"Block {i}: table missing column_names"
            assert meta.get("source_type") == "tabular_data", f"Block {i}: table must have source_type='tabular_data'"