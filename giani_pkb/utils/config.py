import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()
from giani_pkb.utils.exceptions import ConfigurationError

# Centralized GEMINI_API_KEY loading
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    # In a real application, you might raise an error or log a warning.
    # For now, we'll print a message. If running in an environment where
    # .env is not used, this key might need to be set directly or via other means.
    # print("WARNING: GEMINI_API_KEY environment variable not found or not set.") # Old warning
    raise ConfigurationError("GEMINI_API_KEY environment variable not found or not set. Please ensure it is defined in your .env file or environment.")

# Standard Gemini Model Names
GEMINI_PRO_MODEL = "gemini-1.5-pro"
GEMINI_FLASH_MODEL = "gemini-1.5-flash" # Default model for many operations
GEMINI_ADVANCED_MODEL = "gemini-2.0-pro" # Example for a more advanced model
GEMINI_FLASH_ALIAS = "gemini-2.0-flash" # Alias used in CSVProcessor

# You can add other configuration variables here as needed
# For example, base directories, default parameters, etc.

# Example of another config variable
# MAX_UPLOAD_SIZE_MB = 100

def get_api_key():
    """Returns the configured Gemini API key."""
    return GEMINI_API_KEY

def get_default_model():
    """Returns the default Gemini model name."""
    return GEMINI_FLASH_MODEL

def get_pro_model():
    """Returns the Gemini Pro model name."""
    return GEMINI_PRO_MODEL
