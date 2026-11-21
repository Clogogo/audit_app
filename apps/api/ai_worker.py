"""
AI helpers shared by the AI features (OpenRouter free router, see llm_providers.py;
OPENROUTER_MODEL overrides the model, OPENROUTER_API_KEY is required):
  call_ai_text()        text-only prompt -> text ("" on failure); used by the category suggester
  get_provider_status() what /health reports about the AI provider
  _clean_json()         strips <think> blocks, code fences and chatter from model output
"""
import logging
import re

from llm_providers import get_llm_client

logger = logging.getLogger(__name__)


# ── Custom exceptions ────────────────────────────────────────────────────────

class OpenRouterRateLimitError(Exception):
    """Raised when OpenRouter returns HTTP 429 (rate limit)."""


class AIProviderError(Exception):
    """Raised when no AI provider is available."""


def _clean_json(raw: str) -> str:
    """Remove common non-JSON artifacts from AI responses."""
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL)
    raw = re.sub(r"<reasoning>.*?</reasoning>", "", raw, flags=re.DOTALL)
    raw = re.sub(r"```json\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"```\s*", "", raw)
    # Strip any introductory text like "Here is the JSON:"
    raw = re.sub(r"^(?:Here's|Here is|The|This is)\s+(?:the|a)?\s+(?:JSON|json|extracted)?.*?[:\n]", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"^(?:Based on|From|According to)\s+(?:the|this)?.*?[:\n]", "", raw, flags=re.IGNORECASE)
    
    cleaned = raw.strip()
    
    # Try to heuristically fix truncated JSON due to token limits
    if cleaned.startswith("[") and not cleaned.endswith("]"):
        # Remove anything after the last complete object "}"
        last_brace = cleaned.rfind('}')
        if last_brace != -1:
            cleaned = cleaned[:last_brace+1] + "\n]"
        else:
            # If there's no complete object at all, just close the array
            cleaned += "\n]"
    elif cleaned.startswith("{") and not cleaned.endswith("}"):
        # For a single object, remove a partial trailing key like `"date":`
        last_comma = cleaned.rfind(',')
        if last_comma != -1:
            cleaned = cleaned[:last_comma] + "\n}"
        else:
            cleaned += "\n}"

    return cleaned


def _call_openrouter(messages: list[dict], max_tokens: int = 900) -> str:
    """
    Call OpenRouter LLM API.
    Returns raw text response or "" on failure.
    """
    try:
        client = get_llm_client()
        text = client.create_message(
            messages=messages,
            max_tokens=max_tokens,  # default kept low for the free tier; reasoning models need more for long prompts
        )
        logger.info(f"OpenRouter response preview: {text[:200]}...")
        return text
    except ValueError as e:
        # OPENROUTER_API_KEY not set
        raise AIProviderError(
            f"OpenRouter API configuration error: {e}"
        )
    except Exception as e:
        error_msg = str(e)
        # Check for specific HTTP errors
        if "402" in error_msg:
            logger.error(f"OpenRouter HTTP error 402: Insufficient credits. Visit https://openrouter.ai/settings/credits to add credits.")
        elif "429" in error_msg:
            logger.error(f"OpenRouter rate limit exceeded (429). Please wait and try again.")
            raise OpenRouterRateLimitError(error_msg)
        elif "405" in error_msg:
            logger.error(f"OpenRouter HTTP error 405: Method not allowed. Check API configuration.")
        else:
            logger.error(f"OpenRouter call failed: {e}")
        return ""


# ── Public API ───────────────────────────────────────────────────────────────

def get_provider_status() -> dict:
    """Return current provider availability for the health endpoint."""
    try:
        client = get_llm_client()
        model = client.model
        return {
            "provider": f"OpenRouter / {model}",
            "model": model,
            "configured": True,
            "ollama_available": False,
        }
    except Exception:
        return {
            "provider": "None",
            "model": "",
            "configured": False,
            "ollama_available": False,
        }


def call_ai_text(prompt: str, max_tokens: int = 900) -> str:
    """
    Text-only AI call. Used for categorisation and other text tasks.
    Returns "" on failure — never raises.
    """
    try:
        return _call_openrouter([{"role": "user", "content": prompt}], max_tokens)
    except AIProviderError:
        logger.warning("OpenRouter not configured; text-only AI call skipped")
    except Exception as e:
        logger.error(f"OpenRouter text-only call failed: {e}")
    return ""


# backward-compat alias used by other modules
_call_ai_text = call_ai_text
