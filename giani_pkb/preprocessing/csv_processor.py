"""
CSV and Excel file processor for extracting structured data and images with LlamaIndex integration.
"""
import pandas as pd
import openpyxl
from typing import List, Dict, Any, Tuple, Optional, Iterator
import logging
from pathlib import Path

# LlamaIndex imports
try:
    from llama_index.core import Document, VectorStoreIndex, Settings
    from llama_index.core.node_parser import SimpleNodeParser
    from llama_index.core.schema import BaseNode, TextNode
    from llama_index.core.storage.storage_context import StorageContext
    
    # Try different import patterns for embeddings and LLMs
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
    
    # Try different import patterns for vector stores
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
    logger.warning(f"LlamaIndex not available: {e}")
    LLAMAINDEX_AVAILABLE = False
    CHROMA_AVAILABLE = False
    Document = None
    VectorStoreIndex = None
    Settings = None
    SimpleNodeParser = None
    BaseNode = None
    TextNode = None
    StorageContext = None
    OpenAIEmbedding = None
    OpenAI = None
    ChromaVectorStore = None
    chromadb = None

from giani_pkb.utils.exceptions import ParsingError, FileProcessingError

logger = logging.getLogger(__name__)

class CSVProcessor:
    """
    Processor for CSV and Excel files that extracts structured data and images with LlamaIndex integration.

    Features:
    - Multi-encoding CSV support with delimiter detection
    - Excel data extraction with image processing
    - Memory-efficient processing for large files
    - Row-by-row processing option (new approach)
    - Structured output with metadata
    - LlamaIndex integration for advanced indexing and querying
    """

    def __init__(self, api_key: Optional[str] = None, use_row_by_row: bool = True, 
                 openai_api_key: Optional[str] = None, chroma_path: Optional[str] = "./chroma_db"):
        """
        Initialize the CSV processor with LlamaIndex integration.

        Args:
            api_key: Optional API key for image processing (if needed)
            use_row_by_row: Whether to use new row-by-row processing (default: True)
            openai_api_key: OpenAI API key for embeddings and LLM
            chroma_path: Path to ChromaDB storage
        """
        self.api_key = api_key
        self.image_processor = self._get_image_processor()
        self.use_row_by_row = use_row_by_row
        self.openai_api_key = openai_api_key
        self.chroma_path = chroma_path

        # Configuration
        self.default_rows_per_block = 10
        self.supported_csv_encodings = ['utf-8', 'ISO-8859-1', 'latin-1', 'cp1252', 'iso-8859-1']
        self.supported_csv_delimiters = [',', ';', '\t', '|']
        self.supported_extensions = {'.csv', '.xlsx', '.xls'}

        # Initialize LlamaIndex components
        self._setup_llamaindex()
        
        # Storage for processed documents and indices
        self.documents: List[Document] = []
        self.vector_index: Optional[VectorStoreIndex] = None
        self.nodes: List[BaseNode] = []

    def _setup_llamaindex(self):
        """Setup LlamaIndex components."""
        if not LLAMAINDEX_AVAILABLE:
            logger.warning("LlamaIndex not available. Advanced indexing features will be disabled.")
            self.chroma_client = None
            self.node_parser = None
            return
            
        try:
            # Configure LlamaIndex settings
            if self.openai_api_key and OpenAI and OpenAIEmbedding:
                Settings.llm = OpenAI(api_key=self.openai_api_key, model="gpt-3.5-turbo")
                Settings.embed_model = OpenAIEmbedding(api_key=self.openai_api_key)
            
            # Initialize ChromaDB if available
            if CHROMA_AVAILABLE and chromadb:
                self.chroma_client = chromadb.PersistentClient(path=self.chroma_path)
            else:
                self.chroma_client = None
                logger.warning("ChromaDB not available. Using in-memory vector storage.")
            
            # Initialize node parser
            if SimpleNodeParser:
                self.node_parser = SimpleNodeParser.from_defaults(
                    chunk_size=1024,
                    chunk_overlap=20
                )
            else:
                self.node_parser = None
            
            logger.info("LlamaIndex components initialized successfully")
            
        except Exception as e:
            logger.warning(f"Failed to initialize LlamaIndex components: {e}")
            self.chroma_client = None
            self.node_parser = None

    def _get_image_processor(self):
        """Get image processor if available."""
        try:
            from giani_pkb.preprocessing.image_processor import ImageProcessor
            return ImageProcessor()
        except ImportError:
            logger.warning("Image processor not available. Image extraction will be skipped.")
            return None

    def _get_mime_type(self, file_path: str) -> str:
        """
        Get MIME type for file (new approach).
        
        Args:
            file_path: Path to file
            
        Returns:
            MIME type string
        """
        ext = Path(file_path).suffix.lower()
        if ext == ".csv":
            return "text/csv"
        elif ext in [".xlsx", ".xls"]:
            return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        else:
            return "application/octet-stream"

    def _create_llamaindex_document(self, text: str, metadata: Dict[str, Any]) -> Optional[Document]:
        """
        Create a LlamaIndex Document from text and metadata.
        
        Args:
            text: Text content
            metadata: Metadata dictionary
            
        Returns:
            LlamaIndex Document or None if LlamaIndex not available
        """
        if not LLAMAINDEX_AVAILABLE or not Document:
            return None
            
        # Clean metadata for LlamaIndex compatibility
        clean_metadata = {}
        for key, value in metadata.items():
            if isinstance(value, (str, int, float, bool)):
                clean_metadata[key] = value
            elif isinstance(value, list):
                clean_metadata[key] = str(value)
            else:
                clean_metadata[key] = str(value)
        
        return Document(
            text=text,
            metadata=clean_metadata
        )

    def _create_vector_index(self, collection_name: str = "csv_excel_data") -> Optional[VectorStoreIndex]:
        """
        Create a vector index from processed documents.
        
        Args:
            collection_name: Name for the ChromaDB collection
            
        Returns:
            VectorStoreIndex or None if not available
        """
        if not LLAMAINDEX_AVAILABLE or not VectorStoreIndex or not self.documents:
            logger.warning("Cannot create vector index: LlamaIndex not available or no documents")
            return None
            
        try:
            if self.chroma_client and ChromaVectorStore and StorageContext:
                # Create ChromaDB collection
                chroma_collection = self.chroma_client.get_or_create_collection(collection_name)
                vector_store = ChromaVectorStore(chroma_collection=chroma_collection)
                storage_context = StorageContext.from_defaults(vector_store=vector_store)
                
                # Create index
                index = VectorStoreIndex.from_documents(
                    self.documents,
                    storage_context=storage_context
                )
            else:
                # Fallback to in-memory index
                index = VectorStoreIndex.from_documents(self.documents)
            
            logger.info(f"Created vector index with {len(self.documents)} documents")
            return index
            
        except Exception as e:
            logger.error(f"Error creating vector index: {e}")
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
                        result = self.image_processor.process_bytes(image_data)
                        image_text = result['combined_text']

                        if image_text and image_text.strip():
                            metadata = {
                                "page_number": None,
                                "block_type": "image_text",
                                "source_type": "image",
                                "sheet_name": sheet_name,
                                "image_index_on_sheet": img_idx,
                                "image_size": result.get('image_size'),
                                "file_type": "excel_image"
                            }
                            image_blocks.append((image_text.strip(), metadata))

                    except Exception as e:
                        logger.error(f"Error processing image {img_idx} in sheet {sheet_name}: {e}")

        except Exception as e:
            logger.error(f"Error accessing images in sheet {sheet_name}: {e}")

        return image_blocks

    def _convert_to_row_blocks(self, df: pd.DataFrame, sheet_name: Optional[str] = None, file_path: str = None) -> List[Tuple[str, Dict[str, Any]]]:
        """
        Convert DataFrame to row-by-row blocks (new approach).
        
        Args:
            df: Pandas DataFrame
            sheet_name: Sheet name for Excel files
            file_path: Original file path
            
        Returns:
            List of (text_block, metadata) tuples
        """
        blocks = []
        base_name = Path(file_path).name if file_path else "unknown"
        
        for idx, row in df.iterrows():
            # Join non-null cells with " | " (new approach)
            row_text = " | ".join(str(cell) for cell in row.values if pd.notna(cell)).strip()
            
            if row_text:
                metadata = {
                    "page_number": idx + 1,
                    "block_type": "table_row",
                    "source_type": "tabular_data",
                    "sheet_name": sheet_name,
                    "row_number": idx + 1,
                    "column_names": df.columns.tolist(),
                    "total_rows": len(df),
                    "source": f"{base_name}#row={idx + 1}",
                    "file_type": "excel" if sheet_name else "csv"
                }
                blocks.append((row_text, metadata))
        
        return blocks

    def _parse_dataframe_to_blocks(self, df: pd.DataFrame, sheet_name: Optional[str] = None,
                                 rows_per_block: int = None, file_path: str = None) -> List[Tuple[str, Dict[str, Any]]]:
        """
        Convert a pandas DataFrame into structured text blocks.

        Args:
            df: Pandas DataFrame to process
            sheet_name: Name of the sheet (for Excel files)
            rows_per_block: Number of rows to group together
            file_path: Original file path

        Returns:
            List of (text_block, metadata) tuples
        """
        if df.empty:
            return []

        # Clean the DataFrame
        df = self._clean_dataframe(df)

        # Use new row-by-row approach if enabled
        if self.use_row_by_row:
            return self._convert_to_row_blocks(df, sheet_name, file_path)

        # Use old grouped approach
        if rows_per_block is None:
            rows_per_block = self.default_rows_per_block

        blocks: List[Tuple[str, Dict[str, Any]]] = []

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

        # Convert all values to strings for consistent processing (but preserve NaN for filtering)
        # Don't convert to string here to preserve NaN detection in row processing
        return df

    def _enhanced_csv_parsing(self, path: str) -> Optional[pd.DataFrame]:
        """
        Enhanced CSV parsing with multiple encoding and delimiter support (integrated approach).

        Args:
            path: Path to CSV file

        Returns:
            Parsed DataFrame or None if parsing fails
        """
        try:
            # Try new approach first with multiple encodings and delimiters
            for encoding in self.supported_csv_encodings:
                for delimiter in self.supported_csv_delimiters:
                    try:
                        df = pd.read_csv(
                            path,
                            encoding=encoding,
                            delimiter=delimiter,
                            low_memory=False,
                            skipinitialspace=True,
                            on_bad_lines='skip'
                        )
                        
                        # Validate that we got reasonable data
                        if not df.empty and len(df.columns) > 1:
                            logger.info(f"Successfully parsed CSV with {encoding} encoding and '{delimiter}' delimiter")
                            return df
                        
                    except (UnicodeDecodeError, pd.errors.EmptyDataError):
                        continue
                    except Exception as e:
                        logger.debug(f"Error with {encoding} encoding and '{delimiter}' delimiter: {e}")
                        continue

            # Fallback to original approach
            for encoding in self.supported_csv_encodings:
                try:
                    df = pd.read_csv(
                        path,
                        encoding=encoding,
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

            logger.error(f"Could not read CSV file {path} with any supported encoding or delimiter")
            return None

        except Exception as e:
            logger.error(f"Error parsing CSV file {path}: {e}")
            return None

    def _load_excel_dataframe(self, path: str, sheet_name: str = None) -> pd.DataFrame:
        """
        Load Excel file with enhanced error handling (new approach).
        
        Args:
            path: Path to Excel file
            sheet_name: Specific sheet name to load
            
        Returns:
            Loaded DataFrame
        """
        try:
            if sheet_name:
                df = pd.read_excel(path, sheet_name=sheet_name, header=0, na_values=['', 'nan', 'NaN'])
            else:
                df = pd.read_excel(path, header=0, na_values=['', 'nan', 'NaN'])
            
            logger.info(f"Successfully loaded Excel sheet: {sheet_name or 'default'}")
            return df
            
        except Exception as e:
            logger.error(f"Error loading Excel sheet {sheet_name}: {e}")
            raise

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
                    # Parse data rows using new approach
                    df_sheet = self._load_excel_dataframe(path, sheet_name)

                    if not df_sheet.empty:
                        for block_text, metadata in self._parse_dataframe_to_blocks(
                            df_sheet, sheet_name, rows_per_block, path
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

    def process_file(self, path: str, rows_per_block: int = None, create_index: bool = True) -> List[Tuple[str, Dict[str, Any]]]:
        """
        Process a CSV or Excel file and extract structured content with LlamaIndex integration.

        Args:
            path: Path to the file to process
            rows_per_block: Number of rows to group together (ignored if use_row_by_row=True)
            create_index: Whether to create a vector index from processed data

        Returns:
            List of (text_block, metadata) tuples

        Raises:
            ParsingError: If file format is not supported
            FileProcessingError: If processing fails
        """
        path_obj = Path(path)

        if not path_obj.exists():
            raise FileProcessingError(f"File not found: {path}", filepath=str(path))

        if path_obj.suffix.lower() not in self.supported_extensions:
            raise ParsingError(
                f"Unsupported file format: {path_obj.suffix}. Supported: {', '.join(self.supported_extensions)}",
                filename=str(path)
            )

        processed_blocks: List[Tuple[str, Dict[str, Any]]] = []

        try:
            if path_obj.suffix.lower() == '.csv':
                df = self._enhanced_csv_parsing(str(path))
                if df is not None:
                    processed_blocks.extend(
                        self._parse_dataframe_to_blocks(df, rows_per_block=rows_per_block, file_path=path)
                    )

            elif path_obj.suffix.lower() in {'.xlsx', '.xls'}:
                for block_text, metadata in self._enhanced_excel_parsing_iterative(
                    str(path), rows_per_block=rows_per_block
                ):
                    processed_blocks.append((block_text, metadata))

            if not processed_blocks:
                logger.warning(f"No content blocks extracted from {path}")

            # Create LlamaIndex documents
            if create_index and processed_blocks and LLAMAINDEX_AVAILABLE:
                for text_block, metadata in processed_blocks:
                    document = self._create_llamaindex_document(text_block, metadata)
                    if document:
                        self.documents.append(document)

                # Create vector index
                if self.documents:
                    self.vector_index = self._create_vector_index()

            logger.info(f"Successfully processed {path}: {len(processed_blocks)} blocks extracted")
            return processed_blocks

        except (ParsingError, FileProcessingError):
            raise
        except Exception as e:
            logger.error(f"Unexpected error processing file {path}: {e}")
            raise FileProcessingError(f"Error processing file {path}: {e}", filepath=str(path))

    def query_data(self, query: str, top_k: int = 5) -> str:
        """
        Query the processed data using LlamaIndex.
        
        Args:
            query: Natural language query
            top_k: Number of top results to return
            
        Returns:
            Query response
        """
        if not LLAMAINDEX_AVAILABLE:
            return "LlamaIndex not available. Cannot perform semantic queries."
            
        if not self.vector_index:
            return "No index available. Please process files first with create_index=True."
        
        try:
            query_engine = self.vector_index.as_query_engine(similarity_top_k=top_k)
            response = query_engine.query(query)
            return str(response)
        except Exception as e:
            logger.error(f"Error querying data: {e}")
            return f"Error occurred while querying: {e}"

    def get_similar_documents(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """
        Get similar documents based on query.
        
        Args:
            query: Query text
            top_k: Number of similar documents to return
            
        Returns:
            List of similar documents with metadata
        """
        if not LLAMAINDEX_AVAILABLE:
            logger.warning("LlamaIndex not available. Cannot perform similarity search.")
            return []
            
        if not self.vector_index:
            logger.warning("No index available for similarity search.")
            return []
        
        try:
            retriever = self.vector_index.as_retriever(similarity_top_k=top_k)
            nodes = retriever.retrieve(query)
            
            results = []
            for node in nodes:
                results.append({
                    "text": node.text,
                    "metadata": node.metadata,
                    "score": node.score if hasattr(node, 'score') else None
                })
            
            return results
        except Exception as e:
            logger.error(f"Error retrieving similar documents: {e}")
            return []

    def save_index(self, persist_dir: str = "./storage"):
        """
        Save the vector index to disk.
        
        Args:
            persist_dir: Directory to save the index
        """
        if not LLAMAINDEX_AVAILABLE:
            logger.warning("LlamaIndex not available. Cannot save index.")
            return
            
        if not self.vector_index:
            logger.warning("No index to save")
            return
        
        try:
            self.vector_index.storage_context.persist(persist_dir=persist_dir)
            logger.info(f"Index saved to {persist_dir}")
        except Exception as e:
            logger.error(f"Error saving index: {e}")

    def load_index(self, persist_dir: str = "./storage", collection_name: str = "csv_excel_data"):
        """
        Load a previously saved vector index.
        
        Args:
            persist_dir: Directory containing the saved index
            collection_name: ChromaDB collection name
        """
        if not LLAMAINDEX_AVAILABLE:
            logger.warning("LlamaIndex not available. Cannot load index.")
            return
            
        try:
            if self.chroma_client and ChromaVectorStore and StorageContext:
                chroma_collection = self.chroma_client.get_or_create_collection(collection_name)
                vector_store = ChromaVectorStore(chroma_collection=chroma_collection)
                storage_context = StorageContext.from_defaults(
                    vector_store=vector_store,
                    persist_dir=persist_dir
                )
                self.vector_index = VectorStoreIndex.from_vector_store(
                    vector_store,
                    storage_context=storage_context
                )
            else:
                storage_context = StorageContext.from_defaults(persist_dir=persist_dir)
                self.vector_index = VectorStoreIndex.from_storage_context(storage_context)
            
            logger.info(f"Index loaded from {persist_dir}")
        except Exception as e:
            logger.error(f"Error loading index: {e}")

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

    def get_statistics(self) -> Dict[str, Any]:
        """
        Get statistics about processed data.
        
        Returns:
            Dictionary with statistics
        """
        stats = {
            "total_documents": len(self.documents),
            "total_nodes": len(self.nodes),
            "has_vector_index": self.vector_index is not None,
            "chroma_available": CHROMA_AVAILABLE,
            "llamaindex_available": LLAMAINDEX_AVAILABLE
        }
        
        if self.documents:
            # Calculate some basic stats
            total_chars = sum(len(doc.text) for doc in self.documents)
            stats.update({
                "total_characters": total_chars,
                "average_document_length": total_chars / len(self.documents),
                "document_types": list(set(doc.metadata.get("file_type", "unknown") 
                                         for doc in self.documents))
            })
        
        return stats