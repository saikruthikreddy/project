
import asyncio
import sys
import os
import time
import uuid
import traceback
import re
from typing import Dict, Any, List, Optional, Callable
import asyncio
import sys
import os
import time
import uuid
import traceback
import re


from sqlalchemy.orm import Session
from dataclasses import dataclass

import structlog
from prometheus_client import Histogram, Counter, Gauge

from services.rag.config_loader import load_orchestration_config as get_config

from services.rag.core.auth.user_context import UserContext

from services.rag.llm_service import LLMService

from models.database_models import DocumentChunk
from services.rag.planner import route_and_plan, QueryPlan
from services.rag.fusion import fusion_pipeline, FusionEngine


# Import UnifiedRetrievalService without alias for cleaner type hints
from services.rag.retrieval_service import UnifiedRetrievalService
# You can still create an alias for backwards compatibility if needed
Retriever = UnifiedRetrievalService

# Import RetrieverResult for type hints
from services.rag.retrieval_service import RetrieverResult

# ... rest of your imports

...



logger = structlog.get_logger(__name__)

# Prometheus metrics with low-cardinality labels
QUERY_DURATION = Histogram('query_orchestration_seconds', 'Time for query orchestration', ['stage', 'intent', 'result_type'])
QUERY_FAILURES = Counter('query_orchestration_failures_total', 'Query orchestration failures', ['stage', 'error_type'])
QUERY_SUCCESS = Counter('query_orchestration_success_total', 'Successful query orchestrations', ['intent', 'has_partial_results'])
CONCURRENT_QUERIES = Gauge('concurrent_queries_active', 'Number of queries being orchestrated')

class ExecutionStage:
    PLANNING = "planning"
    RETRIEVAL = "retrieval"
    SYNTHESIS = "synthesis"
    POST_PROCESSING = "post_processing"

@dataclass
class OrchestrationResult:
    query_id: str
    success: bool
    answer: str
    sources: List[Dict[str, Any]]
    metadata: Dict[str, Any]
    execution_time: float
    partial_results: bool = False
    error: Optional[Dict[str, Any]] = None

class QueryOrchestrator:
    def __init__(self, retrieval_service: UnifiedRetrievalService, db_session_factory: Callable[[], Session]):
        self.config = get_config('orchestration', default={})
        self.retrieval_service = retrieval_service
        self.llm_service = LLMService()
        self.db_session_factory = db_session_factory

    async def execute_query(self, user: UserContext, query_text: str) -> OrchestrationResult:
        query_id = str(uuid.uuid4())
        start_time = time.time()
        log_context = {"query_id": query_id, "user_id": user.user_id}
        logger.info("Starting query orchestration", **log_context)
        CONCURRENT_QUERIES.inc()

        try:
            plan = await self._plan_stage(query_text, {"project_id": user.project_id}, query_id)

            retrieval_results = await self._retrieval_stage(plan, user, query_id)

            successful_results = [r for r in retrieval_results if r.success]
            if not successful_results:
                raise RuntimeError("All subquery retrievals failed.")

            answer, sources, metadata = await self._synthesis_stage(plan, successful_results, query_id)

            total_duration = time.time() - start_time
            has_partial = len(successful_results) < len(plan.subqueries)

            QUERY_DURATION.labels(stage="complete", intent=plan.intent, result_type="partial" if has_partial else "complete").observe(total_duration)
            QUERY_SUCCESS.labels(intent=plan.intent, has_partial_results=str(has_partial)).inc()

            metadata.update({
                "query_id": query_id,
                "execution_time": total_duration,
                "intent": plan.intent,
                "subquery_count": len(plan.subqueries),
                "successful_subqueries": len(successful_results),
            })

            return OrchestrationResult(
                query_id=query_id, success=True, answer=answer, sources=sources,
                metadata=metadata, execution_time=total_duration, partial_results=has_partial
            )

        except Exception as e:
            QUERY_FAILURES.labels(stage="orchestration_error", error_type=type(e).__name__).inc()
            return self._build_error_result(query_id, e, time.time() - start_time)
        finally:
            CONCURRENT_QUERIES.dec()

    async def _plan_stage(self, query_text: str, user_context: Dict[str, Any], query_id: str) -> QueryPlan:
        with QUERY_DURATION.labels(stage=ExecutionStage.PLANNING, intent='unknown', result_type='n/a').time():
            try:
                timeout = self.config.get('performance', {}).get('timeouts', {}).get('planning', 10.0)
                plan = await asyncio.wait_for(route_and_plan(query_text, user_context, query_id), timeout=timeout)
                logger.info("Planning complete", query_id=query_id, intent=plan.intent)
                return plan
            except Exception as e:
                QUERY_FAILURES.labels(stage=ExecutionStage.PLANNING, error_type=type(e).__name__).inc()
                raise

    async def _retrieval_stage(self, plan: QueryPlan, user: UserContext, query_id: str) -> List[RetrieverResult]:
        with QUERY_DURATION.labels(stage=ExecutionStage.RETRIEVAL, intent=plan.intent, result_type='n/a').time():
            retriever_config = get_config('retriever', default={})
            tasks = [
                self.retrieval_service.retrieve_subquery(
                    query_text=sq['text'],
                    top_k=retriever_config.get('top_k', 10),
                    similarity_threshold=retriever_config.get('similarity_threshold', 0.7),
                    min_results=retriever_config.get('min_results', 3),
                    threshold_relax_factor=retriever_config.get('threshold_relax_factor', 0.8),
                    min_similarity_floor=retriever_config.get('min_similarity_floor', 0.5),
                    user_id=user.user_id,
                    project_id=plan.filters.get('project_id'),
                    query_id=query_id,
                ) for sq in plan.subqueries
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            processed = [res if not isinstance(res, Exception) else RetrieverResult(query_id=query_id, success=False, error={"message": str(res)}) for res in results]
            return processed

    async def _synthesis_stage(self, plan: QueryPlan, results: List[RetrieverResult], query_id: str) -> (str, List[Dict], Dict):
        with QUERY_DURATION.labels(stage=ExecutionStage.SYNTHESIS, intent=plan.intent, result_type='n/a').time():
            fusion_config = self.config.get('fusion', {})

            def fetch_sources_by_ids(ids: List[str]) -> List[Dict[str, Any]]:
                if not ids: return []
                logger.info(f"Fetching {len(ids)} source chunks...", query_id=query_id)
                db_session: Session = self.db_session_factory()
                try:
                    valid_ids = [int(i) for i in ids if i.isdigit()]
                    if not valid_ids: return []
                    chunks = db_session.query(DocumentChunk).filter(DocumentChunk.id.in_(valid_ids)).all()
                    return [{"chunk_id": str(c.id), "text": c.chunk_text, "document_id": str(c.document_id),**(c.metadata_ or {})} for c in chunks]
                finally: db_session.close()

            subquery_docs_as_dicts = [[{"chunk_id": n.node.id_, "text": n.node.get_content(), "score": n.score,**(n.node.metadata or {})} for n in res.results] for res in results]

            packed_context, stats = fusion_pipeline(
                results=subquery_docs_as_dicts,
                fetch_sources_by_ids=fetch_sources_by_ids,
                intent_weights=fusion_config.get('intent_weights'),
                token_budget=fusion_config.get('context_packing', {}).get('token_budget', 3500),
                return_stats=True
            )

            prompt_styles = self.config.get('synthesis', {}).get('prompt_styles', {})
            prompt_template = prompt_styles.get(plan.prompt_style, prompt_styles.get('default', '{context_str}\n\n{query_str}'))

            answer = await self.llm_service.synthesize_answer(
                query=plan.original_query, context_chunks=packed_context, prompt_template=prompt_template
            )

            final_answer = await self._run_post_answer_checks(answer, packed_context, plan)

            return final_answer, packed_context, {"fusion_stats": stats.to_dict()}

    def _extract_numerics_with_units(self, text: str) -> set:
        """Helper to extract numbers with their units for better comparison."""
        pattern = re.compile(r'((?:[\$€£¥])?[\s]*)' r'([\d,]+(?:\.\d+)?)' r'([\s]?(?:%|k|M|B|Trillion|Billion|Million|Thousand|dollars|euros)\b)?', re.IGNORECASE)
        found = set()
        for match in pattern.finditer(text):
            _, number, suffix = match.groups()
            clean_number = number.replace(',', '')
            clean_suffix = suffix.strip().lower() if suffix else ''
            found.add((clean_number, clean_suffix))
        return found

    async def _run_post_answer_checks(self, answer: str, sources: List[Dict[str, Any]], plan: QueryPlan) -> str:
        """
        Runs quality checks on the generated answer, starting with numeric consistency.
        """
        with QUERY_DURATION.labels(stage=ExecutionStage.POST_PROCESSING, intent=plan.intent, result_type='n/a').time():
            logger.info("Running post-answer checks", query_id=plan.query_id)

            # --- FIX: Implemented Numeric Consistency Check ---
            if plan.intent == "METRIC_LOOKUP":
                try:
                    answer_numerics = self._extract_numerics_with_units(answer)
                    if not answer_numerics:
                        return answer # No numbers to check

                    source_text_combined = " ".join([source.get('text', '') for source in sources])
                    source_numerics = self._extract_numerics_with_units(source_text_combined)

                    inconsistent_numerics = [num for num in answer_numerics if num not in source_numerics]

                    # Trigger fallback if a significant number of inconsistencies are found
                    if len(inconsistent_numerics) >= 2:
                        logger.warning("Numeric inconsistency detected. Rebuilding answer from snippets.",
                                       query_id=plan.query_id, inconsistent_count=len(inconsistent_numerics),
                                       details=inconsistent_numerics)

                        fallback_text = "Based on the available data:\n\n"
                        for i, source in enumerate(sources[:3]): # Use top 3 sources for fallback
                            fallback_text += f"- Source [{i+1}]: {source.get('text', '')}\n"
                        return fallback_text
                except Exception as e:
                    logger.error("Numeric consistency check failed", query_id=plan.query_id, error=str(e))

            # --- TODO: Implement other checks like citation validation here ---
            # if check_citations(answer, sources) is False:
            #    logger.warning("Invalid citations detected", query_id=plan.query_id)

            return answer

    def _build_error_result(self, query_id: str, error: Exception, duration: float) -> OrchestrationResult:
        logger.error("Query orchestration failed", query_id=query_id, error=str(error), traceback=traceback.format_exc())
        return OrchestrationResult(
            query_id=query_id, success=False,
            answer="I encountered an issue processing your request. Please try again.",
            sources=[], metadata={}, execution_time=duration,
            error={"message": str(error), "type": type(error).__name__}
        )
