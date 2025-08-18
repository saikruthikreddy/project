"""
Token counting utilities for document chunking.
"""
import tiktoken
import logging

logger = logging.getLogger(__name__)

class TokenCounter:
    """Enhanced token counting using tiktoken"""

    def __init__(self, model_name: str = "gpt-3.5-turbo"):
        try:
            self.encoder = tiktoken.encoding_for_model(model_name)
        except KeyError:
            logger.warning(f"Tiktoken model {model_name} not found, using cl100k_base.")
            self.encoder = tiktoken.get_encoding("cl100k_base")

    def count_tokens(self, text: str) -> int:
        """Count tokens in text using tiktoken"""
        return len(self.encoder.encode(text))

    def estimate_tokens(self, text: str) -> int:
        """Fast token estimation (characters / 4)"""
        return len(text) // 4