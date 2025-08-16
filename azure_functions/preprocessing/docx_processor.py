"""
DOCX file processor for extracting structured content, tables, and images.
Enhanced with LlamaIndex integration for better parsing and node creation.
"""
import os
import docx
import zipfile
import io
import json
import uuid
import mimetypes
from typing import List, Dict, Any, Tuple, Optional
import logging
from pathlib import Path
from datetime import datetime
from PIL import Image

logger = logging.getLogger(__name__)

# LlamaIndex imports
try:
    from llama_index.core.node_parser import SimpleNodeParser
    from llama_index.core.schema import Document as LlamaDocument
    LLAMAINDEX_AVAILABLE = True
except ImportError:
    LLAMAINDEX_AVAILABLE = False
    logger.warning("LlamaIndex not available. Enhanced parsing features will be disabled.")

from services.blob_storage_service import blob_storage_service
from utils.exceptions import ParsingError, FileProcessingError

class DocxProcessor:
    """
    Processor for DOCX files that extracts structured content, tables, and images.
    Enhanced with LlamaIndex integration for better parsing and node creation.

    Features:
    - Text extraction with style-based block classification
    - Table conversion to Markdown format
    - Image extraction and processing
    - Structured output with metadata
    - LlamaIndex integration for enhanced document parsing
    - Node creation and document processing
    """

    def __init__(self, api_key: Optional[str] = None, use_llamaindex: bool = True):
        """
        Initialize the DOCX processor.

        Args:
            api_key: Optional API key for image processing (if needed)
            use_llamaindex: Whether to use LlamaIndex for enhanced parsing
        """
        self.api_key = api_key
        self.use_llamaindex = use_llamaindex and LLAMAINDEX_AVAILABLE
        self.image_processor = self._get_image_processor()

        # Configuration
        self.supported_extensions = {'.docx'}

        # Style mapping for better block classification
        self.style_mapping = {
            'heading 1': 'heading_1',
            'heading 2': 'heading_2',
            'heading 3': 'heading_3',
            'heading 4': 'heading_4',
            'heading 5': 'heading_5',
            'heading 6': 'heading_6',
            'list paragraph': 'list_item',
            'caption': 'caption',
            'quote': 'quote',
            'title': 'title',
            'subtitle': 'subtitle'
        }

        # Initialize LlamaIndex parser if available
        if self.use_llamaindex:
            self.node_parser = SimpleNodeParser.from_defaults()

    def _get_image_processor(self):
        """Get image processor if available."""
        try:
            from preprocessing.image_processor import ImageProcessor
            return ImageProcessor()
        except ImportError:
            logger.warning("Image processor not available. Image extraction will be skipped.")
            return None

    def _get_paragraph_style_type(self, paragraph: docx.text.paragraph.Paragraph) -> str:
        """
        Determine block type based on paragraph style.

        Args:
            paragraph: DOCX paragraph object

        Returns:
            Block type string
        """
        style_name = paragraph.style.name.lower()

        # Check for list items by content
        if paragraph.text.strip().startswith(("* ", "- ", "• ", "1. ", "2. ")):
            return "list_item"

        # Check style mapping
        for style_key, block_type in self.style_mapping.items():
            if style_key in style_name:
                return block_type

        # Check for generic headings
        if 'heading' in style_name:
            return "heading"

        return "paragraph"

    def _table_to_markdown(self, table: docx.table.Table) -> str:
        """
        Convert a DOCX table to Markdown format using enhanced logic.

        Args:
            table: DOCX table object

        Returns:
            Markdown table string
        """
        if not table.rows:
            return ""

        try:
            # Use the new enhanced table conversion logic
            rows = [[cell.text.strip() for cell in row.cells] for row in table.rows]
            if not rows:
                return ""

            header = rows[0]
            separator = ["---"] * len(header)
            body = rows[1:]

            markdown = "| " + " | ".join(header) + " |\n"
            markdown += "| " + " | ".join(separator) + " |\n"

            for row in body:
                # Ensure row has same length as header
                padded_row = row + [""] * (len(header) - len(row))
                markdown += "| " + " | ".join(padded_row[:len(header)]) + " |\n"

            return markdown.strip()

        except Exception as e:
            logger.error(f"Error converting table to markdown: {e}")
            # Fallback: simple text extraction
            return self._table_to_simple_text(table)

    def _table_to_simple_text(self, table: docx.table.Table) -> str:
        """
        Convert table to simple text format as fallback.

        Args:
            table: DOCX table object

        Returns:
            Simple text representation
        """
        text_lines = []
        for row in table.rows:
            row_texts = []
            for cell in row.cells:
                cell_text = cell.text.strip()
                if cell_text:
                    row_texts.append(cell_text)
            if row_texts:
                text_lines.append(" | ".join(row_texts))

        return "\n".join(text_lines)

    def _extract_image_info_enhanced(self, doc: docx.Document) -> List[Dict[str, Any]]:
        """
        Extract enhanced image information using the new logic.

        Args:
            doc: DOCX document object

        Returns:
            List of image info dictionaries
        """
        image_info = []
        try:
            rels = doc.part.rels
            count = 0
            for rel in rels.values():
                if "image" in rel.reltype:
                    count += 1
                    try:
                        img_blob = rel.target_part.blob
                        try:
                            img = Image.open(io.BytesIO(img_blob))
                            width, height = img.size
                            format_type = img.format or "Unknown"
                            mode = img.mode
                            img_description = f"[IMAGE {count}: {format_type} image, {width}x{height} pixels, {mode} mode]"
                        except Exception as e:
                            img_description = f"[IMAGE {count}: Unable to analyze image - {str(e)}]"

                        image_info.append({
                            "index": count,
                            "description": img_description,
                            "size": len(img_blob),
                            "blob": img_blob if self.image_processor else None
                        })
                    except Exception as e:
                        image_info.append({
                            "index": count,
                            "description": f"[IMAGE {count}: Error processing image - {str(e)}]",
                            "size": 0,
                            "blob": None
                        })
        except Exception as e:
            logger.error(f"Error extracting image info: {e}")

        return image_info

    def _extract_images_from_docx(self, container: str, blob_name) -> List[Tuple[str, Dict[str, Any]]]:
        """
        Extract images from DOCX file and process them.

        Args:

        Returns:
            List of (image_text, metadata) tuples
        """
        if not self.image_processor:
            return []

        image_blocks: List[Tuple[str, Dict[str, Any]]] = []

        try:
            media_files = blob_storage_service.list_docx_media_files(container, blob_name)

            for media_file in media_files:
                    try:
                        image_bytes = docx_zip.read(media_file.filename)
                        image_text = self.image_processor.process_image_bytes(image_bytes)

                        if image_text and image_text.strip():
                            metadata = {
                                "page_number": None,
                                "block_type": "image_text",
                                "source_type": "image",
                                "image_filename": os.path.basename(media_file.filename),
                                "file_type": "docx_image"
                            }
                            image_blocks.append((image_text.strip(), metadata))

                    except Exception as e:
                        logger.error(f"Error processing image {media_file.filename}: {e}")

        except Exception as e:
            logger.error(f"Error extracting images from DOCX {blob_name}: {e}")

        return image_blocks

    def _parse_docx_to_blocks_enhanced(self, container: str, blob_name: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Parse DOCX to blocks using the enhanced LlamaIndex logic.

        Args:
            container: Name of the blob container
            blob_name: Blob name

        Returns:
            Tuple of (blocks, image_info)
        """
        doc = blob_storage_service.get_docx_document(container, blob_name)
        blocks = []

        # Extract image information
        image_info_list = self._extract_image_info_enhanced(doc)

        # Create element mappings
        table_elements = {tbl._element: tbl for tbl in doc.tables}
        para_elements = {p._element: p for p in doc.paragraphs}

        img_counter = 0
        element_order = 0

        for element in doc.element.body:
            element_order += 1

            if element in table_elements:
                table = table_elements[element]
                markdown_table = self._table_to_markdown(table)
                if markdown_table:
                    blocks.append({
                        "type": "table",
                        "text": markdown_table,
                        "element_order": element_order,
                        "num_rows": len(table.rows),
                        "num_cols": len(table.columns) if table.rows else 0
                    })

            elif element in para_elements:
                para = para_elements[element]
                text = para.text.strip()
                if text:
                    blocks.append({
                        "type": "text",
                        "text": text,
                        "element_order": element_order,
                        "style_name": para.style.name,
                        "block_type": self._get_paragraph_style_type(para)
                    })

            elif element.tag.endswith("drawing"):
                if img_counter < len(image_info_list):
                    img_info = image_info_list[img_counter]
                    blocks.append({
                        "type": "image_reference",
                        "text": img_info["description"],
                        "element_order": element_order,
                        "image_size": img_info["size"],
                        "image_index": img_info["index"]
                    })
                    img_counter += 1

        # Add any leftover images
        while img_counter < len(image_info_list):
            element_order += 1
            img_info = image_info_list[img_counter]
            blocks.append({
                "type": "image_reference",
                "text": img_info["description"],
                "element_order": element_order,
                "image_size": img_info["size"],
                "image_index": img_info["index"]
            })
            img_counter += 1

        return blocks, image_info_list

    def _process_paragraph(self, paragraph: docx.text.paragraph.Paragraph, element_order: int) -> Optional[Tuple[str, Dict[str, Any]]]:
        """
        Process a single paragraph and return structured data.

        Args:
            paragraph: DOCX paragraph object
            element_order: Order of element in document

        Returns:
            (text, metadata) tuple or None if paragraph is empty
        """
        para_text = paragraph.text.strip()
        if not para_text:
            return None

        metadata = {
            "page_number": None,
            "block_type": self._get_paragraph_style_type(paragraph),
            "source_type": "text",
            "style_name": paragraph.style.name,
            "doc_element_order": element_order,
            "file_type": "docx"
        }

        return (para_text, metadata)

    def _process_table(self, table: docx.table.Table, element_order: int) -> Optional[Tuple[str, Dict[str, Any]]]:
        """
        Process a single table and return structured data.

        Args:
            table: DOCX table object
            element_order: Order of element in document

        Returns:
            (text, metadata) tuple or None if table is empty
        """
        if not table.rows:
            return None

        table_text = self._table_to_markdown(table)
        if not table_text.strip():
            return None

        metadata = {
            "page_number": None,
            "block_type": "table",
            "source_type": "table",
            "num_rows": len(table.rows),
            "num_cols": len(table.columns),
            "doc_element_order": element_order,
            "file_type": "docx"
        }

        return (table_text, metadata)

    def create_llamaindex_nodes(self, blocks: List[Dict[str, Any]]) -> List[Any]:
        """
        Create LlamaIndex nodes from parsed blocks.

        Args:
            blocks: List of parsed blocks

        Returns:
            List of LlamaIndex nodes
        """
        if not self.use_llamaindex:
            logger.warning("LlamaIndex not available or disabled")
            return []

        try:
            # Convert blocks to LlamaIndex Documents
            documents = [LlamaDocument(text=block["text"]) for block in blocks]

            # Parse documents into nodes
            nodes = self.node_parser.get_nodes_from_documents(documents)

            return nodes
        except Exception as e:
            logger.error(f"Error creating LlamaIndex nodes: {e}")
            return []

    def _normalize_blocks_input(self, blocks_input: Any) -> List[Dict[str, Any]]:
        """
        Normalize different types of blocks input to standard format.

        Args:
            blocks_input: Could be list of dicts, ProcessingResult, or other formats

        Returns:
            List of standardized block dictionaries
        """
        normalized_blocks = []

        if not blocks_input:
            return normalized_blocks

        # Handle list input
        if isinstance(blocks_input, list):
            for item in blocks_input:
                if isinstance(item, dict) and 'text' in item:
                    normalized_blocks.append(item)
                elif isinstance(item, str):
                    normalized_blocks.append({"text": item, "type": "text"})
                elif hasattr(item, 'text'):  # Object with text attribute
                    normalized_blocks.append({
                        "text": str(item.text),
                        "type": getattr(item, 'type', 'text')
                    })

        # Handle single object input
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

        # Handle ProcessingResult or similar objects
        elif hasattr(blocks_input, 'chunks_preview'):
            try:
                # Extract from chunks_preview if available
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
        """
        Generate comprehensive metadata using LlamaIndex integration.

        Args:
            blocks: Parsed blocks (can be various formats)
            nodes: Optional LlamaIndex nodes

        Returns:
            Comprehensive metadata dictionary
        """
        document_id = str(uuid.uuid4())
        now_iso = datetime.now().isoformat()

        # Normalize blocks input to standard format
        actual_blocks = self._normalize_blocks_input(blocks)

        # Create preview from nodes or blocks
        preview_entries = []

        # Generate preview from nodes first (preferred)
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

        # Fallback to blocks if no valid nodes
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

        # Final fallback - create a basic preview
        if not preview_entries:
            preview_entries = [{
                "snippet": "Document content available - preview generation failed",
                "node_id": str(uuid.uuid4()),
                "type": "prose"
            }]

        preview_str = json.dumps(preview_entries, ensure_ascii=False, indent=2)

        # Generate full text
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

        # File information
        file_info = blob_storage_service.get_blob_info({container, blob_name})
        file_size = file_info["size_human"]
        mime_type = "" # TODO

        metadata = {
            "document_id": document_id,
            "dateAddedToGiani": now_iso,
            "originalFilename": file_info["file_name"],
            "storagePath": file_info["blob_name"],
            "fileSize": file_size,
            "fileMimeType": mime_type or "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "userID": "user_001",
            "projectID": "project_001",
            "categoryFolder": "Client-Provided Material",
            "finalCategory": "2. Operational Report/Review Deck",
            "finalPurpose": f"\"{blob_name}\" likely contains operational insights or structured data, including tables and embedded images, meant for review or reporting.",
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

    def process_file(self, container: str, blob_name: str, use_enhanced_parsing: bool = None) -> List[Tuple[str, Dict[str, Any]]]:
        """
        Process a DOCX file and extract structured content.

        Args:
            use_enhanced_parsing: Override for using enhanced parsing

        Returns:
            List of (text_block, metadata) tuples

        Raises:
            ParsingError: If file format is not supported
            FileProcessingError: If processing fails
        """

        # Determine parsing method
        enhanced_parsing = use_enhanced_parsing if use_enhanced_parsing is not None else self.use_llamaindex

        try:
            if enhanced_parsing:
                return self._process_file_enhanced(container, blob_name)
            else:
                return self._process_file_legacy(container, blob_name)
        except Exception as e:
            logger.error(f"Error processing DOCX file {blob_name}: {e}")
            raise FileProcessingError(f"Error processing DOCX file {blob_name}: {e}", filepath=str(blob_name))

    def _process_file_enhanced(self, container: str, blob_name) -> List[Tuple[str, Dict[str, Any]]]:
        """
        Process file using enhanced LlamaIndex logic.

        Args:

        Returns:
            List of (text_block, metadata) tuples
        """
        processed_blocks: List[Tuple[str, Dict[str, Any]]] = []

        # Parse using enhanced logic
        blocks, image_info = self._parse_docx_to_blocks_enhanced(container, blob_name)

        # Convert blocks to the expected format
        for block in blocks:
            metadata = {
                "page_number": None,
                "block_type": block.get("block_type", block["type"]),
                "source_type": "table" if block["type"] == "table" else "text",
                "doc_element_order": block.get("element_order", 0),
                "file_type": "docx"
            }

            # Add type-specific metadata
            if block["type"] == "table":
                metadata.update({
                    "num_rows": block.get("num_rows"),
                    "num_cols": block.get("num_cols")
                })
            elif block["type"] == "text":
                metadata.update({
                    "style_name": block.get("style_name", "Normal")
                })
            elif block["type"] == "image_reference":
                metadata.update({
                    "source_type": "image",
                    "image_size": block.get("image_size"),
                    "image_index": block.get("image_index")
                })

            processed_blocks.append((block["text"], metadata))

        # Process actual images if image processor is available
        if self.image_processor:
            image_blocks = self._extract_images_from_docx(container, blob_name)
            for i, (img_text, img_metadata) in enumerate(image_blocks):
                img_metadata["doc_element_order"] = len(processed_blocks) + 1 + i
                processed_blocks.append((img_text, img_metadata))

        if not processed_blocks:
            logger.warning(f"No content blocks extracted from {blob_name}")

        logger.info(f"Successfully processed {blob_name} (enhanced): {len(processed_blocks)} blocks extracted")
        return processed_blocks

    def _process_file_legacy(self, container: str, blob_name: str) -> List[Tuple[str, Dict[str, Any]]]:
        """
        Process file using legacy logic.

        Args:

        Returns:
            List of (text_block, metadata) tuples
        """
        processed_blocks: List[Tuple[str, Dict[str, Any]]] = []
        element_order = 0

        # Load document
        document = blob_storage_service.get_docx_document(container, blob_name)

        # Process document elements in order
        for element in document.element.body:
            element_order += 1

            # Process paragraphs
            if isinstance(element, docx.oxml.text.paragraph.CT_P):
                paragraph = docx.text.paragraph.Paragraph(element, document)
                result = self._process_paragraph(paragraph, element_order)
                if result:
                    processed_blocks.append(result)

            # Process tables
            elif isinstance(element, docx.oxml.table.CT_Tbl):
                table = docx.table.Table(element, document)
                result = self._process_table(table, element_order)
                if result:
                    processed_blocks.append(result)

        # Extract and process images
        image_blocks = self._extract_images_from_docx(container, blob_name)
        for i, (img_text, img_metadata) in enumerate(image_blocks):
            img_metadata["doc_element_order"] = element_order + 1 + i
            processed_blocks.append((img_text, img_metadata))

        if not processed_blocks:
            logger.warning(f"No content blocks extracted from {blob_name}")

        logger.info(f"Successfully processed {blob_name} (legacy): {len(processed_blocks)} blocks extracted")
        return processed_blocks

    def save_metadata_and_blocks(self, container: str, blob_name: str, output_dir: str,
                                blocks_input: Any = None) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        Process file and save metadata and blocks (similar to new code functionality).

        Args:
            output_dir: Output directory for saved files
            blocks_input: Optional pre-parsed blocks (can handle various formats)

        Returns:
            Tuple of (blocks, metadata)
        """
        # Parse using enhanced logic if blocks not provided
        if blocks_input is None:
            blocks, image_info = self._parse_docx_to_blocks_enhanced(container, blob_name)
        else:
            # Use provided blocks and normalize them
            blocks = self._normalize_blocks_input(blocks_input)
            image_info = []

        # Create LlamaIndex nodes if available
        nodes = self.create_llamaindex_nodes(blocks) if self.use_llamaindex else []

        # Generate comprehensive metadata
        metadata = self.generate_metadata_with_llamaindex(container, blob_name, blocks, nodes)

        # Save metadata JSON
        # blob_storage_service.upload_file(container, f"{blob_name}/metadata.json", metadata) # TODO: Do we need to save the metadata to blob storage

        # Save parsed blocks JSON
        # blob_storage_service.upload_file(container, f"{blob_name}/parsed_blocks.json", blocks) # TODO: Do we need to save parsed JOSN blocks to blob storage

        return blocks, metadata

    def process_docx(self, container: str, blob_name: str) -> List[Tuple[str, Dict[str, Any]]]:
        """
        Legacy method for backward compatibility.

        Args:

        Returns:
            List of (text_block, metadata) tuples
        """
        return self.process_file(container, blob_name)