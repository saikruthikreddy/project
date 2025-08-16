"""
NLP processing utilities for document chunking.
"""
import re
import spacy
from typing import List, Dict, Any, Tuple
import logging

logger = logging.getLogger(__name__)

class NLPProcessor:
    """Advanced NLP processing using spaCy"""

    def __init__(self):
        try:
            self.nlp = spacy.load("en_core_web_sm")
        except OSError:
            logger.warning("spaCy model 'en_core_web_sm' not found. Install with: python -m spacy download en_core_web_sm. NLP heading detection will be basic.")
            self.nlp = None

    def detect_headings_in_block(self, block_text: str, block_metadata: Dict[str, Any]) -> List[Tuple[str, int, int, Dict[str, Any]]]:
        """
        Detects headings within a single text block.
        Returns list of (heading_text, start_char, end_char, heading_metadata).
        Leverages block_type from parser if available.
        """
        headings = []
        # Priority to parser's structural metadata
        if "heading" in block_metadata.get("block_type", ""):
            level = int(block_metadata["block_type"].split("_")[-1]) if "_" in block_metadata["block_type"] else 0
            headings.append(
                (block_text, 0, len(block_text), {"level": level, "source": "parser"})
            )
            return headings

        if not self.nlp: # Fallback if spaCy is not available
            # Simple regex for lines that might be headings (e.g., all caps, short, ends with no punctuation)
            # This is very basic and should be improved if spaCy cannot be used.
            if len(block_text.split()) < 10 and block_text.isupper() and not block_text.endswith(('.', '!', '?')):
                 headings.append((block_text, 0, len(block_text), {"level": 0, "source": "regex_fallback"}))
            return headings

        doc = self.nlp(block_text)
        for sent in doc.sents:
            sent_text = sent.text.strip()
            if self._is_heading_like(sent_text, sent): # spaCy based check
                start_char = sent.start_char
                end_char = sent.end_char
                # Basic level detection, can be improved
                level = 1 if sent_text.isupper() else 2
                headings.append((sent_text, start_char, end_char, {"level": level, "source": "spacy"}))
        return headings

    def _is_heading_like(self, text: str, sent) -> bool:
        """
        Advanced heading detection using linguistic features (from original code).
        # Tuning: Thresholds here (e.g., title_case_ratio > 0.6, proper_noun_ratio > 0.2)
        # might need adjustment based on the corpus.
        """
        if len(text.split()) > 15 or len(text) < 3: return False
        words = text.split()
        title_case_ratio = sum(1 for word in words if word[0].isupper()) / len(words)
        ends_with_period = text.endswith(('.', '!', '?'))
        has_colon = text.endswith(':')
        all_caps = text.isupper()

        if self.nlp and sent: # Ensure sent is available for NLP checks
            proper_noun_ratio = sum(1 for token in sent if token.pos_ == 'PROPN') / (len(sent) + 1e-6)
            return (
                (title_case_ratio > 0.6 or all_caps or has_colon) and
                not ends_with_period and
                proper_noun_ratio > 0.2 # Lowered threshold slightly
            )
        return (title_case_ratio > 0.6 or all_caps or has_colon) and not ends_with_period

    def extract_sentences(self, text: str) -> List[str]:
        """Extract sentences using spaCy for better accuracy"""
        if not self.nlp:
            return re.split(r'(?<=[.!?])\s+', text.strip()) # Basic regex split
        doc = self.nlp(text)
        return [sent.text.strip() for sent in doc.sents if sent.text.strip()]

    def detect_speakers(self, text: str) -> List[Tuple[str, str, int, int]]:
        """Enhanced speaker detection with NLP (from original code)."""
        speaker_pattern = re.compile(r'^\s*([A-Za-z0-9_\s]+):\s*(.*)', re.MULTILINE)
        speakers = []
        for match in speaker_pattern.finditer(text):
            speakers.append((match.group(1).strip(), match.group(2).strip(), match.start(), match.end()))
        return speakers