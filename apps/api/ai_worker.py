"""
AI Worker — dual provider
  Primary:  Ollama (local, no rate limits)
  Fallback: Google Gemini API (if GEMINI_API_KEY is set and Ollama is unavailable)

Two extraction modes:
  process_file()       → single transaction  (receipts)
  process_file_batch() → list of transactions (registers, statements, invoices)
"""
import base64
import json
import logging
import os
import re
import threading
import time
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)


# ── Custom exceptions ────────────────────────────────────────────────────────

class GeminiRateLimitError(Exception):
    """Raised when Gemini returns HTTP 429."""


class AIProviderError(Exception):
    """Raised when no AI provider is available or both fail."""


# ── Configuration ────────────────────────────────────────────────────────────

OLLAMA_URL         = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_VISION_MODEL = os.getenv("OLLAMA_VISION_MODEL", "llama3.2-vision")  # for images
OLLAMA_TEXT_MODEL   = os.getenv("OLLAMA_TEXT_MODEL", "llama3.2:1b")    # for PDF text

GEMINI_API_KEY  = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL    = "gemini-2.0-flash-lite"
GEMINI_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL}:generateContent?key={{api_key}}"
)

# ── Gemini rate limiter (only used when falling back to Gemini) ──────────────
_GEMINI_INTERVAL = 4.5          # seconds — keeps us under 15 RPM free tier
_gemini_lock     = threading.Lock()
_gemini_last: float = 0.0


def _gemini_acquire() -> None:
    global _gemini_last
    with _gemini_lock:
        wait = _GEMINI_INTERVAL - (time.monotonic() - _gemini_last)
        if wait > 0:
            logger.info(f"Gemini rate-limiter: sleeping {wait:.1f}s")
            time.sleep(wait)
        _gemini_last = time.monotonic()


# ── Shared prompt schemas ────────────────────────────────────────────────────

SINGLE_SCHEMA = """\
Extract financial information from this receipt/invoice and return ONLY a valid JSON object.
Use null for any field you cannot determine.

{
  "amount": <total amount as a number, e.g. 42.50>,
  "currency": "<3-letter ISO code, e.g. USD>",
  "date": "<YYYY-MM-DD>",
  "vendor": "<business or person name>",
  "category": "<one of: Food & Dining, Transportation, Shopping, Entertainment, \
Bills & Utilities, Healthcare, Travel, Education, Housing, Salary, Freelance, \
Investment, Business, Other>",
  "type": "<expense or income>",
  "description": "<one short sentence>"
}

Return ONLY the JSON object. No markdown, no explanation."""

BATCH_SCHEMA = """\
This document may contain MULTIPLE transactions, payments, or line items.
Extract EVERY row/entry as a separate item. Return ONLY a valid JSON array.
Use null for any field you cannot determine.

[
  {
    "amount": <number>,
    "currency": "<3-letter ISO code, e.g. NGN, USD>",
    "date": "<YYYY-MM-DD or null>",
    "vendor": "<payer name, student name, or party name>",
    "category": "<one of: Food & Dining, Transportation, Shopping, Entertainment, \
Bills & Utilities, Healthcare, Travel, Education, Housing, Salary, Freelance, \
Investment, Business, Other>",
    "type": "<expense or income>",
    "description": "<brief description of this specific entry>",
    "reference": "<receipt number, transaction ID, or row reference if visible>"
  }
]

Important:
- Include ALL rows, even if some fields are missing
- For school fee payments the type is usually "income"
- If a column has a running date, use the most recent date above each entry
- Return ONLY the JSON array. No markdown, no explanation."""


# ── JSON cleanup ─────────────────────────────────────────────────────────────

def _clean_json(raw: str) -> str:
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL)
    raw = re.sub(r"```(?:json)?\s*", "", raw)
    raw = re.sub(r"```", "", raw)
    return raw.strip()


# ── File helpers ─────────────────────────────────────────────────────────────

def _read_image_b64(file_path: str) -> str:
    return base64.b64encode(Path(file_path).read_bytes()).decode()


def _extract_pdf_text(file_path: str) -> str:
    try:
        import pdfplumber
        texts = []
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                t = page.extract_text()
                if t:
                    texts.append(t)
        return "\n".join(texts).strip()
    except Exception as e:
        logger.error(f"pdfplumber failed: {e}")
        return ""


# ── Ollama provider ──────────────────────────────────────────────────────────

def _ollama_available() -> bool:
    try:
        with httpx.Client(timeout=3.0) as c:
            r = c.get(f"{OLLAMA_URL}/api/tags")
            return r.status_code == 200
    except Exception:
        return False


def _call_ollama(prompt: str, file_path: str, mime_type: str) -> str:
    """
    Route to the right Ollama model based on file type:
      - Images → OLLAMA_VISION_MODEL (moondream) with base64 image
      - PDFs   → OLLAMA_TEXT_MODEL   (llama3.2:1b) with extracted text
    Returns raw text response or "" on failure.
    """
    is_pdf = "pdf" in mime_type.lower()

    if is_pdf:
        text = _extract_pdf_text(file_path)
        if not text:
            logger.warning("Ollama: PDF had no extractable text")
            return ""
        model = OLLAMA_TEXT_MODEL
        body = {
            "model": model,
            "prompt": f"{prompt}\n\nDocument text:\n{text[:4000]}",
            "stream": False,
        }
        logger.info(f"Ollama PDF → text model ({model})")
    else:
        b64 = _read_image_b64(file_path)
        model = OLLAMA_VISION_MODEL
        body = {
            "model": model,
            "prompt": prompt,
            "images": [b64],
            "stream": False,
        }
        logger.info(f"Ollama image → vision model ({model})")

    try:
        with httpx.Client(timeout=120.0) as c:
            resp = c.post(f"{OLLAMA_URL}/api/generate", json=body)
            resp.raise_for_status()
            return resp.json().get("response", "")
    except Exception as e:
        logger.error(f"Ollama call failed: {e}")
        return ""


# ── Gemini provider ──────────────────────────────────────────────────────────

def _gemini_parts_for(file_path: str, mime_type: str) -> tuple[str, list[dict]]:
    """Returns (ocr_text, gemini_parts_list)."""
    if "pdf" in mime_type.lower():
        text = _extract_pdf_text(file_path)
        parts = [{"text": f"\n\nDocument text:\n{text[:4000]}"}] if text else []
        return text, parts
    else:
        ocr_text = f"[Image — {Path(file_path).stat().st_size:,} bytes]"
        b64 = _read_image_b64(file_path)
        parts = [{"inline_data": {"mime_type": mime_type, "data": b64}}]
        return ocr_text, parts


def _call_gemini(prompt: str, file_path: str, mime_type: str) -> str:
    """
    Call Gemini API with rate-limiting.
    Raises GeminiRateLimitError on 429.
    """
    if not GEMINI_API_KEY or GEMINI_API_KEY == "your_gemini_api_key_here":
        return ""

    _gemini_acquire()

    _, parts = _gemini_parts_for(file_path, mime_type)
    if not parts:
        return ""

    url = GEMINI_ENDPOINT.format(api_key=GEMINI_API_KEY)
    body = {
        "contents": [{"parts": [{"text": prompt}] + parts}],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 2048},
    }
    try:
        with httpx.Client(timeout=60.0) as c:
            resp = c.post(url, json=body)
            resp.raise_for_status()
            data = resp.json()
        return (
            data.get("candidates", [{}])[0]
            .get("content", {})
            .get("parts", [{}])[0]
            .get("text", "")
        )
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 429:
            raise GeminiRateLimitError(
                "Gemini rate limit reached (30 RPM on free tier). "
                "Please wait a moment and try again."
            )
        logger.error(f"Gemini error {e.response.status_code}: {e.response.text[:300]}")
        return ""
    except GeminiRateLimitError:
        raise
    except Exception as e:
        logger.error(f"Gemini call failed: {e}")
        return ""


# ── Unified dispatcher ───────────────────────────────────────────────────────

def _contains_json(text: str) -> bool:
    """Return True if text has at least one JSON array or object."""
    cleaned = _clean_json(text)
    return bool(re.search(r"[\[{]", cleaned))


def _call_ai(prompt: str, file_path: str, mime_type: str) -> str:
    """
    Try Ollama first.  Fall back to Gemini if:
      - Ollama is not running, OR
      - Ollama returns empty, OR
      - Ollama returns text with no JSON (model couldn't structure the data)
    Raises AIProviderError if both fail.
    """
    if _ollama_available():
        logger.info(f"Using Ollama ({OLLAMA_VISION_MODEL}/{OLLAMA_TEXT_MODEL}) for extraction")
        result = _call_ollama(prompt, file_path, mime_type)
        if result and _contains_json(result):
            return result
        if result:
            logger.warning(
                "Ollama response contained no JSON (model too small for this document) "
                "— falling back to Gemini"
            )
        else:
            logger.warning("Ollama returned empty response — falling back to Gemini")
    else:
        logger.info("Ollama not available — using Gemini")

    result = _call_gemini(prompt, file_path, mime_type)
    if result:
        return result

    raise AIProviderError(
        "Could not extract data. Ollama model (moondream) could not parse this document "
        "and Gemini API key is not configured. "
        "Set GEMINI_API_KEY in apps/api/.env for complex document fallback."
    )


# ── Public API ───────────────────────────────────────────────────────────────

def get_provider_status() -> dict:
    """Return current provider availability for the health endpoint."""
    ollama_up = _ollama_available()
    gemini_up = bool(GEMINI_API_KEY and GEMINI_API_KEY != "your_gemini_api_key_here")
    if ollama_up:
        provider = "Ollama (local)"
        model = f"{OLLAMA_VISION_MODEL} / {OLLAMA_TEXT_MODEL}"
    elif gemini_up:
        provider = "Google Gemini (fallback)"
        model = GEMINI_MODEL
    else:
        provider, model = "None", ""
    return {
        "provider": provider,
        "model": model,
        "configured": ollama_up or gemini_up,
        "ollama_available": ollama_up,
        "gemini_configured": gemini_up,
    }


def process_file(file_path: str, mime_type: str) -> tuple[str, dict]:
    """Single-transaction extraction. Returns (ocr_text, ai_result_dict)."""
    is_pdf = "pdf" in mime_type.lower()
    ocr_text = _extract_pdf_text(file_path) if is_pdf else f"[Image — {Path(file_path).stat().st_size:,} bytes]"

    raw = _call_ai(SINGLE_SCHEMA, file_path, mime_type)
    raw = _clean_json(raw)
    match = re.search(r"\{[\s\S]*\}", raw)
    result = {}
    if match:
        try:
            result = json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return ocr_text, result


def process_file_batch(file_path: str, mime_type: str) -> tuple[str, list[dict]]:
    """
    Multi-row extraction for registers, statements, invoices.
    Returns (ocr_text, list_of_transaction_dicts).
    """
    is_pdf = "pdf" in mime_type.lower()
    ocr_text = _extract_pdf_text(file_path) if is_pdf else f"[Image — {Path(file_path).stat().st_size:,} bytes]"

    raw = _call_ai(BATCH_SCHEMA, file_path, mime_type)
    raw = _clean_json(raw)

    arr_match = re.search(r"\[[\s\S]*\]", raw)
    if arr_match:
        try:
            items = json.loads(arr_match.group())
            if isinstance(items, list):
                return ocr_text, items
        except json.JSONDecodeError:
            pass

    obj_match = re.search(r"\{[\s\S]*\}", raw)
    if obj_match:
        try:
            return ocr_text, [json.loads(obj_match.group())]
        except json.JSONDecodeError:
            pass

    return ocr_text, []
