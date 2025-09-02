import copy
import logging
import uuid
from datetime import datetime
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)

# Central dictionary defining steps for each intent type
INTENT_PLANS: Dict[str, List[Dict[str, str]]] = {
    "ANALYTICS_QUERY": [
        {"action": "extract_metrics", "description": "Identify metrics and KPIs in the query"},
        {"action": "extract_timeframe", "description": "Identify temporal scope and date ranges"},
        {"action": "extract_dimensions", "description": "Identify grouping and filtering dimensions"},
        {"action": "build_analytics_query", "description": "Construct structured analytics query with aggregations"}
    ],
    "COMPARISON_QUERY": [
        {"action": "extract_entities", "description": "Identify entities, products, or concepts to compare"},
        {"action": "extract_comparison_criteria", "description": "Determine comparison attributes and metrics"},
        {"action": "build_comparison_matrix", "description": "Structure comparison parameters and filters"},
        {"action": "build_comparison_query", "description": "Construct comparative analysis query"}
    ],
    "RETRIEVAL_QUERY": [
        {"action": "extract_entities", "description": "Identify target entities and information types"},
        {"action": "extract_context", "description": "Determine contextual constraints and scope"},
        {"action": "build_search_terms", "description": "Generate optimized search terms and filters"},
        {"action": "build_retrieval_query", "description": "Construct document retrieval query"}
    ]
}

# Fallback plan for unknown intents
FALLBACK_PLAN: List[Dict[str, str]] = [
    {"action": "analyze_query", "description": "Perform basic query analysis and entity extraction"},
    {"action": "determine_strategy", "description": "Select appropriate retrieval strategy"},
    {"action": "build_generic_query", "description": "Construct general-purpose query"}
]


def generate_query_plan(query: str, intent: str) -> Dict[str, Any]:
    """
    Generate a structured query plan based on the input query and detected intent.
    
    Args:
        query: The original user query string
        intent: The detected intent type (should be one of the standardized _QUERY types)
        
    Returns:
        Dict[str, Any]: Schema {
            plan_id: str,
            intent: str,
            original_query: str,
            steps: List[Dict[str, str]],s
            timestamp: str
        }
        
    Example:
        >>> plan = generate_query_plan("Show me sales trends for Q1", "ANALYTICS_QUERY")
        >>> print(plan['steps'][0]['action'])
        'extract_metrics'
    """
    # Generate unique identifiers and timestamp
    plan_id = str(uuid.uuid4())
    timestamp = datetime.utcnow().isoformat() + "Z"
    
    logger.info(
        "Generating query plan",
        extra={
            "plan_id": plan_id,
            "intent": intent,
            "query_length": len(query),
            "timestamp": timestamp
        }
    )
    
    # Build the plan structure
    plan: Dict[str, Any] = {
        "plan_id": plan_id,
        "intent": intent,
        "original_query": query,
        "steps": [],
        "timestamp": timestamp
    }
    
    # Determine steps based on intent
    if intent in INTENT_PLANS:
        plan["steps"] = copy.deepcopy(INTENT_PLANS[intent])
        logger.info(
            "Using predefined plan for intent",
            extra={
                "plan_id": plan_id,
                "intent": intent,
                "step_count": len(plan["steps"]),
                "steps": [step["action"] for step in plan["steps"]]
            }
        )
    else:
        # Fallback for unknown intents with warning
        plan["steps"] = copy.deepcopy(FALLBACK_PLAN)
        logger.warning(
            "Unknown intent detected, using fallback plan",
            extra={
                "plan_id": plan_id,
                "intent": intent,
                "available_intents": list(INTENT_PLANS.keys()),
                "fallback_steps": [step["action"] for step in FALLBACK_PLAN]
            }
        )
    
    logger.info(
        "Query plan generated successfully",
        extra={
            "plan_id": plan_id,
            "intent": intent,
            "total_steps": len(plan["steps"]),
            "execution_strategy": plan["steps"][0]["action"] if plan["steps"] else "none"
        }
    )
    
    return plan


def get_supported_intents() -> List[str]:
    """
    Get list of supported intent types.
    
    Returns:
        List of supported intent strings
    """
    return list(INTENT_PLANS.keys())


def add_custom_intent_plan(intent: str, steps: List[Dict[str, str]]) -> None:
    """
    Add a custom intent plan to the registry.
    
    Args:
        intent: The intent type identifier
        steps: List of step dictionaries with 'action' and 'description' keys
        
    Raises:
        ValueError: If steps format is invalid
    """
    # Validate steps format
    if not isinstance(steps, list) or not steps:
        raise ValueError("Steps must be a non-empty list")
    
    for step in steps:
        if not isinstance(step, dict) or "action" not in step or "description" not in step:
            raise ValueError("Each step must be a dict with 'action' and 'description' keys")
    
    INTENT_PLANS[intent] = steps
    logger.info(
        "Custom intent plan added",
        extra={
            "intent": intent,
            "step_count": len(steps),
            "actions": [step["action"] for step in steps]
        }
    )


def validate_plan(plan: Dict[str, Any]) -> bool:
    """
    Validate that a plan has the required structure and fields.
    
    Args:
        plan: The plan dictionary to validate
        
    Returns:
        True if plan is valid, False otherwise
    """
    required_fields = ["plan_id", "intent", "original_query", "steps", "timestamp"]
    
    # Check required fields exist
    if not all(field in plan for field in required_fields):
        return False
    
    # Check steps structure
    if not isinstance(plan["steps"], list):
        return False
    
    for step in plan["steps"]:
        if not isinstance(step, dict) or "action" not in step or "description" not in step:
            return False
    
    return True