"""
OpenRouter LLM Client

Provider: OpenRouter (https://openrouter.ai/)
Model: Nvidia Nemotron 3 Ultra (default: nvidia/nemotron-3-ultra-550b-a55b:free, configurable)
Cost: Free tier with rate limits, or pay-as-you-go
"""

import os
import logging
from functools import lru_cache

logger = logging.getLogger(__name__)


class OpenRouterLLMClient:
    """Wrapper for OpenRouter API."""

    def __init__(self):
        from openai import OpenAI

        api_key = os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            raise ValueError(
                "OPENROUTER_API_KEY environment variable not set. "
                "Get a free API key at https://openrouter.ai/"
            )

        self.model = os.getenv("OPENROUTER_MODEL", "nvidia/nemotron-3-ultra-550b-a55b:free")
        self.client = OpenAI(
            api_key=api_key,
            base_url="https://openrouter.ai/api/v1",
        )
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


@lru_cache(maxsize=1)
def get_llm_client() -> OpenRouterLLMClient:
    """Get the configured LLM client, created once and reused after."""
    return OpenRouterLLMClient()
