import re
import time
import logging
import uuid
from typing import List, Optional, Dict, Any
from dataclasses import dataclass
from functools import wraps

import structlog
from prometheus_client import Histogram, Counter
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from llama_index.core.schema import NodeWithScore
from llama_index.core.postprocessor.types import BaseNodePostprocessor
from llama_index.core.postprocessor import SimilarityPostprocessor
from llama_index.core.postprocessor import SentenceTransformerRerank

# ---------------------------------------------------------------------
# Structured logging + metrics
# ---------------------------------------------------------------------
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer()
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger(__name__)

POST_RETRIEVAL_DURATION = Histogram(
    "post_retrieval_processing_seconds",
    "Time spent in post-retrieval processing",
    ["stage", "query_id"]
)

POST_RETRIEVAL_FAILURES = Counter(
    "post_retrieval_failures_total",
    "Number of post-retrieval processing failures",
    ["stage", "error_type", "query_id"]
)

POST_RETRIEVAL_DOCS_PROCESSED = Counter(
    "post_retrieval_documents_processed_total",
    "Total number of documents processed in post-retrieval",
    ["stage", "query_id"]
)

NUMERIC = re.compile(r"(\d[\d,\.]*\s?%|\$?\s?\d[\d,\.]*\b|\b\d+\s?[xX]\b)")

# ---------------------------------------------------------------------
# Config dataclass
# ---------------------------------------------------------------------
@dataclass
class PostProcessorConfig:
    max_docs_to_rerank: int = 100
    max_docs_to_expand: int = 50
    similarity_cutoff: float = 0.70
    min_overlap_terms: int = 1
    enable_metrics: bool = True
    enable_logging: bool = True
    retry_attempts: int = 3
    retry_wait_multiplier: int = 2
    retry_wait_max: int = 10
    # cap for fallback docstore scan when docstore can't filter
    max_docstore_scan: int = 2000

# ---------------------------------------------------------------------
# Helper: metrics & decorator for postprocessors
# ---------------------------------------------------------------------
class PostProcessorMetrics:
    def __init__(self, stage: str, query_id: str, config: PostProcessorConfig):
        self.stage = stage
        self.query_id = query_id
        self.config = config
        self.start_time = None

    def __enter__(self):
        self.start_time = time.time()
        if self.config.enable_logging:
            logger.info("Starting post-processor stage", stage=self.stage, query_id=self.query_id)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        duration = time.time() - self.start_time
        if self.config.enable_metrics:
            POST_RETRIEVAL_DURATION.labels(stage=self.stage, query_id=self.query_id).observe(duration)
        if exc_type:
            error_type = exc_type.__name__
            if self.config.enable_metrics:
                POST_RETRIEVAL_FAILURES.labels(stage=self.stage, error_type=error_type, query_id=self.query_id).inc()
            if self.config.enable_logging:
                logger.error("Post-processor stage failed", stage=self.stage, query_id=self.query_id,
                             error_type=error_type, duration=duration, error=str(exc_val))
        else:
            if self.config.enable_logging:
                logger.info("Post-processor stage completed", stage=self.stage, query_id=self.query_id, duration=duration)

def safe_postprocessor(stage_name: str):
    """Decorator to wrap post-processors; ensures metrics/logging and fail-open behaviour."""
    def decorator(func):
        @wraps(func)
        def wrapper(self, nodes: List[NodeWithScore], query_str: Optional[str] = None, query_id: Optional[str] = None) -> List[NodeWithScore]:
            if query_id is None:
                query_id = str(uuid.uuid4())
            config = getattr(self, "_config", PostProcessorConfig())

            with PostProcessorMetrics(stage_name, query_id, config):
                try:
                    input_count = len(nodes) if nodes else 0
                    if config.enable_logging:
                        logger.info("Processing post-processor", stage=stage_name, query_id=query_id, input_docs=input_count)
                    if config.enable_metrics:
                        POST_RETRIEVAL_DOCS_PROCESSED.labels(stage=f"{stage_name}_input", query_id=query_id).inc(input_count)

                    result = func(self, nodes, query_str, query_id)

                    output_count = len(result) if result else 0
                    if config.enable_logging:
                        logger.info("Completed post-processor", stage=stage_name, query_id=query_id,
                                    input_docs=input_count, output_docs=output_count)
                    if config.enable_metrics:
                        POST_RETRIEVAL_DOCS_PROCESSED.labels(stage=f"{stage_name}_output", query_id=query_id).inc(output_count)

                    return result or []
                except Exception as e:
                    logger.error("Error in post-processor", stage=stage_name, query_id=query_id, error=str(e), error_type=type(e).__name__)
                    # Fail-open: return original list to keep the pipeline moving
                    return nodes or []
        return wrapper
    return decorator

# ---------------------------------------------------------------------
# Resilient postprocessors
# ---------------------------------------------------------------------
class ResilientIntentBiasPostprocessor(BaseNodePostprocessor):
    def __init__(self, query: str, config: Optional[PostProcessorConfig] = None):
        self._config = config or PostProcessorConfig()
        try:
            q = (query or "").lower()
            self._numeric = bool(NUMERIC.search(q)) or any(k in q for k in ["table", "chart", "by how much", "%", "increase", "decrease"])
        except Exception:
            logger.warning("Error detecting numeric intent, defaulting to False")
            self._numeric = False

    @safe_postprocessor("intent_bias")
    def _postprocess_nodes(self, nodes: List[NodeWithScore], query_str: Optional[str] = None, query_id: Optional[str] = None) -> List[NodeWithScore]:
        if not self._numeric or not nodes:
            return nodes

        out: List[NodeWithScore] = []
        for n in nodes:
            try:
                meta = n.metadata or {}
                ct, role = meta.get("chunk_type"), meta.get("role")
                boost = 0.2 if (ct in {"metric", "table", "chart"} or role == "data") else 0.0
                n.score = min(0.9999, (n.score or 0) + boost)
                out.append(n)
            except Exception as e:
                logger.warning("Error processing node in intent bias", query_id=query_id, node_id=getattr(n, "node_id", "unknown"), error=str(e))
                out.append(n)
        return out

    def postprocess_nodes(self, nodes: List[NodeWithScore], query_str: Optional[str] = None) -> List[NodeWithScore]:
        return self._postprocess_nodes(nodes, query_str)

class ResilientSameGroupDeduper(BaseNodePostprocessor):
    def __init__(self, config: Optional[PostProcessorConfig] = None):
        self._config = config or PostProcessorConfig()

    @safe_postprocessor("same_group_dedup")
    def _postprocess_nodes(self, nodes: List[NodeWithScore], query_str: Optional[str] = None, query_id: Optional[str] = None) -> List[NodeWithScore]:
        if not nodes:
            return nodes

        best: Dict[Any, NodeWithScore] = {}
        failed_nodes: List[NodeWithScore] = []

        for n in nodes:
            try:
                gid = (n.metadata or {}).get("same_table_group_id")
                role = (n.metadata or {}).get("role")
                key = (gid, role) if gid else (getattr(n, "node_id", None), role)
                if key not in best or (n.score or 0) > (best[key].score or 0):
                    best[key] = n
            except Exception as e:
                logger.warning("Error processing node in dedup", query_id=query_id, node_id=getattr(n, "node_id", "unknown"), error=str(e))
                failed_nodes.append(n)

        result = list(best.values()) + failed_nodes
        return sorted(result, key=lambda x: (x.score or 0), reverse=True)

    def postprocess_nodes(self, nodes: List[NodeWithScore], query_str: Optional[str] = None) -> List[NodeWithScore]:
        return self._postprocess_nodes(nodes, query_str)

class ResilientContextTwinExpander(BaseNodePostprocessor):
    """Context twin expansion: scope to groups present in the current results to avoid O(N) docstore scans."""

    def __init__(self, index, config: Optional[PostProcessorConfig] = None):
        self._docstore = getattr(index, "docstore", None)
        self._config = config or PostProcessorConfig()
        self._max_fallback_scan = getattr(self._config, "max_docstore_scan", 2000)

    def _fetch_group_members(self, gid: Any, group_filter: Dict[str, Any]) -> List[Any]:
        """Try fast metadata lookup; fallback to bounded, filtered scan to keep latency stable."""
        # 1) Preferred: docstore supports metadata lookup
        if hasattr(self._docstore, "get_nodes_by_metadata"):
            try:
                nodes = self._docstore.get_nodes_by_metadata({"same_table_group_id": gid}) or []
                # defensive filtering
                proj = group_filter.get("project_id")
                doctype = group_filter.get("document_type")
                if proj or doctype:
                    out = []
                    for n in nodes:
                        meta = getattr(n, "metadata", {}) or {}
                        if proj and str(meta.get("project_id")) != str(proj):
                            continue
                        if doctype and str(meta.get("document_type")) != str(doctype):
                            continue
                        out.append(n)
                    return out
                return nodes
            except Exception as e:
                logger.warning("get_nodes_by_metadata failed; falling back to bounded scan", group_id=str(gid), error=str(e))

        # 2) Bounded fallback scan (guarded by max scan)
        out_nodes: List[Any] = []
        if hasattr(self._docstore, "get_all_nodes"):
            scanned = 0
            proj = group_filter.get("project_id")
            doctype = group_filter.get("document_type")
            try:
                for node in self._docstore.get_all_nodes().values():
                    scanned += 1
                    if scanned > self._max_fallback_scan:
                        logger.info("Fallback scan limit reached; partial group collected", group_id=str(gid), scanned=scanned, limit=self._max_fallback_scan)
                        break
                    meta = getattr(node, "metadata", {}) or {}
                    if meta.get("same_table_group_id") != gid:
                        continue
                    if proj and str(meta.get("project_id")) != str(proj):
                        continue
                    if doctype and str(meta.get("document_type")) != str(doctype):
                        continue
                    out_nodes.append(node)
            except Exception as e:
                logger.error("Error during bounded fallback scan", group_id=str(gid), error=str(e))
        return out_nodes

    @safe_postprocessor("context_twin_expand")
    def _postprocess_nodes(self, nodes: List[NodeWithScore], query_str: Optional[str] = None, query_id: Optional[str] = None) -> List[NodeWithScore]:
        if not nodes:
            return nodes

        nodes_to_process = nodes[: self._config.max_docs_to_expand]
        if len(nodes) > self._config.max_docs_to_expand:
            logger.info("Limiting context expansion", query_id=query_id, original_count=len(nodes), limited_count=self._config.max_docs_to_expand)

        # collect group ids and representative filters from seeds only
        group_ids = set()
        group_filters: Dict[Any, Dict[str, Any]] = {}
        for n in nodes_to_process:
            meta = getattr(n, "metadata", {}) or {}
            gid = meta.get("same_table_group_id")
            if gid is not None:
                group_ids.add(gid)
                if gid not in group_filters:
                    group_filters[gid] = {"project_id": meta.get("project_id"), "document_type": meta.get("document_type")}

        if not group_ids:
            return nodes_to_process

        # preload siblings only for groups we actually have
        groups: Dict[Any, List[Any]] = {}
        for gid in group_ids:
            groups[gid] = self._fetch_group_members(gid, group_filters.get(gid, {}))

        out: List[NodeWithScore] = list(nodes_to_process)
        seen = {getattr(n, "node_id", None) for n in nodes_to_process}

        # add one complementary sibling per seed when available
        for n in nodes_to_process:
            try:
                meta = getattr(n, "metadata", {}) or {}
                gid = meta.get("same_table_group_id")
                role = meta.get("role")
                if not gid:
                    continue
                for sib in groups.get(gid, []):
                    sib_id = getattr(sib, "node_id", None)
                    if not sib_id or sib_id in seen:
                        continue
                    sib_role = (getattr(sib, "metadata", {}) or {}).get("role")
                    if sib_role and sib_role != role:
                        out.append(sib)
                        seen.add(sib_id)
                        break
            except Exception as e:
                logger.warning("Error expanding context for node", query_id=query_id, node_id=getattr(n, "node_id", "unknown"), error=str(e))
                continue

        return out

    def postprocess_nodes(self, nodes: List[NodeWithScore], query_str: Optional[str] = None) -> List[NodeWithScore]:
        return self._postprocess_nodes(nodes, query_str)

class ResilientQueryTermFilter(BaseNodePostprocessor):
    def __init__(self, min_overlap_terms: int = 1, config: Optional[PostProcessorConfig] = None):
        self.min_overlap_terms = min_overlap_terms
        self._config = config or PostProcessorConfig()

    @safe_postprocessor("query_term_filter")
    def _postprocess_nodes(self, nodes: List[NodeWithScore], query_str: Optional[str] = None, query_id: Optional[str] = None) -> List[NodeWithScore]:
        if not query_str or not nodes:
            return nodes

        try:
            q_terms = set([t.lower() for t in re.findall(r"[A-Za-z]\w{2,}", query_str)])
            if not q_terms:
                return nodes
        except Exception as e:
            logger.error("Error extracting query terms", query_id=query_id, error=str(e))
            return nodes

        kept: List[NodeWithScore] = []
        failed_nodes: List[NodeWithScore] = []

        for n in nodes:
            try:
                text = (n.get_content() or "").lower()
                overlap = sum(1 for t in q_terms if t in text)
                if overlap >= self.min_overlap_terms:
                    kept.append(n)
            except Exception as e:
                logger.warning("Error filtering node", query_id=query_id, node_id=getattr(n, "node_id", "unknown"), error=str(e))
                failed_nodes.append(n)

        result = kept + failed_nodes
        return result or nodes

    def postprocess_nodes(self, nodes: List[NodeWithScore], query_str: Optional[str] = None) -> List[NodeWithScore]:
        return self._postprocess_nodes(nodes, query_str)

class ResilientSimilarityPostprocessor(BaseNodePostprocessor):
    def __init__(self, similarity_cutoff: float = 0.70, config: Optional[PostProcessorConfig] = None):
        self._similarity_cutoff = similarity_cutoff
        self._config = config or PostProcessorConfig()
        self._processor = SimilarityPostprocessor(similarity_cutoff=similarity_cutoff)

    @safe_postprocessor("similarity_filter")
    def _postprocess_nodes(self, nodes: List[NodeWithScore], query_str: Optional[str] = None, query_id: Optional[str] = None) -> List[NodeWithScore]:
        return self._processor.postprocess_nodes(nodes, query_str)

    def postprocess_nodes(self, nodes: List[NodeWithScore], query_str: Optional[str] = None) -> List[NodeWithScore]:
        return self._postprocess_nodes(nodes, query_str)

class ResilientSentenceTransformerRerank(BaseNodePostprocessor):
    def __init__(self, model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2", top_n: int = 10, config: Optional[PostProcessorConfig] = None):
        self._config = config or PostProcessorConfig()
        self._top_n = min(top_n, self._config.max_docs_to_rerank)
        self._processor = SentenceTransformerRerank(model=model, top_n=self._top_n)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, max=10),
        retry=retry_if_exception_type((ConnectionError, TimeoutError))
    )
    def _rerank_with_retry(self, nodes: List[NodeWithScore], query_str: str) -> List[NodeWithScore]:
        return self._processor.postprocess_nodes(nodes, query_str)

    @safe_postprocessor("sentence_transformer_rerank")
    def _postprocess_nodes(self, nodes: List[NodeWithScore], query_str: Optional[str] = None, query_id: Optional[str] = None) -> List[NodeWithScore]:
        if not nodes or not query_str:
            return nodes

        nodes_to_rerank = nodes[: self._config.max_docs_to_rerank]
        remaining_nodes = nodes[self._config.max_docs_to_rerank :]

        if remaining_nodes:
            logger.info("Limiting reranking", query_id=query_id, original_count=len(nodes), rerank_count=len(nodes_to_rerank))

        try:
            reranked = self._rerank_with_retry(nodes_to_rerank, query_str)
            return reranked + remaining_nodes
        except Exception as e:
            logger.error("Reranking failed after retries", query_id=query_id, error=str(e))
            return nodes_to_rerank + remaining_nodes

    def postprocess_nodes(self, nodes: List[NodeWithScore], query_str: Optional[str] = None) -> List[NodeWithScore]:
        return self._postprocess_nodes(nodes, query_str)

# ---------------------------------------------------------------------
# Pipeline helpers
# ---------------------------------------------------------------------
def build_resilient_postprocessors(query: str, top_k: int, index, config: Optional[PostProcessorConfig] = None) -> List[BaseNodePostprocessor]:
    if config is None:
        config = PostProcessorConfig()

    return [
        ResilientIntentBiasPostprocessor(query, config),
        ResilientSimilarityPostprocessor(similarity_cutoff=config.similarity_cutoff, config=config),
        ResilientSentenceTransformerRerank(model="cross-encoder/ms-marco-MiniLM-L-6-v2", top_n=top_k, config=config),
        ResilientSameGroupDeduper(config),
        ResilientContextTwinExpander(index, config),
        ResilientQueryTermFilter(min_overlap_terms=config.min_overlap_terms, config=config),
    ]

def process_postretrieval_pipeline(nodes: List[NodeWithScore], query_str: str, postprocessors: List[BaseNodePostprocessor], query_id: Optional[str] = None) -> List[NodeWithScore]:
    if query_id is None:
        query_id = str(uuid.uuid4())

    logger.info("Starting post-retrieval pipeline", query_id=query_id, initial_nodes=len(nodes), processors=len(postprocessors))
    current_nodes = nodes or []

    for i, processor in enumerate(postprocessors):
        try:
            processor_name = type(processor).__name__
            logger.debug("Applying processor", query_id=query_id, processor=processor_name, input_nodes=len(current_nodes))
            processed = processor.postprocess_nodes(current_nodes, query_str)
            current_nodes = processed if processed is not None else current_nodes
            logger.debug("Completed processor", query_id=query_id, processor=processor_name, output_nodes=len(current_nodes))
        except Exception as e:
            logger.error("Post-processor failed", query_id=query_id, processor=type(processor).__name__, error=str(e), error_type=type(e).__name__)
            # Continue using current_nodes
            continue

    logger.info("Completed post-retrieval pipeline", query_id=query_id, final_nodes=len(current_nodes))
    return current_nodes or []

# Legacy compatibility
def build_postprocessors(query: str, top_k: int, index, similarity_cutoff: float = 0.70):
    config = PostProcessorConfig(similarity_cutoff=similarity_cutoff)
    return build_resilient_postprocessors(query, top_k, index, config)
