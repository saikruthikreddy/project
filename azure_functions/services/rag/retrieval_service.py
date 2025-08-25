# --- START OF FILE retrieval_service.py ---

import asyncio
import concurrent.futures
import hashlib
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

import structlog
from llama_index.core import VectorStoreIndex
from llama_index.core.schema import NodeWithScore
from llama_index.core.vector_stores import MetadataFilter, MetadataFilters
from prometheus_client import Counter, Gauge, Histogram

from services.rag.config_loader import OrchestrationConfig, load_orchestration_config

from .post_retrieval import build_resilient_postprocessors, process_postretrieval_pipeline
from services.rag.reranker import CrossEncoderReranker


# --- Configuration and Logging ---

config: OrchestrationConfig = load_orchestration_config()

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(config.logging.level),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)
log = structlog.get_logger("retriever_service")


def _sanitize_for_logging(text: str, max_len: int = 500) -> str:
    """Sanitize text by removing newlines and truncating."""
    if not isinstance(text, str):
        return ""
    sanitized = text.replace("\n", " ").replace("\r", " ")
    return sanitized[:max_len] + "..." if len(sanitized) > max_len else sanitized


# --- Prometheus Metrics ---

RETRIEVER_REQUESTS_TOTAL = Counter(
    "retriever_requests_total",
    "Total number of retriever requests.",
    ["stage", "result_type"],
)
RETRIEVER_REQUESTS_LATENCY_SECONDS = Histogram(
    "retriever_requests_latency_seconds",
    "Histogram of retriever request latencies.",
    ["stage", "result_type"],
    buckets=(0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, float("inf")),
)
ACTIVE_RETRIEVALS = Gauge(
    "retriever_active_requests", "Number of currently active retrieval requests."
)


# --- Exceptions and Data Structures ---

class RetrieverErrorType(Enum):
    TIMEOUT = "timeout"
    CONNECTION_ERROR = "connection_error"
    AUTHENTICATION_ERROR = "authentication_error"
    RATE_LIMIT_ERROR = "rate_limit_error"
    VECTOR_DB_ERROR = "vector_db_error"
    INVALID_REQUEST = "invalid_request"
    UNEXPECTED_ERROR = "unexpected_error"
    NO_RESULTS_FOUND = "no_results_found"


class RetrieverError(Exception):
    def __init__(self, message: str, stage: str, error_type: RetrieverErrorType, query_id: str):
        self.message = message
        self.stage = stage
        self.error_type = error_type
        self.query_id = query_id
        super().__init__(
            f"[QueryID: {query_id}] Stage '{stage}' failed with {error_type.value}: {message}"
        )


@dataclass
class SubRetrievalDetail:
    provider: str
    stage: str
    success: bool
    num_results: int
    execution_time: float
    threshold: float
    error: Optional[str] = None
    cached: bool = False
    error_type: Optional[RetrieverErrorType] = None
    attempts: int = 1


@dataclass
class RetrieverResult:
    query_id: str
    success: bool
    results: List[NodeWithScore] = field(default_factory=list)
    sources: List[Dict[str, Any]] = field(default_factory=list)
    execution_time: float = 0.0
    error: Optional[Dict[str, Any]] = None
    sub_retrievals: List[SubRetrievalDetail] = field(default_factory=list)


# --- Cache Implementation ---

class RetrievalCache:
    """In-memory TTL cache with stable keys including project and document type."""

    def __init__(self, max_size: int, ttl_seconds: int):
        self.cache: Dict[str, Tuple[List[NodeWithScore], float]] = {}
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds

    def _generate_key(
        self,
        query_text: str,
        top_k: int,
        similarity_threshold: float,
        project_id: Optional[int] = None,
        document_content_type: Optional[str] = None,
    ) -> str:
        """Generate cache key including project_id and document_content_type."""
        project_str = str(project_id) if project_id is not None else ""
        doc_type_str = document_content_type or ""
        key_material = f"{query_text}|{top_k}|{similarity_threshold}|{project_str}|{doc_type_str}"
        return hashlib.sha256(key_material.encode("utf-8")).hexdigest()

    def get(
        self,
        query_text: str,
        top_k: int,
        similarity_threshold: float,
        project_id: Optional[int] = None,
        document_content_type: Optional[str] = None,
    ) -> Optional[List[NodeWithScore]]:
        """Get cached results with full context matching."""
        key = self._generate_key(
            query_text, top_k, similarity_threshold, project_id, document_content_type
        )
        entry = self.cache.get(key)
        if not entry:
            return None
        results, timestamp = entry
        if time.monotonic() - timestamp > self.ttl_seconds:
            del self.cache[key]
            return None
        return results

    def set(
        self,
        query_text: str,
        top_k: int,
        similarity_threshold: float,
        results: List[NodeWithScore],
        project_id: Optional[int] = None,
        document_content_type: Optional[str] = None,
    ):
        """Set cached results with full context."""
        if len(self.cache) >= self.max_size:
            try:
                oldest_key = min(self.cache.items(), key=lambda item: item[1][1])[0]
                del self.cache[oldest_key]
            except ValueError:
                pass
        key = self._generate_key(
            query_text, top_k, similarity_threshold, project_id, document_content_type
        )
        self.cache[key] = (results, time.monotonic())


# --- Core Service ---

class UnifiedRetrievalService:
    def __init__(self, primary_index: VectorStoreIndex, secondary_index: Optional[VectorStoreIndex] = None):
        self.primary_index = primary_index
        self.secondary_index = secondary_index
        self.config = config
        self.retriever_config = self.config.retriever

        self.cache = None
        if self.retriever_config.cache.enabled:
            self.cache = RetrievalCache(
                max_size=self.retriever_config.cache.max_size,
                ttl_seconds=self.retriever_config.cache.ttl,
            )

        rerank_config = self.retriever_config.reranking
        self.reranker = CrossEncoderReranker(
            model_name=rerank_config.model,
            top_k=rerank_config.top_k
        ) if rerank_config.enabled else None

        self.primary_provider_name = "primary_vector_db"
        self.secondary_provider_name = "secondary_vector_db"

    async def retrieve_subquery(
        self,
        query_text: str,
        top_k: int,
        similarity_threshold: float,
        min_results: int,
        threshold_relax_factor: float,
        min_similarity_floor: float,
        project_id: Optional[int] = None,
        document_content_type: Optional[str] = None,
        query_id: Optional[str] = None,
        user_id: Optional[str] = None,
        original_query_text: Optional[str] = None,
    ) -> RetrieverResult:
        """Orchestrates retrieval for a single subquery with reranking and post-processing."""
        query_id = query_id or f"ret-{uuid.uuid4()}"
        total_start_time = time.monotonic()
        sub_retrievals: List[SubRetrievalDetail] = []
        final_nodes: List[NodeWithScore] = []

        log_ctx: Dict[str, Any] = {"query_id": query_id}
        if self.config.debug.include_user_ids and user_id:
            log_ctx["user_id"] = user_id
        structlog.contextvars.bind_contextvars(**log_ctx)

        log.info(
            "retrieval_started",
            query=_sanitize_for_logging(query_text),
            params={"top_k": top_k, "threshold": similarity_threshold, "min_results": min_results},
        )
        ACTIVE_RETRIEVALS.inc()

        try:
            # 1. Cache Lookup
            if self.cache:
                cached_results = self.cache.get(query_text, top_k, similarity_threshold, project_id, document_content_type)
                if cached_results is not None:
                    return RetrieverResult(
                        query_id=query_id, success=True, results=cached_results,
                        sources=self._derive_sources_from_nodes(cached_results),
                        execution_time=time.monotonic() - total_start_time,
                        sub_retrievals=[]
                    )

            # 2. Primary Retrieval
            primary_nodes = await self._try_single_retrieval(
                index=self.primary_index, provider_name=self.primary_provider_name, stage="retrieval",
                query_id=query_id, query_text=query_text, top_k=top_k,
                similarity_threshold=similarity_threshold, project_id=project_id,
                document_content_type=document_content_type, sub_details_list=sub_retrievals
            )
            final_nodes.extend(primary_nodes)

            # 3. Fallback Threshold/Secondary
            if len(self._dedupe_by_id(final_nodes)) < min_results:
                relaxed_threshold = max(min_similarity_floor, similarity_threshold * threshold_relax_factor)
                if relaxed_threshold < similarity_threshold:
                    relaxed_nodes = await self._try_single_retrieval(
                        index=self.primary_index, provider_name=self.primary_provider_name, stage="fallback-relax",
                        query_id=query_id, query_text=query_text, top_k=top_k,
                        similarity_threshold=relaxed_threshold, project_id=project_id,
                        document_content_type=document_content_type, sub_details_list=sub_retrievals
                    )
                    final_nodes.extend(relaxed_nodes)
                if self.secondary_index and len(self._dedupe_by_id(final_nodes)) < min_results:
                    secondary_nodes = await self._try_single_retrieval(
                        index=self.secondary_index, provider_name=self.secondary_provider_name, stage="fallback-secondary",
                        query_id=query_id, query_text=query_text, top_k=top_k,
                        similarity_threshold=similarity_threshold, project_id=project_id,
                        document_content_type=document_content_type, sub_details_list=sub_retrievals
                    )
                    final_nodes.extend(secondary_nodes)

            # 4. Reranking
            if self.reranker and final_nodes:
                final_nodes = self.reranker.rerank(query_text, final_nodes)

            # 5. Post-Processing
            processed_nodes = final_nodes
            try:
                post_processors = build_resilient_postprocessors(
                    query=query_text,
                    top_k=self.reranker.top_k if self.reranker else 12,
                    index=self.primary_index,
                )
                processed_nodes = process_postretrieval_pipeline(
                    nodes=final_nodes,
                    query_str=query_text,
                    postprocessors=post_processors,
                    query_id=query_id
                )
            except Exception as e:
                log.warning("post_processing_skipped", error=str(e))

            # 6. Finalize
            final_deduped_nodes = self._dedupe_by_id(processed_nodes)
            final_deduped_nodes = self._ensure_similarity_scores(final_deduped_nodes, stage="final")

            # 🚨 NEW: Fallback to original query if nothing found
            if not final_deduped_nodes and original_query_text:
                log.warning("retrieval_fallback_triggered", reason="no_results_for_subquery", fallback_query=original_query_text)
                final_deduped_nodes = await self._try_single_retrieval(
                    index=self.primary_index,
                    provider_name=self.primary_provider_name,
                    stage="fallback-original",
                    query_id=query_id,
                    query_text=original_query_text,
                    top_k=top_k,
                    similarity_threshold=0.0,
                    project_id=project_id,
                    document_content_type=document_content_type,
                    sub_details_list=sub_retrievals
                )

            if not final_deduped_nodes:
                raise RetrieverError("No documents found after all retrieval stages.", "finalization", RetrieverErrorType.NO_RESULTS_FOUND, query_id)

            total_execution_time = time.monotonic() - total_start_time

            return RetrieverResult(
                query_id=query_id, success=True, results=final_deduped_nodes,
                sources=self._derive_sources_from_nodes(final_deduped_nodes),
                execution_time=total_execution_time,
                sub_retrievals=sub_retrievals if self.config.debug.include_subquery_details else []
            )

        except RetrieverError as e:
            return self._build_error_result(e, time.monotonic() - total_start_time, sub_retrievals)
        except Exception as e:
            unhandled_error = RetrieverError(f"Unexpected error: {str(e)}", "orchestration", RetrieverErrorType.UNEXPECTED_ERROR, query_id)
            return self._build_error_result(unhandled_error, time.monotonic() - total_start_time, sub_retrievals)
        finally:
            ACTIVE_RETRIEVALS.dec()
            structlog.contextvars.clear_contextvars()

    # ----------------------------------------------------------------------
    # Helper methods (all properly indented as class methods)
    # ----------------------------------------------------------------------

    async def _try_single_retrieval(
        self, index: VectorStoreIndex, provider_name: str, stage: str,
        query_id: str, query_text: str, top_k: int, similarity_threshold: float,
        project_id: Optional[int], document_content_type: Optional[str],
        sub_details_list: List[SubRetrievalDetail]
    ) -> List[NodeWithScore]:
        """Attempts a single retrieval, with retries for transient errors."""
        start_time = time.monotonic()
        nodes: List[NodeWithScore] = []
        final_error: Optional[RetrieverError] = None
        success = False

        max_retries = 2
        initial_delay = 0.5
        backoff_factor = 2.0
        transient_errors = {
            RetrieverErrorType.TIMEOUT,
            RetrieverErrorType.CONNECTION_ERROR,
            RetrieverErrorType.RATE_LIMIT_ERROR,
        }

        log.info("sub_retrieval_started",
                 subquery_stage=stage,
                 provider=provider_name,
                 query=_sanitize_for_logging(query_text),
                 params={"top_k": top_k, "threshold": similarity_threshold})

        for attempt in range(max_retries + 1):
            try:
                nodes = await self._execute_single_retrieval(
                    index, stage, query_id, query_text, top_k,
                    similarity_threshold, project_id, document_content_type
                )
                success = True
                if attempt > 0:
                    log.info("retrieval_retry_success", attempt=attempt + 1, stage=stage)
                break
            except RetrieverError as e:
                final_error = e
                if e.error_type in transient_errors and attempt < max_retries:
                    delay = initial_delay * (backoff_factor ** attempt)
                    log.warning("retrieval_retrying",
                                attempt=attempt + 1,
                                delay=delay,
                                error=e.message,
                                error_type=e.error_type.value)
                    await asyncio.sleep(delay)
                else:
                    log.error("sub_retrieval_failed",
                              error=e.message,
                              error_type=e.error_type.value,
                              stage=stage)
                    break

        execution_time = time.monotonic() - start_time
        sub_details_list.append(SubRetrievalDetail(
            provider=provider_name,
            stage=stage,
            success=success,
            num_results=len(nodes),
            execution_time=execution_time,
            threshold=similarity_threshold,
            error=final_error.message if final_error else None,
            error_type=final_error.error_type if final_error else None,
            attempts=attempt + 1,
        ))
        return nodes

    async def _execute_single_retrieval(
        self, index: VectorStoreIndex, stage: str, query_id: str,
        query_text: str, top_k: int, similarity_threshold: float,
        project_id: Optional[int], document_content_type: Optional[str]
    ) -> List[NodeWithScore]:
        """Performs a single I/O call to a vector index with timeout + error wrapping."""
        filters = []
        if project_id is not None:
            filters.append(MetadataFilter(key="project_id", value=str(project_id)))
        if document_content_type:
            filters.append(MetadataFilter(key="document_content_type", value=document_content_type))
        metadata_filters = MetadataFilters(filters=filters) if filters else None

        retriever = index.as_retriever(
            similarity_top_k=top_k,
            vector_store_query_mode="default",
            filters=metadata_filters,
        )

        loop = asyncio.get_running_loop()
        timeout = self.config.retriever.timeouts.per_attempt
        try:
            if hasattr(retriever, "aretrieve"):
                results = await asyncio.wait_for(retriever.aretrieve(query_text), timeout=timeout)
            else:
                results = await asyncio.wait_for(loop.run_in_executor(None, retriever.retrieve, query_text), timeout=timeout)
            normalized = self._normalize_nodes(results)
            score_fixed = self._ensure_similarity_scores(normalized, stage)
            return self._apply_similarity_cutoff(score_fixed, similarity_threshold)
        except asyncio.TimeoutError as e:
            raise RetrieverError(f"Timeout after {timeout}s", stage, RetrieverErrorType.TIMEOUT, query_id) from e
        except Exception as e:
            raise RetrieverError(str(e), stage, self._classify_error(e), query_id) from e

    def _ensure_similarity_scores(self, nodes: List[NodeWithScore], stage: str) -> List[NodeWithScore]:
        """Converts distance scores to similarity (higher=better)."""
        converted = []
        converted_any = False
        for n in nodes:
            if n.score is not None and (n.score < 0 or n.score > 1.0):
                new_score = 1.0 / (1.0 + abs(n.score))
                converted.append(NodeWithScore(node=n.node, score=new_score))
                converted_any = True
            else:
                converted.append(n)
        if converted_any:
            log.info("score_conversion_applied", stage=stage)
        return converted

    def _normalize_nodes(self, nodes: Any) -> List[NodeWithScore]:
        return [] if nodes is None else (nodes if isinstance(nodes, list) else [nodes])

    def _dedupe_by_id(self, nodes: List[NodeWithScore]) -> List[NodeWithScore]:
        seen: Set[str] = set()
        deduped: List[NodeWithScore] = []
        for n in nodes:
            node_id = getattr(n, "node_id", None) or getattr(n, "id_", None)
            if node_id is None and hasattr(n, "node") and hasattr(n.node, "id_"):
                node_id = n.node.id_
            if node_id and node_id not in seen:
                seen.add(node_id)
                deduped.append(n)
        return deduped

    def _apply_similarity_cutoff(self, nodes: List[NodeWithScore], threshold: float) -> List[NodeWithScore]:
        return [n for n in nodes if n.score is None or n.score >= threshold] if threshold > 0.0 else nodes

    def _derive_sources_from_nodes(self, nodes: List[NodeWithScore]) -> List[Dict[str, Any]]:
        return [{"id": n.node.id_, "score": n.score, **n.node.metadata} for n in nodes]

    def _classify_error(self, exc: Exception) -> RetrieverErrorType:
        s = str(exc).lower()
        if "timeout" in s: return RetrieverErrorType.TIMEOUT
        if "connection" in s or "network" in s: return RetrieverErrorType.CONNECTION_ERROR
        if "auth" in s: return RetrieverErrorType.AUTHENTICATION_ERROR
        if "rate" in s: return RetrieverErrorType.RATE_LIMIT_ERROR
        if "vector" in s or "index" in s: return RetrieverErrorType.VECTOR_DB_ERROR
        return RetrieverErrorType.UNEXPECTED_ERROR

    def _build_error_result(self, e: RetrieverError, duration: float, subs: List[SubRetrievalDetail]) -> RetrieverResult:
        log.error("retrieval_failed", stage=e.stage, error=e.message, type=e.error_type.value, duration_ms=duration * 1000)
        return RetrieverResult(
            query_id=e.query_id,
            success=False,
            execution_time=duration,
            error={"message": e.message, "stage": e.stage, "type": e.error_type.value},
            sub_retrievals=subs,
        )

# --- END OF FILE retrieval_service.py ---
