# --- START OF FILE query_executor.py ---

# File: query_executor.py
import os
import logging
import time
import uuid
import traceback
import asyncio
import threading
from typing import Optional, Dict, Any, List
from dataclasses import asdict

import structlog
from prometheus_client import Histogram, Counter
from sqlalchemy.orm import Session, sessionmaker
from llama_index.core import VectorStoreIndex
from llama_index.core.schema import TextNode

# Refactored imports
from query_orchestrator import QueryOrchestrator, OrchestrationResult
from services.rag.retrieval_service import UnifiedRetrievalService as Retriever

from services.rag.embed_chunk import embed_chunks_for_project

from index_builder import RAGIndexer
from services.rag.config_loader import load_orchestration_config as get_config



from core.auth.user_context import UserContext

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

# FIXED Prometheus metrics with low-cardinality labels
PIPELINE_DURATION = Histogram(
    'rag_pipeline_execution_seconds',
    'Time spent in RAG pipeline execution',
    ['stage', 'result_type']  # Removed project_id, query_id
)

PIPELINE_FAILURES = Counter(
    'rag_pipeline_failures_total',
    'Number of RAG pipeline failures',
    ['stage', 'error_type']  # Removed project_id
)

PIPELINE_SUCCESS = Counter(
    'rag_pipeline_success_total',
    'Number of successful RAG pipeline executions',
    ['has_partial_results'] # Simplified labels
)

# Environment flags
_FORCE_REBUILD = bool(os.getenv("RAG_FORCE_REBUILD", "0") == "1")

class RAGPipeline:
    """
    Main entry point for the RAG system.
    Handles synchronous setup (embedding, indexing) and then delegates
    to the asynchronous QueryOrchestrator for query processing.
    """
    def __init__(self, db: Session, SessionLocal: sessionmaker):
        self.db = db
        self.SessionLocal = SessionLocal  # Store the session factory
        self.config = get_config(default={})
        self.indexer = RAGIndexer(self.db)
        self.orchestrator = self._initialize_orchestrator()

    def _initialize_orchestrator(self) -> QueryOrchestrator:
        """
        Initializes all necessary components for the QueryOrchestrator.
        This should be done carefully to manage resource lifetimes.
        """
        # NOTE: This part might need adjustment based on how you manage VectorStoreIndex instances.
        # A more advanced setup might involve a dictionary of indexes per project, managed by the orchestrator.
        try:
            # For initialization, we might need a "default" index.
            # You will need to decide which project_id to use, or if the service can start without one.
            default_project_id_for_init = 1
            primary_index = self.indexer.get_index_for_project(default_project_id_for_init)
            if not primary_index:
                 primary_index = self.indexer.build_index_for_project(default_project_id_for_init)
        except Exception:
            # If loading fails, create an empty one to avoid crashing on startup.
            primary_index = VectorStoreIndex.from_documents([TextNode(text="dummy node")])
            logger.warning("Failed to load a default index; orchestrator initialized with a dummy index.")

        retrieval_service = UnifiedRetrievalService(primary_index)
        # --- FIX: Pass the session factory to the orchestrator ---
        return QueryOrchestrator(retrieval_service, db_session_factory=self.SessionLocal)

    def execute(
        self,
        user: UserContext,
        user_question: str
    ) -> Dict[str, Any]:
        """
        Execute the complete RAG pipeline.
        """
        start_time = time.time()
        query_id = str(uuid.uuid4())
        project_id = user.project_id

        log_context = {"query_id": query_id, "project_id": project_id, "user_id": user.user_id}
        logger.info("Starting RAG pipeline execution", **log_context)

        try:
            # --- SETUP PHASE (Synchronous) ---
            self._ensure_data_is_ready(project_id, query_id)

            # --- QUERY PHASE (Asynchronous) ---
            with PIPELINE_DURATION.labels(stage="query_orchestration", result_type="n/a").time():
                result = self._run_async_orchestration(user, user_question)

            # --- FORMATTING AND METRICS ---
            total_duration = time.time() - start_time
            if result.success:
                PIPELINE_DURATION.labels(stage="complete", result_type="success").observe(total_duration)
                PIPELINE_SUCCESS.labels(has_partial_results=str(result.partial_results)).inc()
            else:
                PIPELINE_DURATION.labels(stage="complete", result_type="failure").observe(total_duration)

            logger.info("RAG pipeline finished", **log_context, total_duration=total_duration, success=result.success)
            return self._format_response(result)

        except Exception as e:
            PIPELINE_FAILURES.labels(stage="pipeline_setup", error_type=type(e).__name__).inc()
            logger.error("RAG pipeline failed during setup", **log_context, error=str(e), traceback=traceback.format_exc())
            return self._format_error_response(query_id, project_id, e)

    def _run_async_orchestration(self, user: UserContext, user_question: str) -> OrchestrationResult:
        """Handles running the async orchestrator, managing the event loop."""
        try:
            loop = asyncio.get_running_loop()
            if loop.is_running():
                # If already in a loop (e.g., FastAPI), use run_coroutine_threadsafe for safety
                # in case the caller is in a different thread.
                logger.warning("Detected a running event loop for orchestration.")
                future = asyncio.run_coroutine_threadsafe(self.orchestrator.execute_query(user, user_question), loop)
                return future.result() # This will block until the coroutine is done.
            else:
                # If no loop is running, we can safely use asyncio.run
                return asyncio.run(self.orchestrator.execute_query(user, user_question))
        except RuntimeError:
            # This handles the case where there's no loop at all.
            return asyncio.run(self.orchestrator.execute_query(user, user_question))

    def _ensure_data_is_ready(self, project_id: int, query_id: str):
        """Ensures embeddings and index are available before querying."""
        log_context = {"query_id": query_id, "project_id": project_id}

        with PIPELINE_DURATION.labels(stage="embedding_check", result_type="n/a").time():
            try:
                # This can spawn a background task or run synchronously based on your needs
                embed_chunks_for_project(self.db, project_id)
            except Exception as e:
                PIPELINE_FAILURES.labels(stage="embedding_check", error_type=type(e).__name__).inc()
                logger.warning("Embedding check/trigger failed; proceeding with existing data.", **log_context, error=str(e))
                # We continue, assuming some embeddings might already exist.

        with PIPELINE_DURATION.labels(stage="indexing_check", result_type="n/a").time():
            try:
                if _FORCE_REBUILD or not self.indexer.index_exists(project_id):
                    logger.info("Index rebuild triggered.", **log_context)
                    self.indexer.build_index_for_project(project_id)
            except Exception as e:
                PIPELINE_FAILURES.labels(stage="indexing_check", error_type=type(e).__name__).inc()
                # This is a critical failure, as we can't query without an index.
                logger.error("Failed to build or load index.", **log_context, error=str(e))
                raise RuntimeError(f"Could not ensure index availability for project {project_id}") from e

    def _format_response(self, result: OrchestrationResult) -> Dict[str, Any]:
        """Formats the final API response from the orchestration result."""
        return asdict(result)

    def _format_error_response(self, query_id: str, project_id: int, error: Exception) -> Dict[str, Any]:
        """Formats a consistent error response for setup failures."""
        return {
            "query_id": query_id,
            "success": False,
            "answer": "Failed to process the query due to a system error during setup.",
            "sources": [],
            "metadata": {"project_id": project_id},
            "execution_time": 0.0,
            "partial_results": False,
            "error": {"message": str(error), "type": type(error).__name__},
        }

# Global pipeline instance for convenience
_pipeline_instance = None
_pipeline_lock = threading.Lock()

def get_rag_pipeline(db: Session, SessionLocal: sessionmaker) -> RAGPipeline:
    """
    Factory function to get a singleton instance of the RAGPipeline.
    It requires the database session and the session factory.
    """
    global _pipeline_instance
    with _pipeline_lock:
        if _pipeline_instance is None:
            _pipeline_instance = RAGPipeline(db, SessionLocal)
        # If the DB session changes, you might need to re-initialize or update the instance
        elif _pipeline_instance.db != db:
             _pipeline_instance = RAGPipeline(db, SessionLocal)
        return _pipeline_instance

# Main function to be called by your API layer
def run_query(
    db: Session,
    SessionLocal: sessionmaker, # Pass your session factory here
    user: UserContext,
    user_question: str,
) -> Dict[str, Any]:
    """Main entry point to execute a query."""
    pipeline = get_rag_pipeline(db, SessionLocal)
    return pipeline.execute(user, user_question)

# --- END OF FILE query_executor.py ---