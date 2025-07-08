import google.generativeai as genai
import logging
import google.api_core.exceptions

from giani_pkb.utils.config import GEMINI_API_KEY, GEMINI_FLASH_MODEL
from giani_pkb.utils.exceptions import ConfigurationError

logger = logging.getLogger(__name__)

def initialize_gemini_client(api_key: str = None):
    """
    Initialize and configure the Gemini client.

    This function attempts to configure the Gemini client with the provided API key
    or falls back to the global GEMINI_API_KEY, and validates that the required model is available.

    Args:
        api_key: Optional custom API key to use. If None, uses GEMINI_API_KEY from config.

    Raises:
        ConfigurationError: If no API key is available or configuration fails
    """
    current_api_key = api_key if api_key else GEMINI_API_KEY

    if not current_api_key:
        logger.error("No API key provided and GEMINI_API_KEY is not set. Cannot configure genai.")
        raise ConfigurationError("No API key available. Cannot initialize Gemini client.")

    try:
        # Check if the model is available
        models = [m for m in genai.list_models() if GEMINI_FLASH_MODEL in m.name]
        if not models:
            logger.warning(
                f"Model {GEMINI_FLASH_MODEL} not found in list_models(). Attempting genai.configure()."
            )
            genai.configure(api_key=current_api_key)
    except google.api_core.exceptions.GoogleAPIError as e:
        logger.warning(f"GoogleAPIError during initial genai check: {e}. Attempting genai.configure().")
        genai.configure(api_key=current_api_key)
    except Exception as e:
        logger.error(f"Unexpected error during initial genai check: {type(e).__name__} - {e}. Attempting genai.configure().")
        genai.configure(api_key=current_api_key)

# Initialize the client when this module is imported
initialize_gemini_client()