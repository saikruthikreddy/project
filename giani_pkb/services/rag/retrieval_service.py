import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def build_subqueries(plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Build enriched subqueries based on the given query plan.
    
    Args:
        plan: Dictionary containing plan metadata and steps
              Expected keys: 'intent', 'plan_id', 'steps'
              
    Returns:
        List of subquery dictionaries with enriched metadata
        
    Raises:
        ValueError: If plan is missing required fields or steps are invalid
    """
    # Extract plan metadata
    intent = plan.get("intent")
    plan_id = plan.get("plan_id")
    steps = plan.get("steps", [])
    
    if not intent:
        raise ValueError("Plan must contain 'intent' field")
    
    if not plan_id:
        raise ValueError("Plan must contain 'plan_id' field")
    
    logger.info(f"Building subqueries for plan intent '{intent}' (plan_id: {plan_id})")
    
    subqueries = []
    
    for i, step in enumerate(steps):
        # Validate step before conversion
        if not _validate_step(step, i):
            logger.warning(f"Skipping invalid step {i}: {step}")
            continue
            
        # Generate subquery with enriched metadata
        subquery_id = str(uuid.uuid4())
        subquery = {
            "subquery_id": subquery_id,
            "plan_id": plan_id,
            "intent": intent,
            "action": step.get("action"),
            "description": step.get("description"),
            "parameters": _build_parameters(step),
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "step_index": i
        }
        
        subqueries.append(subquery)
        logger.debug(f"Created subquery {subquery_id} for action '{step.get('action')}'")
    
    # Handle case where no valid subqueries were generated
    if not subqueries:
        raise ValueError("No valid subqueries could be generated from the plan")
    
    # Validate the complete subquery collection
    if not validate_subqueries(subqueries):
        raise ValueError("Generated subqueries failed validation")
    
    subquery_ids = [sq["subquery_id"] for sq in subqueries]
    logger.info(
        f"Generated {len(subqueries)} subqueries for plan '{plan_id}' "
        f"with intent '{intent}'. Subquery IDs: {subquery_ids}"
    )
    
    return subqueries


def _validate_step(step: Dict[str, Any], step_index: int) -> bool:
    """
    Validate that a step contains required fields for subquery conversion.
    
    Args:
        step: Step dictionary to validate
        step_index: Index of the step for logging purposes
        
    Returns:
        True if step is valid, False otherwise
    """
    if not isinstance(step, dict):
        logger.error(f"Step {step_index} is not a dictionary: {type(step)}")
        return False
    
    if not step.get("action"):
        logger.error(f"Step {step_index} missing required 'action' field")
        return False
        
    if not step.get("description"):
        logger.error(f"Step {step_index} missing required 'description' field")
        return False
    
    return True


def _build_parameters(step: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build parameters dictionary for a subquery step.
    
    Args:
        step: Step dictionary containing action and other metadata
        
    Returns:
        Parameters dictionary with at least source_step
    """
    # Start with placeholder parameters
    parameters = {
        "source_step": step.get("action", "unknown_action")
    }
    
    # Add any additional step-specific parameters
    # This is extensible for future parameter mapping
    if "query" in step:
        parameters["query"] = step["query"]
    if "filters" in step:
        parameters["filters"] = step["filters"]
    if "context" in step:
        parameters["context"] = step["context"]
        
    return parameters


def validate_subqueries(subqueries: List[Dict[str, Any]]) -> bool:
    """
    Validate that all subqueries conform to the expected schema.
    
    Args:
        subqueries: List of subquery dictionaries to validate
        
    Returns:
        True if all subqueries are valid, False otherwise
    """
    if not isinstance(subqueries, list):
        logger.error("Subqueries must be a list")
        return False
    
    required_fields = {
        "subquery_id", "plan_id", "intent", "action", 
        "description", "parameters", "timestamp", "step_index"
    }
    
    for i, subquery in enumerate(subqueries):
        if not isinstance(subquery, dict):
            logger.error(f"Subquery {i} is not a dictionary")
            return False
            
        missing_fields = required_fields - set(subquery.keys())
        if missing_fields:
            logger.error(f"Subquery {i} missing required fields: {missing_fields}")
            return False
            
        # Validate specific field types
        if not isinstance(subquery.get("subquery_id"), str):
            logger.error(f"Subquery {i} 'subquery_id' must be string")
            return False
            
        if not isinstance(subquery.get("parameters"), dict):
            logger.error(f"Subquery {i} 'parameters' must be dictionary")
            return False
    
    logger.debug(f"Successfully validated {len(subqueries)} subqueries")
    return True