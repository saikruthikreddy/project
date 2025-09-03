import logging
import uuid
import re
import json
from datetime import datetime
from typing import Any, Dict, List, Set

logger = logging.getLogger(__name__)


def build_subqueries(plan: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build natural language subqueries based on the given query plan and save to JSON file.
    
    Args:
        plan: Dictionary containing plan metadata and steps
              Expected keys: 'intent', 'plan_id', 'steps', 'original_query'
              
    Returns:
        Dictionary with 'subqueries' key containing list of natural language queries
        and 'structured_subqueries' key containing the structured JSON format
        
    Raises:
        ValueError: If plan is missing required fields
    """
    # Extract plan metadata
    intent = plan.get("intent", "RETRIEVAL_QUERY")
    plan_id = plan.get("plan_id")
    original_query = plan.get("original_query", "")
    
    if not plan_id:
        raise ValueError("Plan must contain 'plan_id' field")
    
    if not original_query:
        raise ValueError("Plan must contain 'original_query' field")
    
    logger.info(f"Building natural language subqueries for plan intent '{intent}' (plan_id: {plan_id})")
    logger.info(f"Original query: '{original_query}'")
    
    # Analyze the original query to extract components
    query_analysis = _analyze_query(original_query)
    
    # Generate natural language subqueries
    subqueries = _generate_natural_language_subqueries(original_query, query_analysis)
    
    # Ensure we have at least one subquery
    if not subqueries:
        # Fallback to the original query if no subqueries were generated
        subqueries = [original_query]
    
    logger.info(f"Generated {len(subqueries)} natural language subqueries for plan '{plan_id}'")
    logger.debug(f"Subqueries: {subqueries}")
    
    # Create structured subqueries following the schema
    structured_subqueries = _create_structured_subqueries(subqueries, plan_id, intent)
    
    # Save structured subqueries to JSON file
    _save_subqueries_to_json(structured_subqueries)
    
    return {
        "subqueries": subqueries,
        "structured_subqueries": structured_subqueries
    }


def _create_structured_subqueries(subqueries: List[str], plan_id: str, intent: str) -> List[Dict[str, Any]]:
    """
    Create structured subqueries following the required schema.
    
    Args:
        subqueries: List of natural language subqueries
        plan_id: The plan ID from the input
        intent: The intent from the input plan
        
    Returns:
        List of structured subquery dictionaries
    """
    structured_subqueries = []
    current_timestamp = datetime.utcnow().isoformat() + "Z"
    
    for index, subquery in enumerate(subqueries):
        structured_subquery = {
            "subquery_id": str(uuid.uuid4()),
            "plan_id": plan_id,
            "intent": intent,
            "action": "build_natural_language_subquery",
            "description": subquery,
            "parameters": {
                "generated_from": "build_subqueries",
                "original_index": index,
                "generation_method": "natural_language_processing"
            },
            "timestamp": current_timestamp,
            "step_index": index
        }
        structured_subqueries.append(structured_subquery)
    
    logger.debug(f"Created {len(structured_subqueries)} structured subqueries")
    return structured_subqueries


def _save_subqueries_to_json(structured_subqueries: List[Dict[str, Any]], filename: str = "subqueries.json") -> None:
    """
    Save structured subqueries to a JSON file.
    
    Args:
        structured_subqueries: List of structured subquery dictionaries
        filename: Name of the JSON file to save to
    """
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(structured_subqueries, f, indent=2, ensure_ascii=False)
        logger.info(f"Successfully saved {len(structured_subqueries)} structured subqueries to {filename}")
    except Exception as e:
        logger.error(f"Failed to save subqueries to {filename}: {e}")
        raise


def _generate_natural_language_subqueries(original_query: str, analysis: Dict[str, Any]) -> List[str]:
    """
    Generate natural language subqueries based on the original query and its analysis.
    
    Args:
        original_query: The original user query
        analysis: Analyzed components of the query
        
    Returns:
        List of natural language subqueries
    """
    subqueries = []
    entities = analysis.get("entities", [])
    context = analysis.get("context", "")
    intent_type = analysis.get("intent_type", "")
    keywords = analysis.get("keywords", [])
    
    # Always start with the main reformulated query
    main_query = _build_main_reformulated_query(original_query, analysis)
    subqueries.append(main_query)
    
    # Generate context-specific subqueries based on the type of query
    if _is_stock_query(original_query, entities, keywords):
        subqueries.extend(_generate_stock_subqueries(entities, original_query))
    
    elif _is_financial_performance_query(original_query, entities, keywords):
        subqueries.extend(_generate_financial_performance_subqueries(entities, original_query))
    
    elif _is_comparison_query(original_query, context, intent_type):
        subqueries.extend(_generate_comparison_subqueries(entities, original_query))
    
    elif _is_how_to_query(original_query, context, intent_type):
        subqueries.extend(_generate_how_to_subqueries(entities, original_query))
    
    elif _is_benefits_why_query(original_query, context, intent_type):
        subqueries.extend(_generate_benefits_subqueries(entities, original_query))
    
    elif _is_cost_pricing_query(original_query, context, keywords):
        subqueries.extend(_generate_cost_subqueries(entities, original_query))
    
    else:
        # General subqueries for other types of queries
        subqueries.extend(_generate_general_subqueries(entities, original_query, analysis))
    
    # Remove duplicates while preserving order
    seen = set()
    unique_subqueries = []
    for query in subqueries:
        if query.lower() not in seen:
            seen.add(query.lower())
            unique_subqueries.append(query)
    
    return unique_subqueries


def _build_main_reformulated_query(original_query: str, analysis: Dict[str, Any]) -> str:
    """
    Build the main reformulated query based on the original query and analysis.
    
    Args:
        original_query: The original user query
        analysis: Analyzed components of the query
        
    Returns:
        Reformulated main query string
    """
    entities = analysis.get("entities", [])
    intent_type = analysis.get("intent_type", "")
    
    # Clean up the original query and ensure it ends with a question mark
    cleaned_query = original_query.strip()
    if not cleaned_query.endswith('?'):
        cleaned_query += '?'
    
    # For stock queries, be more specific about "current" price
    if _is_stock_query(original_query, entities, analysis.get("keywords", [])):
        if entities:
            main_entity = entities[0]
            if "stock" in original_query.lower() and "today" in original_query.lower():
                return f"What is the current stock price of {main_entity} today?"
            elif "stock" in original_query.lower():
                return f"What is the current stock price of {main_entity}?"
    
    # For other specific query types, enhance clarity
    if intent_type == "explanation" and entities:
        main_entity = entities[0]
        return f"What are the benefits and reasons for using {main_entity}?"
    
    elif intent_type == "instruction" and entities:
        main_entity = entities[0]
        return f"How do you implement and use {main_entity}?"
    
    elif intent_type == "comparison" and entities:
        main_entity = entities[0]
        return f"How does {main_entity} compare to alternatives?"
    
    # Default: return cleaned original query
    return cleaned_query


def _is_stock_query(query: str, entities: List[str], keywords: List[str]) -> bool:
    """Check if this is a stock-related query."""
    query_lower = query.lower()
    stock_indicators = ['stock', 'share', 'price', 'trading', 'market cap', 'ticker']
    return any(indicator in query_lower for indicator in stock_indicators) or any(keyword in ['stock', 'share', 'price'] for keyword in keywords)


def _is_financial_performance_query(query: str, entities: List[str], keywords: List[str]) -> bool:
    """Check if this is a financial performance query."""
    query_lower = query.lower()
    financial_indicators = ['revenue', 'profit', 'earnings', 'margin', 'q1', 'q2', 'q3', 'q4', 'quarter', 'quarterly']
    return any(indicator in query_lower for indicator in financial_indicators)


def _is_comparison_query(query: str, context: str, intent_type: str) -> bool:
    """Check if this is a comparison query."""
    return intent_type == "comparison" or "comparative analysis" in context


def _is_how_to_query(query: str, context: str, intent_type: str) -> bool:
    """Check if this is a how-to/implementation query."""
    return intent_type == "instruction" or "implementation guidance" in context


def _is_benefits_why_query(query: str, context: str, intent_type: str) -> bool:
    """Check if this is a benefits/why query."""
    return intent_type == "explanation" or "reasons for usage, benefits" in context


def _is_cost_pricing_query(query: str, context: str, keywords: List[str]) -> bool:
    """Check if this is a cost/pricing query."""
    return "cost and pricing" in context or any(keyword in ['cost', 'price', 'pricing'] for keyword in keywords)


def _generate_stock_subqueries(entities: List[str], original_query: str) -> List[str]:
    """Generate stock-specific subqueries."""
    subqueries = []
    main_entity = entities[0] if entities else "the stock"
    
    subqueries.extend([
        f"How did {main_entity} stock perform in the last trading session?",
        f"What is the intraday high and low of {main_entity} stock today?",
        f"What is the trading volume of {main_entity} today?",
        f"How does {main_entity} performance today compare to yesterday?"
    ])
    
    if "today" in original_query.lower():
        subqueries.append(f"What news or events are influencing {main_entity} stock today?")
    else:
        subqueries.append(f"What are the recent market trends affecting {main_entity}?")
    
    return subqueries


def _generate_financial_performance_subqueries(entities: List[str], original_query: str) -> List[str]:
    """Generate financial performance subqueries."""
    subqueries = []
    main_entity = entities[0] if entities else "the company"
    
    if "q4" in original_query.lower() or "quarter" in original_query.lower():
        subqueries.extend([
            f"What were the gross and operating margins for {main_entity} last quarter?",
            f"What was the revenue growth for {main_entity} last quarter?",
            f"What were the main drivers of change for {main_entity} versus the previous quarter?",
            f"How did {main_entity} perform compared to market expectations last quarter?"
        ])
    else:
        subqueries.extend([
            f"What is {main_entity}'s current financial performance?",
            f"What are the key financial metrics for {main_entity}?",
            f"How has {main_entity}'s financial performance trended over time?",
            f"What factors are driving {main_entity}'s financial results?"
        ])
    
    return subqueries


def _generate_comparison_subqueries(entities: List[str], original_query: str) -> List[str]:
    """Generate comparison subqueries."""
    subqueries = []
    main_entity = entities[0] if entities else "the service"
    
    subqueries.extend([
        f"What are the key features and capabilities of {main_entity}?",
        f"What are the main competitors or alternatives to {main_entity}?",
        f"What are the pros and cons of {main_entity} compared to alternatives?",
        f"In what scenarios is {main_entity} the best choice?",
        f"What do users typically choose between {main_entity} and its competitors?"
    ])
    
    return subqueries


def _generate_how_to_subqueries(entities: List[str], original_query: str) -> List[str]:
    """Generate how-to/implementation subqueries."""
    subqueries = []
    main_entity = entities[0] if entities else "the service"
    
    subqueries.extend([
        f"What are the prerequisites for implementing {main_entity}?",
        f"What are the step-by-step instructions for setting up {main_entity}?",
        f"What are the common challenges when implementing {main_entity}?",
        f"What are the best practices for using {main_entity}?",
        f"What resources and documentation are available for {main_entity}?"
    ])
    
    return subqueries


def _generate_benefits_subqueries(entities: List[str], original_query: str) -> List[str]:
    """Generate benefits/why subqueries."""
    subqueries = []
    main_entity = entities[0] if entities else "the service"
    
    subqueries.extend([
        f"What are the main advantages of using {main_entity}?",
        f"What problems does {main_entity} solve?",
        f"What are the key use cases for {main_entity}?",
        f"How does {main_entity} improve business outcomes?",
        f"What makes {main_entity} different from other solutions?"
    ])
    
    return subqueries


def _generate_cost_subqueries(entities: List[str], original_query: str) -> List[str]:
    """Generate cost/pricing subqueries."""
    subqueries = []
    main_entity = entities[0] if entities else "the service"
    
    subqueries.extend([
        f"What are the pricing tiers and options for {main_entity}?",
        f"What factors affect the cost of {main_entity}?",
        f"How does the pricing of {main_entity} compare to competitors?",
        f"What is the total cost of ownership for {main_entity}?",
        f"Are there any hidden costs or additional fees for {main_entity}?"
    ])
    
    return subqueries


def _generate_general_subqueries(entities: List[str], original_query: str, analysis: Dict[str, Any]) -> List[str]:
    """Generate general supporting subqueries."""
    subqueries = []
    main_entity = entities[0] if entities else "the topic"
    context = analysis.get("context", "")
    
    # Add context-appropriate subqueries
    if "performance" in context:
        subqueries.append(f"What are the performance characteristics of {main_entity}?")
    
    if "security" in context:
        subqueries.append(f"What are the security features of {main_entity}?")
    
    if "features" in context or "capabilities" in context:
        subqueries.append(f"What are the key features and capabilities of {main_entity}?")
    
    # Add some general supporting queries if none were added yet
    if not subqueries:
        subqueries.extend([
            f"What is {main_entity} and how does it work?",
            f"What are the main use cases for {main_entity}?",
            f"What should I know about {main_entity}?"
        ])
    
    return subqueries


def _analyze_query(query: str) -> Dict[str, Any]:
    """
    Analyze the original query to extract entities, context, and intent.
    
    Args:
        query: The original user query
        
    Returns:
        Dictionary containing extracted components
    """
    analysis = {
        "entities": _extract_entities(query),
        "context": _extract_context(query),
        "keywords": _extract_keywords(query),
        "intent_type": _determine_intent_type(query)
    }
    
    logger.debug(f"Query analysis: {analysis}")
    return analysis


def _extract_entities(query: str) -> List[str]:
    """
    Extract named entities from the query using heuristics.
    
    Args:
        query: The original user query
        
    Returns:
        List of identified entities
    """
    entities = []
    
    # Pattern for capitalized phrases (likely proper nouns/products)
    capitalized_pattern = r'\b[A-Z][a-zA-Z]*(?:\s+[A-Z][a-zA-Z]*)*\b'
    matches = re.findall(capitalized_pattern, query)
    
    # Filter out common words and single letters
    common_words = {'I', 'Why', 'What', 'How', 'When', 'Where', 'Should', 'Can', 'Will', 'Does', 'Is', 'Are'}
    for match in matches:
        if match not in common_words and len(match) > 1:
            entities.append(match)
    
    # Look for technical terms or products (containing specific patterns)
    technical_patterns = [
        r'\b\w*AI\w*\b',  # AI-related terms
        r'\b\w*Search\w*\b',  # Search-related terms
        r'\b\w*Azure\w*\b',  # Azure-related terms
        r'\b\w*Service\w*\b',  # Service-related terms
    ]
    
    for pattern in technical_patterns:
        matches = re.findall(pattern, query, re.IGNORECASE)
        for match in matches:
            if match.lower() not in [e.lower() for e in entities]:
                entities.append(match)
    
    # If no entities found, try to extract key nouns
    if not entities:
        # Simple noun extraction (words that aren't common question words)
        words = re.findall(r'\b[a-zA-Z]+\b', query)
        question_words = {'why', 'what', 'how', 'when', 'where', 'should', 'can', 'will', 'does', 'is', 'are', 'i', 'use', 'the', 'a', 'an', 'and', 'or', 'but'}
        for word in words:
            if word.lower() not in question_words and len(word) > 2:
                entities.append(word.title())
    
    return list(set(entities))  # Remove duplicates


def _extract_context(query: str) -> str:
    """
    Extract contextual information from the query.
    
    Args:
        query: The original user query
        
    Returns:
        String describing the context
    """
    query_lower = query.lower()
    
    # Context patterns and their meanings
    context_patterns = {
        r'\b(?:why|reasons?|benefits?|advantages?)\b': 'reasons for usage, benefits',
        r'\b(?:how|guide|tutorial|steps?)\b': 'implementation guidance, instructions',
        r'\b(?:what|definition|explanation)\b': 'conceptual understanding, definitions',
        r'\b(?:when|timing|schedule)\b': 'timing and scheduling information',
        r'\b(?:where|location|deployment)\b': 'location and deployment context',
        r'\b(?:comparison|vs|versus|compare|better)\b': 'comparative analysis',
        r'\b(?:cost|price|pricing|expensive|cheap)\b': 'cost and pricing information',
        r'\b(?:performance|speed|fast|slow)\b': 'performance characteristics',
        r'\b(?:security|secure|safety)\b': 'security and safety considerations',
        r'\b(?:features?|capabilities|functionality)\b': 'feature exploration'
    }
    
    contexts = []
    for pattern, context in context_patterns.items():
        if re.search(pattern, query_lower):
            contexts.append(context)
    
    if contexts:
        return ', '.join(contexts)
    else:
        return 'general information'


def _extract_keywords(query: str) -> List[str]:
    """
    Extract and expand keywords from the query.
    
    Args:
        query: The original user query
        
    Returns:
        List of keywords including synonyms
    """
    keywords = []
    query_lower = query.lower()
    
    # Synonym mapping for common terms
    synonym_map = {
        'why': ['reasons', 'benefits', 'advantages', 'rationale'],
        'use': ['utilize', 'implement', 'employ', 'apply'],
        'search': ['find', 'discover', 'lookup', 'query', 'retrieve'],
        'ai': ['artificial intelligence', 'machine learning', 'intelligent'],
        'azure': ['microsoft azure', 'cloud platform'],
        'benefits': ['advantages', 'pros', 'merits', 'value'],
        'features': ['capabilities', 'functionality', 'options'],
        'performance': ['speed', 'efficiency', 'optimization'],
        'cost': ['price', 'pricing', 'expense', 'budget']
    }
    
    # Extract base keywords from query
    words = re.findall(r'\b[a-zA-Z]+\b', query_lower)
    stop_words = {'i', 'should', 'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with'}
    
    base_keywords = [word for word in words if word not in stop_words and len(word) > 2]
    
    # Add synonyms for recognized terms
    for word in base_keywords:
        keywords.append(word)
        if word in synonym_map:
            keywords.extend(synonym_map[word])
    
    # Add domain-specific terms based on entities
    entities = _extract_entities(query)
    for entity in entities:
        entity_lower = entity.lower()
        if 'azure' in entity_lower and 'search' in entity_lower:
            keywords.extend(['cognitive search', 'search service', 'indexing', 'search engine'])
    
    return list(set(keywords))  # Remove duplicates


def _determine_intent_type(query: str) -> str:
    """
    Determine the type of intent from the query.
    
    Args:
        query: The original user query
        
    Returns:
        String representing the intent type
    """
    query_lower = query.lower()
    
    if re.search(r'\b(?:why|reasons?|benefits?)\b', query_lower):
        return 'explanation'
    elif re.search(r'\b(?:how|guide|tutorial)\b', query_lower):
        return 'instruction'
    elif re.search(r'\b(?:what|definition)\b', query_lower):
        return 'definition'
    elif re.search(r'\b(?:compare|vs|versus|better)\b', query_lower):
        return 'comparison'
    else:
        return 'general'


# Legacy validation functions kept for compatibility but not used in new implementation
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
            
        # Validate that parameters is not empty
        if not subquery.get("parameters"):
            logger.error(f"Subquery {i} 'parameters' cannot be empty")
            return False
    
    logger.debug(f"Successfully validated {len(subqueries)} subqueries")
    return True