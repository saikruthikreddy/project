import unittest
from giani_pkb.preprocessing.chunking import (
    chunk_formal_document,
    chunk_conversational_record,
    chunk_data_heavy_document,
)

class TestChunkingStrategies(unittest.TestCase):
    def test_chunk_formal_document_simple(self):
        text = "This is the first paragraph.\n\nThis is the second paragraph, which is a bit longer."
        chunks = chunk_formal_document(text)
        self.assertEqual(len(chunks), 1) # Expecting 1 chunk as total length is small
        self.assertTrue("first paragraph" in chunks[0])
        self.assertTrue("second paragraph" in chunks[0])

    def test_chunk_formal_document_multiple_chunks(self):
        paragraph = "This is a single paragraph that will be repeated to create a long text. " * 50 # Approx 3500 chars
        text = paragraph.strip() + "\n\n" + paragraph.strip() # Two such paragraphs
        chunks = chunk_formal_document(text)
        # Each very long paragraph should ideally be its own chunk.
        # The merging logic might combine them if the first one is considered "small" before adding the second.
        # Let's test that it produces chunks and they are substantial.
        self.assertTrue(len(chunks) >= 1, f"Chunks found: {len(chunks)}, content: {chunks}")
        for chunk in chunks:
            self.assertTrue(len(chunk) > 100) # Ensure chunks are not trivially small
        self.assertTrue(chunks[0].startswith("This is a single paragraph"))

    def test_chunk_formal_document_with_headings(self):
        text = (
            "Main Title\n"
            "Some introductory text under the main title.\n\n"
            "First Section Heading\n"
            "Content for the first section. It's quite detailed.\n"
            "More content for the first section, spanning multiple lines.\n\n"
            "Second Section Heading\n"
            "Content for the second section. This section is shorter.\n\n"
            "Another Paragraph without heading\n"
            "This is just some more text."
        )
        chunks = chunk_formal_document(text)
        self.assertGreaterEqual(len(chunks), 2) # Expect at least two chunks due to headings/content size
        self.assertTrue("Main Title" in chunks[0])
        self.assertTrue("First Section Heading" in chunks[0] or "First Section Heading" in chunks[1])
        self.assertTrue("Second Section Heading" in chunks[1] or "Second Section Heading" in chunks[2] if len(chunks)>2 else "Second Section Heading" in chunks[-1])


    def test_chunk_conversational_record_simple_no_attribution(self):
        text = "Hello there. How are you doing today? I hope you are well."
        chunks = chunk_conversational_record(text)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0], text) # No speaker tags, should return as is if short enough

    def test_chunk_conversational_record_with_attribution(self):
        text = (
            "Alice: Hi Bob!\n"
            "Bob: Hello Alice. How are you?\n"
            "Alice: I'm good, thanks! And you?\n"
            "Bob: Doing well. Did you see the new memo?\n"
            "Alice: No, what did it say? It must have been very important for you to ask about it so directly."
        )
        chunks = chunk_conversational_record(text, max_tokens=100, overlap=20) # Smaller tokens for testing overlap
        self.assertGreater(len(chunks), 1)
        self.assertTrue("[Alice]" in chunks[0])
        self.assertTrue("[Bob]" in chunks[0] or "[Bob]" in chunks[1]) # Bob might be in first or second chunk
        if len(chunks) > 1:
            # Check for overlap: end of first chunk should have some commonality with start of second
            # This is a heuristic check.
            first_chunk_words = chunks[0].split()
            second_chunk_words = chunks[1].split()
            # Check if some words from end of first appear at start of second
            overlap_found = any(word in second_chunk_words[:5] for word in first_chunk_words[-5:])
            self.assertTrue(overlap_found, "Overlap not clearly detected between conversational chunks.")
        for chunk in chunks:
            self.assertTrue(len(chunk) > 0)


    def test_chunk_conversational_record_multiple_chunks_no_attribution(self):
        sentence_text = "This is a test sentence for conversational records without any speaker tags. " # len=70
        full_sentence_block = sentence_text * 2 # len=140. Two of these make a chunk for max_tokens=200.
        text = full_sentence_block + "Another sentence follows. " + full_sentence_block
        # max_tokens=200, overlap should be larger than one sentence_text to see sentence-level overlap
        chunks = chunk_conversational_record(text, max_tokens=200, overlap=80)
        self.assertGreater(len(chunks), 1, f"Expected multiple chunks, got {len(chunks)}. Chunks: {chunks}")
        self.assertTrue(chunks[0].startswith("This is a test sentence"))
        if len(chunks) > 1:
            # A more direct way to check for overlap:
            # The start of the second chunk should contain some text that was also at the end of the first chunk.
            # Let's take last `overlap` characters (or a bit less to be safe) from first chunk
            # and see if a significant part of it is at the start of the second chunk.
            end_of_first = chunks[0][-40:] # Look at last 40 chars of first chunk
            start_of_second = chunks[1][:40] # Look at first 40 chars of second chunk

            common_substring_found = False
            # Check for common substring of reasonable length (e.g. 10 chars)
            for i in range(len(end_of_first) - 10):
                substring = end_of_first[i:i+10]
                if substring in start_of_second:
                    common_substring_found = True
                    break
            self.assertTrue(common_substring_found, f"Overlap not detected. End of C1: '...{end_of_first[-20:]}', Start of C2: '{start_of_second[:20]}...' Chunks: {chunks}")


    def test_chunk_data_heavy_document_simple_prose(self):
        text = "This is some introductory text.\n\nThis is a second paragraph of analysis."
        chunks = chunk_data_heavy_document(text)
        # Should behave like formal document chunking
        self.assertEqual(len(chunks), 1)
        self.assertTrue("introductory text" in chunks[0])
        self.assertTrue("second paragraph" in chunks[0])

    def test_chunk_data_heavy_document_with_simple_table(self):
        text = (
            "Here is some analysis leading to the table.\n\n"
            "ColA,ColB,ColC\n"
            "1,2,3\n"
            "4,5,6\n"
            "7,8,9\n\n"
            "And here is some text after the table."
        )
        chunks = chunk_data_heavy_document(text)
        self.assertEqual(len(chunks), 3) # Prose before, table, prose after
        self.assertTrue(chunks[0].startswith("Here is some analysis"))
        self.assertTrue(chunks[1].startswith("[TABLE_DATA_START]"))
        self.assertTrue("ColA,ColB,ColC" in chunks[1])
        self.assertTrue(chunks[1].endswith("[TABLE_DATA_END]"))
        self.assertTrue(chunks[2].startswith("And here is some text"))

    def test_chunk_data_heavy_document_table_only(self):
        text = ("ColA,ColB\nVal1,Val2\nVal3,Val4\nVal5,Val6")
        chunks = chunk_data_heavy_document(text)
        self.assertEqual(len(chunks), 1)
        self.assertTrue(chunks[0].startswith("[TABLE_DATA_START]"))
        self.assertTrue(chunks[0].endswith("[TABLE_DATA_END]"))

    def test_chunk_data_heavy_document_no_real_table(self):
        text = "Line with one, comma.\nAnother line but, not really a table.\nThis line, has, several, commas but only one line."
        chunks = chunk_data_heavy_document(text)
        # Expect formal chunking behavior, no table tags
        self.assertFalse(any("[TABLE_DATA_START]" in chunk for chunk in chunks))
        self.assertGreaterEqual(len(chunks), 1)


    def test_empty_text_formal(self):
        text = ""
        chunks = chunk_formal_document(text)
        self.assertEqual(chunks, [])

    def test_empty_text_conversational(self):
        text = ""
        chunks = chunk_conversational_record(text)
        self.assertEqual(chunks, [])

    def test_empty_text_data_heavy(self):
        text = ""
        chunks = chunk_data_heavy_document(text)
        self.assertEqual(chunks, [])

if __name__ == '__main__':
    unittest.main()
