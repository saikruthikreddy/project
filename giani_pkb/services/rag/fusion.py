"""
Enhanced query orchestration fusion module.

This module implements the fan-in stage for merging results from multiple subqueries
before synthesis. It provides reciprocal rank fusion, deduplication, derived chunk
expansion, and context packing functionality with improved error handling and telemetry.
"""

import logging
from typing import Dict, List, Any, Callable, Optional, Set, Tuple, Union
from collections import defaultdict
import math
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)


@dataclass
class FusionStats:
    """Statistics from the fusion pipeline execution."""
    total_input_chunks: int = 0
    chunks_after_fusion: int = 0
    chunks_after_dedup: int = 0
    duplicates_removed: int = 0
    derived_chunks_found: int = 0
    source_chunks_fetched: int = 0
    chunks_after_expansion: int = 0
    final_chunks_packed: int = 0
    total_tokens_used: int = 0
    token_budget: int = 0
    errors: List[str] = None
    
    def __post_init__(self):
        if self.errors is None:
            self.errors = []
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging/telemetry."""
        return asdict(self)


def rrf_fuse(
    results: List[List[Any]], 
    intent_weights: Optional[Dict[str, float]] = None, 
    k: int = 60,
    stats: Optional[FusionStats] = None
) -> List[Dict[str, Any]]:
    """
    Implement Reciprocal Rank Fusion (RRF) to merge multiple ranked result lists.
    CRITICAL FIX: Properly handles NodeWithScore objects and preserves all data.
    """
    if stats is None:
        stats = FusionStats()
    
    total_input = sum(len(r) for r in results)
    stats.total_input_chunks = total_input
    
    logger.info(f"Starting RRF fusion with {len(results)} result lists, k={k}, total_chunks={total_input}")
    
    try:
        if not results:
            logger.warning("No results provided for fusion")
            return []
        
        results = [r for r in results if r]
        if not results:
            logger.warning("All result lists are empty")
            return []
        
        if intent_weights is None:
            intent_weights = {str(i): 1.0 for i in range(len(results))}
        
        doc_scores: Dict[str, float] = defaultdict(float)
        doc_metadata: Dict[str, Dict[str, Any]] = {}
        
        for list_idx, result_list in enumerate(results):
            for rank, node_or_dict in enumerate(result_list):
                # CRITICAL: Extract data properly from NodeWithScore or dict
                doc = _extract_node_data(node_or_dict)
                
                weight_key = doc.get('query_intent', str(list_idx))
                list_weight = intent_weights.get(weight_key, intent_weights.get(str(list_idx), 1.0))
                
                doc_id = _get_document_identifier(doc)
                if not doc_id:
                    logger.warning(f"Could not generate document ID for doc in list {list_idx}, rank {rank}")
                    continue
                
                rrf_score = list_weight / (k + rank + 1)
                doc_scores[doc_id] += rrf_score
                
                # CRITICAL FIX: Store normalized document data with better text handling
                text_value = doc.get("text") or doc.get("text_chunk") or doc.get("content")
                if not text_value or not str(text_value).strip():
                    # fallback more aggressively
                    text_value = doc.get("text_chunk") or doc.get("content") or ""

                normalized = {
                    "id": doc.get("id") or doc.get("chunk_id") or doc_id,
                    "chunk_id": doc.get("chunk_id") or doc.get("id") or doc_id,
                    "text": text_value,
                    "text_chunk": text_value,
                    "metadata": doc.get("metadata") if doc.get("metadata") is not None else {},
                    "rrf_score": rrf_score
                }
                
                # CRITICAL: Smart document preservation logic
                existing = doc_metadata.get(doc_id)
                if not existing:
                    doc_metadata[doc_id] = normalized
                else:
                    # Keep whichever version has richer text
                    existing_text = existing.get("text") or ""
                    new_text = normalized.get("text") or ""
                    if (len(new_text.strip()) > len(existing_text.strip())):
                        doc_metadata[doc_id] = normalized
                    else:
                        # Merge metadata if new one has extra keys
                        merged_meta = {**existing.get("metadata", {}), **normalized.get("metadata", {})}
                        existing["metadata"] = merged_meta
                        doc_metadata[doc_id] = existing
            
            logger.debug(f"Processed list {list_idx}: {len(result_list)} items, weight={list_weight}")
        
        # Sort documents by their combined RRF scores
        sorted_docs = sorted(doc_scores.items(), key=lambda x: x[1], reverse=True)
        
        fused_results = []
        for doc_id, score in sorted_docs:
            if doc_id in doc_metadata:
                doc_copy = doc_metadata[doc_id].copy()
                doc_copy['rrf_score'] = score  # Update with final combined score
                
                # Ensure we have the essential fields - validation
                if not doc_copy.get('text') and not doc_copy.get('text_chunk'):
                    logger.warning(f"Document {doc_id} has no text content after fusion")
                
                fused_results.append(doc_copy)
            else:
                logger.error(f"CRITICAL: Metadata not found for doc_id {doc_id} despite being in scores!")
                continue
        
        stats.chunks_after_fusion = len(fused_results)
        logger.info(f"RRF fusion complete. Input: {total_input} docs, Output: {len(fused_results)} docs")
        return fused_results
        
    except Exception as e:
        error_msg = f"RRF fusion failed: {str(e)}"
        logger.error(error_msg, exc_info=True)
        stats.errors.append(error_msg)
        return []


def dedupe(
    results: List[Dict[str, Any]], 
    stats: Optional[FusionStats] = None
) -> List[Dict[str, Any]]:
    """
    Remove duplicates based on normalized document identifiers.
    """
    if stats is None:
        stats = FusionStats()
    
    logger.info(f"Starting deduplication on {len(results)} results")
    
    try:
        seen_keys: Set[Tuple] = set()
        deduplicated = []
        
        for doc in results:
            dedup_key = _get_deduplication_key(doc)
            
            if dedup_key not in seen_keys:
                seen_keys.add(dedup_key)
                deduplicated.append(doc)
            else:
                logger.debug(f"Duplicate found and removed: {dedup_key}")
        
        duplicates_removed = len(results) - len(deduplicated)
        stats.chunks_after_dedup = len(deduplicated)
        stats.duplicates_removed = duplicates_removed
        
        logger.info(f"Deduplication complete. Removed {duplicates_removed} duplicates")
        return deduplicated
        
    except Exception as e:
        error_msg = f"Deduplication failed: {str(e)}"
        logger.error(error_msg, exc_info=True)
        stats.errors.append(error_msg)
        return results


def expand_derived(
    results: List[Dict[str, Any]], 
    fetch_sources_by_ids: Callable[[List[str]], List[Dict[str, Any]]],
    stats: Optional[FusionStats] = None
) -> List[Dict[str, Any]]:
    """
    Expand derived chunks by fetching their source chunks.
    """
    if stats is None:
        stats = FusionStats()
    
    logger.info(f"Starting derived chunk expansion on {len(results)} results")
    
    try:
        expanded_results = []
        source_ids_to_fetch = []
        derived_chunks = []
        
        for doc in results:
            if doc.get('metadata', {}).get('chunk_type') == 'derived' and doc.get('metadata', {}).get('source_chunk_ids'):
                derived_chunks.append(doc)
                source_ids = doc['metadata']['source_chunk_ids']
                if isinstance(source_ids, str):
                    source_ids = [source_ids]
                source_ids_to_fetch.extend(source_ids)
            else:
                expanded_results.append(doc)
        
        stats.derived_chunks_found = len(derived_chunks)
        
        if source_ids_to_fetch:
            unique_source_ids = list(set(source_ids_to_fetch))
            logger.info(f"Fetching {len(unique_source_ids)} unique source chunks")
            
            source_chunks = fetch_sources_by_ids(unique_source_ids)
            stats.source_chunks_fetched = len(source_chunks)
            
            source_map = {_get_document_identifier(chunk): chunk for chunk in source_chunks}
            
            for derived_doc in derived_chunks:
                source_ids = derived_doc.get('metadata', {}).get('source_chunk_ids', [])
                if isinstance(source_ids, str):
                    source_ids = [source_ids]
                
                sources_found = 0
                for source_id in source_ids:
                    if source_id in source_map:
                        source_chunk = source_map[source_id].copy()
                        if 'rrf_score' in derived_doc:
                            source_chunk['rrf_score'] = derived_doc['rrf_score']
                        if 'query_intent' in derived_doc:
                            source_chunk['query_intent'] = derived_doc['query_intent']
                        
                        source_chunk['expanded_from_derived'] = True
                        source_chunk['original_derived_id'] = _get_document_identifier(derived_doc)
                        
                        expanded_results.append(source_chunk)
                        sources_found += 1
                    else:
                        logger.warning(f"Source chunk {source_id} not found")
                
                if sources_found == 0:
                    logger.warning(f"No sources found for derived chunk {_get_document_identifier(derived_doc)}, keeping original")
                    expanded_results.append(derived_doc)
        
        stats.chunks_after_expansion = len(expanded_results)
        logger.info(f"Derived expansion complete. Output: {len(expanded_results)} chunks")
        return expanded_results
        
    except Exception as e:
        error_msg = f"Derived expansion failed: {str(e)}"
        logger.error(error_msg, exc_info=True)
        stats.errors.append(error_msg)
        return results


def pack_context(
    results: List[Dict[str, Any]], 
    token_budget: int = 3500,
    stats: Optional[FusionStats] = None
) -> List[Dict[str, Any]]:
    """
    Pack chunks into context until token budget is reached.
    """
    if stats is None:
        stats = FusionStats()
    
    stats.token_budget = token_budget
    
    logger.info(f"Starting context packing with budget of {token_budget} tokens")
    
    try:
        if not results:
            logger.warning("No results to pack")
            return []
        
        packed_results = []
        total_tokens = 0
        
        for doc in results:
            doc_tokens = _estimate_tokens(doc)
            
            if total_tokens + doc_tokens > token_budget:
                logger.info(f"Token budget reached. Packed {len(packed_results)} chunks with {total_tokens} tokens")
                break
            
            doc_copy = doc.copy()
            doc_copy['estimated_tokens'] = doc_tokens
            packed_results.append(doc_copy)
            total_tokens += doc_tokens
            
            logger.debug(f"Added chunk with {doc_tokens} tokens. Total: {total_tokens}/{token_budget}")
        
        stats.final_chunks_packed = len(packed_results)
        stats.total_tokens_used = total_tokens
        
        logger.info(f"Context packing complete. Final: {len(packed_results)} chunks, {total_tokens} tokens")
        return packed_results
        
    except Exception as e:
        error_msg = f"Context packing failed: {str(e)}"
        logger.error(error_msg, exc_info=True)
        stats.errors.append(error_msg)
        return results[:10] if results else []


def _get_document_identifier(doc: Dict[str, Any]) -> str:
    """
    Generate a unique identifier for a document for RRF fusion.
    CRITICAL: Properly handles nested metadata structure.
    """
    if not isinstance(doc, dict):
        logger.warning(f"Document is not a dictionary: {type(doc)}")
        return f"obj_{id(doc)}"
    
    meta = doc.get('metadata', {})
    
    # Priority 1: chunk_id from metadata (most reliable)
    chunk_id = meta.get('chunk_id')
    if chunk_id:
        return str(chunk_id)
    
    # Priority 2: top-level id fields
    for id_field in ['id', 'chunk_id', '_id']:
        if id_field in doc and doc[id_field]:
            return str(doc[id_field])
    
    # Priority 3: other metadata ID fields
    for id_field in ['document_id', 'node_id']:
        if id_field in meta and meta[id_field]:
            return str(meta[id_field])
    
    # Priority 4: hash of text content
    content = _get_text_from_doc(doc)
    if content and content.strip():
        content_hash = abs(hash(content.strip()))
        return f"hash_{content_hash}"
    
    # Last resort: object ID
    logger.warning(f"Using object ID as document identifier for doc: {doc.keys()}")
    return f"obj_{id(doc)}"


def _get_deduplication_key(doc: Dict[str, Any]) -> Tuple:
    """
    Generate a robust deduplication key.
    CRITICAL: Simplified to prevent data loss - uses chunk_id as primary key.
    """
    if not isinstance(doc, dict):
        return (str(id(doc)),)
    
    meta = doc.get('metadata', {})
    
    # Primary approach: Use chunk_id as the most reliable deduplication key
    chunk_id = meta.get('chunk_id') or doc.get('id') or doc.get('chunk_id')
    if chunk_id:
        return (str(chunk_id),)
    
    # Fallback approach: Use document_id + additional identifiers for more precision
    document_id = meta.get('document_id', doc.get('document_id', ''))
    
    # Try to get additional distinguishing features
    struct_meta = meta.get('structural_metadata', {})
    page_or_slide = struct_meta.get('slide_number') or \
                   (meta.get('source_page_numbers', [None])[0] if meta.get('source_page_numbers') else None) or \
                   meta.get('page_number', '')
    
    chunk_index = meta.get('chunk_index', doc.get('chunk_index', ''))
    table_group_id = meta.get('same_table_group_id', '')
    
    # Create a more specific key when we don't have chunk_id
    if document_id or page_or_slide or chunk_index:
        return (str(document_id), str(page_or_slide), str(chunk_index), str(table_group_id))
    
    # Last resort: hash of text content
    content = _get_text_from_doc(doc)
    if content and content.strip():
        content_hash = abs(hash(content.strip()))
        return (f"content_{content_hash}",)
    
    # Ultimate fallback
    return (str(id(doc)),)


def _extract_node_data(node_or_dict: Any) -> Dict[str, Any]:
    """
    CRITICAL: Properly extract data from NodeWithScore objects or dictionaries.
    This prevents the fusion pipeline from stripping away chunk text and metadata.
    """
    # If it's already a dictionary, return it as-is
    if isinstance(node_or_dict, dict):
        return node_or_dict
    
    # Handle NodeWithScore objects
    if hasattr(node_or_dict, 'node'):
        node = node_or_dict.node
        score = getattr(node_or_dict, 'score', None)
        
        # Extract data from the actual node
        node_metadata = getattr(node, "metadata", {})
        if node_metadata is None:
            node_metadata = {}
        
        extracted = {
            "id": getattr(node, "id_", getattr(node, "id", None)),
            "text_chunk": getattr(node, "text", ""),
            "text": getattr(node, "text", ""),  # Fallback field
            "metadata": node_metadata,
            "score": score
        }
        
        # Add chunk_id from metadata if available, or use node ID
        chunk_id = None
        if node_metadata:
            chunk_id = node_metadata.get("chunk_id")
        if not chunk_id:
            chunk_id = getattr(node, "id_", getattr(node, "id", None))
        if chunk_id:
            extracted["chunk_id"] = chunk_id
        
        return extracted
    
    # Handle raw node objects (without score wrapper)
    if hasattr(node_or_dict, 'text') or hasattr(node_or_dict, 'metadata'):
        node_metadata = getattr(node_or_dict, "metadata", {})
        if node_metadata is None:
            node_metadata = {}
            
        return {
            "id": getattr(node_or_dict, "id_", getattr(node_or_dict, "id", None)),
            "text_chunk": getattr(node_or_dict, "text", ""),
            "text": getattr(node_or_dict, "text", ""),
            "metadata": node_metadata,
            "chunk_id": node_metadata.get("chunk_id") if node_metadata else None
        }
    
    # Fallback: treat as dictionary-like
    logger.warning(f"Unknown node type {type(node_or_dict)}, treating as dict")
    result = dict(node_or_dict) if node_or_dict else {}
    # Ensure metadata is never None
    if result.get("metadata") is None:
        result["metadata"] = {}
    return result


def _get_text_from_doc(doc: Dict[str, Any]) -> str:
    """Safely extracts text from a document dictionary."""
    # Check for the primary field 'text_chunk' first.
    if 'text_chunk' in doc and doc['text_chunk']:
        return str(doc['text_chunk'])
    
    # Fallback to other common text fields.
    text_fields = ['text', 'content', 'body', 'description', 'summary']
    for field in text_fields:
        if field in doc and doc[field]:
            return str(doc[field])
    
    # If no text is found, return an empty string.
    logger.warning(f"Could not find a valid text field in document with ID: {_get_document_identifier(doc)}")
    return ""


def _estimate_tokens(doc: Dict[str, Any]) -> int:
    """
    Estimate the number of tokens in a document with improved accuracy.
    
    Args:
        doc: Document dictionary.
    
    Returns:
        Estimated token count.
    """
    # Use the corrected helper function to get text content.
    text_content = _get_text_from_doc(doc)
    
    if not text_content.strip():
        return 0  # Return 0 if there is no text to pack.

    # A common and simple heuristic: 1 word is roughly 1.33 tokens.
    # This is more reliable than complex ratios.
    word_count = len(text_content.split())
    estimated_tokens = math.ceil(word_count * 1.33)
    
    return estimated_tokens


def fusion_pipeline(
    results: List[List[Any]],
    fetch_sources_by_ids: Callable[[List[str]], List[Dict[str, Any]]],
    intent_weights: Optional[Dict[str, float]] = None,
    k: int = 60,
    token_budget: int = 3500,
    skip_dedup: bool = False,
    skip_expansion: bool = False,
    return_stats: bool = False
) -> Union[List[Dict[str, Any]], Tuple[List[Dict[str, Any]], FusionStats]]:
    """
    Run the complete fusion pipeline: RRF -> dedupe -> expand -> pack.
    CRITICAL: Handles both NodeWithScore objects and dictionaries.
    """
    stats = FusionStats()
    logger.info("Starting fusion pipeline")
    
    try:
        # Convert input to consistent format first
        converted_results = []
        for result_list in results:
            converted_list = []
            for item in result_list:
                converted_list.append(_extract_node_data(item))
            converted_results.append(converted_list)
        
        if not validate_fusion_input(converted_results):
            error_msg = "Invalid input to fusion pipeline"
            stats.errors.append(error_msg)
            return ([], stats) if return_stats else []
        
        fused = rrf_fuse(converted_results, intent_weights, k, stats)
        if not fused:
            logger.warning("No results after RRF fusion")
            return ([], stats) if return_stats else []
        
        if not skip_dedup:
            fused = dedupe(fused, stats)
        else:
            logger.info("Skipping deduplication step")
            stats.chunks_after_dedup = len(fused)
        
        if not skip_expansion:
            fused = expand_derived(fused, fetch_sources_by_ids, stats)
        else:
            logger.info("Skipping derived chunk expansion")
            stats.chunks_after_expansion = len(fused)
        
        packed = pack_context(fused, token_budget, stats)
        
        logger.info(f"Fusion pipeline complete. Final: {len(packed)} chunks, {stats.total_tokens_used} tokens")
        
        if stats.errors:
            logger.warning(f"Pipeline completed with {len(stats.errors)} errors: {stats.errors}")
        
        return (packed, stats) if return_stats else packed
        
    except Exception as e:
        error_msg = f"Fusion pipeline failed: {str(e)}"
        logger.error(error_msg, exc_info=True)
        stats.errors.append(error_msg)
        return ([], stats) if return_stats else []


def analyze_fusion_stats(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Analyze fusion results and return detailed statistics.
    """
    if not results:
        return {
            'total_chunks': 0, 'total_tokens': 0, 'doc_types': {}, 'sources': {},
            'intents': {}, 'avg_score': 0.0, 'score_distribution': {}
        }
    
    total_tokens = sum(doc.get('estimated_tokens', 0) for doc in results)
    doc_types = defaultdict(int)
    sources = defaultdict(int)
    intents = defaultdict(int)
    scores = []
    expanded_count = 0
    
    for doc in results:
        doc_meta = doc.get('metadata', {})
        doc_types[doc_meta.get('chunk_type', 'unknown')] += 1
        sources[doc_meta.get('document_id', 'unknown')] += 1
        intents[doc.get('query_intent', 'unknown')] += 1
        
        if doc.get('expanded_from_derived'):
            expanded_count += 1
        
        if 'rrf_score' in doc:
            scores.append(doc['rrf_score'])
    
    score_distribution = {}
    if scores:
        scores_sorted = sorted(scores, reverse=True)
        score_distribution = {
            'min': min(scores), 'max': max(scores), 'median': scores_sorted[len(scores) // 2],
            'top_10_pct_avg': sum(scores_sorted[:max(1, len(scores) // 10)]) / max(1, len(scores) // 10),
            'bottom_10_pct_avg': sum(scores_sorted[-max(1, len(scores) // 10):]) / max(1, len(scores) // 10)
        }
    
    return {
        'total_chunks': len(results), 'total_tokens': total_tokens, 'expanded_chunks': expanded_count,
        'doc_types': dict(doc_types), 'sources': dict(sources), 'intents': dict(intents),
        'avg_score': sum(scores) / len(scores) if scores else 0.0,
        'score_distribution': score_distribution
    }


def validate_fusion_input(results: List[List[Dict[str, Any]]]) -> bool:
    """
    Validate input for fusion functions.
    """
    if not isinstance(results, list):
        logger.error("Results must be a list")
        return False
    
    for i, result_list in enumerate(results):
        if not isinstance(result_list, list):
            logger.error(f"Result list {i} is not a list: {type(result_list)}")
            return False
        
        for j, doc in enumerate(result_list):
            if not isinstance(doc, dict):
                logger.error(f"Document {j} in list {i} is not a dictionary: {type(doc)}")
                return False
            
            if not any(field in doc for field in ['text_chunk', 'text', 'content']):
                logger.warning(f"Document {j} in list {i} may lack a primary content field")
    
    return True


class FusionEngine:
    """
    Production-ready wrapper class for fusion pipeline operations.
    """
    
    def __init__(
        self, 
        k: int = 60, 
        token_budget: int = 3500, 
        skip_dedup: bool = False, 
        skip_expansion: bool = False
    ):
        """
        Initialize the FusionEngine with configuration parameters.
        """
        self.k = k
        self.token_budget = token_budget
        self.skip_dedup = skip_dedup
        self.skip_expansion = skip_expansion
        
        logger.info(f"FusionEngine initialized with k={k}, token_budget={token_budget}, "
                   f"skip_dedup={skip_dedup}, skip_expansion={skip_expansion}")
    
    def fuse(
        self, 
        results: List[List[Any]], 
        fetch_sources_by_ids: Callable[[List[str]], List[Dict[str, Any]]], 
        intent_weights: Optional[Dict[str, float]] = None
    ) -> List[Dict[str, Any]]:
        """
        Execute the fusion pipeline and return the final processed results.
        CRITICAL: Handles NodeWithScore objects properly.
        """
        results, _ = fusion_pipeline(
            results=results,
            fetch_sources_by_ids=fetch_sources_by_ids,
            intent_weights=intent_weights,
            k=self.k,
            token_budget=self.token_budget,
            skip_dedup=self.skip_dedup,
            skip_expansion=self.skip_expansion,
            return_stats=True
        )
        return results
    
    def fuse_with_stats(
        self, 
        results: List[List[Any]], 
        fetch_sources_by_ids: Callable[[List[str]], List[Dict[str, Any]]], 
        intent_weights: Optional[Dict[str, float]] = None
    ) -> Tuple[List[Dict[str, Any]], FusionStats]:
        """
        Execute the fusion pipeline and return both results and detailed statistics.
        CRITICAL: Handles NodeWithScore objects properly.
        """
        return fusion_pipeline(
            results=results,
            fetch_sources_by_ids=fetch_sources_by_ids,
            intent_weights=intent_weights,
            k=self.k,
            token_budget=self.token_budget,
            skip_dedup=self.skip_dedup,
            skip_expansion=self.skip_expansion,
            return_stats=True
        )
    
    def update_config(
        self, 
        k: Optional[int] = None, 
        token_budget: Optional[int] = None, 
        skip_dedup: Optional[bool] = None, 
        skip_expansion: Optional[bool] = None
    ) -> None:
        """
        Update the engine's configuration parameters.
        """
        if k is not None:
            self.k = k
        if token_budget is not None:
            self.token_budget = token_budget
        if skip_dedup is not None:
            self.skip_dedup = skip_dedup
        if skip_expansion is not None:
            self.skip_expansion = skip_expansion
            
        logger.info(f"FusionEngine config updated: k={self.k}, token_budget={self.token_budget}, "
                   f"skip_dedup={self.skip_dedup}, skip_expansion={self.skip_expansion}")
    
    def get_config(self) -> Dict[str, Any]:
        """
        Get the current engine configuration.
        """
        return {
            'k': self.k,
            'token_budget': self.token_budget,
            'skip_dedup': self.skip_dedup,
            'skip_expansion': self.skip_expansion
        }