# File: retriever_service.py
import logging
import time
import hashlib
from dataclasses import dataclass
from typing import Optional, List, Dict, Any, Set
from enum import Enum
import asyncio
from llama_index.core.vector_stores import MetadataFilter, MetadataFilters
from prometheus_client import Counter, Histogram, Gauge
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from llama_index.core import VectorStoreIndex
from llama_index.core.retrievers import VectorIndexRetriever
from llama_index.core.schema import NodeWithScore

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Metrics
RETRIEVAL_REQUESTS_TOTAL = Counter("retrieval_requests_total", "Total number of retrieval requests", ["provider", "status"])
RETRIEVAL_FAILURES_TOTAL = Counter("retrieval_failures_total", "Total number of retrieval failures by error type", ["error_type", "provider"])
RETRIEVAL_LATENCY_SECONDS = Histogram(
    "retrieval_latency_seconds",
    "Histogram of retrieval request latencies",
    ["provider"],
    buckets=(0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, float("inf")),
)
ACTIVE_RETRIEVALS = Gauge("active_retrievals", "Number of currently active retrieval operations")

RETRIEVAL_CACHE_HITS = Counter("retrieval_cache_hits_total", "Number of retrieval cache hits")
RETRIEVAL_MIN_RESULTS_FALLBACK = Counter("retrieval_min_results_fallback_total", "Number of times min_results fallback triggered")
RETRIEVAL_FALLBACK_SUCCESS = Counter("retrieval_fallback_success_total", "Number of successful fallbacks (secondary or relaxed-threshold)")

class ErrorType(Enum):
    TIMEOUT = "timeout"
    CONNECTION = "connection"
    AUTHENTICATION = "authentication"
    RATE_LIMIT = "rate_limit"
    VECTOR_DB = "vector_db"
    PARSING = "parsing"
    UNKNOWN = "unknown"

@dataclass
class RetrievalResult:
    success: bool
    documents: List[NodeWithScore]
    error_message: Optional[str] = None
    error_type: Optional[ErrorType] = None
    latency_ms: Optional[float] = None
    provider: Optional[str] = None
    fallback_used: bool = False
    cached: bool = False
    partial_success: bool = False

@dataclass
class RetrievalRequest:
    query_text: str
    document_id: Optional[str] = None
    top_k: int = 5
    similarity_threshold: float = 0.7
    timeout_seconds: float = 30.0
    max_retries: int = 3
    project_id: Optional[int] = None
    document_content_type: Optional[str] = None
    # New: minimum acceptable results before we try fallback logic
    min_results: int = 3
    # How much to reduce threshold when relaxing (fraction)
    threshold_relax_factor: float = 0.5
    # Minimum floor for similarity_threshold when relaxing
    min_similarity_floor: float = 0.2

class TransientRetrievalError(Exception):
    def __init__(self, message: str, error_type: ErrorType):
        super().__init__(message)
        self.error_type = error_type

class PermanentRetrievalError(Exception):
    def __init__(self, message: str, error_type: ErrorType):
        super().__init__(message)
        self.error_type = error_type

class RetrievalCache:
    """In-memory TTL cache with stable keys including project and document type."""
    def __init__(self, max_size: int = 1000, ttl_seconds: int = 3600):
        self.cache: Dict[str, tuple] = {}
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds

    def _generate_key(self, query_text: str, top_k: int, similarity_threshold: float, 
                     project_id: Optional[int] = None, document_content_type: Optional[str] = None) -> str:
        """Generate cache key including project_id and document_content_type for proper isolation."""
        # Normalize None values to empty strings for consistent hashing
        project_str = str(project_id) if project_id is not None else ""
        doc_type_str = document_content_type or ""
        
        key_material = f"{query_text}|{top_k}|{similarity_threshold}|{project_str}|{doc_type_str}"
        return hashlib.sha256(key_material.encode("utf-8")).hexdigest()

    def get(self, query_text: str, top_k: int, similarity_threshold: float,
           project_id: Optional[int] = None, document_content_type: Optional[str] = None):
        """Get cached results with full context matching."""
        key = self._generate_key(query_text, top_k, similarity_threshold, project_id, document_content_type)
        v = self.cache.get(key)
        if not v:
            return None
        results, ts = v
        if time.time() - ts > self.ttl_seconds:
            del self.cache[key]
            return None
        return results

    def set(self, query_text: str, top_k: int, similarity_threshold: float, results,
           project_id: Optional[int] = None, document_content_type: Optional[str] = None):
        """Set cached results with full context."""
        if len(self.cache) >= self.max_size:
            # evict oldest
            oldest = min(self.cache.items(), key=lambda kv: kv[1][1])[0]
            del self.cache[oldest]
        key = self._generate_key(query_text, top_k, similarity_threshold, project_id, document_content_type)
        self.cache[key] = (results, time.time())

class EnhancedRetrievalService:
    def __init__(self, primary_index: VectorStoreIndex, secondary_index: Optional[VectorStoreIndex] = None, cache_enabled: bool = True, cache_size: int = 1000, cache_ttl: int = 3600):
        self.primary_index = primary_index
        self.secondary_index = secondary_index
        self.cache = RetrievalCache(cache_size, cache_ttl) if cache_enabled else None
        self.primary_provider = "primary_vector_db"
        self.secondary_provider = "secondary_vector_db"

    def _log(self, request: RetrievalRequest, stage: str, provider: str = None, count: int = None, latency_ms: float = None, error: str = None, extra: dict = None):
        payload = {
            "stage": stage,
            "provider": provider,
            "query_preview": request.query_text[:200] + ("..." if len(request.query_text) > 200 else ""),
            "top_k": request.top_k,
            "similarity_threshold": request.similarity_threshold,
            "min_results": request.min_results,
            "project_id": request.project_id,
            "document_content_type": request.document_content_type,
            "result_count": count,
            "latency_ms": latency_ms,
            "error": error
        }
        if extra:
            payload.update(extra)
        if error:
            logger.error("retrieval", extra=payload)
        else:
            logger.info("retrieval", extra=payload)

    def _classify_error(self, exception: Exception) -> ErrorType:
        s = str(exception).lower()
        if "timeout" in s or "timed out" in s:
            return ErrorType.TIMEOUT
        if "connection" in s or "network" in s:
            return ErrorType.CONNECTION
        if "auth" in s or "permission" in s:
            return ErrorType.AUTHENTICATION
        if "rate" in s or "limit" in s:
            return ErrorType.RATE_LIMIT
        if "vector" in s or "index" in s:
            return ErrorType.VECTOR_DB
        if "parse" in s or "format" in s:
            return ErrorType.PARSING
        return ErrorType.UNKNOWN

    def _should_retry(self, error_type: ErrorType) -> bool:
        return error_type in {ErrorType.TIMEOUT, ErrorType.CONNECTION, ErrorType.RATE_LIMIT, ErrorType.VECTOR_DB}

    def _normalize_nodes(self, nodes) -> List[NodeWithScore]:
        # Defensive: ensure return is list of NodeWithScore-like objects
        if nodes is None:
            return []
        if isinstance(nodes, list):
            return nodes
        # If single node returned, wrap
        return [nodes]

    def _dedupe_by_id(self, nodes: List[NodeWithScore]) -> List[NodeWithScore]:
        seen: Set[str] = set()
        out: List[NodeWithScore] = []
        for n in nodes:
            node_id = getattr(n, "node_id", None) or getattr(n, "id_", None) or (getattr(n, "node", None) and getattr(n.node, "id_", None))
            if node_id is None:
                # fallback to chunk metadata if present
                meta = getattr(n, "metadata", {}) if hasattr(n, "metadata") else {}
                node_id = meta.get("chunk_id") or meta.get("chunkId") or meta.get("id")
            key = str(node_id) if node_id is not None else str(id(n))
            if key in seen:
                continue
            seen.add(key)
            out.append(n)
        return out

    def _apply_similarity_cutoff(self, nodes: List[NodeWithScore], threshold: float) -> List[NodeWithScore]:
        """Apply similarity threshold cutoff in post-processing."""
        if threshold <= 0.0:
            return nodes
        
        filtered_nodes = []
        for node in nodes:
            # Get similarity score - handle different possible score attributes
            score = getattr(node, 'score', None)
            if score is None and hasattr(node, 'node'):
                score = getattr(node.node, 'score', None)
            
            # If we can't find a score, include the node (conservative approach)
            if score is None or score >= threshold:
                filtered_nodes.append(node)
        
        return filtered_nodes

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10), retry=retry_if_exception_type(TransientRetrievalError), reraise=True)
    async def _perform_retrieval_with_timeout(self, index: VectorStoreIndex, request: RetrievalRequest, provider: str):
        start = time.time()
        # Build vector_store_kwargs if metadata filters provided
        vector_store_kwargs = {}
        if request.project_id is not None:
            filters = [MetadataFilter(key="project_id", value=str(request.project_id))]
            if request.document_content_type:
                filters.append(MetadataFilter(key="document_type", value=request.document_content_type))
            vector_store_kwargs["filters"] = MetadataFilters(filters=filters)

        try:
            # Use similarity_cutoff=0.0 to get all results, apply threshold in post-processing
            retriever: VectorIndexRetriever = index.as_retriever(
                similarity_top_k=request.top_k,
                similarity_cutoff=0.0,  # Get all results, filter later
                vector_store_kwargs=vector_store_kwargs if vector_store_kwargs else None,
            )

            loop = asyncio.get_running_loop()
            # run blocking call in executor
            future = loop.run_in_executor(None, retriever.retrieve, request.query_text)
            results = await asyncio.wait_for(future, timeout=request.timeout_seconds)

            elapsed = time.time() - start
            if elapsed > request.timeout_seconds + 0.5:
                raise TransientRetrievalError(f"retrieval exceeded timeout ({elapsed:.2f}s)", ErrorType.TIMEOUT)

            # Normalize and apply similarity cutoff in post-processing
            normalized_results = self._normalize_nodes(results)
            filtered_results = self._apply_similarity_cutoff(normalized_results, request.similarity_threshold)
            
            return filtered_results

        except asyncio.TimeoutError as te:
            raise TransientRetrievalError(f"timeout: {str(te)}", ErrorType.TIMEOUT)
        except TransientRetrievalError:
            raise
        except Exception as e:
            err_type = self._classify_error(e)
            if self._should_retry(err_type):
                raise TransientRetrievalError(f"transient: {str(e)}", err_type)
            else:
                raise PermanentRetrievalError(f"permanent: {str(e)}", err_type)

    async def retrieve_documents(self, request: RetrievalRequest) -> RetrievalResult:
        start_time = time.time()
        ACTIVE_RETRIEVALS.inc()
        provider_used = None
        try:
            # 1) cache - now includes project_id and document_content_type
            if self.cache:
                cached = self.cache.get(
                    request.query_text, 
                    request.top_k, 
                    request.similarity_threshold,
                    request.project_id,
                    request.document_content_type
                )
                if cached:
                    latency_ms = (time.time() - start_time) * 1000
                    self._log(request, "cache_hit", provider="cache", count=len(cached), latency_ms=latency_ms)
                    RETRIEVAL_CACHE_HITS.inc()
                    RETRIEVAL_REQUESTS_TOTAL.labels(provider="cache", status="success").inc()
                    RETRIEVAL_LATENCY_SECONDS.labels(provider="cache").observe(latency_ms / 1000)
                    return RetrievalResult(success=True, documents=cached, latency_ms=latency_ms, provider="cache", cached=True)

            # 2) primary try
            provider_used = self.primary_provider
            self._log(request, "primary_start", provider=provider_used)
            try:
                primary_results = await self._perform_retrieval_with_timeout(self.primary_index, request, provider_used)
                primary_results = self._normalize_nodes(primary_results)
                primary_results = self._dedupe_by_id(primary_results)

                latency_ms = (time.time() - start_time) * 1000
                self._log(request, "primary_success", provider=provider_used, count=len(primary_results), latency_ms=latency_ms)
                RETRIEVAL_REQUESTS_TOTAL.labels(provider=provider_used, status="success").inc()
                RETRIEVAL_LATENCY_SECONDS.labels(provider=provider_used).observe(latency_ms / 1000)

                # Cache primary results with full context
                if self.cache and primary_results:
                    self.cache.set(
                        request.query_text, 
                        request.top_k, 
                        request.similarity_threshold, 
                        primary_results,
                        request.project_id,
                        request.document_content_type
                    )

                # If we have enough results, return
                if len(primary_results) >= request.min_results:
                    return RetrievalResult(success=True, documents=primary_results, latency_ms=latency_ms, provider=provider_used)

                # Not enough results -> apply min-results fallback logic
                RETRIEVAL_MIN_RESULTS_FALLBACK.inc()
                self._log(request, "min_results_short", provider=provider_used, count=len(primary_results))

                # 2a) Try relaxing threshold on primary (if allowed)
                relaxed_threshold = max(request.min_similarity_floor, request.similarity_threshold * request.threshold_relax_factor)
                if relaxed_threshold < request.similarity_threshold:
                    relaxed_req = RetrievalRequest(
                        query_text=request.query_text,
                        document_id=request.document_id,
                        top_k=request.top_k,
                        similarity_threshold=relaxed_threshold,
                        timeout_seconds=request.timeout_seconds,
                        max_retries=request.max_retries,
                        project_id=request.project_id,
                        document_content_type=request.document_content_type,
                        min_results=request.min_results,
                        threshold_relax_factor=request.threshold_relax_factor,
                        min_similarity_floor=request.min_similarity_floor,
                    )
                    try:
                        self._log(relaxed_req, "relaxed_threshold_retry", provider=provider_used, extra={"from_threshold": request.similarity_threshold, "to_threshold": relaxed_threshold})
                        relaxed_results = await self._perform_retrieval_with_timeout(self.primary_index, relaxed_req, provider_used)
                        relaxed_results = self._dedupe_by_id(self._normalize_nodes(relaxed_results))
                        latency_ms = (time.time() - start_time) * 1000
                        if relaxed_results and len(relaxed_results) >= request.min_results:
                            RETRIEVAL_FALLBACK_SUCCESS.inc()
                            self._log(relaxed_req, "relaxed_threshold_success", provider=provider_used, count=len(relaxed_results), latency_ms=latency_ms)
                            # cache relaxed results with its own context
                            if self.cache:
                                self.cache.set(
                                    relaxed_req.query_text, 
                                    relaxed_req.top_k, 
                                    relaxed_req.similarity_threshold, 
                                    relaxed_results,
                                    relaxed_req.project_id,
                                    relaxed_req.document_content_type
                                )
                            return RetrievalResult(success=True, documents=relaxed_results, latency_ms=latency_ms, provider=provider_used, fallback_used=True, partial_success=False)
                        # if relaxed produced more docs but still < min_results, continue to fallback secondary
                    except (TransientRetrievalError, PermanentRetrievalError) as re:
                        self._log(request, "relaxed_retry_failed", provider=provider_used, error=str(re))
                        # fallthrough to secondary if configured

                # 2b) Try secondary index (if provided)
                if self.secondary_index:
                    provider_used = self.secondary_provider
                    try:
                        self._log(request, "secondary_start", provider=provider_used)
                        secondary_results = await self._perform_retrieval_with_timeout(self.secondary_index, request, provider_used)
                        secondary_results = self._normalize_nodes(secondary_results)
                        # combine primary + secondary and dedupe
                        combined = primary_results + secondary_results
                        combined = self._dedupe_by_id(combined)
                        latency_ms = (time.time() - start_time) * 1000
                        if combined:
                            RETRIEVAL_FALLBACK_SUCCESS.inc()
                            self._log(request, "secondary_success", provider=provider_used, count=len(combined), latency_ms=latency_ms)
                            # cache combined with full context
                            if self.cache:
                                self.cache.set(
                                    request.query_text, 
                                    request.top_k, 
                                    request.similarity_threshold, 
                                    combined,
                                    request.project_id,
                                    request.document_content_type
                                )
                            partial_flag = len(combined) < request.min_results
                            return RetrievalResult(success=True, documents=combined, latency_ms=latency_ms, provider=provider_used, fallback_used=True, partial_success=partial_flag)
                        else:
                            # secondary returned nothing
                            self._log(request, "secondary_empty", provider=provider_used)
                    except (TransientRetrievalError, PermanentRetrievalError) as se:
                        latency_ms = (time.time() - start_time) * 1000
                        self._log(request, "secondary_failed", provider=provider_used, error=str(se), latency_ms=latency_ms)
                        RETRIEVAL_FAILURES_TOTAL.labels(error_type=se.error_type.value if hasattr(se, "error_type") else "unknown", provider=provider_used).inc()
                        RETRIEVAL_REQUESTS_TOTAL.labels(provider=provider_used, status="failed").inc()

                # If we reached here, both primary (including relaxed) and secondary failed to meet min_results.
                latency_ms = (time.time() - start_time) * 1000
                # return primary results if any (partial) otherwise empty with failure flag
                if primary_results:
                    self._log(request, "return_partial_primary", provider=self.primary_provider, count=len(primary_results), latency_ms=latency_ms)
                    return RetrievalResult(success=True, documents=primary_results, latency_ms=latency_ms, provider=self.primary_provider, partial_success=True)
                else:
                    self._log(request, "no_results_found", provider=self.primary_provider, latency_ms=latency_ms)
                    return RetrievalResult(success=False, documents=[], error_message="No documents found", error_type=ErrorType.UNKNOWN, latency_ms=latency_ms, provider=self.primary_provider)

            except (TransientRetrievalError, PermanentRetrievalError) as e:
                # primary provider failure -> try secondary for transient errors
                latency_ms = (time.time() - start_time) * 1000
                self._log(request, "primary_failed", provider=self.primary_provider, error=str(e), latency_ms=latency_ms)
                RETRIEVAL_FAILURES_TOTAL.labels(error_type=e.error_type.value if hasattr(e, "error_type") else "unknown", provider=self.primary_provider).inc()
                RETRIEVAL_REQUESTS_TOTAL.labels(provider=self.primary_provider, status="failed").inc()

                if isinstance(e, TransientRetrievalError) and self.secondary_index:
                    provider_used = self.secondary_provider
                    try:
                        self._log(request, "secondary_fallback_start", provider=provider_used)
                        secondary_results = await self._perform_retrieval_with_timeout(self.secondary_index, request, provider_used)
                        secondary_results = self._normalize_nodes(secondary_results)
                        secondary_results = self._dedupe_by_id(secondary_results)
                        latency_ms = (time.time() - start_time) * 1000
                        self._log(request, "secondary_fallback_success", provider=provider_used, count=len(secondary_results), latency_ms=latency_ms)
                        RETRIEVAL_FALLBACK_SUCCESS.inc()
                        RETRIEVAL_REQUESTS_TOTAL.labels(provider=provider_used, status="success").inc()
                        RETRIEVAL_LATENCY_SECONDS.labels(provider=provider_used).observe(latency_ms / 1000)
                        return RetrievalResult(success=True, documents=secondary_results, latency_ms=latency_ms, provider=provider_used, fallback_used=True)
                    except (TransientRetrievalError, PermanentRetrievalError) as e2:
                        latency_ms = (time.time() - start_time) * 1000
                        self._log(request, "secondary_fallback_failed", provider=provider_used, error=str(e2), latency_ms=latency_ms)
                        RETRIEVAL_FAILURES_TOTAL.labels(error_type=e2.error_type.value if hasattr(e2, "error_type") else "unknown", provider=provider_used).inc()
                        RETRIEVAL_REQUESTS_TOTAL.labels(provider=provider_used, status="failed").inc()

                # If no fallback or fallback failed, return error
                return RetrievalResult(success=False, documents=[], error_message=str(e), error_type=e.error_type if hasattr(e, "error_type") else ErrorType.UNKNOWN, latency_ms=latency_ms, provider=self.primary_provider)

        except Exception as unexpected:
            latency_ms = (time.time() - start_time) * 1000
            err_type = self._classify_error(unexpected)
            self._log(request, "unexpected_error", provider=provider_used or "unknown", error=str(unexpected), latency_ms=latency_ms)
            RETRIEVAL_FAILURES_TOTAL.labels(error_type=err_type.value, provider=provider_used or "unknown").inc()
            return RetrievalResult(success=False, documents=[], error_message=str(unexpected), error_type=err_type, latency_ms=latency_ms, provider=provider_used or "unknown")
        finally:
            ACTIVE_RETRIEVALS.dec()

def build_metadata_filtered_retriever(index: VectorStoreIndex, project_id: int, document_content_type: Optional[str] = None, top_k: int = 5, similarity_threshold: float = 0.7) -> VectorIndexRetriever:
    """Create retriever with enforced metadata filters."""
    filters = [MetadataFilter(key="project_id", value=str(project_id))]
    if document_content_type:
        filters.append(MetadataFilter(key="document_type", value=document_content_type))
    meta_filters = MetadataFilters(filters=filters)

    # Use similarity_cutoff=0.0 to get all results, caller can apply threshold as needed
    retriever = index.as_retriever(similarity_top_k=top_k, similarity_cutoff=0.0, vector_store_kwargs={"filters": meta_filters})
    logger.info("Built metadata-filtered retriever", extra={"project_id": project_id, "document_type": document_content_type, "top_k": top_k})
    return retriever