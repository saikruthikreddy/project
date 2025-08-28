# query_engine.py
import logging
import time
import hashlib
import json
import uuid
from typing import Optional, Dict, Any, Union, List
from dataclasses import dataclass, asdict
from functools import wraps
import asyncio

import structlog
import redis
from prometheus_client import Histogram, Counter
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)

from llama_index.core.response_synthesizers import CompactAndRefine
from llama_index.core import VectorStoreIndex
from llama_index.core.schema import QueryBundle, NodeWithScore
from llama_index.core.base.response.schema import Response

from services.rag.retrieval_service import build_metadata_filtered_retriever

from rag.post_retrieval import build_postprocessors
from rag.reranker import CrossEncoderReranker  # NEW: cross-encoder reranker

# -----------------------------------------------------------------------------
# Logging / Metrics
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

QUERY_DURATION = Histogram(
    "query_execution_seconds",
    "Time spent in query execution",
    ["stage", "query_id", "user_id"],
)

QUERY_FAILURES = Counter(
    "query_execution_failures_total",
    "Number of query execution failures",
    ["stage", "error_type", "query_id", "user_id"],
)

QUERY_CACHE_HITS = Counter(
    "query_cache_hits_total",
    "Number of query cache hits",
    ["cache_type", "user_id"],
)

QUERY_CACHE_MISSES = Counter(
    "query_cache_misses_total",
    "Number of query cache misses",
    ["cache_type", "user_id"],
)

# -----------------------------------------------------------------------------
# Config / Models
# -----------------------------------------------------------------------------
@dataclass
class QueryEngineConfig:
    """Configuration for query engine reliability and performance."""
    # Retry configuration
    max_retry_attempts: int = 3
    retry_wait_multiplier: int = 2
    retry_wait_max: int = 10

    # Timeout configuration (seconds)
    retrieval_timeout: int = 60
    synthesis_timeout: int = 120
    total_query_timeout: int = 300

    # Cache configuration
    enable_memory_cache: bool = True
    enable_redis_cache: bool = False
    memory_cache_ttl: int = 300  # 5 minutes
    redis_cache_ttl: int = 1800  # 30 minutes
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0

    # Performance configuration
    max_cache_size: int = 1000
    cache_compression: bool = True
    similarity_cutoff: float = 0.0  # NEW: similarity threshold for post-processing

    # Observability
    enable_metrics: bool = True
    enable_detailed_logging: bool = True

@dataclass
class QueryResult:
    """Structured query result with metadata."""
    response: Optional[Response] = None
    query_id: str = ""
    user_id: Optional[str] = None
    success: bool = False
    error_message: Optional[str] = None
    error_type: Optional[str] = None
    execution_time: float = 0.0
    cache_hit: bool = False
    stages_completed: Dict[str, bool] = None

    def __post_init__(self):
        if self.stages_completed is None:
            self.stages_completed = {}

class QueryCache:
    """Multi-tier caching system for query results."""

    def __init__(self, config: QueryEngineConfig):
        self.config = config
        self._memory_cache: Dict[str, tuple] = {}  # (result, timestamp)
        self._redis_client = None

        if config.enable_redis_cache:
            try:
                self._redis_client = redis.Redis(
                    host=config.redis_host,
                    port=config.redis_port,
                    db=config.redis_db,
                    decode_responses=True,
                    socket_timeout=5,
                    socket_connect_timeout=5,
                )
                self._redis_client.ping()
                logger.info("Redis cache initialized successfully")
            except Exception as e:
                logger.warning("Failed to initialize Redis cache", error=str(e))
                self._redis_client = None

    def _generate_cache_key(
        self, query_text: str, user_id: Optional[str], project_id: int, **kwargs
    ) -> str:
        cache_data = {
            "query": query_text.strip().lower(),
            "user_id": user_id,
            "project_id": project_id,
            **{k: v for k, v in kwargs.items() if v is not None},
        }
        cache_str = json.dumps(cache_data, sort_keys=True)
        return hashlib.md5(cache_str.encode()).hexdigest()

    def get(
        self, query_text: str, user_id: Optional[str], project_id: int, **kwargs
    ) -> Optional[QueryResult]:
        cache_key = self._generate_cache_key(query_text, user_id, project_id, **kwargs)

        # Memory
        if self.config.enable_memory_cache:
            if cache_key in self._memory_cache:
                result, timestamp = self._memory_cache[cache_key]
                if time.time() - timestamp < self.config.memory_cache_ttl:
                    if self.config.enable_metrics:
                        QUERY_CACHE_HITS.labels(
                            cache_type="memory", user_id=user_id or "anonymous"
                        ).inc()
                    logger.info("Memory cache hit", cache_key=cache_key[:8])
                    result.cache_hit = True
                    return result
                else:
                    del self._memory_cache[cache_key]

        # Redis
        if self._redis_client:
            try:
                cached_data = self._redis_client.get(f"query:{cache_key}")
                if cached_data:
                    result = QueryResult(**json.loads(cached_data))
                    if self.config.enable_metrics:
                        QUERY_CACHE_HITS.labels(
                            cache_type="redis", user_id=user_id or "anonymous"
                        ).inc()
                    logger.info("Redis cache hit", cache_key=cache_key[:8])
                    result.cache_hit = True
                    return result
            except Exception as e:
                logger.warning("Redis cache get failed", error=str(e))

        if self.config.enable_metrics:
            QUERY_CACHE_MISSES.labels(
                cache_type="combined", user_id=user_id or "anonymous"
            ).inc()

        return None

    def set(
        self,
        query_text: str,
        user_id: Optional[str],
        project_id: int,
        result: QueryResult,
        **kwargs,
    ):
        cache_key = self._generate_cache_key(query_text, user_id, project_id, **kwargs)

        # Memory
        if self.config.enable_memory_cache:
            if len(self._memory_cache) >= self.config.max_cache_size:
                oldest_key = min(
                    self._memory_cache.keys(),
                    key=lambda k: self._memory_cache[k][1],
                )
                del self._memory_cache[oldest_key]
            self._memory_cache[cache_key] = (result, time.time())
            logger.debug("Cached result in memory", cache_key=cache_key[:8])

        # Redis
        if self._redis_client:
            try:
                cache_result = QueryResult(
                    response=None,
                    query_id=result.query_id,
                    user_id=result.user_id,
                    success=result.success,
                    error_message=result.error_message,
                    error_type=result.error_type,
                    execution_time=result.execution_time,
                    cache_hit=False,
                    stages_completed=result.stages_completed,
                )
                self._redis_client.setex(
                    f"query:{cache_key}",
                    self.config.redis_cache_ttl,
                    json.dumps(asdict(cache_result)),
                )
                logger.debug("Cached result in Redis", cache_key=cache_key[:8])
            except Exception as e:
                logger.warning("Redis cache set failed", error=str(e))

class QueryMetrics:
    """Context manager for query execution metrics and logging."""

    def __init__(
        self,
        stage: str,
        query_id: str,
        user_id: Optional[str],
        config: QueryEngineConfig,
    ):
        self.stage = stage
        self.query_id = query_id
        self.user_id = user_id or "anonymous"
        self.config = config
        self.start_time = None

    def __enter__(self):
        self.start_time = time.time()
        if self.config.enable_detailed_logging:
            logger.info(
                "Starting query stage",
                stage=self.stage,
                query_id=self.query_id,
                user_id=self.user_id,
            )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        duration = time.time() - self.start_time
        if self.config.enable_metrics:
            QUERY_DURATION.labels(
                stage=self.stage, query_id=self.query_id, user_id=self.user_id
            ).observe(duration)

        if exc_type:
            error_type = exc_type.__name__
            if self.config.enable_metrics:
                QUERY_FAILURES.labels(
                    stage=self.stage,
                    error_type=error_type,
                    query_id=self.query_id,
                    user_id=self.user_id,
                ).inc()
            if self.config.enable_detailed_logging:
                logger.error(
                    "Query stage failed",
                    stage=self.stage,
                    query_id=self.query_id,
                    user_id=self.user_id,
                    error_type=error_type,
                    duration=duration,
                    error=str(exc_val),
                )
        else:
            if self.config.enable_detailed_logging:
                logger.info(
                    "Query stage completed",
                    stage=self.stage,
                    query_id=self.query_id,
                    user_id=self.user_id,
                    duration=duration,
                )

# -----------------------------------------------------------------------------
# Resilient Query Engine (with cross-encoder reranker)
# -----------------------------------------------------------------------------
class ResilientQueryEngine:
    """
    Retrieval -> Cross-Encoder Rerank (24→12) -> Post-Processing -> Synthesis.
    - Retrieval uses enforced metadata filters (project_id, document_type).
    - Reranker happens BEFORE other post-processors.
    """

    def __init__(
        self,
        index: VectorStoreIndex,
        project_id: int,
        document_content_type: Optional[str] = None,
        top_k: int = 12,
        config: Optional[QueryEngineConfig] = None,
        enable_reranker: bool = True,
    ):
        self.index = index
        self.project_id = project_id
        self.document_content_type = document_content_type
        self.top_k = max(1, top_k)
        self.config = config or QueryEngineConfig()

        # Cache
        self._cache = QueryCache(self.config)

        # Synthesizer
        self._synthesizer = CompactAndRefine()

        # Reranker (NEW)
        self._reranker: Optional[CrossEncoderReranker] = (
            CrossEncoderReranker(top_k=self.top_k) if enable_reranker else None
        )

    # -------------------- Internal helpers --------------------
    def _build_resilient_retriever(self):
        """Build retriever with enforced metadata filters."""
        try:
            # Expand retrieval pool (e.g., 24) to give reranker headroom
            return build_metadata_filtered_retriever(
                index=self.index,
                project_id=self.project_id,
                document_content_type=self.document_content_type,
                top_k=max(self.top_k * 2, 16),
                similarity_threshold=0.0,  # cutoff handled later if needed
            )
        except Exception as e:
            logger.error("Failed to build retriever", error=str(e))
            raise

    def _retrieve_nodes(
        self, query_bundle: QueryBundle, query_id: str, user_id: Optional[str]
    ) -> List[NodeWithScore]:
        """Retrieve nodes with timeout & metrics."""
        with QueryMetrics("retrieval", query_id, user_id, self.config):
            retriever = self._build_resilient_retriever()

            # Try async retrieval if available; else fallback to sync
            if hasattr(retriever, "aretrieve"):
                async def _run():
                    return await asyncio.wait_for(
                        retriever.aretrieve(query_bundle),
                        timeout=self.config.retrieval_timeout,
                    )
                try:
                    return asyncio.run(_run())
                except RuntimeError:
                    # Already in an event loop (e.g., FastAPI) — run in thread
                    loop = asyncio.get_event_loop()
                    coro = retriever.aretrieve(query_bundle)
                    return loop.run_until_complete(
                        asyncio.wait_for(coro, timeout=self.config.retrieval_timeout)
                    )
            else:
                # Synchronous retrieval (best-effort timeout via thread)
                nodes: List[NodeWithScore] = []

                def _work():
                    nonlocal nodes
                    nodes = retriever.retrieve(query_bundle)

                loop = asyncio.new_event_loop()
                try:
                    loop.run_until_complete(
                        asyncio.wait_for(loop.run_in_executor(None, _work), timeout=self.config.retrieval_timeout)
                    )
                except Exception:
                    # As a fallback (envs without executors), just call directly
                    nodes = retriever.retrieve(query_bundle)
                finally:
                    loop.close()

                return nodes

    def _rerank_nodes(
        self,
        nodes: List[NodeWithScore],
        query_text: str,
        query_id: str,
        user_id: Optional[str],
    ) -> List[NodeWithScore]:
        """Cross-encoder rerank BEFORE other post-processing."""
        if not self._reranker or not nodes:
            return nodes
        with QueryMetrics("rerank", query_id, user_id, self.config):
            try:
                return self._reranker.rerank(query_text, nodes)
            except Exception as e:
                logger.warning("Reranker failed; proceeding without rerank", error=str(e))
                return nodes

    def _post_process_nodes(
        self,
        nodes: List[NodeWithScore],
        query_text: str,
        query_id: str,
        user_id: Optional[str],
    ) -> List[NodeWithScore]:
        """Run post-processors in the correct order."""
        with QueryMetrics("post_process", query_id, user_id, self.config):
            try:
                postprocessors = build_postprocessors(
                    query_text,
                    self.top_k,
                    self.index,
                    self.config.similarity_cutoff
                )
                processed = nodes
                for p in postprocessors:
                    processed = p.postprocess_nodes(processed, query_text)
                return processed
            except Exception as e:
                logger.warning("Post-processing failed; returning original nodes", error=str(e))
                return nodes

    def _synthesize_response(
        self,
        processed_nodes: List[NodeWithScore],
        query_bundle: QueryBundle,
        query_id: str,
        user_id: Optional[str],
    ) -> Response:
        """Compact-and-Refine synthesis over processed nodes."""
        with QueryMetrics("synthesis", query_id, user_id, self.config):
            # In LlamaIndex, the synthesizer can be called directly with nodes
            return self._synthesizer.synthesize(query_bundle, processed_nodes)

    # -------------------- Public API --------------------
    @retry(
        stop=stop_after_attempt(QueryEngineConfig.max_retry_attempts if hasattr(QueryEngineConfig, "max_retry_attempts") else 3),
        wait=wait_exponential(
            multiplier=QueryEngineConfig.retry_wait_multiplier if hasattr(QueryEngineConfig, "retry_wait_multiplier") else 2,
            max=QueryEngineConfig.retry_wait_max if hasattr(QueryEngineConfig, "retry_wait_max") else 10,
        ),
        retry=retry_if_exception_type((ConnectionError, TimeoutError, IOError)),
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )
    def query(
        self,
        query_text: str,
        user_id: Optional[str] = None,
        use_cache: bool = True,
    ) -> QueryResult:
        """
        Full pipeline:
        1) Cache check
        2) Retrieval (metadata-filtered)
        3) Cross-encoder rerank (24→12)
        4) Post-processing
        5) Synthesis
        """
        start = time.time()
        query_id = str(uuid.uuid4())
        result = QueryResult(query_id=query_id, user_id=user_id, success=False, stages_completed={})

        # Total timeout guard (best-effort)
        deadline = start + self.config.total_query_timeout

        # Cache
        if use_cache:
            cached = self._cache.get(
                query_text, user_id, self.project_id,
                document_content_type=self.document_content_type,
                top_k=self.top_k,
                similarity_cutoff=self.config.similarity_cutoff,
            )
            if cached:
                cached.execution_time = time.time() - start
                return cached

        try:
            # Build query bundle
            qb = QueryBundle(query_str=query_text)

            # 1) Retrieve
            nodes = self._retrieve_nodes(qb, query_id, user_id)
            result.stages_completed["retrieval"] = True

            # 2) Rerank (NEW)
            if time.time() > deadline:
                raise TimeoutError("Total query timeout exceeded before rerank")
            nodes = self._rerank_nodes(nodes, query_text, query_id, user_id)
            result.stages_completed["rerank"] = True

            # 3) Post-process
            if time.time() > deadline:
                raise TimeoutError("Total query timeout exceeded before post-processing")
            nodes = self._post_process_nodes(nodes, query_text, query_id, user_id)
            result.stages_completed["post_process"] = True

            # 4) Synthesize
            if time.time() > deadline:
                raise TimeoutError("Total query timeout exceeded before synthesis")
            response = self._synthesize_response(nodes, qb, query_id, user_id)
            result.stages_completed["synthesis"] = True

            result.response = response
            result.success = True
            result.execution_time = time.time() - start

            # Cache lightweight metadata (we don't cache the full response object in Redis)
            self._cache.set(
                query_text,
                user_id,
                self.project_id,
                result,
                document_content_type=self.document_content_type,
                top_k=self.top_k,
                similarity_cutoff=self.config.similarity_cutoff,
            )

            return result

        except Exception as e:
            result.success = False
            result.error_message = str(e)
            result.error_type = type(e).__name__
            result.execution_time = time.time() - start
            if self.config.enable_detailed_logging:
                logger.error(
                    "Query execution failed",
                    query_id=query_id,
                    user_id=user_id or "anonymous",
                    error=str(e),
                    error_type=type(e).__name__,
                )
            return result

# -----------------------------------------------------------------------------
# Factory
# -----------------------------------------------------------------------------
def build_query_engine(
    index: VectorStoreIndex,
    project_id: int,
    document_content_type: Optional[str] = None,
    top_k: int = 12,
    config: Optional[QueryEngineConfig] = None,
    enable_reranker: bool = True,
    similarity_cutoff: float = 0.0,
) -> ResilientQueryEngine:
    """
    Convenience factory for ResilientQueryEngine.
    """
    if config is None:
        config = QueryEngineConfig()

    # Set similarity_cutoff in config if provided
    config.similarity_cutoff = similarity_cutoff

    return ResilientQueryEngine(
        index=index,
        project_id=project_id,
        document_content_type=document_content_type,
        top_k=top_k,
        config=config,
        enable_reranker=enable_reranker,
    )