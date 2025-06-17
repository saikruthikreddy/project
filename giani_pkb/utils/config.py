import os
from dotenv import load_dotenv
load_dotenv()
from giani_pkb.utils.exceptions import ConfigurationError


GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not GEMINI_API_KEY:
    raise ConfigurationError("GEMINI_API_KEY environment variable not found or not set. Please ensure it is defined in your .env file or environment.")

GEMINI_PRO_MODEL = "gemini-1.5-pro"
GEMINI_FLASH_MODEL = "gemini-1.5-flash" 
GEMINI_ADVANCED_MODEL = "gemini-2.0-pro" 
GEMINI_FLASH_ALIAS = "gemini-2.0-flash" 


def get_api_key():
    """Returns the configured Gemini API key."""
    return GEMINI_API_KEY

def get_default_model():
    """Returns the default Gemini model name."""
    return GEMINI_FLASH_MODEL

def get_pro_model():
    """Returns the Gemini Pro model name."""
    return GEMINI_PRO_MODEL
