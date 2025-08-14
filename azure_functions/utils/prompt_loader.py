import os
from utils.exceptions import FileProcessingError

PROMPTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "prompts"))

def load_prompt_template(template_filename: str) -> str:
    """
    Loads a prompt template from the /prompts directory.

    Args:
        template_filename: The name of the prompt template file (e.g., "file_classification_prompt.txt").

    Returns:
        The content of the prompt template file as a string.

    Raises:
        FileProcessingError: If the prompt template file cannot be found or read.
    """
    filepath = os.path.join(PROMPTS_DIR, template_filename)
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        if not os.path.isdir(PROMPTS_DIR):
            raise FileProcessingError(f"Prompts directory not found at {PROMPTS_DIR}. Cannot load template {template_filename}.", filepath=PROMPTS_DIR)
        raise FileProcessingError(f"Prompt template file not found: {filepath}", filepath=filepath)
    except IOError as e:
        raise FileProcessingError(f"Error reading prompt template file {filepath}: {e}", filepath=filepath)
