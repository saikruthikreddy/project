"""
Classification service for document classification using Gemini LLM and fallback logic.
"""
import logging
import google.generativeai as genai
from giani_pkb.utils.config import GEMINI_API_KEY, GEMINI_FLASH_MODEL
from giani_pkb.utils.prompt_loader import load_prompt_template
from giani_pkb.utils.constants import AI_CLASSIFICATIONS
from giani_pkb.utils.exceptions import APIError, ConfigurationError
from giani_pkb.utils.gemini_client import initialize_gemini_client
from giani_pkb.utils.classification_utils import fallback_classification

# Initialize Gemini client
initialize_gemini_client()

class ClassificationService:
    """
    Service for classifying documents using Gemini LLM, with fallback to filename-based heuristics.
    """
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        if not GEMINI_API_KEY:
            self.logger.error("GEMINI_API_KEY not found in environment/config. ClassificationService requires it.")
            raise ConfigurationError("GEMINI_API_KEY not found. ClassificationService cannot be initialized.")

        try:
            self.model = genai.GenerativeModel(GEMINI_FLASH_MODEL)
        except Exception as e:
            self.logger.error(f"Failed to initialize GenerativeModel ({GEMINI_FLASH_MODEL}) for ClassificationService: {type(e).__name__} - {e}")
            raise ConfigurationError(f"Failed to initialize GenerativeModel for ClassificationService. Check API key and model name ('{GEMINI_FLASH_MODEL}'). Original error: {e}")

    def _get_classification_prompt(self, filename: str, text_preview: str, source: str) -> str:
        """Generates the prompt for document classification."""
        max_preview_length = 5000
        safe_text_preview = text_preview[:max_preview_length]

        classification_list = "\n".join(
            [f"{i+1}. {cat.split('. ', 1)[1] if '. ' in cat else cat}" for i, cat in enumerate(AI_CLASSIFICATIONS)]
        )
        prompt_template = load_prompt_template("file_classification_prompt.txt")
        return prompt_template.format(
            filename=filename,
            text_preview=safe_text_preview,
            source=source,
            classification_list=classification_list
        )

    def _parse_llm_response(self, ai_response: str) -> tuple[str, str]:
        """Parses the raw LLM response to extract classification and purpose."""
        lines = ai_response.split('\n')
        classification = "39. Generic Text Document"
        purpose = "Document classification pending - unable to determine specific purpose from available content."

        for line in lines:
            line = line.strip()
            if line.startswith('CLASSIFICATION:'):
                classification_text = line.replace('CLASSIFICATION:', '').strip()
                for cat in AI_CLASSIFICATIONS:
                    if classification_text == cat or \
                       (isinstance(cat, str) and '. ' in cat and classification_text == cat.split('. ', 1)[1]):
                        classification = cat
                        break
            elif line.startswith('PURPOSE:'):
                purpose = line.replace('PURPOSE:', '').strip()
        return classification, purpose

    def classify_document(self, filename: str, text_preview: str, source:str) -> tuple[str, str, str]:
        """
        Classifies the document using LLM and falls back to filename-based patterns if needed.
        Returns:
            tuple[str, str, str]: (classification, purpose, prompt_text)
        """
        print(text_preview)
        prompt_text = self._get_classification_prompt(filename, text_preview, source)

        try:
            self.logger.info(f"Attempting LLM classification for: {filename}")
            response = self.model.generate_content(prompt_text)

            if not response.text:
                self.logger.error(f"LLM returned empty response for {filename}. Proceeding to fallback.")
                raise APIError(f"LLM returned empty response for {filename}")

            self.logger.info(f"LLM response received for {filename}. Raw: {response.text[:100]}...")
            try:
                classification, purpose = self._parse_llm_response(response.text.strip())
                self.logger.info(f"LLM classification for {filename}: {classification}, Purpose: {purpose}")
                return classification, purpose, prompt_text
            except Exception as parse_ex:
                self.logger.error(f"Error parsing LLM response for {filename}: {type(parse_ex).__name__} - {parse_ex}. Attempting fallback.")

        except APIError as ae:
            self.logger.error(f"APIError during LLM classification for {filename}: {ae}. Attempting fallback.")
        except Exception as e:
            self.logger.error(f"Unexpected error during LLM classification for {filename}: {type(e).__name__} - {e}. Attempting fallback.")

        classification, purpose = fallback_classification(filename, self.logger)
        return classification, purpose, prompt_text