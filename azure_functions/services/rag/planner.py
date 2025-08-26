# --- START OF FILE planner.py ---
import logging
import os
from typing import List, Dict, Any

import yaml
from dataclasses import dataclass
from sentence_transformers import SentenceTransformer
import numpy as np

from services.rag.config_loader import load_orchestration_config as get_config

from services.rag.intent_router import IntentRouter, PlanDraft, SubQuery, INTENTS

from services.rag.llm_service import LLMService


logger = logging.getLogger(__name__)

# --- FIX: Implemented a mock classifier for demonstration ---
# In a real application, you would load your actual SetFit model.
# This mock demonstrates the interface IntentRouter expects.
class MockClassifier:
    def __init__(self, model_name_or_path: str):
        # In a real SetFit implementation, you'd use:
        # from setfit import SetFitModel
        # self.model = SetFitModel.from_pretrained(model_name_or_path)
        logger.info(f"Loading mock classifier model: {model_name_or_path}")
        # For demonstration, we'll use a simple sentence transformer and cosine similarity
        self.model = SentenceTransformer(model_name_or_path)
        self.intent_embeddings = self.model.encode([intent.replace("_", " ") for intent in INTENTS])

    def predict_proba(self, texts: List[str]) -> np.ndarray:
        # This is a mock implementation. Your actual model would just be `self.model.predict_proba(texts)`
        text_embedding = self.model.encode(texts[0])
        # Calculate cosine similarity
        sim = np.dot(self.intent_embeddings, text_embedding) / (np.linalg.norm(self.intent_embeddings, axis=1) * np.linalg.norm(text_embedding))
        # Apply softmax to get probabilities
        probs = np.exp(sim) / np.sum(np.exp(sim))
        return np.array([probs])


# Singleton instances for models, loaded once on first use.
_intent_router_instance = None
_llm_service_instance = None

def get_intent_router() -> IntentRouter:
    """
    Gets the singleton IntentRouter instance.
    This function now contains a working implementation of model loading.
    """
    global _intent_router_instance
    if _intent_router_instance is None:
        logger.info("Initializing IntentRouter and its models for the first time...")

        # --- FIX: Use dataclass attribute access ---
        # 1. Load the entire config object
        config = get_config()
        # 2. Access attributes directly with dot notation
        # Note: Your config structure doesn't have 'orchestration.intent_router'
        # based on config_loader.py. We access what is actually there.
        confidence_threshold = config.retriever.reranking.top_k / 20.0 if config.retriever.reranking else 0.6 # Placeholder logic
        classifier_model_path = config.retriever.reranking.model if config.retriever.reranking else 'sentence-transformers/all-MiniLM-L6-v2'
        # --- END OF FIX ---

        # 2. Load the models
        try:
            # Replace MockClassifier with your actual SetFit model loader if you have one
            clf_model = MockClassifier(classifier_model_path)
            llm_client = get_llm_service() # We can reuse the LLM service
        except Exception as e:
            logger.error(f"Fatal error: Could not load models for IntentRouter. Details: {e}", exc_info=True)
            raise e

        # 3. Initialize the IntentRouter with the loaded models
        _intent_router_instance = IntentRouter(clf_model, llm_client, thresh=confidence_threshold)
        logger.info("IntentRouter initialized successfully.")

    return _intent_router_instance

def get_llm_service() -> LLMService:
    """Gets the singleton LLMService instance."""
    global _llm_service_instance
    if _llm_service_instance is None:
        logger.info("Initializing LLMService for the first time...")

        try:
            # Load LLM configuration from environment variables
            # You can also modify this to read from your config file if you prefer
            provider = os.getenv("LLM_PROVIDER", "openai")
            model = os.getenv("LLM_MODEL", "gpt-3.5-turbo")

            # Optional: Set temperature and max_tokens from environment or use defaults
            temperature = float(os.getenv("LLM_TEMPERATURE", "0.2"))
            max_tokens = int(os.getenv("LLM_MAX_TOKENS", "2048"))

            _llm_service_instance = LLMService(
                provider=provider,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens
            )

            logger.info(f"LLMService initialized successfully with provider={provider}, model={model}")

        except Exception as e:
            logger.error(f"Failed to initialize LLMService: {e}", exc_info=True)
            # Re-raise the exception to stop the process if the LLM is critical
            raise

    return _llm_service_instance

@dataclass
class QueryPlan:
    """Query execution plan with intent and decomposition."""
    intent: str
    confidence: float
    subqueries: List[SubQuery]
    filters: Dict[str, Any]
    needs_decomposition: bool = False
    prompt_style: str = "factual"
    original_query: str = ""
    transformed_query: str = ""
    query_id: str = "" # Added to pass query_id downstream

def _apply_query_transformations(query: str) -> str:
    """Apply query rewriting based on configuration."""
    # This function is not used in your current setup, but to prevent crashes,
    # we can make it do nothing for now.
    return query

async def route_and_plan(query: str, user_context: Dict[str, Any], query_id: str) -> QueryPlan:
    """
    Normalize query, classify intent, decompose, and build a full query plan.
    """
    intent_router = get_intent_router()

    normalized_query = query.strip()
    transformed_query = _apply_query_transformations(normalized_query)

    best_intent, confidence, _ = intent_router.classify(transformed_query)

    plan_draft: PlanDraft = await intent_router.decompose_if_needed(
        transformed_query, best_intent, confidence
    )

    filters = plan_draft.get("filters", {})
    if user_context.get("project_id"):
        filters["project_id"] = user_context["project_id"]

    intent_name = plan_draft.get("intent", "UNKNOWN")
    if intent_name == "METRIC_LOOKUP":
        filters["prefer_tables"] = True
    elif intent_name == "COMPARISON":
        filters["expand_context"] = True

    # This part of the config doesn't exist in config_loader.py, so we'll use a safe default.
    prompt_style = "default"

    needs_decomposition = len(plan_draft["subqueries"]) > 1 or \
        plan_draft["subqueries"][0]['text'] != transformed_query

    return QueryPlan(
        intent=intent_name,
        confidence=confidence,
        subqueries=plan_draft["subqueries"],
        filters=filters,
        needs_decomposition=needs_decomposition,
        prompt_style=prompt_style,
        original_query=normalized_query,
        transformed_query=transformed_query,
        query_id=query_id
    )
# --- END OF FILE planner.py ---