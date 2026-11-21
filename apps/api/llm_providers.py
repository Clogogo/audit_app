"""
OpenRouter LLM Client

Provider: OpenRouter (https://openrouter.ai/)
Model: OpenRouter's free model router (configurable)
Cost: Free tier with rate limits, or pay-as-you-go
"""

import os
import logging
from functools import lru_cache

logger = logging.getLogger(__name__)


EMPTY_REPLY_ATTEMPTS = 3
REQUEST_TIMEOUT_SECONDS = 60


class EmptyModelReply(RuntimeError):
    """The model answered but returned no text (several free models do this now and then)."""


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

        self.model = os.getenv("OPENROUTER_MODEL", "openrouter/free")
        self.client = OpenAI(
            api_key=api_key,
            base_url="https://openrouter.ai/api/v1",
            max_retries=1,  # the SDK default of 2 would triple a slow call; empty replies are retried below
            timeout=REQUEST_TIMEOUT_SECONDS,  # the SDK default is 10 minutes; a stuck free model must not hang a request
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
        # The free router picks a different free model on every call, and some of them
        # sometimes return no text. Ask again: the next call usually lands on another model.
        # (Rate limits and server errors are already retried by the OpenAI SDK itself.)
        # Reasoning models bill their hidden thinking against max_tokens, and on the default effort
        # can use all of it before writing the answer (finish=length, empty content): ask for brief thinking.
        kwargs.setdefault("extra_body", {"reasoning": {"effort": "low"}})
        for attempt in range(1, EMPTY_REPLY_ATTEMPTS + 1):
            response = self.client.chat.completions.create(
                model=self.model,
                max_tokens=max_tokens,
                messages=messages,
                **kwargs
            )
            choices = response.choices or []
            text = ((choices[0].message.content if choices else None) or "").strip()
            if text:
                return text
            logger.warning(
                "OpenRouter returned no text (attempt %d/%d, served by %s, finish=%s)",
                attempt, EMPTY_REPLY_ATTEMPTS, getattr(response, "model", "?"),
                getattr(choices[0], "finish_reason", None) if choices else None,
            )
        raise EmptyModelReply(f"OpenRouter returned no text after {EMPTY_REPLY_ATTEMPTS} attempts")


@lru_cache(maxsize=1)
def get_llm_client() -> OpenRouterLLMClient:
    """Get the configured LLM client, created once and reused after."""
    return OpenRouterLLMClient()
