"""
Query Orchestrator Module - Enhanced Version

This module handles the orchestration of query processing up to subquery generation.
It follows the pipeline: Query → Intent → QueryPlan → Subqueries → Fusion → Post-retrieval
Enhanced with improved error handling, telemetry, and robustness.

Author: Enhanced based on recommendations and best practices
"""

import logging
import uuid
import time
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

# NEW imports
from fusion import fusion_pipeline
from post_retrieval import run_post_retrieval_on_fused

from intent_router import route_intent
from query_engine import generate_query_plan
from retrieval_service import build_subqueries


# Configure structured logging
logger = logging.getLogger(__name__)


class PipelineStage(Enum):
    """Enumeration of pipeline stages for better tracking"""
    INTENT_DETECTION = "intent_detection"
    QUERY_PLANNING = "query_planning"
    SUBQUERY_GENERATION = "subquery_generation"
    EXECUTION = "execution"
    FUSION = "fusion"
    POST_RETRIEVAL = "post_retrieval"


@dataclass
class PipelineMetrics:
    """Container for pipeline performance metrics"""
    intent_detection_ms: int = 0
    query_planning_ms: int = 0
    subquery_generation_ms: int = 0
    fusion_ms: int = 0
    post_retrieval_ms: int = 0
    total_ms: int = 0
    
    def to_dict(self) -> Dict[str, int]:
        return {
            "intent_detection_ms": self.intent_detection_ms,
            "query_planning_ms": self.query_planning_ms,
            "subquery_generation_ms": self.subquery_generation_ms,
            "fusion_ms": self.fusion_ms,
            "post_retrieval_ms": self.post_retrieval_ms,
            "total_ms": self.total_ms
        }


@dataclass
class OrchestrationResult:
    """
    Result object containing the outputs of query orchestration.
    
    Attributes:
        query_id: Unique identifier for the query
        original_query: The input query string
        intent: Detected intent from the query
        plan: Generated query plan
        subqueries: List of subqueries ready for execution
        timestamp: When the orchestration was completed
        success: Whether orchestration was successful
        error_message: Error message if orchestration failed
        search_results_count: Number of search results retrieved
        fused_count: Number of chunks after fusion
        context: Final processed context
        citations: List of citation objects
        metrics: Performance metrics for the pipeline
        failed_stage: Stage where failure occurred (if any)
    """
    query_id: str
    original_query: str
    intent: str
    plan: Dict[str, Any]
    subqueries: List[Dict[str, Any]]
    timestamp: str
    success: bool = True
    error_message: Optional[str] = None
    search_results_count: int = 0
    fused_count: int = 0
    context: str = ""
    citations: List[Dict[str, Any]] = field(default_factory=list)
    metrics: PipelineMetrics = field(default_factory=PipelineMetrics)
    failed_stage: Optional[PipelineStage] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert OrchestrationResult to dictionary format."""
        return {
            "query_id": self.query_id,
            "original_query": self.original_query,
            "intent": self.intent,
            "plan": self.plan,
            "subqueries": self.subqueries,
            "timestamp": self.timestamp,
            "success": self.success,
            "error_message": self.error_message,
            "search_results_count": self.search_results_count,
            "fused_count": self.fused_count,
            "context": self.context,
            "citations": self.citations,
            "metrics": self.metrics.to_dict(),
            "failed_stage": self.failed_stage.value if self.failed_stage else None
        }


class QueryOrchestratorError(Exception):
    """Custom exception for orchestrator-specific errors"""
    def __init__(self, message: str, stage: PipelineStage = None):
        super().__init__(message)
        self.stage = stage


class QueryOrchestrator:
    """
    Enhanced Query Orchestrator with improved error handling, metrics, and robustness.
    
    Handles the complete retrieval pipeline:
    1. Intent Detection - Determines what the user is trying to accomplish
    2. Query Planning - Creates a structured plan based on intent and query
    3. Subquery Generation - Breaks down the plan into executable subqueries
    4. Post-retrieval Processing - Fusion and context generation
    
    Usage:
        orchestrator = QueryOrchestrator()
        result = orchestrator.process_query("What are the sales figures for Q3?")
        if result.success:
            # Use result.context and result.citations for answer generation
    """

    def __init__(self, enable_metrics: bool = True, timeout_seconds: int = 30) -> None:
        """
        Initialize the QueryOrchestrator.
        
        Args:
            enable_metrics: Whether to collect detailed performance metrics
            timeout_seconds: Maximum time allowed for orchestration
        """
        self.enable_metrics = enable_metrics
        self.timeout_seconds = timeout_seconds
        logger.info("QueryOrchestrator initialized", extra={
            "metrics_enabled": enable_metrics,
            "timeout_seconds": timeout_seconds
        })

    def _time_stage(self, stage_name: str):
        """Context manager for timing pipeline stages"""
        class StageTimer:
            def __init__(self, stage_name: str, enable_metrics: bool):
                self.stage_name = stage_name
                self.enable_metrics = enable_metrics
                self.start_time = 0
                self.duration_ms = 0
                
            def __enter__(self):
                if self.enable_metrics:
                    self.start_time = time.time()
                return self
                
            def __exit__(self, exc_type, exc_val, exc_tb):
                if self.enable_metrics:
                    self.duration_ms = int((time.time() - self.start_time) * 1000)
                    logger.info(f"{self.stage_name} completed", extra={
                        "stage": self.stage_name,
                        "duration_ms": self.duration_ms
                    })
                    
        return StageTimer(stage_name, self.enable_metrics)

    def _fetch_sources_by_ids(self, index):
        """
        Return a callable(ids)->List[dict] used by fusion to expand derived chunks.
        Enhanced with better error handling.
        """
        def _noop(ids): 
            logger.debug(f"No index provided, skipping source fetch for {len(ids)} ids")
            return []
            
        if index is None:
            return _noop
            
        # Try different method names that might exist on the index
        method_names = [
            "fetch_sources_by_ids", 
            "get_sources_by_ids", 
            "get_nodes_by_ids", 
            "fetch_by_ids"
        ]
        
        for method_name in method_names:
            if hasattr(index, method_name):
                original_fn = getattr(index, method_name)
                
                def safe_fetch(ids):
                    try:
                        result = original_fn(ids)
                        return result or []
                    except Exception as e:
                        logger.warning(f"Source fetch failed for {len(ids)} ids", extra={
                            "method": method_name,
                            "error": str(e)
                        })
                        return []
                        
                logger.debug(f"Using {method_name} for source fetching")
                return safe_fetch
                
        logger.warning("No suitable fetch method found on index, using noop")
        return _noop

    def run_postretrieval_and_fusion(
        self,
        original_query: str,
        subqueries: List[str],
        search_results: List[List[Any]],
        index=None,
        k: int = 60,
        token_budget: int = 3500,
        metrics: Optional[PipelineMetrics] = None
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        Run fusion and post-retrieval processing with enhanced error handling and metrics.
        
        Args:
            original_query: The original user query
            subqueries: List of generated subqueries
            search_results: Results from search execution
            index: Optional index for source expansion
            k: Number of chunks to keep after fusion
            token_budget: Token limit for fusion
            metrics: Optional metrics object to update
            
        Returns:
            Tuple of (fused_chunks, context_package)
        """
        
        # Fusion stage
        with self._time_stage("fusion") as timer:
            try:
                fetcher = self._fetch_sources_by_ids(index)
                fused_chunks = fusion_pipeline(
                    results=search_results,
                    fetch_sources_by_ids=fetcher,
                    k=k,
                    token_budget=token_budget,
                    skip_dedup=False,
                    skip_expansion=False,
                    return_stats=False,
                )
                logger.info(f"Fusion completed: {len(fused_chunks)} chunks")
                
            except Exception as e:
                logger.error("Fusion stage failed", extra={"error": str(e)}, exc_info=True)
                fused_chunks = []
                
        if metrics and self.enable_metrics:
            metrics.fusion_ms = timer.duration_ms

        # Post-retrieval stage  
        with self._time_stage("post_retrieval") as timer:
            try:
                context_pkg = run_post_retrieval_on_fused(
                    fused_chunks=fused_chunks,
                    original_query=original_query,
                    index=index,
                    top_k=min(20, len(fused_chunks)),
                    similarity_cutoff=0.15,
                    return_nodes=False,
                    subqueries=subqueries,
                    provenance={"stage": "query_orchestrator", "timestamp": datetime.utcnow().isoformat()}
                )
                logger.info("Post-retrieval completed", extra={
                    "context_length": len(context_pkg.get("context", "")),
                    "citations_count": len(context_pkg.get("citations", []))
                })
                
            except Exception as e:
                logger.error("Post-retrieval stage failed", extra={"error": str(e)}, exc_info=True)
                context_pkg = {"context": "", "citations": []}
                
        if metrics and self.enable_metrics:
            metrics.post_retrieval_ms = timer.duration_ms

        return fused_chunks, context_pkg

    def process_query(self, query: str, index=None, execution_service=None) -> OrchestrationResult:
        """
        Process a user query through the complete orchestration pipeline.
        
        Args:
            query: The user's natural language query
            index: Optional index for post-retrieval processing
            execution_service: Service to execute subqueries against Azure AI Search
            
        Returns:
            OrchestrationResult: Complete result with context and citations
        """
        # Input validation
        if not query or not query.strip():
            raise ValueError("Query cannot be empty or whitespace only")
        
        query = query.strip()
        query_id = str(uuid.uuid4())
        timestamp = datetime.utcnow().isoformat()
        metrics = PipelineMetrics() if self.enable_metrics else None
        
        # Track total time
        total_start = time.time() if self.enable_metrics else 0
        
        logger.info("Starting query orchestration", extra={
            "query_id": query_id,
            "query_length": len(query),
            "timestamp": timestamp
        })
        
        try:
            # Step 1: Intent Detection
            with self._time_stage("intent_detection") as timer:
                intent = route_intent(query)
                
            if metrics:
                metrics.intent_detection_ms = timer.duration_ms
                
            logger.info("Intent detected", extra={
                "query_id": query_id,
                "intent": intent,
                "duration_ms": timer.duration_ms if self.enable_metrics else None
            })
            
            # Step 2: Query Planning
            with self._time_stage("query_planning") as timer:
                plan = generate_query_plan(query, intent)
                
            if metrics:
                metrics.query_planning_ms = timer.duration_ms
                
            logger.info("Query plan generated", extra={
                "query_id": query_id,
                "plan_type": plan.get("type", "unknown"),
                "duration_ms": timer.duration_ms if self.enable_metrics else None
            })
            
            # Step 3: Subquery Generation
            with self._time_stage("subquery_generation") as timer:
                subqueries = build_subqueries(plan)
                
            if metrics:
                metrics.subquery_generation_ms = timer.duration_ms
                
            logger.info("Subqueries generated", extra={
                "query_id": query_id,
                "subquery_count": len(subqueries),
                "duration_ms": timer.duration_ms if self.enable_metrics else None
            })
            
            # Step 4: Execute subqueries (if execution service provided)
            search_results = []
            if execution_service and subqueries:
                try:
                    # FIX #1: Actually call the execution service instead of hardcoded empty list
                    search_results = execution_service.run(subqueries)
                    logger.info("Search execution completed", extra={
                        "query_id": query_id,
                        "results_per_subquery": [len(result) for result in search_results]
                    })
                except Exception as e:
                    logger.warning("Search execution failed", extra={
                        "query_id": query_id,
                        "error": str(e)
                    })
                    search_results = []
            
            # Step 5: Post-retrieval + Fusion (only if we have meaningful results)
            fused_chunks = []
            context_pkg = {"context": "", "citations": []}
            
            # FIX #4: Better edge case handling for empty results
            if any(search_results) and index:
                try:
                    fused_chunks, context_pkg = self.run_postretrieval_and_fusion(
                        original_query=query,
                        subqueries=[
                            sq.get("text", sq) if isinstance(sq, dict) else str(sq) 
                            for sq in subqueries
                        ],
                        search_results=search_results,
                        index=index,
                        metrics=metrics
                    )
                except Exception as e:
                    logger.error("Post-retrieval and fusion failed", extra={
                        "query_id": query_id,
                        "error": str(e)
                    }, exc_info=True)
                    # Continue with empty results rather than failing completely
                    fused_chunks = []
                    context_pkg = {"context": "", "citations": []}
            
            # Calculate total time
            if metrics:
                metrics.total_ms = int((time.time() - total_start) * 1000)
            
            # Create successful result
            result = OrchestrationResult(
                query_id=query_id,
                original_query=query,
                intent=intent,
                plan=plan,
                subqueries=subqueries,
                timestamp=timestamp,
                success=True,
                search_results_count=sum(len(lst or []) for lst in (search_results or [])),
                fused_count=len(fused_chunks or []),
                context=context_pkg.get("context", ""),
                citations=context_pkg.get("citations", []),  # FIX #2: Always list, never None
                metrics=metrics or PipelineMetrics()
            )
            
            logger.info("Query orchestration completed successfully", extra={
                "query_id": query_id,
                "intent": intent,
                "subquery_count": len(subqueries),
                "search_results_count": result.search_results_count,
                "fused_count": result.fused_count,
                "citations_count": len(result.citations),
                "total_duration_ms": metrics.total_ms if metrics else None
            })
            
            return result
            
        except Exception as e:
            # Determine which stage failed
            failed_stage = self._determine_failed_stage(e)
            error_message = f"Query orchestration failed at {failed_stage.value}: {str(e)}"
            
            logger.error("Query orchestration failed", extra={
                "query_id": query_id,
                "failed_stage": failed_stage.value,
                "error_type": type(e).__name__,
                "error_message": str(e)
            }, exc_info=True)
            
            # Calculate partial metrics
            if metrics:
                metrics.total_ms = int((time.time() - total_start) * 1000)
            
            return OrchestrationResult(
                query_id=query_id,
                original_query=query,
                intent="",
                plan={},
                subqueries=[],
                timestamp=timestamp,
                success=False,
                error_message=error_message,
                failed_stage=failed_stage,
                metrics=metrics or PipelineMetrics()
            )

    def _determine_failed_stage(self, exception: Exception) -> PipelineStage:
        """Determine which pipeline stage failed based on the exception context"""
        # This could be enhanced with more sophisticated error analysis
        error_msg = str(exception).lower()
        
        if "intent" in error_msg:
            return PipelineStage.INTENT_DETECTION
        elif "plan" in error_msg:
            return PipelineStage.QUERY_PLANNING
        elif "subquer" in error_msg:
            return PipelineStage.SUBQUERY_GENERATION
        elif "fusion" in error_msg:
            return PipelineStage.FUSION
        elif "post" in error_msg or "retrieval" in error_msg:
            return PipelineStage.POST_RETRIEVAL
        else:
            return PipelineStage.INTENT_DETECTION  # Default to first stage

    def process_query_batch(self, queries: List[str], index=None, execution_service=None) -> List[OrchestrationResult]:
        """
        Process multiple queries in batch for efficiency testing.
        
        Args:
            queries: List of query strings to process
            index: Optional index for post-retrieval processing
            execution_service: Service to execute subqueries
            
        Returns:
            List[OrchestrationResult]: Results for each query
        """
        results = []
        batch_start = time.time()
        
        logger.info("Starting batch orchestration", extra={
            "batch_size": len(queries),
            "timestamp": datetime.utcnow().isoformat()
        })
        
        for i, query in enumerate(queries):
            try:
                result = self.process_query(query, index, execution_service)
                results.append(result)
                
                logger.info("Batch query completed", extra={
                    "query_index": i + 1,
                    "total_queries": len(queries),
                    "success": result.success
                })
                
            except Exception as e:
                logger.error("Batch query failed", extra={
                    "query_index": i + 1,
                    "query": query,
                    "error": str(e)
                })
                # Continue with other queries instead of failing entire batch
                continue
        
        batch_duration = int((time.time() - batch_start) * 1000)
        success_count = sum(1 for r in results if r.success)
        
        logger.info("Batch orchestration completed", extra={
            "total_queries": len(queries),
            "successful": success_count,
            "failed": len(queries) - success_count,
            "batch_duration_ms": batch_duration
        })
        
        return results

    def get_orchestration_info(self) -> Dict[str, str]:
        """Get information about the enhanced orchestration pipeline stages."""
        return {
            "stage_1": "Intent Detection - Analyzes query to determine user intent",
            "stage_2": "Query Planning - Creates structured plan based on intent",
            "stage_3": "Subquery Generation - Breaks plan into executable subqueries",
            "stage_4": "Execution - Runs subqueries against Azure AI Search",
            "stage_5": "Fusion - Merges and deduplicates search results",
            "stage_6": "Post-retrieval - Processes fused results into final context",
            "output": "Processed context with citations ready for answer generation",
            "pipeline_flow": "Query → Intent → Plan → Subqueries → Execute → Fuse → Process → Context",
            "enhancements": "Metrics collection, robust error handling, batch processing"
        }


# Enhanced validation function
def validate_orchestration_result(result: OrchestrationResult) -> Tuple[bool, List[str]]:
    """
    Validate that an orchestration result is properly formatted.
    
    Args:
        result: The result to validate
        
    Returns:
        Tuple of (is_valid, list_of_issues)
    """
    issues = []
    
    if not result.success:
        issues.append("Result indicates failure")
        
    if not result.query_id:
        issues.append("Missing query_id")
        
    if not result.original_query:
        issues.append("Missing original_query")
        
    if not result.intent:
        issues.append("Missing intent")
        
    if not isinstance(result.plan, dict):
        issues.append("Plan is not a dictionary")
        
    if not isinstance(result.subqueries, list) or len(result.subqueries) == 0:
        issues.append("Subqueries is not a non-empty list")
    
    # Validate subqueries structure
    for i, subquery in enumerate(result.subqueries):
        if not isinstance(subquery, (dict, str)):
            issues.append(f"Subquery {i} is neither dict nor string")
    
    # Validate citations structure
    if result.citations is not None:
        if not isinstance(result.citations, list):
            issues.append("Citations is not a list")
        else:
            for i, citation in enumerate(result.citations):
                if not isinstance(citation, dict):
                    issues.append(f"Citation {i} is not a dictionary")
    
    # Validate metrics
    if result.metrics and not isinstance(result.metrics, PipelineMetrics):
        issues.append("Metrics is not a PipelineMetrics object")
        
    return len(issues) == 0, issues


# Enhanced example usage
if __name__ == "__main__":
    """
    Enhanced example usage with proper error handling and metrics.
    """
    
    # Configure logging for local testing
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
    )
    
    # Mock execution service for testing
    class MockExecutionService:
        def run(self, subqueries):
            # Simulate search results
            return [
                [{"id": f"doc_{i}_{j}", "content": f"Mock content {i}-{j}"} 
                 for j in range(3)] 
                for i in range(len(subqueries))
            ]
    
    # Initialize orchestrator with metrics enabled
    orchestrator = QueryOrchestrator(enable_metrics=True)
    execution_service = MockExecutionService()
    
    # Example queries to test
    test_queries = [
        "What are the revenue figures for Q3 2023?",
        "Show me customer satisfaction trends",
        "Compare sales performance across regions",
        "",  # Test empty query handling
    ]
    
    print("=== Query Orchestrator Enhanced Demo ===\n")
    
    # Process queries individually
    for query in test_queries:
        if not query:  # Skip empty query for individual processing
            continue
            
        print(f"--- Processing: {query} ---")
        
        try:
            result = orchestrator.process_query(query, execution_service=execution_service)
            
            if result.success:
                print(f"✓ Query ID: {result.query_id}")
                print(f"✓ Intent: {result.intent}")
                print(f"✓ Subqueries: {len(result.subqueries)}")
                print(f"✓ Search Results: {result.search_results_count}")
                print(f"✓ Fused Chunks: {result.fused_count}")
                print(f"✓ Citations: {len(result.citations)}")
                print(f"✓ Total Time: {result.metrics.total_ms}ms")
                
                # Enhanced validation
                is_valid, issues = validate_orchestration_result(result)
                if is_valid:
                    print("✓ Validation passed - ready for answer generation")
                else:
                    print(f"✗ Validation issues: {', '.join(issues)}")
                    
            else:
                print(f"✗ Failed at {result.failed_stage.value if result.failed_stage else 'unknown stage'}")
                print(f"✗ Error: {result.error_message}")
                
        except Exception as e:
            print(f"✗ Exception during processing: {str(e)}")
        
        print()
    
    # Demonstrate batch processing
    print("--- Batch Processing Demo ---")
    batch_results = orchestrator.process_query_batch(
        test_queries[:-1],  # Exclude empty query
        execution_service=execution_service
    )
    
    success_rate = sum(1 for r in batch_results if r.success) / len(batch_results) * 100
    avg_time = sum(r.metrics.total_ms for r in batch_results) / len(batch_results)
    
    print(f"Batch completed: {len(batch_results)} queries")
    print(f"Success rate: {success_rate:.1f}%")
    print(f"Average time: {avg_time:.1f}ms")
    
    # Display pipeline info
    print("\n--- Pipeline Information ---")
    info = orchestrator.get_orchestration_info()
    for key, value in info.items():
        print(f"{key}: {value}")