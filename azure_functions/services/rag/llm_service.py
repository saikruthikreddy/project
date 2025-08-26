"""
LLM Service module for Retrieval-Augmented Generation (RAG) pipeline.

This module provides a unified interface for interacting with multiple LLM providers
including OpenAI and Anthropic Claude.
"""

import os
import json
import logging
from typing import Optional, Union, Dict, Any, List
from dataclasses import dataclass
import asyncio

try:
    import openai
    from openai import OpenAI, AsyncOpenAI
except ImportError:
    openai = None
    OpenAI = None
    AsyncOpenAI = None

try:
    import anthropic
    from anthropic import Anthropic, AsyncAnthropic
except ImportError:
    anthropic = None
    Anthropic = None
    AsyncAnthropic = None

try:
    from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
except ImportError:
    raise ImportError("tenacity is required for retry logic. Install with: pip install tenacity")


# Configure logging
logger = logging.getLogger(__name__)


@dataclass
class LLMConfig:
    """Configuration class for LLM settings."""
    provider: str
    model: str
    temperature: float = 0.2
    max_tokens: int = 2048  # Increased default for potentially more detailed answers


class LLMServiceError(Exception):
    """Base exception for LLM service errors."""
    pass


class ProviderNotSupportedError(LLMServiceError):
    """Raised when an unsupported provider is specified."""
    pass


class APIKeyMissingError(LLMServiceError):
    """Raised when required API keys are missing."""
    pass


class LLMService:
    """
    Unified LLM service for RAG pipeline supporting multiple providers.
    
    Supports OpenAI and Anthropic Claude with retry logic
    and both synchronous and asynchronous operations.
    """
    
    SUPPORTED_PROVIDERS = {"openai", "anthropic"}
    
    def __init__(
        self,
        provider: str,
        model: str,
        temperature: float = 0.2,
        max_tokens: int = 2048
    ):
        """
        Initialize the LLM service.
        
        Args:
            provider: LLM provider ("openai", "anthropic")
            model: Model name
            temperature: Sampling temperature (0.0-1.0)
            max_tokens: Maximum tokens to generate
            
        Raises:
            ProviderNotSupportedError: If provider is not supported
            APIKeyMissingError: If required API keys are missing
        """
        if provider not in self.SUPPORTED_PROVIDERS:
            raise ProviderNotSupportedError(
                f"Provider '{provider}' not supported. "
                f"Supported providers: {', '.join(self.SUPPORTED_PROVIDERS)}"
            )
        
        self.config = LLMConfig(
            provider=provider,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens
        )
        
        # Initialize clients
        self._sync_client = None
        self._async_client = None
        
        self._validate_and_setup_clients()
    
    def _validate_and_setup_clients(self) -> None:
        """Validate environment variables and setup API clients."""
        if self.config.provider == "openai":
            self._setup_openai_clients()
        elif self.config.provider == "anthropic":
            self._setup_anthropic_clients()
    
    def _setup_openai_clients(self) -> None:
        """Setup OpenAI clients."""
        if not OpenAI:
            raise ImportError("openai library is required for OpenAI provider. Install with: pip install openai")
        
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise APIKeyMissingError("OPENAI_API_KEY environment variable is required")
        
        self._sync_client = OpenAI(api_key=api_key)
        self._async_client = AsyncOpenAI(api_key=api_key)
    
    def _setup_anthropic_clients(self) -> None:
        """Setup Anthropic clients."""
        if not Anthropic:
            raise ImportError("anthropic library is required for Anthropic provider. Install with: pip install anthropic")
        
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise APIKeyMissingError("ANTHROPIC_API_KEY environment variable is required")
        
        self._sync_client = Anthropic(api_key=api_key)
        self._async_client = AsyncAnthropic(api_key=api_key)
    
    def _create_rag_prompt(self, query: str, context: str) -> str:
        """
        Creates a robust, instruction-based prompt for the RAG pipeline.
        
        This is the core of the correction, providing detailed instructions to the LLM.
        
        Args:
            query: The user's original question.
            context: The retrieved context from the knowledge base.
            
        Returns:
            A detailed, formatted prompt string for the LLM.
        """
        
        prompt_template = """
        **You are an expert AI assistant for project management and risk analysis.**

        **Your Task:**
        You must provide a clear, concise, and direct answer to the user's query.
        Your answer must be based *exclusively* on the information provided in the "Context Documents" below.
        Do not use any external knowledge or make assumptions not supported by the context.

        **Instructions for Answering:**
        1.  Carefully read the user's "Query" to understand exactly what they are asking for.
        2.  Thoroughly review all "Context Documents" to find all relevant facts, figures, and details.
        3.  Synthesize the findings into a comprehensive, well-structured answer. Do not simply copy-paste from the context.
        4.  If the user asks for a plan, list, or steps, format your answer with clear headings, bullet points, or numbered lists.
        5.  **Crucially, you must cite your sources.** At the end of every sentence that uses information from a source, add a citation in the format `[DOCUMENT_ID]`. For example: "The performance test is scheduled for 2025-10-20. [TIMELINE #0174]".
        6.  If multiple documents support a single statement, you may cite them together, like this: `[NOTE #0443, RISK-REGISTER #0097]`.
        7.  If the provided context does not contain enough information to fully answer the query, you must explicitly state what information is missing. For example: "The provided context does not contain specific details on the budget for this mitigation."

        ---
        **Context Documents:**
        {context}
        ---
        **Query:**
        {query}
        ---
        **Answer:**
        """
        
        return prompt_template.format(context=context, query=query)
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((Exception,))
    )
    def _call_openai_api(self, messages: list) -> str:
        """Call OpenAI API with retry logic."""
        try:
            response = self._sync_client.chat.completions.create(
                model=self.config.model,
                messages=messages,
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"OpenAI API call failed: {str(e)}")
            raise LLMServiceError(f"OpenAI API call failed: {str(e)}")
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((Exception,))
    )
    async def _call_openai_api_async(self, messages: list) -> str:
        """Call OpenAI API asynchronously with retry logic."""
        try:
            response = await self._async_client.chat.completions.create(
                model=self.config.model,
                messages=messages,
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"OpenAI API async call failed: {str(e)}")
            raise LLMServiceError(f"OpenAI API async call failed: {str(e)}")
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((Exception,))
    )
    def _call_anthropic_api(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """Call Anthropic API with retry logic."""
        try:
            # For Claude 3, it's better to separate system and user prompts
            system_message = "You are an expert AI assistant for project management and risk analysis. Your task is to provide clear, concise answers based exclusively on the provided context, citing sources for every piece of information."
            
            response = self._sync_client.messages.create(
                model=self.config.model,
                max_tokens=self.config.max_tokens,
                temperature=self.config.temperature,
                system=system_message,
                messages=[{"role": "user", "content": prompt}]
            )
            return response.content[0].text.strip()
        except Exception as e:
            logger.error(f"Anthropic API call failed: {str(e)}")
            raise LLMServiceError(f"Anthropic API call failed: {str(e)}")
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((Exception,))
    )
    async def _call_anthropic_api_async(self, prompt: str) -> str:
        """Call Anthropic API asynchronously with retry logic."""
        try:
            system_message = "You are an expert AI assistant for project management and risk analysis. Your task is to provide clear, concise answers based exclusively on the provided context, citing sources for every piece of information."

            response = await self._async_client.messages.create(
                model=self.config.model,
                max_tokens=self.config.max_tokens,
                temperature=self.config.temperature,
                system=system_message,
                messages=[{"role": "user", "content": prompt}]
            )
            return response.content[0].text.strip()
        except Exception as e:
            logger.error(f"Anthropic API async call failed: {str(e)}")
            raise LLMServiceError(f"Anthropic API async call failed: {str(e)}")
    
    def generate(self, prompt: str, context: Optional[str] = None) -> str:
        """
        Generate text using the selected LLM provider.
        
        Args:
            prompt: The input prompt
            context: Optional context to use for RAG. If None, performs a direct generation.
            
        Returns:
            Generated text output
        """
        if context:
            final_prompt = self._create_rag_prompt(query=prompt, context=context)
        else:
            final_prompt = prompt

        try:
            if self.config.provider == "openai":
                messages = [{"role": "user", "content": final_prompt}]
                return self._call_openai_api(messages)
            elif self.config.provider == "anthropic":
                # With the new prompt, we only need to pass the user-facing part to Claude
                # as the system prompt is now handled inside the API call function.
                user_facing_prompt = f"**Context Documents:**\n{context}\n\n**Query:**\n{prompt}"
                return self._call_anthropic_api(user_facing_prompt)
        except Exception as e:
            logger.error(f"Text generation failed: {str(e)}")
            raise
    
    async def async_generate(self, prompt: str, context: Optional[str] = None) -> str:
        """
        Generate text asynchronously using the selected LLM provider.
        
        Args:
            prompt: The input prompt
            context: Optional context to use for RAG. If None, performs a direct generation.
            
        Returns:
            Generated text output
        """
        if context:
            final_prompt = self._create_rag_prompt(query=prompt, context=context)
        else:
            final_prompt = prompt
        
        try:
            if self.config.provider == "openai":
                messages = [{"role": "user", "content": final_prompt}]
                return await self._call_openai_api_async(messages)
            elif self.config.provider == "anthropic":
                user_facing_prompt = f"**Context Documents:**\n{context}\n\n**Query:**\n{prompt}"
                return await self._call_anthropic_api_async(user_facing_prompt)
        except Exception as e:
            logger.error(f"Async text generation failed: {str(e)}")
            raise
    
    async def json_tool(self, tool_name: str, spec: Dict[str, Any]) -> Union[Dict, List]:
        """
        Calls the LLM with a specific prompt to force a JSON output.
        This is what the IntentRouter expects.
        
        Args:
            tool_name: The name of the tool to execute
            spec: Tool specification containing instructions, labels, and query
            
        Returns:
            JSON response as a dictionary or list
        """
        # A simple but effective prompt to instruct the LLM to generate JSON.
        # More advanced versions could use provider-specific JSON modes.
        prompt = f"""
        You are a helpful AI assistant that only responds with perfectly formatted JSON.
        Do not include any preamble, explanations, or markdown code fences.
        
        Your task is to execute the tool named '{tool_name}'.

        Tool Specification:
        - Instructions: {spec.get('instructions', 'No instructions provided.')}
        - Available Labels: {spec.get('labels', [])}
        - User Query: "{spec.get('query', '')}"

        Based on the user query, generate a JSON object that fulfills the instructions.
        The main keys should be "intent", "subqueries", and "filters".
        Each item in "subqueries" should be a JSON object with keys "intent", "text", and "facets".
        
        Return only the JSON object, nothing else.
        """

        try:
            # We use the existing async_generate method to call the API
            raw_response = await self.async_generate(prompt)
            
            # Clean the response in case it has markdown code fences
            cleaned_response = raw_response.strip()
            if cleaned_response.startswith("```json"):
                cleaned_response = cleaned_response[7:]
            if cleaned_response.endswith("```"):
                cleaned_response = cleaned_response[:-3]
            cleaned_response = cleaned_response.strip()
            
            # The most important step: parse the LLM's string response into a Python dictionary
            json_response = json.loads(cleaned_response)
            return json_response

        except json.JSONDecodeError as e:
            logger.error(f"Failed to decode LLM response into JSON: {str(e)}", extra={
                "llm_response": raw_response[:500],  # Log first 500 chars for debugging
                "tool_name": tool_name
            })
            # Fallback to a simple structure if JSON parsing fails
            return {
                "intent": "NARRATIVE_SUMMARY",
                "subqueries": [{"intent": "NARRATIVE_SUMMARY", "text": spec.get('query', ''), "facets": {}}],
                "filters": {}
            }
        except Exception as e:
            logger.error(f"Error in json_tool execution: {e}", exc_info=True)
            raise LLMServiceError(f"json_tool failed: {e}")
    
    def get_config(self) -> Dict[str, Any]:
        """
        Get current configuration.
        
        Returns:
            Dictionary containing current configuration
        """
        return {
            "provider": self.config.provider,
            "model": self.config.model,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens
        }
    
    def update_config(
        self,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None
    ) -> None:
        """
        Update configuration parameters.
        
        Args:
            temperature: New temperature value
            max_tokens: New max_tokens value
        """
        if temperature is not None:
            self.config.temperature = temperature
        if max_tokens is not None:
            self.config.max_tokens = max_tokens
        
        logger.info(f"Configuration updated: {self.get_config()}")