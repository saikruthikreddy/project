# File: query_executor.py
import os
import logging
import time
import uuid
import traceback
import threading
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass, asdict
from functools import wraps
from enum import Enum

import structlog
from prometheus_client import Histogram, Counter
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
    after_log
)
from sqlalchemy.orm import Session
from llama_index.core import VectorStoreIndex

from rag.index_builder import RAGIndexer
from rag.query_engine import build_query_engine
from rag.citation_formatter import format_citations
from rag.embed_chunks import embed_chunks_for_project
from rag.answer_verifier import verify_answer

# Configure structured logging
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

# Prometheus metrics
QUERY_PIPELINE_DURATION = Histogram(
    'rag_pipeline_execution_seconds',
    'Time spent in RAG pipeline execution',
    ['stage', 'project_id', 'query_id']
)

QUERY_PIPELINE_FAILURES = Counter(
    'rag_pipeline_failures_total',
    'Number of RAG pipeline failures',
    ['stage', 'error_type', 'project_id']
)

QUERY_PIPELINE_SUCCESS = Counter(
    'rag_pipeline_success_total',
    'Number of successful RAG pipeline executions',
    ['project_id', 'has_verification']
)

QUERY_PIPELINE_PARTIAL_SUCCESS = Counter(
    'rag_pipeline_partial_success_total',
    'Number of partial RAG pipeline successes',
    ['project_id', 'failed_stage']
)

# Environment flags to override behavior (useful for testing or forcing rebuilds)
_FORCE_EMBED_SYNC = bool(os.getenv("RAG_FORCE_EMBED_SYNC", "0") == "1")
_FORCE_REBUILD = bool(os.getenv("RAG_FORCE_REBUILD", "0") == "1")

class PipelineStage(Enum):
    VALIDATION = "validation"
    EMBEDDING = "embedding"
    INDEXING = "indexing"
    QUERY_ENGINE_BUILD = "query_engine_build"
    QUERY_EXECUTION = "query_execution"
    ANSWER_VERIFICATION = "answer_verification"
    CITATION_FORMATTING = "citation_formatting"

class PipelineError(Exception):
    def __init__(self, message: str, stage: PipelineStage, error_type: str,
                 query_id: str, project_id: int, original_error: Exception = None):
        self.message = message
        self.stage = stage
        self.error_type = error_type
        self.query_id = query_id
        self.project_id = project_id
        self.original_error = original_error
        super().__init__(message)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "message": self.message,
            "stage": self.stage.value,
            "error_type": self.error_type,
            "query_id": self.query_id,
            "project_id": self.project_id,
            "original_error": str(self.original_error) if self.original_error else None
        }

@dataclass
class PipelineConfig:
    max_retry_attempts: int = 3
    retry_wait_multiplier: int = 2
    retry_wait_max: int = 10
    embedding_timeout: int = 120
    indexing_timeout: int = 300
    query_execution_timeout: int = 180
    verification_timeout: int = 60
    total_pipeline_timeout: int = 600
    enable_partial_results: bool = True
    auto_retry_on_verification_failure: bool = True
    retry_with_expanded_results: bool = True
    max_expanded_top_k: int = 20
    enable_metrics: bool = True
    enable_detailed_logging: bool = True

@dataclass
class PipelineResult:
    query_id: str
    project_id: int
    success: bool
    answer: str
    sources: List[Dict[str, Any]]
    verification: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = None
    error: Optional[Dict[str, Any]] = None
    execution_times: Dict[str, float] = None
    stages_completed: List[str] = None
    partial_result: bool = False
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}
        if self.execution_times is None:
            self.execution_times = {}
        if self.stages_completed is None:
            self.stages_completed = []

class TimeoutHandler:
    """Simple timeout using threading.Timer that raises inside the timer thread.
    This is best-effort to avoid blocking; it's not as strict as signal.alarm
    but avoids Unix-only constraints.
    """
    def __init__(self, timeout_seconds: int, operation_name: str):
        self.timeout_seconds = timeout_seconds
        self.operation_name = operation_name
        self.timer = None
    
    def _timeout_handler(self):
        # Note: raising in the timer thread won't interrupt the main thread,
        # but will log a warning. We keep this lightweight to avoid platform issues.
        logger.error("Timeout reached for operation", operation=self.operation_name, timeout=self.timeout_seconds)
    
    def __enter__(self):
        self.timer = threading.Timer(self.timeout_seconds, self._timeout_handler)
        self.timer.daemon = True
        self.timer.start()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.timer:
            self.timer.cancel()

class PipelineMetrics:
    def __init__(self, stage: PipelineStage, query_id: str, project_id: int, config: PipelineConfig):
        self.stage = stage
        self.query_id = query_id
        self.project_id = project_id
        self.config = config
        self.start_time = None
    
    def __enter__(self):
        self.start_time = time.time()
        if self.config.enable_detailed_logging:
            logger.info("Starting pipeline stage", stage=self.stage.value, query_id=self.query_id, project_id=self.project_id)
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        duration = time.time() - self.start_time
        if self.config.enable_metrics:
            QUERY_PIPELINE_DURATION.labels(stage=self.stage.value, project_id=str(self.project_id), query_id=self.query_id).observe(duration)
        if exc_type:
            if self.config.enable_metrics:
                QUERY_PIPELINE_FAILURES.labels(stage=self.stage.value, error_type=exc_type.__name__, project_id=str(self.project_id)).inc()
            if self.config.enable_detailed_logging:
                logger.error("Pipeline stage failed", stage=self.stage.value, query_id=self.query_id, project_id=self.project_id, error_type=exc_type.__name__, duration=duration, error=str(exc_val))
        else:
            if self.config.enable_detailed_logging:
                logger.info("Pipeline stage completed", stage=self.stage.value, query_id=self.query_id, project_id=self.project_id, duration=duration)

def resilient_pipeline_step(stage: PipelineStage, config: PipelineConfig, timeout: Optional[int] = None):
    def decorator(func):
        @retry(
            stop=stop_after_attempt(config.max_retry_attempts),
            wait=wait_exponential(multiplier=config.retry_wait_multiplier, max=config.retry_wait_max),
            retry=retry_if_exception_type((ConnectionError, TimeoutError, IOError)),
            before_sleep=before_sleep_log(logger, logging.WARNING),
            after=after_log(logger, logging.INFO)
        )
        @wraps(func)
        def wrapper(*args, **kwargs):
            query_id = kwargs.get('query_id', str(uuid.uuid4()))
            project_id = kwargs.get('project_id', 0)
            operation_name = f"{stage.value}_operation"
            timeout_seconds = timeout or getattr(config, f"{stage.value}_timeout", 60)
            with TimeoutHandler(timeout_seconds, operation_name):
                with PipelineMetrics(stage, query_id, project_id, config):
                    try:
                        return func(*args, **kwargs)
                    except Exception as e:
                        raise PipelineError(f"Failed in {stage.value}: {str(e)}", stage, type(e).__name__, query_id, project_id, e)
        return wrapper
    return decorator

class EnhancedRAGPipeline:
    """Enhanced RAG pipeline with comprehensive error handling and observability."""
    
    def __init__(self, config: Optional[PipelineConfig] = None):
        self.config = config or PipelineConfig()
    
    @resilient_pipeline_step(PipelineStage.VALIDATION, PipelineConfig())
    def _validate_inputs(self, db: Session, project_id: int, user_question: str, 
                        query_id: str, **kwargs) -> Tuple[Session, int, str]:
        """Validate pipeline inputs."""
        if not db:
            raise ValueError("Database session is required")
        if not project_id or project_id <= 0:
            raise ValueError("Valid project_id is required")
        if not user_question or not user_question.strip():
            raise ValueError("User question cannot be empty")
        
        return db, project_id, user_question.strip()
    
    def _spawn_background_embed(self, db: Session, project_id: int, query_id: str):
        """Start embed_chunks_for_project in a background thread (best-effort)."""
        def _worker():
            try:
                logger.info("Background embedding started", project_id=project_id, query_id=query_id)
                embed_chunks_for_project(db, project_id)
                logger.info("Background embedding completed", project_id=project_id, query_id=query_id)
            except Exception as e:
                logger.exception("Background embedding failed", project_id=project_id, query_id=query_id, error=str(e))
        t = threading.Thread(target=_worker, daemon=True)
        t.start()
        return t

    @resilient_pipeline_step(PipelineStage.EMBEDDING, PipelineConfig())
    def _embed_chunks(self, db: Session, project_id: int, query_id: str, **kwargs) -> None:
        """Embed chunks for the project."""
        logger.info("Embedding chunks for project (entry)", project_id=project_id, query_id=query_id)

        indexer = RAGIndexer(db)

        # If caller forced sync embedding via env, do synchronous embedding
        if _FORCE_EMBED_SYNC:
            logger.info("RAG_FORCE_EMBED_SYNC=1; running embed_chunks synchronously", project_id=project_id)
            embed_chunks_for_project(db, project_id)
            return

        # Try best-effort check: if indexer exposes a helper to tell if embeddings exist/up-to-date, use it.
        emb_up_to_date = None
        try:
            if hasattr(indexer, "has_embeddings_for_project"):
                emb_up_to_date = indexer.has_embeddings_for_project(project_id)
            elif hasattr(indexer, "embeddings_exist"):
                emb_up_to_date = indexer.embeddings_exist(project_id)
        except Exception as e:
            logger.warning("Failed checking embeddings existence; will schedule background embed", project_id=project_id, error=str(e))

        if emb_up_to_date is True:
            logger.info("Embeddings appear up-to-date; skipping embedding step", project_id=project_id)
            return

        # Spawn background embedding (best-effort)
        try:
            self._spawn_background_embed(db, project_id, query_id)
            logger.info("Embedding scheduled in background", project_id=project_id, query_id=query_id)
        except Exception as e:
            logger.warning("Scheduling background embedding failed; falling back to synchronous embedding", project_id=project_id, error=str(e))
            embed_chunks_for_project(db, project_id)

    @resilient_pipeline_step(PipelineStage.INDEXING, PipelineConfig())
    def _build_index(self, db: Session, project_id: int, 
                    document_content_type: Optional[str], query_id: str, 
                    **kwargs) -> VectorStoreIndex:
        """Build or load vector store index. Prefer loading existing index to avoid rebuild on every query."""
        logger.info("Index step: load-or-build", project_id=project_id, query_id=query_id, content_type=document_content_type)

        indexer = RAGIndexer(db)

        # If user explicitly forces rebuild, do it (useful for admin/debug)
        if _FORCE_REBUILD:
            logger.info("RAG_FORCE_REBUILD=1; forcing index rebuild", project_id=project_id)
            index = indexer.build_index_for_project(project_id=project_id, document_content_type=document_content_type)
            if not index:
                raise ValueError(f"Forced rebuild failed for project {project_id}")
            return index

        # Best-effort: try to load an existing index using common helper names
        try:
            index = None
            if hasattr(indexer, "get_index_for_project"):
                try:
                    index = indexer.get_index_for_project(project_id=project_id, document_content_type=document_content_type)
                    if index:
                        logger.info("Loaded existing index via get_index_for_project", project_id=project_id, query_id=query_id)
                        return index
                except Exception as e:
                    logger.warning("get_index_for_project failed; will attempt other methods or build", project_id=project_id, error=str(e))

            # Alternate helper names sometimes used
            if hasattr(indexer, "load_index"):
                try:
                    index = indexer.load_index(project_id=project_id, document_content_type=document_content_type)
                    if index:
                        logger.info("Loaded existing index via load_index", project_id=project_id, query_id=query_id)
                        return index
                except Exception as e:
                    logger.warning("load_index failed; will attempt build", project_id=project_id, error=str(e))

            # If indexer exposes "index_exists" or similar, and it says no index, skip build and return error
            if hasattr(indexer, "index_exists"):
                try:
                    exists = indexer.index_exists(project_id=project_id, document_content_type=document_content_type)
                    if exists:
                        # if exists but we couldn't load above, try build as last resort
                        logger.info("Index reported exists but load attempts failed; trying build", project_id=project_id)
                    else:
                        logger.info("No index exists and rebuild not forced; attempting build anyway (fallback behavior)", project_id=project_id)
                except Exception:
                    # ignore and continue to build
                    pass

        except Exception as e:
            logger.warning("Index load attempts failed; will fallback to build", project_id=project_id, error=str(e))

        # Final fallback: build index synchronously (if loading didn't succeed)
        logger.info("Building index synchronously as fallback", project_id=project_id, query_id=query_id)
        index = indexer.build_index_for_project(project_id=project_id, document_content_type=document_content_type)
        if not index:
            raise ValueError(f"Failed to build or load index for project {project_id}")
        return index

    @resilient_pipeline_step(PipelineStage.QUERY_ENGINE_BUILD, PipelineConfig())
    def _build_query_engine(self, index: VectorStoreIndex, project_id: int,
                           document_content_type: Optional[str], top_k: int,
                           similarity_threshold: float, query_id: str, **kwargs):
        """Build query engine."""
        logger.info("Building query engine", project_id=project_id, query_id=query_id, top_k=top_k, similarity_threshold=similarity_threshold)
        return build_query_engine(
            index=index,
            project_id=project_id,
            document_content_type=document_content_type,
            top_k=top_k,
            similarity_cutoff=similarity_threshold
        )
    
    @resilient_pipeline_step(PipelineStage.QUERY_EXECUTION, PipelineConfig())
    def _execute_query(self, query_engine, user_question: str, query_id: str,
                      project_id: int, **kwargs):
        """Execute the query."""
        logger.info("Executing query", project_id=project_id, query_id=query_id, question_length=len(user_question))
        response = query_engine.query(user_question)
        if not response:
            raise ValueError("Query returned empty response")
        return response
    
    @resilient_pipeline_step(PipelineStage.ANSWER_VERIFICATION, PipelineConfig(), 
                           timeout=60)
    def _verify_answer(self, answer: str, sources: List, query_id: str,
                      project_id: int, **kwargs) -> Dict[str, Any]:
        """Verify the answer quality."""
        logger.info("Verifying answer", project_id=project_id, query_id=query_id, answer_length=len(answer), source_count=len(sources))
        return verify_answer(answer, sources)
    
    @resilient_pipeline_step(PipelineStage.CITATION_FORMATTING, PipelineConfig())
    def _format_citations(self, source_nodes, query_id: str, project_id: int,
                         **kwargs) -> List[Dict[str, Any]]:
        """Format citations from source nodes."""
        logger.info("Formatting citations", project_id=project_id, query_id=query_id, source_count=len(source_nodes) if source_nodes else 0)
        return format_citations(source_nodes) if source_nodes else []
    
    def _create_partial_result(self, query_id: str, project_id: int, 
                              user_question: str, failed_stage: PipelineStage,
                              error: PipelineError, 
                              partial_data: Dict[str, Any] = None) -> PipelineResult:
        """Create partial result when pipeline fails."""
        logger.warning("Creating partial result", query_id=query_id, project_id=project_id, failed_stage=failed_stage.value)
        if self.config.enable_metrics:
            QUERY_PIPELINE_PARTIAL_SUCCESS.labels(project_id=str(project_id), failed_stage=failed_stage.value).inc()
        partial_data = partial_data or {}
        return PipelineResult(
            query_id=query_id,
            project_id=project_id,
            success=False,
            partial_result=True,
            answer=partial_data.get('answer', "I encountered an issue while processing your query, but partial results may be available."),
            sources=partial_data.get('sources', []),
            verification=partial_data.get('verification'),
            metadata={
                "chunks_retrieved": len(partial_data.get('sources', [])),
                "query_successful": False,
                "failed_stage": failed_stage.value,
                "partial_results_available": bool(partial_data),
                "project_id": project_id,
                "error_stage": failed_stage.value
            },
            error=error.to_dict(),
            stages_completed=partial_data.get('stages_completed', [])
        )
    
    def execute_pipeline(
        self,
        db: Session,
        project_id: int,
        user_question: str,
        document_content_type: Optional[str] = None,
        top_k: int = 10,
        similarity_threshold: float = 0.7
    ) -> PipelineResult:
        """
        Execute the complete RAG pipeline with comprehensive error handling.
        """
        query_id = str(uuid.uuid4())
        start_time = time.time()
        stages_completed = []
        execution_times = {}
        partial_data = {}
        
        logger.info("Starting RAG pipeline execution", query_id=query_id, project_id=project_id, question_preview=user_question[:100], stage="QUERY_EXECUTION")
        
        # Common kwargs for all pipeline steps
        common_kwargs = {
            'query_id': query_id,
            'project_id': project_id,
            'document_content_type': document_content_type,
            'top_k': top_k,
            'similarity_threshold': similarity_threshold
        }
        
        try:
            with TimeoutHandler(self.config.total_pipeline_timeout, "RAG Pipeline"):
                
                # Stage 1: Validation
                stage_start = time.time()
                try:
                    db, project_id, user_question = self._validate_inputs(db, project_id, user_question, **common_kwargs)
                    stages_completed.append(PipelineStage.VALIDATION.value)
                    execution_times[PipelineStage.VALIDATION.value] = time.time() - stage_start
                except PipelineError as e:
                    return self._create_partial_result(query_id, project_id, user_question, PipelineStage.VALIDATION, e)
                
                # Stage 2: Embedding (now background by default)
                stage_start = time.time()
                try:
                    self._embed_chunks(db, project_id, **common_kwargs)
                    stages_completed.append(PipelineStage.EMBEDDING.value)
                    execution_times[PipelineStage.EMBEDDING.value] = time.time() - stage_start
                except PipelineError as e:
                    if self.config.enable_partial_results:
                        logger.warning("Embedding failed or was deferred, continuing", query_id=query_id)
                    else:
                        return self._create_partial_result(query_id, project_id, user_question, PipelineStage.EMBEDDING, e, partial_data)
                
                # Stage 3: Indexing - load existing index when possible
                stage_start = time.time()
                try:
                    index = self._build_index(db, project_id, document_content_type, **common_kwargs)
                    stages_completed.append(PipelineStage.INDEXING.value)
                    execution_times[PipelineStage.INDEXING.value] = time.time() - stage_start
                    partial_data['index_built'] = True
                except PipelineError as e:
                    return self._create_partial_result(query_id, project_id, user_question, PipelineStage.INDEXING, e, partial_data)
                
                # Stage 4: Query Engine Building
                stage_start = time.time()
                try:
                    query_engine = self._build_query_engine(index, project_id, document_content_type, top_k, similarity_threshold, **common_kwargs)
                    stages_completed.append(PipelineStage.QUERY_ENGINE_BUILD.value)
                    execution_times[PipelineStage.QUERY_ENGINE_BUILD.value] = time.time() - stage_start
                    partial_data['query_engine_built'] = True
                except PipelineError as e:
                    return self._create_partial_result(query_id, project_id, user_question, PipelineStage.QUERY_ENGINE_BUILD, e, partial_data)
                
                # Stage 5: Query Execution
                stage_start = time.time()
                try:
                    response = self._execute_query(query_engine, user_question, **common_kwargs)
                    stages_completed.append(PipelineStage.QUERY_EXECUTION.value)
                    execution_times[PipelineStage.QUERY_EXECUTION.value] = time.time() - stage_start
                    
                    answer = str(response)
                    sources = response.source_nodes or []
                    
                    partial_data.update({'answer': answer, 'raw_sources': sources, 'response_available': True})
                    
                except PipelineError as e:
                    return self._create_partial_result(query_id, project_id, user_question, PipelineStage.QUERY_EXECUTION, e, partial_data)
                
                # Stage 6: Answer Verification (with auto-retry)
                stage_start = time.time()
                verification = None
                try:
                    verification = self._verify_answer(answer, sources, **common_kwargs)
                    stages_completed.append(PipelineStage.ANSWER_VERIFICATION.value)
                    execution_times[PipelineStage.ANSWER_VERIFICATION.value] = time.time() - stage_start
                    
                    # Auto-retry logic
                    if (self.config.auto_retry_on_verification_failure and not verification.get("ok", True) and self.config.retry_with_expanded_results):
                        logger.info("Answer verification failed, retrying with expanded results", query_id=query_id)
                        try:
                            expanded_query_engine = self._build_query_engine(index, project_id, document_content_type, min(top_k * 2, self.config.max_expanded_top_k), similarity_threshold, **common_kwargs)
                            retry_response = self._execute_query(expanded_query_engine, user_question, **common_kwargs)
                            retry_answer = str(retry_response)
                            retry_sources = retry_response.source_nodes or []
                            retry_verification = self._verify_answer(retry_answer, retry_sources, **common_kwargs)
                            if retry_verification.get("ok", False):
                                answer, sources, verification = retry_answer, retry_sources, retry_verification
                                logger.info("Retry successful with better results", query_id=query_id)
                        except Exception as retry_error:
                            logger.warning("Auto-retry failed, using original results", query_id=query_id, error=str(retry_error))
                    
                except PipelineError as e:
                    if self.config.enable_partial_results:
                        logger.warning("Answer verification failed, continuing without verification", query_id=query_id)
                        verification = {"ok": False, "error": str(e)}
                    else:
                        return self._create_partial_result(query_id, project_id, user_question, PipelineStage.ANSWER_VERIFICATION, e, partial_data)
                
                # Stage 7: Citation Formatting
                stage_start = time.time()
                try:
                    formatted_sources = self._format_citations(sources, **common_kwargs)
                    stages_completed.append(PipelineStage.CITATION_FORMATTING.value)
                    execution_times[PipelineStage.CITATION_FORMATTING.value] = time.time() - stage_start
                except PipelineError as e:
                    if self.config.enable_partial_results:
                        logger.warning("Citation formatting failed, using raw sources", query_id=query_id)
                        formatted_sources = [{"content": str(s)} for s in sources]
                    else:
                        return self._create_partial_result(query_id, project_id, user_question, PipelineStage.CITATION_FORMATTING, e, partial_data)
                
                # Success metrics
                if self.config.enable_metrics:
                    QUERY_PIPELINE_SUCCESS.labels(project_id=str(project_id), has_verification=str(verification is not None)).inc()
                
                total_execution_time = time.time() - start_time
                logger.info("RAG pipeline completed successfully", query_id=query_id, project_id=project_id, total_duration=total_execution_time, stages_completed=len(stages_completed), source_count=len(formatted_sources))
                
                return PipelineResult(
                    query_id=query_id,
                    project_id=project_id,
                    success=True,
                    answer=answer,
                    sources=formatted_sources,
                    verification=verification,
                    metadata={
                        "chunks_retrieved": len(formatted_sources),
                        "query_successful": True,
                        "project_id": project_id,
                        "document_type_filter": document_content_type,
                        "total_execution_time": total_execution_time,
                        "auto_retry_used": verification and not verification.get("ok", True)
                    },
                    execution_times=execution_times,
                    stages_completed=stages_completed
                )
                
        except TimeoutError as e:
            error = PipelineError(message=str(e), stage=PipelineStage.QUERY_EXECUTION, error_type="TimeoutError", query_id=query_id, project_id=project_id, original_error=e)
            return self._create_partial_result(query_id, project_id, user_question, PipelineStage.QUERY_EXECUTION, error, partial_data)
        
        except Exception as e:
            logger.error("Unexpected error in RAG pipeline", query_id=query_id, project_id=project_id, error=str(e), error_type=type(e).__name__, traceback=traceback.format_exc())
            error = PipelineError(message=f"Unexpected pipeline error: {str(e)}", stage=PipelineStage.QUERY_EXECUTION, error_type=type(e).__name__, query_id=query_id, project_id=project_id, original_error=e)
            return self._create_partial_result(query_id, project_id, user_question, PipelineStage.QUERY_EXECUTION, error, partial_data)

# Enhanced main function
def run_query(
    db: Session,
    project_id: int,
    user_question: str,
    document_content_type: Optional[str] = None,
    top_k: int = 10,
    similarity_threshold: float = 0.7,
    config: Optional[PipelineConfig] = None
) -> Dict[str, Any]:
    pipeline = EnhancedRAGPipeline(config)
    
    result = pipeline.execute_pipeline(
        db=db,
        project_id=project_id,
        user_question=user_question,
        document_content_type=document_content_type,
        top_k=top_k,
        similarity_threshold=similarity_threshold
    )
    
    # Convert to legacy format for backward compatibility
    response_dict = {
        "answer": result.answer,
        "sources": result.sources,
        "metadata": result.metadata
    }
    
    if result.verification:
        response_dict["verification"] = result.verification
    
    if result.error:
        response_dict["error"] = result.error
        response_dict["metadata"]["error_details"] = result.error
    
    if result.execution_times:
        response_dict["metadata"]["execution_times"] = result.execution_times
    
    if result.stages_completed:
        response_dict["metadata"]["stages_completed"] = result.stages_completed
    
    response_dict["metadata"]["partial_result"] = result.partial_result
    response_dict["metadata"]["query_id"] = result.query_id
    
    return response_dict

# Legacy compatibility wrapper
def run_query_legacy(
    db: Session,
    project_id: int,
    user_question: str,
    document_content_type: Optional[str] = None,
    top_k: int = 10,
    similarity_threshold: float = 0.7
) -> Dict[str, Any]:
    """Legacy function for backward compatibility."""
    return run_query(
        db=db,
        project_id=project_id,
        user_question=user_question,
        document_content_type=document_content_type,
        top_k=top_k,
        similarity_threshold=similarity_threshold
    )