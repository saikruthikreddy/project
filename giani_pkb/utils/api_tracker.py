"""
Utility for tracking API calls and their metadata.
"""
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

class APICallTracker:
    """
    Tracks API calls and provides summary statistics.
    """
    def __init__(self):
        self.api_calls = []
        self.call_count = 0

    def log_api_call(self, prompt: str, response: str, model: str, timestamp: str):
        """Log an API call with its metadata."""
        self.call_count += 1
        call_info = {
            "call_number": self.call_count,
            "timestamp": timestamp,
            "model": model,
            "prompt_preview": prompt[:200] + "..." if len(prompt) > 200 else prompt,
            "full_prompt": prompt,
            "response_preview": response[:200] + "..." if len(response) > 200 else response,
            "full_response": response,
            "prompt_length": len(prompt),
            "response_length": len(response)
        }
        self.api_calls.append(call_info)

    def get_summary(self) -> Dict[str, Any]:
        """Get summary statistics of all API calls."""
        return {
            "total_api_calls": self.call_count,
            "total_prompt_characters": sum(call["prompt_length"] for call in self.api_calls),
            "total_response_characters": sum(call["response_length"] for call in self.api_calls),
            "individual_api_calls": self.api_calls
        }