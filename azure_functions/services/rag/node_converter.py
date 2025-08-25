import logging
import time
from typing import Optional, Dict, Any, List, Tuple, Union
from dataclasses import dataclass
from enum import Enum

from llama_index.core.schema import TextNode
from prometheus_client import Histogram, Counter
from giani_pkb.models.database_models import DocumentChunk

# Configure logging
logger = logging.getLogger(__name__)

# Prometheus metrics
NODE_CONVERSION_DURATION = Histogram(
    'node_conversion_duration_seconds',
    'Time spent converting chunks to nodes',
    ['conversion_type', 'document_type']
)

NODE_CONVERSION_FAILURES = Counter(
    'node_conversion_failures_total',
    'Number of node conversion failures by error type',
    ['error_type', 'conversion_type']
)

NODE_CONVERSION_SUCCESS = Counter(
    'node_conversion_success_total',
    'Number of successful node conversions',
    ['conversion_type', 'document_type']
)

NODE_TRUNCATIONS = Counter(
    'node_truncations_total',
    'Number of nodes that were truncated due to size limits',
    ['conversion_type', 'truncation_reason']
)

# Configuration constants
DEFAULT_MAX_TOKEN_LIMIT = 8000  # Configurable token limit
DEFAULT_MAX_CHAR_LIMIT = 32000  # Configurable character limit


class ConversionErrorType(Enum):
    MISSING_REQUIRED_FIELD = "missing_required_field"
    INVALID_METADATA = "invalid_metadata"
    EMBEDDING_ERROR = "embedding_error"
    TEXT_PROCESSING_ERROR = "text_processing_error"
    UNKNOWN_ERROR = "unknown_error"


@dataclass
class ConversionResult:
    """Result structure for node conversion operations."""
    success_count: int
    error_count: int
    truncated_count: int
    nodes: List[TextNode]
    errors: List[Dict[str, Any]]


def normalize_page_numbers(page_data: Union[int, List[int], str, None]) -> List[int]:
    """
    Normalize various page number formats to a consistent List[int] format.
    
    Args:
        page_data: Page number(s) in various formats:
            - int: Single page number
            - List[int]: Already normalized
            - str: Comma-separated page numbers or single number
            - None: No page information
            
    Returns:
        List[int]: Normalized page numbers, empty list if no valid pages
    """
    if page_data is None:
        return []
    
    # Already a list of integers
    if isinstance(page_data, list):
        # Filter out None values and ensure all are integers
        try:
            return [int(p) for p in page_data if p is not None]
        except (ValueError, TypeError):
            logger.warning(
                "Invalid page numbers in list, returning empty list",
                extra={"page_data": page_data}
            )
            return []
    
    # Single integer
    if isinstance(page_data, int):
        return [page_data] if page_data > 0 else []
    
    # String format - try to parse
    if isinstance(page_data, str):
        try:
            # Handle comma-separated values
            if ',' in page_data:
                pages = []
                for p in page_data.split(','):
                    p = p.strip()
                    if p and p.isdigit():
                        pages.append(int(p))
                return pages
            # Single number as string
            elif page_data.strip().isdigit():
                return [int(page_data.strip())]
            else:
                logger.warning(
                    "Unable to parse page numbers from string",
                    extra={"page_data": page_data}
                )
                return []
        except (ValueError, AttributeError):
            logger.warning(
                "Error parsing page numbers from string",
                extra={"page_data": page_data}
            )
            return []
    
    # Unsupported format
    logger.warning(
        "Unsupported page number format, returning empty list",
        extra={"page_data": page_data, "type": type(page_data)}
    )
    return []


def truncate_text_if_needed(
    text: str, 
    max_chars: int = DEFAULT_MAX_CHAR_LIMIT,
    max_tokens: int = DEFAULT_MAX_TOKEN_LIMIT
) -> Tuple[str, bool]:
    """
    Truncate text if it exceeds configured limits.
    
    Args:
        text: The text to potentially truncate
        max_chars: Maximum character limit
        max_tokens: Maximum token limit (rough estimation)
        
    Returns:
        Tuple of (processed_text, was_truncated)
    """
    if not text:
        return "", False
    
    was_truncated = False
    
    # Simple token estimation (rough approximation: 1 token ≈ 4 chars)
    estimated_tokens = len(text) // 4
    
    if len(text) > max_chars or estimated_tokens > max_tokens:
        # Truncate to character limit, but try to break at word boundaries
        if len(text) > max_chars:
            truncated_text = text[:max_chars]
            # Try to break at last complete word
            last_space = truncated_text.rfind(' ')
            if last_space > max_chars * 0.9:  # Only if we don't lose too much
                truncated_text = truncated_text[:last_space]
            text = truncated_text + "... [TRUNCATED]"
            was_truncated = True
        
        # Additional token-based truncation if needed
        estimated_tokens_after = len(text) // 4
        if estimated_tokens_after > max_tokens:
            char_limit_for_tokens = max_tokens * 4
            text = text[:char_limit_for_tokens] + "... [TRUNCATED]"
            was_truncated = True
    
    return text, was_truncated


def safe_extract_metadata(source: Any, field_name: str, default: Any = None) -> Any:
    """Safely extract metadata field with fallback."""
    try:
        if hasattr(source, field_name):
            return getattr(source, field_name)
        elif isinstance(source, dict):
            return source.get(field_name, default)
        return default
    except Exception:
        return default


def convert_chunk_to_node(
    chunk: DocumentChunk, 
    project_id: int,
    max_chars: int = DEFAULT_MAX_CHAR_LIMIT,
    max_tokens: int = DEFAULT_MAX_TOKEN_LIMIT
) -> Optional[TextNode]:
    """
    Convert a DocumentChunk ORM object to a LlamaIndex TextNode,
    injecting the known project_id explicitly.
    
    Args:
        chunk: DocumentChunk ORM object
        project_id: Project ID to inject
        max_chars: Maximum character limit for text content
        max_tokens: Maximum token limit for text content
        
    Returns:
        TextNode if successful, None if conversion failed
    """
    conversion_type = "orm_chunk"
    document_type = "unknown"
    start_time = time.time()
    
    try:
        # Extract document type for metrics
        document_type = safe_extract_metadata(
            getattr(chunk, 'document', None), 
            'final_category', 
            'unknown'
        ) or 'unknown'
        
        # Log conversion attempt
        logger.info(
            "Starting node conversion",
            extra={
                "stage": "NODE_CONVERSION",
                "conversion_type": conversion_type,
                "document_id": safe_extract_metadata(chunk, 'document_id'),
                "chunk_id": safe_extract_metadata(chunk, 'chunk_id'),
                "project_id": project_id,
                "document_type": document_type
            }
        )
        
        # Validate required fields
        chunk_text = safe_extract_metadata(chunk, 'chunk_text', '')
        chunk_id = safe_extract_metadata(chunk, 'chunk_id')
        
        if not chunk_text:
            raise ValueError("Missing or empty chunk_text")
        
        if chunk_id is None:
            raise ValueError("Missing chunk_id")
        
        # Process and potentially truncate text
        processed_text, was_truncated = truncate_text_if_needed(
            chunk_text, max_chars, max_tokens
        )
        
        if was_truncated:
            NODE_TRUNCATIONS.labels(
                conversion_type=conversion_type,
                truncation_reason="size_limit"
            ).inc()
            logger.warning(
                "Text content truncated due to size limits",
                extra={
                    "stage": "NODE_CONVERSION",
                    "chunk_id": chunk_id,
                    "original_length": len(chunk_text),
                    "truncated_length": len(processed_text)
                }
            )
        
        # Normalize page numbers - handle both old and new formats
        page_numbers = []
        
        # Try new format first (if processors already emit page_numbers)
        page_numbers_raw = safe_extract_metadata(chunk, 'page_numbers')
        if page_numbers_raw:
            page_numbers = normalize_page_numbers(page_numbers_raw)
        
        # Fallback to legacy source_page_number for backward compatibility
        if not page_numbers:
            source_page_number = safe_extract_metadata(chunk, 'source_page_number')
            page_numbers = normalize_page_numbers(source_page_number)
        
        # Build metadata safely
        metadata = {
            "chunk_id": chunk_id,
            "document_id": safe_extract_metadata(chunk, 'document_id'),
            "project_id": project_id,
            "document_type": document_type,
            "page_numbers": page_numbers,  # Normalized page numbers
            "same_table_group_id": safe_extract_metadata(chunk, 'same_table_group_id'),
            "structural_metadata": safe_extract_metadata(chunk, 'metadata_', {}),
            "created_at": str(safe_extract_metadata(chunk, 'created_at', '')),
        }
        
        # Handle embedding vector safely
        embedding_vector = None
        try:
            embedding_vector = safe_extract_metadata(chunk, 'embedding_vector')
        except Exception as e:
            logger.warning(
                "Failed to extract embedding vector",
                extra={
                    "stage": "NODE_CONVERSION",
                    "chunk_id": chunk_id,
                    "error": str(e)
                }
            )
            # Continue without embedding - don't fail the conversion
        
        # Create TextNode
        node = TextNode(
            text=processed_text,
            id_=str(chunk_id),
            metadata=metadata,
            embedding=embedding_vector
        )
        
        # Record success metrics
        NODE_CONVERSION_SUCCESS.labels(
            conversion_type=conversion_type,
            document_type=document_type
        ).inc()
        
        logger.info(
            "Node conversion successful",
            extra={
                "stage": "NODE_CONVERSION",
                "chunk_id": chunk_id,
                "text_length": len(processed_text),
                "was_truncated": was_truncated,
                "page_numbers": page_numbers
            }
        )
        
        return node
        
    except Exception as e:
        error_type = _classify_error(e)
        
        NODE_CONVERSION_FAILURES.labels(
            error_type=error_type.value,
            conversion_type=conversion_type
        ).inc()
        
        logger.error(
            "Node conversion failed",
            extra={
                "stage": "NODE_CONVERSION",
                "conversion_type": conversion_type,
                "document_id": safe_extract_metadata(chunk, 'document_id'),
                "chunk_id": safe_extract_metadata(chunk, 'chunk_id'),
                "project_id": project_id,
                "error_type": error_type.value,
                "error": str(e)
            },
            exc_info=True
        )
        
        return None
    
    finally:
        # Record duration metric
        duration = time.time() - start_time
        NODE_CONVERSION_DURATION.labels(
            conversion_type=conversion_type,
            document_type=document_type
        ).observe(duration)


def convert_dict_to_node(
    chunk_dict: dict,
    max_chars: int = DEFAULT_MAX_CHAR_LIMIT,
    max_tokens: int = DEFAULT_MAX_TOKEN_LIMIT
) -> Optional[TextNode]:
    """
    Convert a dictionary (from a JSON file) to a LlamaIndex TextNode.
    
    Args:
        chunk_dict: Dictionary containing chunk data
        max_chars: Maximum character limit for text content
        max_tokens: Maximum token limit for text content
        
    Returns:
        TextNode if successful, None if conversion failed
    """
    conversion_type = "dict_chunk"
    document_type = "unknown"
    start_time = time.time()
    
    try:
        # Extract metadata safely
        meta = chunk_dict.get("metadata", {})
        chunk_id = meta.get("chunk_id")
        document_id = meta.get("document_id")
        
        # Determine document type for metrics
        document_type = meta.get("document_type", "unknown")
        
        # Log conversion attempt
        logger.info(
            "Starting dict node conversion",
            extra={
                "stage": "NODE_CONVERSION",
                "conversion_type": conversion_type,
                "document_id": document_id,
                "chunk_id": chunk_id,
                "document_type": document_type
            }
        )
        
        # Validate required fields
        chunk_text = chunk_dict.get("text_chunk", "")
        
        if not chunk_text:
            raise ValueError("Missing or empty text_chunk")
        
        if chunk_id is None:
            raise ValueError("Missing chunk_id in metadata")
        
        # Process and potentially truncate text
        processed_text, was_truncated = truncate_text_if_needed(
            chunk_text, max_chars, max_tokens
        )
        
        if was_truncated:
            NODE_TRUNCATIONS.labels(
                conversion_type=conversion_type,
                truncation_reason="size_limit"
            ).inc()
            logger.warning(
                "Dict text content truncated due to size limits",
                extra={
                    "stage": "NODE_CONVERSION",
                    "chunk_id": chunk_id,
                    "original_length": len(chunk_text),
                    "truncated_length": len(processed_text)
                }
            )
        
        # Normalize page numbers - handle multiple possible sources
        page_numbers = []
        
        # Try the normalized page_numbers field first
        if "page_numbers" in meta:
            page_numbers = normalize_page_numbers(meta["page_numbers"])
        
        # Fallback to legacy source_page_numbers (note the 's')
        elif "source_page_numbers" in meta:
            page_numbers = normalize_page_numbers(meta["source_page_numbers"])
        
        # Fallback to legacy source_page_number (singular)
        elif "source_page_number" in meta:
            page_numbers = normalize_page_numbers(meta["source_page_number"])
        
        # Handle slide_number for PPTX files (add to page_numbers)
        slide_number = meta.get("slide_number")
        if slide_number is not None and not page_numbers:
            slide_pages = normalize_page_numbers(slide_number)
            page_numbers.extend(slide_pages)
        
        # Build metadata safely
        node_metadata = {
            "chunk_id": chunk_id,
            "document_id": document_id,
            "project_id": meta.get("project_id"),
            "page_numbers": page_numbers,  # Normalized page numbers
            "slide_number": meta.get("slide_number"),  # Keep for backward compatibility
            "chunk_type": meta.get("chunk_type"),
            "same_table_group_id": meta.get("same_table_group_id"),  # Keep intact for table grouping
            "structural_metadata": meta.get("structural_metadata", {})
        }
        
        # Handle embedding vector safely
        embedding_vector = None
        try:
            embedding_vector = chunk_dict.get("embedding_vector")
        except Exception as e:
            logger.warning(
                "Failed to extract embedding vector from dict",
                extra={
                    "stage": "NODE_CONVERSION",
                    "chunk_id": chunk_id,
                    "error": str(e)
                }
            )
            # Continue without embedding - don't fail the conversion
        
        # Create TextNode
        node = TextNode(
            text=processed_text,
            id_=str(chunk_id),
            metadata=node_metadata,
            embedding=embedding_vector
        )
        
        # Record success metrics
        NODE_CONVERSION_SUCCESS.labels(
            conversion_type=conversion_type,
            document_type=document_type
        ).inc()
        
        logger.info(
            "Dict node conversion successful",
            extra={
                "stage": "NODE_CONVERSION",
                "chunk_id": chunk_id,
                "text_length": len(processed_text),
                "was_truncated": was_truncated,
                "page_numbers": page_numbers
            }
        )
        
        return node
        
    except Exception as e:
        error_type = _classify_error(e)
        
        NODE_CONVERSION_FAILURES.labels(
            error_type=error_type.value,
            conversion_type=conversion_type
        ).inc()
        
        chunk_id = chunk_dict.get("metadata", {}).get("chunk_id", "unknown")
        document_id = chunk_dict.get("metadata", {}).get("document_id", "unknown")
        
        logger.error(
            "Dict node conversion failed",
            extra={
                "stage": "NODE_CONVERSION",
                "conversion_type": conversion_type,
                "document_id": document_id,
                "chunk_id": chunk_id,
                "error_type": error_type.value,
                "error": str(e)
            },
            exc_info=True
        )
        
        return None
    
    finally:
        # Record duration metric
        duration = time.time() - start_time
        NODE_CONVERSION_DURATION.labels(
            conversion_type=conversion_type,
            document_type=document_type
        ).observe(duration)


def batch_convert_chunks_to_nodes(
    chunks: List[DocumentChunk],
    project_id: int,
    max_chars: int = DEFAULT_MAX_CHAR_LIMIT,
    max_tokens: int = DEFAULT_MAX_TOKEN_LIMIT
) -> ConversionResult:
    """
    Convert multiple DocumentChunk objects to TextNodes with comprehensive error handling.
    
    Args:
        chunks: List of DocumentChunk objects to convert
        project_id: Project ID to inject
        max_chars: Maximum character limit for text content
        max_tokens: Maximum token limit for text content
        
    Returns:
        ConversionResult with success/error counts and converted nodes
    """
    nodes = []
    errors = []
    success_count = 0
    error_count = 0
    truncated_count = 0
    
    logger.info(
        "Starting batch node conversion",
        extra={
            "stage": "NODE_CONVERSION",
            "total_chunks": len(chunks),
            "project_id": project_id
        }
    )
    
    for i, chunk in enumerate(chunks):
        try:
            node = convert_chunk_to_node(chunk, project_id, max_chars, max_tokens)
            if node:
                nodes.append(node)
                success_count += 1
                # Check if this node was truncated (rough check)
                if "[TRUNCATED]" in node.text:
                    truncated_count += 1
            else:
                error_count += 1
                errors.append({
                    "index": i,
                    "chunk_id": safe_extract_metadata(chunk, 'chunk_id'),
                    "error": "Conversion returned None"
                })
        except Exception as e:
            error_count += 1
            errors.append({
                "index": i,
                "chunk_id": safe_extract_metadata(chunk, 'chunk_id'),
                "error": str(e)
            })
            logger.error(
                "Unexpected error in batch conversion",
                extra={
                    "stage": "NODE_CONVERSION",
                    "chunk_index": i,
                    "error": str(e)
                },
                exc_info=True
            )
    
    logger.info(
        "Batch node conversion completed",
        extra={
            "stage": "NODE_CONVERSION",
            "success_count": success_count,
            "error_count": error_count,
            "truncated_count": truncated_count,
            "total_processed": len(chunks)
        }
    )
    
    return ConversionResult(
        success_count=success_count,
        error_count=error_count,
        truncated_count=truncated_count,
        nodes=nodes,
        errors=errors
    )


def batch_convert_dicts_to_nodes(
    chunk_dicts: List[dict],
    max_chars: int = DEFAULT_MAX_CHAR_LIMIT,
    max_tokens: int = DEFAULT_MAX_TOKEN_LIMIT
) -> ConversionResult:
    """
    Convert multiple dictionary chunks to TextNodes with comprehensive error handling.
    
    Args:
        chunk_dicts: List of dictionary objects to convert
        max_chars: Maximum character limit for text content
        max_tokens: Maximum token limit for text content
        
    Returns:
        ConversionResult with success/error counts and converted nodes
    """
    nodes = []
    errors = []
    success_count = 0
    error_count = 0
    truncated_count = 0
    
    logger.info(
        "Starting batch dict node conversion",
        extra={
            "stage": "NODE_CONVERSION",
            "total_chunks": len(chunk_dicts)
        }
    )
    
    for i, chunk_dict in enumerate(chunk_dicts):
        try:
            node = convert_dict_to_node(chunk_dict, max_chars, max_tokens)
            if node:
                nodes.append(node)
                success_count += 1
                # Check if this node was truncated (rough check)
                if "[TRUNCATED]" in node.text:
                    truncated_count += 1
            else:
                error_count += 1
                chunk_id = chunk_dict.get("metadata", {}).get("chunk_id", "unknown")
                errors.append({
                    "index": i,
                    "chunk_id": chunk_id,
                    "error": "Conversion returned None"
                })
        except Exception as e:
            error_count += 1
            chunk_id = chunk_dict.get("metadata", {}).get("chunk_id", "unknown")
            errors.append({
                "index": i,
                "chunk_id": chunk_id,
                "error": str(e)
            })
            logger.error(
                "Unexpected error in batch dict conversion",
                extra={
                    "stage": "NODE_CONVERSION",
                    "chunk_index": i,
                    "error": str(e)
                },
                exc_info=True
            )
    
    logger.info(
        "Batch dict node conversion completed",
        extra={
            "stage": "NODE_CONVERSION",
            "success_count": success_count,
            "error_count": error_count,
            "truncated_count": truncated_count,
            "total_processed": len(chunk_dicts)
        }
    )
    
    return ConversionResult(
        success_count=success_count,
        error_count=error_count,
        truncated_count=truncated_count,
        nodes=nodes,
        errors=errors
    )


def _classify_error(error: Exception) -> ConversionErrorType:
    """Classify error types for metrics."""
    error_str = str(error).lower()
    
    if "missing" in error_str or "required" in error_str or "none" in error_str:
        return ConversionErrorType.MISSING_REQUIRED_FIELD
    elif "metadata" in error_str:
        return ConversionErrorType.INVALID_METADATA
    elif "embedding" in error_str:
        return ConversionErrorType.EMBEDDING_ERROR
    elif "text" in error_str or "truncat" in error_str:
        return ConversionErrorType.TEXT_PROCESSING_ERROR
    else:
        return ConversionErrorType.UNKNOWN_ERROR