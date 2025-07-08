"""
Document chunking strategies for different document types.
"""
import logging
from typing import List, Dict, Any, Optional, Tuple
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_experimental.text_splitter import SemanticChunker
from langchain_openai import OpenAIEmbeddings

from giani_pkb.preprocessing.chunking.models import ChunkMetadata
from giani_pkb.preprocessing.chunking.token_counter import TokenCounter
from giani_pkb.preprocessing.chunking.nlp_processor import NLPProcessor

logger = logging.getLogger(__name__)

# Initialize global instances
token_counter = TokenCounter()
nlp_processor = NLPProcessor()

def _create_chunk_metadata(
    document_id: str,
    project_id: str,
    source_blocks_metadata: List[Dict[str, Any]],
    chunk_type_str: str,
    current_heading_info: Optional[Dict[str, Any]] = None
) -> ChunkMetadata:
    """Helper to create ChunkMetadata, aggregating page numbers and structural info."""
    try:
        page_numbers = sorted(list(set(
            meta.get("page_number") for meta in source_blocks_metadata if meta and meta.get("page_number") is not None
        )))

        struct_meta = {"source_block_types": []}
        if source_blocks_metadata and isinstance(source_blocks_metadata, list):
            # Filter out None or non-dict items from source_blocks_metadata
            valid_source_metas = [m for m in source_blocks_metadata if isinstance(m, dict)]
            struct_meta["source_block_types"] = [meta.get("block_type", "unknown") for meta in valid_source_metas]

            if valid_source_metas:
                first_block_meta = valid_source_metas[0]
                struct_meta["primary_block_type"] = first_block_meta.get("block_type", "unknown")
                if "bbox" in first_block_meta: struct_meta["primary_block_bbox"] = first_block_meta.get("bbox")
                if "style_name" in first_block_meta: struct_meta["style_name"] = first_block_meta.get("style_name")
                if "sheet_name" in first_block_meta:
                     struct_meta["sheet_name"] = first_block_meta.get("sheet_name")
                     struct_meta["row_numbers"] = first_block_meta.get("row_numbers")
                     struct_meta["column_names"] = first_block_meta.get("column_names")

        if current_heading_info and isinstance(current_heading_info, dict):
            struct_meta["current_heading_text"] = current_heading_info.get("text")
            struct_meta["current_heading_level"] = current_heading_info.get("level")
            struct_meta["current_heading_source"] = current_heading_info.get("source")

        return ChunkMetadata(
            document_id=document_id,
            project_id=project_id,
            source_page_numbers=page_numbers,
            structural_metadata=struct_meta,
            chunk_type=chunk_type_str
        )
    except Exception as e:
        logger.error(f"Error creating chunk metadata for doc {document_id}, type {chunk_type_str}: {e}", exc_info=True)
        return ChunkMetadata( # Return a minimal valid object
            document_id=document_id, project_id=project_id, chunk_id=str(uuid.uuid4()),
            source_page_numbers=[], structural_metadata={"error": "metadata_creation_failed"},
            chunk_type=chunk_type_str if chunk_type_str else "unknown_error_chunk"
        )

def chunk_formal_document(
    parsed_blocks: List[Tuple[str, Dict[str, Any]]],
    document_id: str,
    project_id: str,
    max_tokens: int = 1000,         # Tuning: Max tokens for a chunk.
    min_chunk_tokens: int = 100,    # Tuning: Min tokens for a chunk before trying to merge.
    overlap_tokens: int = 100       # Tuning: Token overlap between chunks.
) -> List[Tuple[str, ChunkMetadata]]:
    """
    Chunk formal documents (reports, papers, etc.) with heading-aware splitting.
    """
    chunks = []
    current_chunk_text = ""
    current_blocks_metadata = []
    current_heading_info = None

    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=max_tokens,
        chunk_overlap=overlap_tokens,
        length_function=token_counter.count_tokens,
        separators=["\n\n", "\n", ". ", " ", ""]
    )

    for block_text, block_metadata in parsed_blocks:
        # Detect headings in this block
        headings = nlp_processor.detect_headings_in_block(block_text, block_metadata)

        if headings:
            # If we have accumulated content, create a chunk
            if current_chunk_text.strip():
                chunk_metadata = _create_chunk_metadata(
                    document_id, project_id, current_blocks_metadata, "prose", current_heading_info
                )
                chunks.append((current_chunk_text.strip(), chunk_metadata))

            # Start new chunk with the heading
            current_chunk_text = block_text
            current_blocks_metadata = [block_metadata]
            current_heading_info = {
                "text": headings[0][0],
                "level": headings[0][3].get("level", 1),
                "source": headings[0][3].get("source", "unknown")
            }
        else:
            # Regular content block
            current_chunk_text += "\n\n" + block_text if current_chunk_text else block_text
            current_blocks_metadata.append(block_metadata)

            # Check if current chunk is getting too large
            if token_counter.count_tokens(current_chunk_text) > max_tokens:
                # Split the current chunk
                sub_chunks = text_splitter.split_text(current_chunk_text)
                for i, sub_chunk in enumerate(sub_chunks):
                    if token_counter.count_tokens(sub_chunk) >= min_chunk_tokens:
                        chunk_metadata = _create_chunk_metadata(
                            document_id, project_id, current_blocks_metadata, "prose", current_heading_info
                        )
                        chunks.append((sub_chunk.strip(), chunk_metadata))

                # Reset for next chunk
                current_chunk_text = ""
                current_blocks_metadata = []
                current_heading_info = None

    # Handle remaining content
    if current_chunk_text.strip():
        chunk_metadata = _create_chunk_metadata(
            document_id, project_id, current_blocks_metadata, "prose", current_heading_info
        )
        chunks.append((current_chunk_text.strip(), chunk_metadata))

    return chunks

def chunk_conversational_record(
    parsed_blocks: List[Tuple[str, Dict[str, Any]]],
    document_id: str,
    project_id: str,
    max_tokens: int = 300,          # Tuning: Max tokens for a conversational turn/chunk.
    overlap_tokens: int = 50        # Tuning: Overlap for conversational chunks if split.
) -> List[Tuple[str, ChunkMetadata]]:
    """
    Chunk conversational records (transcripts, chat logs, etc.) by speaker turns.
    """
    chunks = []
    current_chunk_text = ""
    current_blocks_metadata = []
    current_speaker = None

    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=max_tokens,
        chunk_overlap=overlap_tokens,
        length_function=token_counter.count_tokens,
        separators=["\n", ". ", " ", ""]
    )

    for block_text, block_metadata in parsed_blocks:
        # Detect speakers in this block
        speakers = nlp_processor.detect_speakers(block_text)

        if speakers:
            # If we have accumulated content, create a chunk
            if current_chunk_text.strip():
                chunk_metadata = _create_chunk_metadata(
                    document_id, project_id, current_blocks_metadata, "dialogue_turn"
                )
                chunk_metadata.speaker_attribution = current_speaker
                chunks.append((current_chunk_text.strip(), chunk_metadata))

            # Start new chunk with the speaker turn
            current_chunk_text = block_text
            current_blocks_metadata = [block_metadata]
            current_speaker = speakers[0][0] if speakers else None
        else:
            # Continue current speaker's content
            current_chunk_text += "\n" + block_text if current_chunk_text else block_text
            current_blocks_metadata.append(block_metadata)

            # Check if current chunk is getting too large
            if token_counter.count_tokens(current_chunk_text) > max_tokens:
                # Split the current chunk
                sub_chunks = text_splitter.split_text(current_chunk_text)
                for sub_chunk in sub_chunks:
                    if token_counter.count_tokens(sub_chunk) >= 50:  # Min tokens for dialogue
                        chunk_metadata = _create_chunk_metadata(
                            document_id, project_id, current_blocks_metadata, "dialogue_turn"
                        )
                        chunk_metadata.speaker_attribution = current_speaker
                        chunks.append((sub_chunk.strip(), chunk_metadata))

                # Reset for next chunk
                current_chunk_text = ""
                current_blocks_metadata = []
                current_speaker = None

    # Handle remaining content
    if current_chunk_text.strip():
        chunk_metadata = _create_chunk_metadata(
            document_id, project_id, current_blocks_metadata, "dialogue_turn"
        )
        chunk_metadata.speaker_attribution = current_speaker
        chunks.append((current_chunk_text.strip(), chunk_metadata))

    return chunks

def chunk_data_heavy_document(
    parsed_blocks: List[Tuple[str, Dict[str, Any]]],
    document_id: str,
    project_id: str,
    max_tokens_table: int = 1500,   # Tuning: Max tokens for a table chunk/fragment.
    max_tokens_prose: int = 1000,   # Tuning: Max tokens for prose sections within data-heavy docs.
    min_chunk_tokens: int = 50      # Tuning: Min tokens for prose chunks.
) -> List[Tuple[str, ChunkMetadata]]:
    """
    Chunk data-heavy documents (spreadsheets, reports with tables, etc.) with table-aware splitting.
    """
    chunks = []
    current_prose_text = ""
    current_prose_metadata = []

    for block_text, block_metadata in parsed_blocks:
        block_type = block_metadata.get("block_type", "unknown")

        if "table" in block_type.lower():
            # Handle table blocks separately
            if current_prose_text.strip():
                # Create chunk for accumulated prose
                chunk_metadata = _create_chunk_metadata(
                    document_id, project_id, current_prose_metadata, "prose"
                )
                chunks.append((current_prose_text.strip(), chunk_metadata))
                current_prose_text = ""
                current_prose_metadata = []

            # Create table chunk
            table_chunk_metadata = _create_chunk_metadata(
                document_id, project_id, [block_metadata], "table"
            )
            chunks.append((block_text, table_chunk_metadata))

        else:
            # Handle prose blocks
            current_prose_text += "\n\n" + block_text if current_prose_text else block_text
            current_prose_metadata.append(block_metadata)

            # Check if prose chunk is getting too large
            if token_counter.count_tokens(current_prose_text) > max_tokens_prose:
                # Split prose chunk
                text_splitter = RecursiveCharacterTextSplitter(
                    chunk_size=max_tokens_prose,
                    chunk_overlap=100,
                    length_function=token_counter.count_tokens,
                    separators=["\n\n", "\n", ". ", " ", ""]
                )

                sub_chunks = text_splitter.split_text(current_prose_text)
                for sub_chunk in sub_chunks:
                    if token_counter.count_tokens(sub_chunk) >= min_chunk_tokens:
                        chunk_metadata = _create_chunk_metadata(
                            document_id, project_id, current_prose_metadata, "prose"
                        )
                        chunks.append((sub_chunk.strip(), chunk_metadata))

                current_prose_text = ""
                current_prose_metadata = []

    # Handle remaining prose content
    if current_prose_text.strip():
        chunk_metadata = _create_chunk_metadata(
            document_id, project_id, current_prose_metadata, "prose"
        )
        chunks.append((current_prose_text.strip(), chunk_metadata))

    return chunks

def chunk_document_semantic(
    parsed_blocks: List[Tuple[str, Dict[str, Any]]],
    document_id: str,
    project_id: str,
    embeddings_model_instance: Any,
    breakpoint_threshold_type: str ="percentile", # Tuning: "percentile", "standard_deviation", "interquartile"
                                                 # Also consider SemanticChunker's internal thresholds if accessible/tunable.
    **kwargs
) -> List[Tuple[str, ChunkMetadata]]:
    """
    Chunk documents using semantic similarity for breakpoint detection.
    """
    try:
        # Combine all blocks into a single text
        full_text = "\n\n".join([block[0] for block in parsed_blocks])
        all_metadata = [block[1] for block in parsed_blocks]

        # Create semantic chunker
        semantic_chunker = SemanticChunker(
            embeddings=embeddings_model_instance,
            breakpoint_threshold_type=breakpoint_threshold_type,
            **kwargs
        )

        # Split text semantically
        semantic_chunks = semantic_chunker.split_text(full_text)

        chunks = []
        for chunk_text in semantic_chunks:
            if chunk_text.strip():
                chunk_metadata = _create_chunk_metadata(
                    document_id, project_id, all_metadata, "semantic"
                )
                chunks.append((chunk_text.strip(), chunk_metadata))

        return chunks

    except Exception as e:
        logger.error(f"Error in semantic chunking: {e}")
        # Fallback to basic chunking
        return chunk_formal_document(parsed_blocks, document_id, project_id)

def chunk_document_adaptive(
    parsed_blocks: List[Tuple[str, Dict[str, Any]]],
    document_id: str,
    project_id: str,
    document_type: str = "formal",
    use_semantic_chunker: bool = False,
    openai_api_key: Optional[str] = None, # Allow passing API key directly
    # **kwargs can be used to pass tuning parameters like max_tokens, min_chunk_tokens, overlap_tokens,
    # breakpoint_threshold_type, etc., to the underlying specific chunking functions.
    # Example: chunk_document_adaptive(..., max_tokens=800, overlap_tokens=50)
    **kwargs
) -> List[Tuple[str, ChunkMetadata]]:
    """
    Adaptive chunking that chooses the best strategy based on document type and content.
    """
    if use_semantic_chunker:
        try:
            # Initialize OpenAI embeddings for semantic chunking
            embeddings = OpenAIEmbeddings(openai_api_key=openai_api_key)
            return chunk_document_semantic(parsed_blocks, document_id, project_id, embeddings, **kwargs)
        except Exception as e:
            logger.warning(f"Semantic chunking failed, falling back to type-based chunking: {e}")

    # Type-based chunking
    if document_type == "conversational":
        return chunk_conversational_record(parsed_blocks, document_id, project_id, **kwargs)
    elif document_type == "data_heavy":
        return chunk_data_heavy_document(parsed_blocks, document_id, project_id, **kwargs)
    else:  # Default to formal document chunking
        return chunk_formal_document(parsed_blocks, document_id, project_id, **kwargs)