from typing import Dict, List, Optional
import logging
import re

logger = logging.getLogger(__name__)

# Standardized intent names with _QUERY suffix
ANALYTICS_QUERY = "ANALYTICS_QUERY"
COMPARISON_QUERY = "COMPARISON_QUERY"
RETRIEVAL_QUERY = "RETRIEVAL_QUERY"
DEFAULT_QUERY = "DEFAULT_QUERY"

# Extensible keyword mapping dictionary

# Extensible keyword mapping dictionary
INTENT_KEYWORDS: Dict[str, List[str]] = {
    ANALYTICS_QUERY: [
        "trend", "revenue", "sales", "growth", "report", "metrics", "kpi",
        "performance", "analytics", "dashboard", "chart", "graph", "statistics",
        "analysis", "insights", "data", "numbers", "summary", "overview"
    ],
    COMPARISON_QUERY: [
        "compare", "vs", "versus", "difference", "against", "between",
        "comparison", "contrast", "relative", "better", "worse", "than",
        "benchmark", "baseline", "compete", "competing"
    ],
    RETRIEVAL_QUERY: [
        "find", "get", "show", "list", "retrieve", "fetch", "search",
        "lookup", "display", "view", "see", "information", "details",
        "query", "pull", "extract", "obtain", "access"
    ],
    DEFAULT_QUERY: []  # Fallback intent with no specific keywords
}


def get_intent_priority() -> List[str]:
    """
    Get the intent priority order for tie-breaking.

    DEFAULT_QUERY is always last, other intents maintain their order from INTENT_KEYWORDS.

    Returns:
        List[str]: List of intents in priority order
    """
    # Get all intents except DEFAULT_QUERY, maintaining their order
    priority_intents = [intent for intent in INTENT_KEYWORDS.keys() if intent != DEFAULT_QUERY]
    # DEFAULT_QUERY is always last
    priority_intents.append(DEFAULT_QUERY)
    return priority_intents


def extract_word_tokens(text: str) -> List[str]:
    """
    Extract word tokens from text using regex word boundaries.

    Args:
        text: Input text to tokenize

    Returns:
        List[str]: List of lowercase word tokens
    """
    # Use regex to find word tokens (sequences of word characters)
    tokens = re.findall(r'\b\w+\b', text.lower())
    return tokens


def validate_query(query: Optional[str]) -> str:
    """
    Validate and normalize the input query.

    Args:
        query: The input query string to validate

    Returns:
        str: The validated and normalized query string

    Raises:
        ValueError: If query is None, empty, or contains only whitespace
    """
    if query is None:
        raise ValueError("Query cannot be None")

    if not isinstance(query, str):
        raise ValueError(f"Query must be a string, got {type(query)}")

    query_stripped = query.strip()
    if not query_stripped:
        raise ValueError("Query cannot be empty or contain only whitespace")

    return query_stripped


def calculate_intent_scores(query: str) -> Dict[str, int]:
    """
    Calculate keyword match scores for each intent using full word matching.

    Args:
        query: The normalized query string

    Returns:
        Dict[str, int]: Dictionary mapping intent names to their match scores
    """
    query_tokens = extract_word_tokens(query)
    query_token_set = set(query_tokens)
    scores = {}

    for intent, keywords in INTENT_KEYWORDS.items():
        score = 0
        matched_tokens = []

        for keyword in keywords:
            keyword_tokens = extract_word_tokens(keyword)
            # Check if all tokens in the keyword are present in the query
            if all(token in query_token_set for token in keyword_tokens):
                score += 1
                matched_tokens.extend(keyword_tokens)

        scores[intent] = score

        if matched_tokens:
            # Remove duplicates while preserving order
            unique_matched = list(dict.fromkeys(matched_tokens))
            logger.debug(f"Intent '{intent}' matched tokens: {unique_matched} (score: {score})")

    return scores


def select_best_intent(scores: Dict[str, int]) -> str:
    """
    Select the best intent based on scores and priority order.

    Args:
        scores: Dictionary mapping intent names to their match scores

    Returns:
        str: The selected intent name
    """
    # Find the maximum score
    max_score = max(scores.values())

    # If no keywords matched, return default
    if max_score == 0:
        logger.info("No keywords matched, selecting DEFAULT_QUERY")
        return DEFAULT_QUERY

    # Find all intents with the maximum score
    top_intents = [intent for intent, score in scores.items() if score == max_score]

    # If only one intent has the max score, return it
    if len(top_intents) == 1:
        selected_intent = top_intents[0]
        logger.info(f"Intent '{selected_intent}' selected with score {max_score}")
        return selected_intent

    # Handle ties by using priority order
    intent_priority = get_intent_priority()
    for priority_intent in intent_priority:
        if priority_intent in top_intents:
            logger.info(f"Tie-breaking: Intent '{priority_intent}' selected with score {max_score} "
                       f"(candidates with same score: {top_intents})")
            return priority_intent

    # Fallback (should never reach here given our priority list)
    selected_intent = top_intents[0]
    logger.warning(f"Unexpected tie-breaking scenario, selecting '{selected_intent}' "
                  f"from candidates: {top_intents}")
    return selected_intent


def route_intent(query: Optional[str]) -> str:
    """
    Route the given query to an intent type using keyword-based scoring.

    This function implements a robust keyword matching algorithm that:
    1. Validates input and handles edge cases
    2. Counts keyword matches for each intent
    3. Selects the intent with the highest score
    4. Breaks ties using a defined priority order
    5. Falls back to DEFAULT_QUERY when no keywords match

    Args:
        query: User's natural language query string

    Returns:
        str: Detected intent name (e.g., "ANALYTICS_QUERY", "COMPARISON_QUERY",
             "RETRIEVAL_QUERY", "DEFAULT_QUERY")

    Raises:
        ValueError: If query is None, empty, or contains only whitespace

    Examples:
        >>> route_intent("Show me sales trends")
        'ANALYTICS_QUERY'

        >>> route_intent("Compare revenue vs last year")
        'COMPARISON_QUERY'

        >>> route_intent("Find customer information")
        'RETRIEVAL_QUERY'

        >>> route_intent("Hello world")
        'DEFAULT_QUERY'
    """
    try:
        # Step 1: Validate and normalize input
        normalized_query = validate_query(query)
        logger.debug(f"Processing query: '{normalized_query}'")

        # Step 2: Calculate keyword match scores for each intent
        scores = calculate_intent_scores(normalized_query)
        logger.debug(f"Intent scores: {scores}")

        # Step 3: Select the best intent based on scores and priority
        selected_intent = select_best_intent(scores)

        # Step 4: Log final result
        max_score = max(scores.values())
        if max_score > 0:
            logger.info(f"Query '{normalized_query}' routed to '{selected_intent}' with score {max_score}")
        else:
            logger.info(f"Query '{normalized_query}' routed to '{selected_intent}' (no keyword matches)")

        return selected_intent

    except ValueError as e:
        logger.error(f"Query validation failed: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error during intent routing: {e}")
        # In case of unexpected errors, fallback to default intent
        logger.info(f"Falling back to '{DEFAULT_QUERY}' due to error")
        return DEFAULT_QUERY


def get_supported_intents() -> List[str]:
    """
    Get the list of supported intent types.

    Returns:
        List[str]: List of all supported intent names
    """
    return list(INTENT_KEYWORDS.keys())


def get_intent_keywords(intent: str) -> List[str]:
    """
    Get the keywords associated with a specific intent.

    Args:
        intent: The intent name to get keywords for

    Returns:
        List[str]: List of keywords for the specified intent

    Raises:
        ValueError: If the intent is not supported
    """
    if intent not in INTENT_KEYWORDS:
        raise ValueError(f"Unsupported intent: {intent}. "
                        f"Supported intents: {list(INTENT_KEYWORDS.keys())}")

    return INTENT_KEYWORDS[intent].copy()


def add_intent_keywords(intent: str, keywords: List[str]) -> None:
    """
    Add keywords to an existing intent or create a new intent.

    Args:
        intent: The intent name to add keywords to
        keywords: List of keywords to add

    Raises:
        ValueError: If keywords is not a list or contains non-string elements
    """
    if not isinstance(keywords, list):
        raise ValueError("Keywords must be provided as a list")

    if not all(isinstance(kw, str) for kw in keywords):
        raise ValueError("All keywords must be strings")

    if intent not in INTENT_KEYWORDS:
        INTENT_KEYWORDS[intent] = []
        logger.info(f"Created new intent: {intent}")

    # Add new keywords, avoiding duplicates
    existing_keywords = set(INTENT_KEYWORDS[intent])
    new_keywords = [kw for kw in keywords if kw not in existing_keywords]

    if new_keywords:
        INTENT_KEYWORDS[intent].extend(new_keywords)
        logger.info(f"Added {len(new_keywords)} new keywords to intent '{intent}': {new_keywords}")
    else:
        logger.info(f"No new keywords added to intent '{intent}' (all keywords already exist)")