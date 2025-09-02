"""
Query Orchestrator Module

This module handles the orchestration of query processing up to subquery generation.
It follows the pipeline: Query → Intent → QueryPlan → Subqueries → Azure AI Search
The post-processing and fusion phases are handled separately.

Author: Refactored for clean separation of concerns
"""

import logging
import uuid
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from datetime import datetime

from giani_pkb.services.rag.intent_router import route_intent
from giani_pkb.services.rag.query_engine import generate_query_plan
from giani_pkb.services.rag.retrieval_service import build_subqueries
from giani_pkb.services.ai_search_service import AzureSearchService

# Configure structured logging
logger = logging.getLogger(__name__)

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
        search_results: Results from Azure AI Search for each subquery
        timestamp: When the orchestration was completed
        success: Whether orchestration was successful
        error_message: Error message if orchestration failed
    """
    query_id: str
    original_query: str
    intent: str
    plan: Dict[str, Any]
    subqueries: List[Dict[str, Any]]
    search_results: Optional[List[Dict[str, Any]]] = None
    timestamp: str = ""
    success: bool = True
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert OrchestrationResult to dictionary format.

        Returns:
            Dict[str, Any]: Dictionary containing all fields
        """
        return {
            "query_id": self.query_id,
            "original_query": self.original_query,
            "intent": self.intent,
            "plan": self.plan,
            "subqueries": self.subqueries,
            "search_results": self.search_results,
            "timestamp": self.timestamp,
            "success": self.success,
            "error_message": self.error_message
        }


class QueryOrchestrator:
    """
    Query Orchestrator handles the first four stages of the retrieval pipeline:
    1. Intent Detection - Determines what the user is trying to accomplish
    2. Query Planning - Creates a structured plan based on intent and query
    3. Subquery Generation - Breaks down the plan into executable subqueries
    4. Azure AI Search - Executes subqueries against the search index (includes semantic reranking)

    The orchestrator stops after Azure AI Search, allowing the post-processing
    and fusion phases to be handled separately by downstream components.

    Usage:
        orchestrator = QueryOrchestrator()
        result = orchestrator.process_query("What are the sales figures for Q3?")
        # Pass result.search_results to post-processing service
    """

    def __init__(self) -> None:
        """Initialize the QueryOrchestrator."""
        self.ai_search_service = AzureSearchService()
        logger.info("QueryOrchestrator initialized with Azure AI Search Service")

    async def process_query(self, query: str, project_id: int) -> OrchestrationResult:
        """
        Process a user query through the orchestration pipeline.

        This method executes the following steps:
        1. Intent Detection: Analyzes the query to determine user intent
        2. Query Planning: Creates a structured plan based on intent and query content
        3. Subquery Generation: Breaks down the plan into executable subqueries
        4. Azure AI Search: Executes subqueries against the search index (includes semantic reranking)

        Args:
            query (str): The user's natural language query

        Returns:
            OrchestrationResult: Contains intent, plan, subqueries, and search results

        Raises:
            ValueError: If query is empty or invalid
            Exception: For any processing errors during orchestration

        Example:
            >>> orchestrator = QueryOrchestrator()
            >>> result = orchestrator.process_query("Show me revenue trends for 2023")
            >>> print(result.intent)  # "ANALYTICS_QUERY"
            >>> print(len(result.search_results))  # 4 subqueries executed
        """
        # Input validation
        if not query or not query.strip():
            raise ValueError("Query cannot be empty or whitespace only")

        query = query.strip()
        query_id = str(uuid.uuid4())
        timestamp = datetime.utcnow().isoformat()

        logger.info(
            "Starting query orchestration",
            extra={
                "query_id": query_id,
                "query_length": len(query),
                "timestamp": timestamp
            }
        )

        try:
            # Step 1: Intent Detection
            logger.info(
                "Step 1: Detecting intent",
                extra={"query_id": query_id, "step": "intent_detection"}
            )
            intent = route_intent(query)
            logger.info(
                "Intent detection completed",
                extra={
                    "query_id": query_id,
                    "detected_intent": intent,
                    "step": "intent_detection"
                }
            )

            # Step 2: Query Planning
            logger.info(
                "Step 2: Generating query plan",
                extra={"query_id": query_id, "step": "query_planning", "intent": intent}
            )
            plan = generate_query_plan(query, intent)
            logger.info(
                "Query plan generation completed",
                extra={
                    "query_id": query_id,
                    "plan_type": plan.get("type", "unknown"),
                    "step": "query_planning"
                }
            )

            # Step 3: Subquery Generation
            logger.info(
                "Step 3: Building subqueries",
                extra={"query_id": query_id, "step": "subquery_generation", "plan_type": plan.get("type")}
            )
            subqueries = build_subqueries(plan)
            logger.info(
                "Subquery generation completed",
                extra={
                    "query_id": query_id,
                    "subquery_count": len(subqueries),
                    "step": "subquery_generation"
                }
            )

            # Step 4: Azure AI Search (includes semantic reranking)
            logger.info(
                "Step 4: Executing Azure AI Search",
                extra={"query_id": query_id, "step": "azure_ai_search", "subquery_count": len(subqueries)}
            )
            search_results = await self._execute_search_queries(subqueries, project_id)
            logger.info(
                "Azure AI Search completed",
                extra={
                    "query_id": query_id,
                    "search_results_count": len(search_results),
                    "step": "azure_ai_search"
                }
            )

            # Create successful result
            result = OrchestrationResult(
                query_id=query_id,
                original_query=query,
                intent=intent,
                plan=plan,
                subqueries=subqueries,
                search_results=search_results,
                timestamp=timestamp,
                success=True
            )

            logger.info(
                "Query orchestration completed successfully",
                extra={
                    "query_id": query_id,
                    "intent": intent,
                    "subquery_count": len(subqueries),
                    "search_results_count": len(search_results),
                    "execution_stage": "completed"
                }
            )

            return result

        except Exception as e:
            error_message = f"Query orchestration failed: {str(e)}"
            logger.error(
                "Query orchestration failed",
                extra={
                    "query_id": query_id,
                    "error_type": type(e).__name__,
                    "error_message": str(e)
                },
                exc_info=True
            )

            # Return error result instead of raising
            return OrchestrationResult(
                query_id=query_id,
                original_query=query,
                intent="",
                plan={},
                subqueries=[],
                timestamp=timestamp,
                success=False,
                error_message=error_message
            )

    def get_orchestration_info(self) -> Dict[str, str]:
        """
        Get information about the orchestration pipeline stages.

        Returns:
            Dict[str, str]: Information about each pipeline stage
        """
        return {
            "stage_1": "Intent Detection - Analyzes query to determine user intent",
            "stage_2": "Query Planning - Creates structured plan based on intent",
            "stage_3": "Subquery Generation - Breaks plan into executable subqueries",
            "stage_4": "Azure AI Search - Executes subqueries with semantic reranking",
            "stage_5": "Post-Processing - Deduplicates, filters, and enriches results",
            "stage_6": "Fusion - Combines results from multiple subqueries",
            "stage_7": "Synthesis - Calls LLM to get the answer",
            "pipeline_flow": "Query → Intent → QueryPlan → Subqueries → Azure AI Search → PostProcess → Fusion → Synthesis Service"
        }

    async def _execute_search_queries(self, subqueries: List[Dict[str, Any]], project_id: int) -> List[Dict[str, Any]]:
        """
        Execute Azure AI Search for each subquery.
        This includes semantic reranking automatically handled by Azure AI Search.

        Args:
            subqueries: List of subqueries to execute

        Returns:
            List[Dict[str, Any]]: Search results for each subquery
        """
        search_results = []

        for i, subquery in enumerate(subqueries):
            try:
                query_text = subquery.get("query", "")
                chunk_types = subquery.get("chunk_types", None)

                logger.info(
                    f"Executing subquery {i+1}/{len(subqueries)}",
                    extra={
                        "subquery_index": i,
                        "query_text": query_text[:100],  # Truncate for logging
                        "chunk_types": chunk_types
                    }
                )

                # Execute search with semantic and vector search enabled
                result = await self.ai_search_service.search_documents(
                    query=query_text,
                    project_id=project_id,
                    chunk_types=chunk_types,
                    top=20,  # Get more results for better fusion
                    use_semantic_search=True,  # Enables semantic reranking
                    use_vector_search=True
                )

                # Add subquery metadata to results
                result["subquery_metadata"] = {
                    "subquery_index": i,
                    "subquery_id": subquery.get("id", f"subquery_{i}"),
                    "subquery_type": subquery.get("type", "unknown")
                }

                search_results.append(result)

            except Exception as e:
                logger.error(
                    f"Error executing subquery {i+1}: {str(e)}",
                    extra={"subquery_index": i, "error": str(e)}
                )
                # Add empty result to maintain indexing
                search_results.append({
                    "documents": [],
                    "total_count": 0,
                    "query": subquery.get("query", ""),
                    "subquery_metadata": {
                        "subquery_index": i,
                        "subquery_id": subquery.get("id", f"subquery_{i}"),
                        "subquery_type": subquery.get("type", "unknown"),
                        "error": str(e)
                    }
                })

        return search_results

# Utility function for external validation
def validate_orchestration_result(result: OrchestrationResult) -> bool:
    """
    Validate that an orchestration result is properly formatted for handoff.

    Args:
        result (OrchestrationResult): The result to validate

    Returns:
        bool: True if result is valid for handoff to post-processing service
    """
    if not result.success:
        return False

    required_fields = [
        result.query_id,
        result.original_query,
        result.intent,
        result.plan,
        result.subqueries
    ]

    # Check all required fields are present and non-empty
    if not all(field for field in required_fields):
        return False

    # Validate subqueries structure
    if not isinstance(result.subqueries, list) or len(result.subqueries) == 0:
        return False

    # Ensure each subquery is a dictionary
    for subquery in result.subqueries:
        if not isinstance(subquery, dict):
            return False

    # Validate search results if present
    if result.search_results is not None:
        if not isinstance(result.search_results, list):
            return False

    return True


# Example usage and testing helper
if __name__ == "__main__":
    """
    Example usage of the QueryOrchestrator.
    This demonstrates the orchestration pipeline from query to search results.
    """

    import asyncio

    # Configure logging for local testing
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s'
    )

    async def test_orchestrator():
        # Initialize orchestrator
        orchestrator = QueryOrchestrator()

        # Example queries to test
        test_queries = [
            "What are the revenue figures for Q3 2023?",
            "Show me customer satisfaction trends",
            "Compare sales performance across regions"
        ]

        for query in test_queries:
            print(f"\n--- Processing: {query} ---")

            # Process query through orchestration pipeline
            result = await orchestrator.process_query(query)

            if result.success:
                print(f"✓ Query ID: {result.query_id}")
                print(f"✓ Intent: {result.intent}")
                print(f"✓ Subqueries: {len(result.subqueries)} generated")
                print(f"✓ Search Results: {len(result.search_results) if result.search_results else 0} subqueries executed")

                # Validate result before handoff
                if validate_orchestration_result(result):
                    print("✓ Result validated - ready for post-processing service")

                    # Send results for post processing

                else:
                    print("✗ Result validation failed")
            else:
                print(f"✗ Orchestration failed: {result.error_message}")

            # Demonstrate the to_dict method for JSON-like output
            result_dict = result.to_dict()
            print(f"✓ Dictionary format available with {len(result_dict)} fields")

    # Run the async test
    asyncio.run(test_orchestrator())