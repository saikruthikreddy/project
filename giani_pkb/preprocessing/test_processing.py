"""
Test script for document processing functionality.
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
import tempfile
from giani_pkb.models.document import DocumentMetadata # Ensure this can be imported or mock it
from giani_pkb.preprocessing.document_processor import DocumentProcessor

# Mock DocumentMetadata if it's complex or has external dependencies not needed for this test
class MockDocumentMetadata:
    def __init__(self, id="test_doc", finalCategory="1. Strategy Document/Deck", **kwargs):
        self.id = id
        self.finalCategory = finalCategory
        # Add other fields if MainProcessing directly uses them
        # For now, finalCategory is the key for routing to chunking strategy

class TestMainProcessingIntegration(unittest.TestCase):
    def setUp(self):
        self.processor = MainProcessing()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_files_paths = []

        # Create dummy files for testing
        # 1. Formal Document (e.g., .txt treated as formal based on mock metadata)
        self.formal_text_content = "This is paragraph one.\n\nThis is paragraph two, which is quite a bit longer to see how it chunks."
        formal_file_path = os.path.join(self.temp_dir.name, "formal_doc.txt")
        with open(formal_file_path, "w") as f:
            f.write(self.formal_text_content)
        self.test_files_paths.append(formal_file_path)

        # 2. Conversational Record (e.g., .txt treated as conversational)
        self.convo_text_content = "Hi there. How's it going? Just checking in. Let me know if you need anything."
        convo_file_path = os.path.join(self.temp_dir.name, "convo_doc.txt")
        with open(convo_file_path, "w") as f:
            f.write(self.convo_text_content)
        self.test_files_paths.append(convo_file_path)

        # 3. Data-Heavy (e.g., .txt treated as data-heavy)
        self.data_text_content = "Column A, Column B, Column C\n1,2,3\n4,5,6\n\nAnother table perhaps or more data points."
        data_file_path = os.path.join(self.temp_dir.name, "data_doc.txt")
        with open(data_file_path, "w") as f:
            f.write(self.data_text_content)
        self.test_files_paths.append(data_file_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_process_files_integration_formal(self):
        # In the current MainProcessing.process_files, classification is hardcoded.
        # We'll test assuming the first file is processed with "1. Strategy Document/Deck"
        # which maps to GROUP_A -> chunk_formal_document

        # To properly test, we might need to:
        # A) Modify MainProcessing to accept DocumentMetadata or category for routing
        # B) Mock the CATEGORY_TO_GROUP_MAPPING or the classification part within process_files
        # For now, we rely on the hardcoded "1. Strategy Document/Deck" for the first call.

        # Let's simulate processing the formal_doc.txt
        # We need to adjust how process_files gets its category or mock it.
        # The current `process_files` in `Processing.py` hardcodes:
        # `document_category = "1. Strategy Document/Deck"`
        # This means all files will currently be processed as formal documents.

        text, chunks = self.processor.process_files(self.test_files_paths[0])
        self.assertEqual(text, self.formal_text_content)
        self.assertTrue(len(chunks) > 0, "Should produce at least one chunk for formal text.")
        # Add more specific assertions based on expected chunking of formal_text_content
        self.assertTrue("paragraph one" in chunks[0])

    def test_process_files_integration_conversational_and_data_heavy_requires_modification(self):
        # As noted, current `process_files` hardcodes one category.
        # To test other categories, `Processing.py` needs to be refactored
        # to allow dynamic category determination for chunking.
        # This test serves as a placeholder to highlight that.

        # If we could set the category for the second file (convo_doc.txt) to something in GROUP_D:
        # e.g., by modifying `process_files` to take `document_category` as an argument
        # or by having a more sophisticated (mockable) classification step.

        # For instance, if we could tell it this is "30. Meeting Minutes (Formal)" (Group D)
        # _, chunks_convo = self.processor.process_files(self.test_files_paths[1], document_category="30. Meeting Minutes (Formal)")
        # self.assertTrue(len(chunks_convo) > 0)
        # self.assertTrue("Hi there" in chunks_convo[0])

        # And for data-heavy (e.g. "10. Market Data Dump/Raw Data File" - Group B)
        # _, chunks_data = self.processor.process_files(self.test_files_paths[2], document_category="10. Market Data Dump/Raw Data File")
        # self.assertTrue(len(chunks_data) > 0)
        # self.assertTrue("Column A" in chunks_data[0])
        pass # Passing this test as it's more of a design note for future refactoring

    def test_main_processing_with_various_files(self):
        # main_processing iterates through files found by read_files.
        # Currently, each file processed by process_files will use the hardcoded category.
        results = self.processor.main_processing(self.temp_dir.name)

        self.assertEqual(len(results), 3) # Expect results for all 3 files

        for result in results:
            self.assertIn("path", result)
            if "status" not in result : # successfully processed files
                self.assertIn("processed_text_preview", result)
                self.assertIn("chunk_count", result)
                self.assertIn("chunks_preview", result)
                self.assertGreater(result["chunk_count"], 0)

        # Example: Check details for the first file (formal_doc.txt)
        # Note: The order from os.walk isn't guaranteed, so find it by path if needed.
        # For simplicity, assuming order is maintained for this test.
        formal_result = None
        for r in results:
            if "formal_doc.txt" in r["path"]:
                formal_result = r
                break
        self.assertIsNotNone(formal_result)
        self.assertTrue(self.formal_text_content.startswith(formal_result["processed_text_preview"].strip()))


if __name__ == '__main__':
    unittest.main()
