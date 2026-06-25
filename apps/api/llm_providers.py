"""
OpenRouter LLM Client Factory

Provider: OpenRouter (https://openrouter.ai/)
Model: Liquid LFM 2.5 (default: liquid/lfm-2.5-1.2b-thinking:free, configurable)
Cost: Free tier with rate limits, or pay-as-you-go

This module provides a unified interface for accessing LLMs via OpenRouter.
"""

import os
import logging

logger = logging.getLogger(__name__)


class LLMConfig:
    """Configuration for OpenRouter LLM provider."""
    
    @staticmethod
    def get_model() -> str:
        """
        Get the OpenRouter LLM model name.

        Environment variables:
        - OPENROUTER_MODEL: (default: "liquid/lfm-2.5-1.2b-thinking:free")

        Returns:
            str: The model identifier
        """
        model = os.getenv("OPENROUTER_MODEL", "liquid/lfm-2.5-1.2b-thinking:free")
        logger.info(f"Using OpenRouter model: {model}")
        return model





class OpenRouterLLMClient:
    """Wrapper for OpenRouter API with Liquid LFM."""
    
    def __init__(self):
        from openai import OpenAI
        
        api_key = os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            raise ValueError(
                "OPENROUTER_API_KEY environment variable not set. "
                "Get a free API key at https://openrouter.ai/"
            )
        
        self.client = OpenAI(
            api_key=api_key,
            base_url="https://openrouter.ai/api/v1",
        )
        self.model = LLMConfig.get_model()
        logger.info(f"Initialized OpenRouter client with model: {self.model}")
    
    def create_message(self, messages: list, max_tokens: int = 4096, **kwargs) -> str:
        """
        Create a message using OpenRouter LLM.
        
        Args:
            messages: List of message dicts with "role" and "content"
            max_tokens: Maximum tokens in response
            **kwargs: Additional arguments to pass to API
            
        Returns:
            str: The text response
        """
        response = self.client.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens,
            messages=messages,
            **kwargs
        )
        return response.choices[0].message.content.strip()


class LLMClientFactory:
    """Factory for creating OpenRouter LLM client."""
    
    _instance = None
    
    @classmethod
    def get_client(cls):
        """
        Get or create the OpenRouter LLM client.

        Returns:
            OpenRouterLLMClient: Configured client for Liquid LFM model
        """
        if cls._instance is not None:
            return cls._instance
        
        logger.info("Initializing OpenRouter LLM client")
        cls._instance = OpenRouterLLMClient()
        return cls._instance
    
    @classmethod
    def reset(cls):
        """Reset the singleton (useful for testing)."""
        cls._instance = None


# Convenient global access
def get_llm_client():
    """Get the configured LLM client."""
    return LLMClientFactory.get_client()
