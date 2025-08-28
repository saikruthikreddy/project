# File: giani_pkb/services/rag/citation_formatter.py

from __future__ import annotations

import os
import time
import logging
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import structlog
from prometheus_client import Counter, Histogram
from llama_index.core.schema import NodeWithScore

# -----------------------------------------------------------------------------
# Logging (structured) & Metrics
# -----------------------------------------------------------------------------

structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger(__name__)

CITATION_FORMATTING_DURATION = Histogram(
    "citation_formatting_duration_seconds",
    "Time spent formatting citations",
    ["project_id"],
)

CITATIONS_FORMATTED_TOTAL = Counter(
    "citations_formatted_total",
    "Number of citations formatted",
    ["project_id"],
)

CITATION_FORMATTING_FAILURES = Counter(
    "citation_formatting_failures_total",
    "Number of citation formatting failures by reason",
    ["project_id", "reason"],
)

CITATION_MISSING_FIELDS = Counter(
    "citation_missing_fields_total",
    "Number of citations missing required fields",
    ["project_id", "field"],
)

# -----------------------------------------------------------------------------
# Config & Schema
# -----------------------------------------------------------------------------

@dataclass
class CitationFormatterConfig:
    """
    Configuration for citation formatting and normalization.
    """
    max_section_title_len: int = int(os.getenv("CITATION_MAX_SECTION_TITLE_LEN", "200"))
    include_score: bool = True
    include_filename: bool = True
    include_source_path: bool = True
    # When True, drop citations missing `chunk_id` or `document_id` instead of keeping them.
    drop_if_missing_required: bool = False
    # Deduplicate by (document_id, chunk_id) if both present
    deduplicate: bool = True


@dataclass
class Citation:
    """
    Normalized citation schema emitted by `format_citations`.
    """
    chunk_id: Optional[str]
    document_id: Optional[Union[str, int]]
    project_id: Optional[Union[str, int]]
    page_numbers: Optional[List[int]]
    document_type: Optional[str]
    section_title: Optional[str]
    score: Optional[float] = None
    filename: Optional[str] = None
    source_path: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# -----------------------------------------------------------------------------
# Internal helpers
# -----------------------------------------------------------------------------

def _safe_get_node_and_meta(
    node_with_score: NodeWithScore,
) -> Tuple[Optional[Any], Dict[str, Any], Optional[str], Optional[float]]:
    """
    Extract the underlying node object, metadata, chunk id, and score from
    a LlamaIndex NodeWithScore safely across versions.

    Supports both:
      - node_with_score.node.metadata / node_with_score.node.id_
      - node_with_score.metadata / node_with_score.node_id (legacy usage)
    """
    score = getattr(node_with_score, "score", None)

    # Try modern access first
    node = getattr(node_with_score, "node", None)
    meta = {}
    chunk_id = None

    if node is not None:
        # Node.id_ in newer versions; fallback to .node_id if present
        chunk_id = getattr(node, "id_", None) or getattr(node, "node_id", None)
        # Node.metadata or Node.extra_info depending on how it was created
        meta = getattr(node, "metadata", None) or getattr(node, "extra_info", {}) or {}
    else:
        # Legacy pattern (seen in your previous formatter)
        meta = getattr(node_with_score, "metadata", {}) or {}
        chunk_id = getattr(node_with_score, "node_id", None)

    # Normalize metadata to a dict
    if not isinstance(meta, dict):
        try:
            meta = dict(meta)  # best-effort
        except Exception:
            meta = {}

    return node, meta, chunk_id, score


def _normalize_page_numbers(pages: Any) -> Optional[List[int]]:
    """
    Normalize page_numbers to a sorted list of distinct positive ints.
    Accepts int, str (comma/space separated), list/tuple of ints/strs.
    Enhanced to handle more edge cases and ensure reliability.
    """
    if pages is None:
        return None

    def _to_ints(seq: Sequence[Any]) -> List[int]:
        out: List[int] = []
        for p in seq:
            if p is None:
                continue
            try:
                # Handle string representations that might have extra characters
                p_str = str(p).strip()
                # Remove common non-numeric characters that might appear in page references
                p_str = p_str.replace('p.', '').replace('pg.', '').replace('page', '').strip()
                # Handle ranges like "5-7" by taking the first number
                if '-' in p_str:
                    p_str = p_str.split('-')[0].strip()
                
                val = int(float(p_str))  # Handle floats that represent integers
                if val > 0:
                    out.append(val)
            except (ValueError, TypeError):
                # ignore non-numeric page entries
                continue
        return sorted(list(set(out)))

    if isinstance(pages, (int, float)):
        val = int(pages)
        return [val] if val > 0 else None
    if isinstance(pages, str):
        # split on comma, semicolon, or whitespace
        raw = []
        for delimiter in [',', ';', ' ', '\t', '\n']:
            if delimiter in pages:
                raw.extend(pages.split(delimiter))
                break
        else:
            raw = [pages]
        # Filter out empty strings
        raw = [x.strip() for x in raw if x.strip()]
        return _to_ints(raw)
    if isinstance(pages, (list, tuple)):
        return _to_ints(pages)

    return None


def _extract_comprehensive_page_info(meta: Dict[str, Any]) -> Optional[List[int]]:
    """
    Comprehensively extract page numbers from various possible metadata fields.
    This ensures page_numbers is consistently available for citations.
    """
    # Primary page number fields (in order of preference)
    page_fields = [
        'page_numbers',  # Most explicit
        'pages',         # Common alternative
        'page',          # Singular form
        'page_number',   # Another common variant
        'page_label',    # Sometimes used for page references
        'slide_number',  # For presentation documents
        'pageNumber',    # CamelCase variant
        'pageNumbers',   # CamelCase plural
    ]
    
    for field in page_fields:
        if field in meta and meta[field] is not None:
            normalized = _normalize_page_numbers(meta[field])
            if normalized:  # Only return if we got valid page numbers
                return normalized
    
    # Try to extract from filename or path if available
    filename_fields = ['filename', 'file_name', 'original_filename', 'source_path', 'source']
    for field in filename_fields:
        if field in meta and meta[field]:
            filename = str(meta[field])
            # Look for patterns like "page_5", "p5", "slide_10", etc.
            import re
            patterns = [
                r'page[_\-\s]*(\d+)',
                r'p[_\-\s]*(\d+)',
                r'slide[_\-\s]*(\d+)',
                r'pg[_\-\s]*(\d+)',
            ]
            for pattern in patterns:
                match = re.search(pattern, filename.lower())
                if match:
                    try:
                        page_num = int(match.group(1))
                        if page_num > 0:
                            return [page_num]
                    except ValueError:
                        continue
    
    return None


def _truncate(text: Optional[str], limit: int) -> Optional[str]:
    if text is None:
        return None
    if limit <= 0:
        return text
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _build_citation(
    meta: Dict[str, Any],
    chunk_id: Optional[str],
    score: Optional[float],
    cfg: CitationFormatterConfig,
) -> Citation:
    """
    Create a normalized Citation from raw metadata.
    Enhanced to ensure page_numbers is consistently present.
    """
    project_id = meta.get("project_id") or meta.get("projectId")
    document_id = meta.get("document_id") or meta.get("documentId")
    section_title = meta.get("section_title") or meta.get("sectionTitle")
    document_type = meta.get("document_type") or meta.get("documentType")

    # Enhanced page number extraction - this is the key improvement
    page_numbers = _extract_comprehensive_page_info(meta)

    filename = None
    source_path = None

    if cfg.include_filename:
        filename = meta.get("filename") or meta.get("file_name") or meta.get("original_filename")
    if cfg.include_source_path:
        source_path = meta.get("source_path") or meta.get("source") or meta.get("storage_path")

    # --- Append slide/page info to section title ---
    slide_or_page = None
    if "slide_number" in meta and meta["slide_number"] is not None:
        slide_or_page = f"Slide {meta['slide_number']}"
    elif "page_label" in meta and meta["page_label"] is not None:
        slide_or_page = f"Page {meta['page_label']}"
    elif "page_number" in meta and meta["page_number"] is not None:
        slide_or_page = f"Page {meta['page_number']}"
    elif page_numbers and len(page_numbers) == 1:
        # If we extracted a single page number, use it for the section title enhancement
        slide_or_page = f"Page {page_numbers[0]}"

    if section_title and slide_or_page:
        section_title = f"{section_title} ({slide_or_page})"
    elif slide_or_page:
        section_title = slide_or_page
    # --- END section title enhancement ---

    citation = Citation(
        chunk_id=chunk_id,
        document_id=document_id,
        project_id=project_id,
        page_numbers=page_numbers,  # Now consistently extracted
        document_type=str(document_type) if document_type is not None else None,
        section_title=_truncate(section_title, cfg.max_section_title_len) if section_title else None,
        score=score if cfg.include_score else None,
        filename=filename,
        source_path=source_path,
    )

    # Track missing required fields
    if citation.chunk_id is None:
        CITATION_MISSING_FIELDS.labels(str(project_id or "unknown"), "chunk_id").inc()
    if citation.document_id is None:
        CITATION_MISSING_FIELDS.labels(str(project_id or "unknown"), "document_id").inc()
    # Track when page numbers are missing (for monitoring)
    if citation.page_numbers is None:
        CITATION_MISSING_FIELDS.labels(str(project_id or "unknown"), "page_numbers").inc()

    return citation


def _should_keep(c: Citation, cfg: CitationFormatterConfig) -> bool:
    if cfg.drop_if_missing_required:
        return c.chunk_id is not None and c.document_id is not None
    return True


# -----------------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------------

def format_citations(
    source_nodes: Optional[Sequence[NodeWithScore]],
    project_id: Optional[Union[str, int]] = None,
    config: Optional[CitationFormatterConfig] = None,
) -> List[Dict[str, Any]]:
    """
    Format LlamaIndex source nodes into normalized citations with resilience,
    metrics, and structured logging.

    Args:
        source_nodes: list of NodeWithScore
        project_id: optional project id for metrics/labels
        config: optional CitationFormatterConfig

    Returns:
        List of citation dicts (normalized)
    """
    cfg = config or CitationFormatterConfig()
    proj_label = str(project_id or "unknown")

    start = time.time()
    citations: List[Citation] = []
    seen: set[Tuple[Any, Any]] = set()

    logger.info(
        "Formatting citations: start",
        project_id=proj_label,
        count=len(source_nodes or []),
        config=asdict(cfg),
    )

    with CITATION_FORMATTING_DURATION.labels(proj_label).time():
        if not source_nodes:
            logger.warning("No source nodes provided for citation formatting", project_id=proj_label)
            return []

        for idx, nws in enumerate(source_nodes):
            try:
                node, meta, chunk_id, score = _safe_get_node_and_meta(nws)
                citation = _build_citation(meta, chunk_id, score, cfg)

                if not _should_keep(citation, cfg):
                    CITATION_FORMATTING_FAILURES.labels(proj_label, "missing_required").inc()
                    logger.warning(
                        "Dropping citation due to missing required fields",
                        project_id=proj_label,
                        index=idx,
                        citation=citation.to_dict(),
                    )
                    continue

                if cfg.deduplicate and citation.document_id is not None and citation.chunk_id is not None:
                    key = (str(citation.document_id), str(citation.chunk_id))
                    if key in seen:
                        logger.debug(
                            "Skipping duplicate citation",
                            project_id=proj_label,
                            index=idx,
                            key=key,
                        )
                        continue
                    seen.add(key)

                citations.append(citation)

            except Exception as e:
                CITATION_FORMATTING_FAILURES.labels(proj_label, type(e).__name__).inc()
                logger.error(
                    "Failed to format citation",
                    project_id=proj_label,
                    index=idx,
                    error=str(e),
                    error_type=type(e).__name__,
                )

    duration = time.time() - start
    CITATIONS_FORMATTED_TOTAL.labels(proj_label).inc(len(citations))

    logger.info(
        "Formatting citations: complete",
        project_id=proj_label,
        duration_seconds=round(duration, 3),
        total=len(citations),
        deduplicated=len(seen) if cfg.deduplicate else "n/a",
    )

    return [c.to_dict() for c in citations]


__all__ = [
    "CitationFormatterConfig",
    "Citation",
    "format_citations",
]