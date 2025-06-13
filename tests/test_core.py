import unittest
from unittest.mock import patch, MagicMock
import os

# Ensure GEMINI_API_KEY is set for tests that might initialize services relying on it globally
# For robust CI/CD, this should be handled by the test environment setup
# For now, setting it if not present to allow tests to run locally if needed.
if "GEMINI_API_KEY" not in os.environ:
    os.environ["GEMINI_API_KEY"] = "test_api_key_for_unit_tests_only"

from giani_pkb.core.models import DocumentMetadata
from giani_pkb.core.summarization_service import SummarizationService
from giani_pkb.core.classification_service import ClassificationService
from giani_pkb.utils.constants import DocumentGroup, AI_CLASSIFICATIONS, CATEGORY_TO_GROUP_MAPPING
from giani_pkb.utils.exceptions import APIError

# A category that maps to Group A for testing SummarizationService
TEST_CATEGORY_GROUP_A = ""
for category, group in CATEGORY_TO_GROUP_MAPPING.items():
    if group == DocumentGroup.GROUP_A:
        TEST_CATEGORY_GROUP_A = category
        break
if not TEST_CATEGORY_GROUP_A:
    # Fallback if no Group A category is found (should not happen with current constants)
    TEST_CATEGORY_GROUP_A = AI_CLASSIFICATIONS[0] if AI_CLASSIFICATIONS else "1. Strategy Document/Deck"


class TestSummarizationService(unittest.TestCase):
    def setUp(self):
        # Mock MetadataManagerService to avoid actual file operations
        self.mock_metadata_manager = MagicMock()

        with patch('giani_pkb.core.summarization_service.MetadataManagerService', return_value=self.mock_metadata_manager):
            # It's also good to mock MainProcessing if it makes external calls or heavy local processing
            with patch('giani_pkb.core.summarization_service.MainProcessing'):
                self.summarization_service = SummarizationService(gemini_api_key="test_key")

    def test_get_appropriate_prompt_happy_path(self):
        doc_meta = DocumentMetadata(
            id="test_doc_id",
            originalFilename="Strategy_Doc.pdf",
            finalCategory=TEST_CATEGORY_GROUP_A, # Using a known Group A category
            finalPurpose="To outline company strategy",
            # Fill other mandatory fields with dummy data
            fileSize=1024,
            fileMimeType="application/pdf",
            dateAddedToGiani="2023-01-01T00:00:00Z",
            userID="test_user",
            projectID="test_project",
            textPreview="Strategic content...",
            priority="High",
            finalizedAt="2023-01-01T00:00:00Z",
            storagePath="data/uploaded_documents/Strategy/Strategy_Doc.pdf",
            categoryFolder="Strategy",
            storedFilename="data/uploaded_documents/Strategy/Strategy_Doc_metadata.json",
            savedAt="2023-01-01T00:00:00Z",
            summaryStoragePath=None
        )
        key_document_chunks = "Chunk 1: Strategic direction. Chunk 2: Market analysis."

        prompt = self.summarization_service.get_appropriate_prompt(doc_meta, key_document_chunks)

        self.assertIsInstance(prompt, str)
        self.assertIn(doc_meta.originalFilename, prompt)
        self.assertIn(doc_meta.finalCategory, prompt) # documentSourceType in prompt
        self.assertIn(doc_meta.finalPurpose, prompt) # userNoteOnPurpose in prompt
        self.assertIn(key_document_chunks, prompt)
        # Check for keywords specific to Group A prompt template if possible
        # This depends on the content of "summarization_group_a_prompt.txt"
        # For example, if Group A prompts always ask for "KEY THEMES"
        # self.assertIn("KEY THEMES", prompt)


class TestClassificationService(unittest.TestCase):
    def setUp(self):
        # Mock genai.configure if it's called in __init__ or module level in a problematic way
        # However, ClassificationService __init__ doesn't call genai.configure directly if key is present
        # The module level one might have run. For safety, can patch it.
        with patch('giani_pkb.core.classification_service.genai.configure'):
            self.classification_service = ClassificationService()

    @patch('giani_pkb.core.classification_service.genai.GenerativeModel.generate_content')
    def test_classify_document_happy_path_llm(self, mock_generate_content):
        mock_response = MagicMock()
        # Ensure AI_CLASSIFICATIONS has items before trying to access AI_CLASSIFICATIONS[0]
        expected_classification = AI_CLASSIFICATIONS[0] if AI_CLASSIFICATIONS else "1. Strategy Document/Deck"
        expected_purpose = "This is the AI generated purpose."
        mock_response.text = f"CLASSIFICATION: {expected_classification}\nPURPOSE: {expected_purpose}"
        mock_generate_content.return_value = mock_response

        filename = "test_document.pdf"
        text_preview = "This is a test document preview."

        classification, purpose, _ = self.classification_service.classify_document(filename, text_preview)

        self.assertEqual(classification, expected_classification)
        self.assertEqual(purpose, expected_purpose)
        mock_generate_content.assert_called_once()

    @patch('giani_pkb.core.classification_service.genai.GenerativeModel.generate_content')
    def test_classify_document_happy_path_fallback(self, mock_generate_content):
        # Configure the mock to raise an APIError to trigger fallback
        mock_generate_content.side_effect = APIError("LLM API is down")

        # Use a filename that matches a fallback rule
        filename = "financial_report_final.docx"
        text_preview = "This document contains financial data."

        # Expected fallback for "financial" in filename
        expected_classification = "3. Financial Report/Analysis Deck"
        expected_purpose = "This document contains financial analysis and data relevant to the consulting engagement. It provides quantitative insights to support business recommendations and decision-making processes."

        classification, purpose, _ = self.classification_service.classify_document(filename, text_preview)

        self.assertEqual(classification, expected_classification)
        self.assertEqual(purpose, expected_purpose)
        mock_generate_content.assert_called_once()

if __name__ == '__main__':
    unittest.main()
