"""
Query Orchestrator Module

This module handles the orchestration of query processing up to subquery generation.
It follows the pipeline: Query → Intent → QueryPlan → Subqueries
The execution phase (Azure AI Search) is handled separately.

Author: Refactored for clean separation of concerns
"""

import logging
import uuid
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from datetime import datetime

from intent_router import route_intent
from query_engine import generate_query_plan
from retrieval_service import build_subqueries


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
        timestamp: When the orchestration was completed
        success: Whether orchestration was successful
        error_message: Error message if orchestration failed
    """
    query_id: str
    original_query: str
    intent: str
    plan: Dict[str, Any]
    subqueries: List[Dict[str, Any]]
    timestamp: str
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
            "timestamp": self.timestamp,
            "success": self.success,
            "error_message": self.error_message
        }


class QueryOrchestrator:
    """
    Query Orchestrator handles the first three stages of the retrieval pipeline:
    1. Intent Detection - Determines what the user is trying to accomplish
    2. Query Planning - Creates a structured plan based on intent and query
    3. Subquery Generation - Breaks down the plan into executable subqueries
    
    The orchestrator stops after subquery generation, allowing the execution
    phase to be handled separately by downstream components.
    
    Usage:
        orchestrator = QueryOrchestrator()
        result = orchestrator.process_query("What are the sales figures for Q3?")
        # Pass result.subqueries to execution service
    """

    def __init__(self) -> None:
        """Initialize the QueryOrchestrator."""
        logger.info("QueryOrchestrator initialized")

    def process_query(self, query: str) -> OrchestrationResult:
        """
        Process a user query through the orchestration pipeline.
        
        This method executes the following steps:
        1. Intent Detection: Analyzes the query to determine user intent
        2. Query Planning: Creates a structured plan based on intent and query content
        3. Subquery Generation: Breaks down the plan into executable subqueries
        
        Args:
            query (str): The user's natural language query
            
        Returns:
            OrchestrationResult: Contains intent, plan, subqueries, and metadata
            
        Raises:
            ValueError: If query is empty or invalid
            Exception: For any processing errors during orchestration
            
        Example:
            >>> orchestrator = QueryOrchestrator()
            >>> result = orchestrator.process_query("Show me revenue trends for 2023")
            >>> print(result.intent)  # "ANALYTICS_QUERY"
            >>> print(len(result.subqueries))  # 2
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
            
            # Create successful result
            result = OrchestrationResult(
                query_id=query_id,
                original_query=query,
                intent=intent,
                plan=plan,
                subqueries=subqueries,
                timestamp=timestamp,
                success=True
            )
            
            logger.info(
                "Query orchestration completed successfully",
                extra={
                    "query_id": query_id,
                    "intent": intent,
                    "subquery_count": len(subqueries),
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
            "handoff_point": "Subqueries are passed to execution service (handled separately)",
            "pipeline_flow": "Query → Intent → QueryPlan → Subqueries → [Execution Service]"
        }


# Utility function for external validation
def validate_orchestration_result(result: OrchestrationResult) -> bool:
    """
    Validate that an orchestration result is properly formatted for handoff.
    
    Args:
        result (OrchestrationResult): The result to validate
        
    Returns:
        bool: True if result is valid for handoff to execution service
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
        
    return True


# Example usage and testing helper
if __name__ == "__main__":
    """
    Example usage of the QueryOrchestrator.
    This demonstrates how Sneha & Kruthik can use the orchestrator
    and hand off subqueries to Rishabh's execution service.
    """
    
    # Configure logging for local testing
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s'
    )
    
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
        
        # Process query through orchestration
        result = orchestrator.process_query(query)
        
        if result.success:
            print(f"✓ Query ID: {result.query_id}")
            print(f"✓ Intent: {result.intent}")
            print(f"✓ Subqueries: {len(result.subqueries)} generated")
            
            # Validate result before handoff
            if validate_orchestration_result(result):
                print("✓ Result validated - ready for execution service")
                
                # This is where you would hand off to Rishabh's execution service:
                # execution_result = rishabh_execution_service.execute(result.subqueries)
                
            else:
                print("✗ Result validation failed")
        else:
            print(f"✗ Orchestration failed: {result.error_message}")
        
        # Demonstrate the to_dict method for JSON-like output
        result_dict = result.to_dict()
        print(f"✓ Dictionary format available with {len(result_dict)} fields")