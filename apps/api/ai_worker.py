"""
AI Worker — Google Gemini provider
  Model: gemini-2.0-flash  (GEMINI_MODEL env var to override)
  Requires: GEMINI_API_KEY environment variable

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
    """Raised when no AI provider is available."""


# ── Configuration ────────────────────────────────────────────────────────────

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL   = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
GEMINI_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL}:generateContent?key={{api_key}}"
)

# Rate limiter — gemini-2.0-flash free tier: 15 RPM
_GEMINI_INTERVAL = 4.5
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
Use null for any field you cannot clearly see in the document — do NOT guess or invent values.

{
  "amount": <total amount as a number, e.g. 42.50>,
  "currency": "<3-letter ISO code, e.g. NGN, USD>",
  "date": "<YYYY-MM-DD>",
  "vendor": "<business or person name>",
  "category": "<one of: Food & Dining, Transportation, Shopping, Entertainment, \
Bills & Utilities, Healthcare, Travel, Education, School Fees, Housing, Administration, Repairs, \
Salary, Freelance, Investment, Business, Other>",
  "type": "<expense or income>",
  "description": "<one short sentence describing what was paid for>"
}

IMPORTANT: Only extract information that is explicitly visible in the document.
Return ONLY the JSON object. No markdown, no explanation, no extra text."""

BATCH_SCHEMA = """\
This document may contain MULTIPLE transactions, payments, or line items.
Extract EVERY row/entry as a separate item. Return ONLY a valid JSON array.
Use null for any field you cannot clearly see — do NOT guess or invent values.

[
  {
    "amount": <number — must be explicitly visible in the document>,
    "currency": "<3-letter ISO code, e.g. NGN, USD>",
    "date": "<YYYY-MM-DD or null>",
    "vendor": "<payer name, student name, or party name>",
    "category": "<one of: Food & Dining, Transportation, Shopping, Entertainment, \
Bills & Utilities, Healthcare, Travel, Education, School Fees, Housing, Administration, Repairs, \
Salary, Freelance, Investment, Business, Other>",
    "type": "<expense or income>",
    "description": "<brief description of this specific entry>",
    "reference": "<receipt number, transaction ID, or row reference if visible>"
  }
]

IMPORTANT rules:
- Only extract data that is explicitly visible in the document. Never hallucinate amounts, dates, or names.
- Include ALL rows/entries, even if some fields are missing (use null for those fields).
- For school fee payments the type is usually "income".
- If a column has a running date, use the most recent date above each entry.
- Return ONLY the JSON array. No markdown, no explanation, no extra text."""


# ── JSON cleanup ─────────────────────────────────────────────────────────────

def _clean_json(raw: str) -> str:
    """Remove common non-JSON artifacts from AI responses."""
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL)
    raw = re.sub(r"<reasoning>.*?</reasoning>", "", raw, flags=re.DOTALL)
    raw = re.sub(r"```(?:json)?\s*", "", raw)
    raw = re.sub(r"```", "", raw)
    raw = re.sub(r"^(?:Here's|Here is|The|This is)\s+(?:the|a)?\s+(?:JSON|json|extracted)?.*?[:\n]", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"^(?:Based on|From|According to)\s+(?:the|this)?.*?[:\n]", "", raw, flags=re.IGNORECASE)
    return raw.strip()


# ── File helpers ─────────────────────────────────────────────────────────────

def _read_image_b64(file_path: str) -> str:
    return base64.b64encode(Path(file_path).read_bytes()).decode()


def _extract_pdf_text(file_path: str) -> str:
    """Extract text from PDF using pdfplumber; falls back to OCR for scanned PDFs."""
    try:
        import pdfplumber
        texts = []
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                t = page.extract_text()
                if t:
                    texts.append(t)
        result = "\n".join(texts).strip()
        if not result or len(result) < 50:
            logger.info("pdfplumber found no text, attempting OCR for scanned PDF")
            result = _extract_pdf_text_ocr(file_path)
        return result
    except Exception as e:
        logger.error(f"pdfplumber failed: {e}")
        return ""


def _extract_pdf_text_ocr(file_path: str) -> str:
    """Extract text from scanned PDF via pytesseract OCR."""
    try:
        from pdf2image import convert_from_path
        import pytesseract
        images = convert_from_path(file_path, dpi=300)
        texts = []
        for i, image in enumerate(images):
            logger.info(f"OCR processing page {i+1}/{len(images)}")
            text = pytesseract.image_to_string(image, lang='eng')
            if text.strip():
                texts.append(text.strip())
        result = "\n".join(texts).strip()
        logger.info(f"OCR extracted {len(result)} characters from {len(images)} pages")
        return result
    except ImportError:
        logger.warning("OCR libraries not installed (pytesseract / pdf2image)")
        return ""
    except Exception as e:
        logger.warning(f"OCR extraction failed: {e}")
        return ""


# ── Gemini provider ──────────────────────────────────────────────────────────

def _gemini_parts_for(file_path: str, mime_type: str) -> list[dict]:
    """Build the Gemini content parts list for the given file."""
    if "pdf" in mime_type.lower():
        text = _extract_pdf_text(file_path)
        return [{"text": f"\n\nDocument text:\n{text[:4000]}"}] if text else []
    else:
        b64 = _read_image_b64(file_path)
        return [{"inline_data": {"mime_type": mime_type, "data": b64}}]


def _call_gemini(prompt: str, parts: list[dict]) -> str:
    """
    Call Gemini API with the given prompt and content parts.
    Raises GeminiRateLimitError on HTTP 429.
    Returns raw text response or "" on failure.
    """
    if not GEMINI_API_KEY:
        raise AIProviderError(
            "GEMINI_API_KEY is not set. Add it to your environment variables."
        )

    _gemini_acquire()

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
        text = (
            data.get("candidates", [{}])[0]
            .get("content", {})
            .get("parts", [{}])[0]
            .get("text", "")
        )
        logger.info(f"Gemini response preview: {text[:200]}...")
        return text
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 429:
            raise GeminiRateLimitError(
                "Gemini rate limit reached. Please wait a moment and try again."
            )
        logger.error(f"Gemini HTTP error {e.response.status_code}: {e.response.text[:300]}")
        return ""
    except GeminiRateLimitError:
        raise
    except Exception as e:
        logger.error(f"Gemini call failed: {e}")
        return ""


def _contains_json(text: str) -> bool:
    """Return True if text contains at least one JSON array or object."""
    return bool(re.search(r"[\[{]", _clean_json(text)))


# ── Public API ───────────────────────────────────────────────────────────────

def get_provider_status() -> dict:
    """Return current provider availability for the health endpoint."""
    configured = bool(GEMINI_API_KEY)
    return {
        "provider": f"Google Gemini ({GEMINI_MODEL})" if configured else "None",
        "model": GEMINI_MODEL if configured else "",
        "configured": configured,
        "ollama_available": False,
        "gemini_configured": configured,
    }


def process_file(file_path: str, mime_type: str) -> tuple[str, dict]:
    """Single-transaction extraction. Returns (ocr_text, ai_result_dict)."""
    is_pdf = "pdf" in mime_type.lower()
    ocr_text = _extract_pdf_text(file_path) if is_pdf else f"[Image — {Path(file_path).stat().st_size:,} bytes]"

    parts = _gemini_parts_for(file_path, mime_type)
    if not parts:
        logger.warning("No content parts extracted from file")
        return ocr_text, {}

    raw = _call_gemini(SINGLE_SCHEMA, parts)
    logger.info(f"Raw AI response length: {len(raw)} chars")

    cleaned = _clean_json(raw)
    logger.info(f"Cleaned response preview: {cleaned[:300]}")

    match = re.search(r"\{[\s\S]*?\}", cleaned, re.DOTALL)
    result = {}
    if match:
        try:
            result = json.loads(match.group())
            logger.info(f"Successfully parsed JSON with keys: {list(result.keys())}")
        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error: {e}")
            try:
                fixed = re.sub(r",\s*([}\]])", r"\1", match.group().replace("\n", " "))
                result = json.loads(fixed)
                logger.info("Successfully parsed JSON after fixes")
            except Exception:
                pass
    else:
        logger.warning(f"No JSON object found in response: {cleaned[:500]}")

    return ocr_text, result


def process_file_batch(file_path: str, mime_type: str) -> tuple[str, list[dict]]:
    """
    Multi-row extraction for registers, statements, invoices.
    Returns (ocr_text, list_of_transaction_dicts).
    """
    is_pdf = "pdf" in mime_type.lower()
    ocr_text = _extract_pdf_text(file_path) if is_pdf else f"[Image — {Path(file_path).stat().st_size:,} bytes]"

    parts = _gemini_parts_for(file_path, mime_type)
    if not parts:
        return ocr_text, []

    raw = _call_gemini(BATCH_SCHEMA, parts)
    logger.info(f"Batch extraction raw response length: {len(raw)} chars")

    cleaned = _clean_json(raw)
    logger.info(f"Batch cleaned response preview: {cleaned[:500]}")

    # Strategy 1: JSON array
    arr_match = re.search(r"\[[\s\S]*?\]", cleaned, re.DOTALL)
    if arr_match:
        json_text = arr_match.group()
        for attempt, fixer in enumerate([
            lambda x: x,
            lambda x: x.replace("\n", " ").replace("\r", ""),
            lambda x: re.sub(r",\s*([}\]])", r"\1", x),
            lambda x: re.sub(r",\s*([}\]])", r"\1", x.replace("\n", " ")),
            lambda x: re.sub(r"([}\]])\s*([{\[])", r"\1,\2", x),
        ], start=1):
            try:
                items = json.loads(fixer(json_text))
                if isinstance(items, list) and items:
                    logger.info(f"Parsed {len(items)} items (attempt {attempt})")
                    return ocr_text, items
            except json.JSONDecodeError:
                continue

    # Strategy 2: extract individual objects
    objects = []
    for match in re.finditer(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", cleaned):
        try:
            obj = json.loads(match.group())
            if isinstance(obj, dict) and obj:
                objects.append(obj)
        except json.JSONDecodeError:
            continue

    if objects:
        logger.info(f"Extracted {len(objects)} objects from response")
        return ocr_text, objects

    # Strategy 3: single object as array
    obj_match = re.search(r"\{[\s\S]*?\}", cleaned, re.DOTALL)
    if obj_match:
        try:
            obj = json.loads(obj_match.group())
            if isinstance(obj, dict) and obj:
                return ocr_text, [obj]
        except json.JSONDecodeError:
            pass

    logger.warning(f"No valid JSON found in batch response: {cleaned[:800]}")
    return ocr_text, []


def call_ai_text(prompt: str) -> str:
    """
    Text-only AI call (no file). Used for categorisation and other text tasks.
    Returns "" on failure — never raises.
    """
    if not GEMINI_API_KEY:
        logger.warning("GEMINI_API_KEY not set; text-only AI call skipped")
        return ""

    _gemini_acquire()
    url = GEMINI_ENDPOINT.format(api_key=GEMINI_API_KEY)
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
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
            logger.warning("Gemini rate limit on text-only call — skipping")
        else:
            logger.error(f"Gemini text-only error {e.response.status_code}: {e.response.text[:200]}")
    except Exception as e:
        logger.error(f"Gemini text-only call failed: {e}")
    return ""


# backward-compat alias used by other modules
_call_ai_text = call_ai_text
