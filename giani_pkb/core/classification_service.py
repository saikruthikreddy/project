import google.generativeai as genai
import logging

from giani_pkb.utils.config import GEMINI_API_KEY, GEMINI_FLASH_MODEL
from giani_pkb.utils.prompt_loader import load_prompt_template
from giani_pkb.utils.constants import AI_CLASSIFICATIONS
from giani_pkb.utils.exceptions import APIError

# Configure genai if not already configured (though it's often done at application entry point)
try:
    # Attempt to get a model to see if it's configured. This is a bit of a workaround.
    # A more direct genai.is_configured() or similar would be better if available.
    genai.get_model(GEMINI_FLASH_MODEL)
except Exception: # Broad exception because specific configuration error isn't clearly documented
    genai.configure(api_key=GEMINI_API_KEY)


class ClassificationService:
    def __init__(self):
        self.model = genai.GenerativeModel(GEMINI_FLASH_MODEL)
        self.logger = logging.getLogger(__name__)
        # Ensure API key is available for the service, though genai.configure is global
        if not GEMINI_API_KEY:
            self.logger.error("GEMINI_API_KEY not found. ClassificationService may not function.")
            # Depending on strictness, could raise ConfigurationError here

    def _get_classification_prompt(self, filename: str, text_preview: str) -> str:
        """Generates the prompt for document classification."""
        # Ensure text_preview is not excessively long for the prompt
        max_preview_length = 5000 # As used in original FileUpload.py
        safe_text_preview = text_preview[:max_preview_length]

        classification_list = "\n".join(
            [f"{i+1}. {cat.split('. ', 1)[1] if '. ' in cat else cat}" for i, cat in enumerate(AI_CLASSIFICATIONS)]
        )
        prompt_template = load_prompt_template("file_classification_prompt.txt")
        return prompt_template.format(
            filename=filename,
            text_preview=safe_text_preview,
            classification_list=classification_list
        )

    def _parse_llm_response(self, ai_response: str) -> tuple[str, str]:
        """Parses the raw LLM response to extract classification and purpose."""
        lines = ai_response.split('\n')
        classification = "39. Generic Text Document"  # Default
        purpose = "Document classification pending - unable to determine specific purpose from available content."  # Default

        for line in lines:
            line = line.strip()
            if line.startswith('CLASSIFICATION:'):
                classification_text = line.replace('CLASSIFICATION:', '').strip()
                for cat in AI_CLASSIFICATIONS:
                    # Ensure robust matching, e.g. "1. Strategy Document/Deck" should match "Strategy Document/Deck"
                    if classification_text == cat or \
                       (isinstance(cat, str) and '. ' in cat and classification_text == cat.split('. ', 1)[1]):
                        classification = cat
                        break
            elif line.startswith('PURPOSE:'):
                purpose = line.replace('PURPOSE:', '').strip()
        return classification, purpose

    def _fallback_classification(self, filename: str) -> tuple[str, str]:
        """Provides a fallback classification based on filename patterns."""
        self.logger.info(f"Executing fallback classification for filename: {filename}")
        filename_lower = filename.lower()

        # Default values
        classification = "39. Generic Text Document"
        purpose = "This document contains information relevant to the consulting project that requires further analysis to determine its specific role and contribution to the engagement."

        if any(word in filename_lower for word in ['strategy', 'strategic']):
            classification = "1. Strategy Document/Deck"
            purpose = "This document appears to contain strategic analysis and recommendations for business decision-making. It likely includes market insights, competitive positioning, and strategic options for the client's consideration."
        elif any(word in filename_lower for word in ['financial', 'finance', 'budget', 'cost', 'revenue', 'expenses', 'p&l', 'balance sheet']):
            classification = "3. Financial Report/Analysis Deck"
            purpose = "This document contains financial analysis and data relevant to the consulting engagement. It provides quantitative insights to support business recommendations and decision-making processes."
        elif any(word in filename_lower for word in ['meeting minutes', 'minutes of meeting', 'meeting notes', 'action items']):
            classification = "30. Meeting Minutes (Formal)"
            purpose = "This document captures key discussions, decisions, and action items from project meetings. It serves as a record of stakeholder alignment and project progress."
        elif any(word in filename_lower for word in ['market research', 'market analysis', 'industry report']):
            classification = "9. Market Research Report (Internal/External)"
            purpose = "This document provides market intelligence and research findings to inform strategic recommendations. It contains data and analysis about market conditions, trends, and opportunities."
        elif any(word in filename_lower for word in ['proposal', 'sow', 'statement of work', 'engagement letter']):
            classification = "4. Statement of Work (SoW)"
            purpose = "This document outlines the scope, deliverables, and terms of the consulting engagement. It serves as a foundational agreement between the consulting team and client."
        elif any(word in filename_lower for word in ['presentation', 'deck', 'slides', 'workshop materials']):
            classification = "20. Working Draft - Presentation Section" # Default for presentations
            if "final" in filename_lower or "client version" in filename_lower:
                 classification = "2. Client-Facing Presentation/Deck"
            purpose = "This document contains presentation materials or slides being developed for client communication. It represents work-in-progress content for stakeholder engagement."
        elif any(word in filename_lower for word in ['project plan', 'timeline', 'schedule', 'gantt chart', 'work plan']):
            classification = "24. Project Plan Document"
            purpose = "This document outlines project timelines, milestones, and deliverables. It serves as a roadmap for project execution and stakeholder alignment."
        elif any(word in filename_lower for word in ['data', 'dataset', 'raw data', '.csv', '.xlsx', '.xls', 'spreadsheet']): # Added common data extensions
            classification = "10. Market Data Dump/Raw Data File"
            purpose = "This document contains raw data or datasets that will be analyzed to support consulting recommendations. It provides the foundational information for quantitative analysis."
        elif any(word in filename_lower for word in ['interview notes', 'expert interview', 'stakeholder interview']):
            classification = "31. Interview Notes/Transcript"
            purpose = "This document contains notes or transcripts from interviews conducted for the project. It provides qualitative insights and stakeholder perspectives."
        elif any(word in filename_lower for word in ['survey results', 'questionnaire data']):
            classification = "11. Survey Data/Results"
            purpose = "This document contains data or results from surveys conducted as part of the project. It provides quantitative or qualitative feedback from a wider audience."

        self.logger.info(f"Fallback classification for {filename}: {classification}")
        return classification, purpose

    def classify_document(self, filename: str, text_preview: str) -> tuple[str, str, str]:
        """
        Classifies the document using LLM and falls back to filename-based patterns if needed.
        Returns:
            tuple[str, str, str]: (classification, purpose, prompt_text)
        """
        prompt_text = self._get_classification_prompt(filename, text_preview)

        try:
            self.logger.info(f"Attempting LLM classification for: {filename}")
            response = self.model.generate_content(prompt_text)

            if not response.text:
                self.logger.error(f"LLM returned empty response for {filename}. Proceeding to fallback.")
                raise APIError(f"LLM returned empty response for {filename}")

            self.logger.info(f"LLM response received for {filename}. Raw: {response.text[:100]}...") # Log snippet
            classification, purpose = self._parse_llm_response(response.text.strip())
            self.logger.info(f"LLM classification for {filename}: {classification}, Purpose: {purpose}")
            return classification, purpose, prompt_text

        except Exception as e: # Catch broader exceptions during API call or parsing
            self.logger.error(f"Error during LLM classification for {filename}: {e}. Attempting fallback.")
            # If the error is not already an APIError, wrap it or log appropriately.
            # For now, any exception here triggers fallback.
            classification, purpose = self._fallback_classification(filename)
            return classification, purpose, prompt_text # Still return the prompt used for the attempt

