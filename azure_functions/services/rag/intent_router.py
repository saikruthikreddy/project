# --- START OF FILE intent_router.py ---
from typing import Dict, List, Tuple, Any, TypedDict
import numpy as np
import logging

# --- FIX: Import the central config loader ---
from services.rag.config_loader import load_orchestration_config as get_config


logger = logging.getLogger(__name__)

INTENTS = [
    "METRIC_LOOKUP",
    "NARRATIVE_SUMMARY",
    "ENTITY_LOOKUP",
    "COMPARISON",
    "TEMPORAL_TREND",
    "MULTI_HOP",
    "NAVIGATION"
]

class SubQuery(TypedDict):
    """Type definition for a subquery component."""
    intent: str
    text: str
    facets: Dict[str, Any]

class PlanDraft(TypedDict):
    """Type definition for the complete query plan."""
    intent: str
    subqueries: List[SubQuery]
    filters: Dict[str, Any]

class IntentRouter:
    """Intent classification and query decomposition router."""

    # --- FIX: Remove config_path and use central config ---
    def __init__(self, clf_model, llm_client, thresh: float = None):
        """
        Initialize the IntentRouter.

        Args:
            clf_model: SetFit or compatible classifier with predict_proba method
            llm_client: Small LLM tool client with .json_tool() interface
            thresh: Classification confidence threshold (overrides config)
        """
        self.clf_model = clf_model
        self.llm_client = llm_client

        # Get the threshold from the single source of truth: the central config.
        # The `thresh` parameter can still be used for testing overrides.
        self.thresh = thresh if thresh is not None else get_config(
            'orchestration.intent_router', 'threshold', default=0.6
        )

        logger.info(f"IntentRouter initialized with confidence threshold: {self.thresh}")

    # --- FIX: Removed the local _load_config method ---

    def classify(self, q: str) -> Tuple[str, float, Dict[str, float]]:
        """
        Classify query intent using the trained classifier.
        """
        probs = self.clf_model.predict_proba([q])[0]

        assert len(probs) == len(INTENTS), f"Classifier output length mismatch: got {len(probs)}, expected {len(INTENTS)}"

        probs_dict = {intent: float(prob) for intent, prob in zip(INTENTS, probs)}
        best_idx = np.argmax(probs)
        best_intent = INTENTS[best_idx]
        best_prob = float(probs[best_idx])

        logger.info(f"[Router] Query='{q}' -> Intent={best_intent} (p={best_prob:.2f})")
        logger.debug(f"[Router] Full probabilities: {probs_dict}")

        return best_intent, best_prob, probs_dict

    async def decompose_if_needed(self, q: str, intent: str, p: float) -> PlanDraft:
        """
        Decompose query into subqueries if needed based on confidence and intent type.
        """
        complex_intents = {"COMPARISON", "MULTI_HOP", "TEMPORAL_TREND"}

        if p >= self.thresh and intent not in complex_intents:
            logger.info(f"[Router] Using simple plan - high confidence ({p:.2f}) for {intent}")
            return {
                "intent": intent,
                "subqueries": [{"intent": intent, "text": q, "facets": {}}],
                "filters": {}
            }
        else:
            logger.info(f"[Router] Using LLM decomposition - confidence={p:.2f}, intent={intent}")

            llm_spec = {
                "instructions": "Decompose user query into 1-3 subqueries with intents from this list.",
                "labels": INTENTS,
                "query": q
            }

            try:
                result = await self.llm_client.json_tool("classify_and_decompose", llm_spec)

                if not isinstance(result, dict):
                    raise ValueError(f"LLM returned non-dictionary response: {type(result)}")

                result = self._normalize_llm_result(result, q, intent)

                logger.info(f"[Router] LLM decomposition successful: {len(result['subqueries'])} subqueries")
                return result

            except Exception as e:
                logger.error(f"[Router] LLM decomposition failed: {e}")
                return self._create_fallback_plan(q, intent)

    def _normalize_llm_result(self, result: Dict[str, Any], original_query: str, fallback_intent: str) -> PlanDraft:
        """Normalize and validate LLM decomposition result."""
        if "intent" not in result:
            result["intent"] = fallback_intent

        if "subqueries" not in result or not isinstance(result["subqueries"], list) or not result["subqueries"]:
            logger.warning("[Router] LLM returned empty or invalid subqueries, creating fallback")
            result["subqueries"] = [{"intent": result["intent"], "text": original_query, "facets": {}}]

        if "filters" not in result or not isinstance(result["filters"], dict):
            result["filters"] = {}

        for i, subquery in enumerate(result["subqueries"]):
            if not isinstance(subquery, dict):
                result["subqueries"][i] = {"intent": result["intent"], "text": original_query, "facets": {}}
            else:
                subquery.setdefault("facets", {})
                subquery.setdefault("text", original_query)
                subquery.setdefault("intent", result["intent"])

        return result

    def _create_fallback_plan(self, query: str, intent: str) -> PlanDraft:
        """Create a fallback plan when LLM decomposition fails."""
        logger.info(f"[Router] Creating fallback plan for query: '{query}'")
        return {
            "intent": intent,
            "subqueries": [{"intent": intent, "text": query, "facets": {}}],
            "filters": {}
        }

    def get_router_stats(self) -> Dict[str, Any]:
        """Get router configuration and statistics."""
        return {
            "confidence_threshold": self.thresh,
            "supported_intents": INTENTS,
        }
# --- END OF FILE intent_router.py ---