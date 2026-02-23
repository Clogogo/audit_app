"""
AI Worker — OpenRouter Qwen provider
  Model: qwen/qwen-3.5-plus-02-15 (OPENROUTER_MODEL env var to override)
  Requires: OPENROUTER_API_KEY environment variable

Two extraction modes:
  process_file()       → single transaction  (receipts)
  process_file_batch() → list of transactions (registers, statements, invoices)
"""
import base64
import json
import logging
import os
import re
from pathlib import Path

from llm_providers import get_llm_client

logger = logging.getLogger(__name__)


# ── Custom exceptions ────────────────────────────────────────────────────────

class AILimitError(Exception):
    """Raised when the AI Provider returns HTTP 429."""


class AIProviderError(Exception):
    """Raised when no AI provider is available."""


# ── Configuration ────────────────────────────────────────────────────────────

# OpenRouter client is initialized via llm_providers module


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
Return ONLY the JSON object. Do not include markdown formatting or reasoning."""

BATCH_SCHEMA = """\
This document may contain MULTIPLE transactions, payments, or line items.
Extract EVERY row/entry as a separate item. Return ONLY a valid JSON array of objects.
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
- Return ONLY the JSON array. Do not include markdown formatting, backticks, or reasoning blocks."""


# ── JSON cleanup ─────────────────────────────────────────────────────────────

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


# ── File helpers ─────────────────────────────────────────────────────────────

def _extract_image_text_ocr(file_path: str) -> str:
    """Extract text from a standard image using pytesseract OCR."""
    try:
        from PIL import Image
        import pytesseract
        image = Image.open(file_path)
        logger.info(f"OCR processing single image")
        text = pytesseract.image_to_string(image, lang='eng')
        return text.strip()
    except Exception as e:
        logger.warning(f"Image OCR failed: {e}")
        return ""


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


# ── OpenRouter Qwen provider ────────────────────────────────────────────

def _build_messages(prompt: str, file_path: str | None, mime_type: str | None) -> list[dict]:
    """
    Build the OpenAI-style messages list.
    - PDF: extract text, send as plain text message
    - Image: OCR to text using pytesseract, send as plain text
    - None (text-only): send prompt as plain text
    """
    if file_path is None or mime_type is None:
        return [{"role": "user", "content": prompt}]

    text = ""
    if "pdf" in mime_type.lower():
        text = _extract_pdf_text(file_path)
    else:
        text = _extract_image_text_ocr(file_path)
        
    if not text:
        return []
    combined = f"{prompt}\n\nDocument text:\n{text[:6000]}"
    return [{"role": "user", "content": combined}]


def _call_openrouter(messages: list[dict]) -> str:
    """
    Call OpenRouter Qwen API.
    Returns raw text response or "" on failure.
    """
    try:
        client = get_llm_client()
        text = client.create_message(
            messages=messages,
            max_tokens=1300,
        )
        logger.info(f"OpenRouter response preview: {text[:200]}...")
        return text
    except ValueError as e:
        # OPENROUTER_API_KEY not set
        raise AIProviderError(
            f"OpenRouter API configuration error: {e}"
        )
    except Exception as e:
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


def process_file(file_path: str, mime_type: str) -> tuple[str, dict]:
    """Single-transaction extraction. Returns (ocr_text, ai_result_dict)."""
    is_pdf = "pdf" in mime_type.lower()
    ocr_text = _extract_pdf_text(file_path) if is_pdf else f"[Image — {Path(file_path).stat().st_size:,} bytes]"

    messages = _build_messages(SINGLE_SCHEMA, file_path, mime_type)
    if not messages:
        logger.warning("No content parts extracted from file")
        return ocr_text, {}

    raw = _call_openrouter(messages)
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

    messages = _build_messages(BATCH_SCHEMA, file_path, mime_type)
    if not messages:
        return ocr_text, []

    raw = _call_openrouter(messages)
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
    try:
        messages = _build_messages(prompt, None, None)
        return _call_openrouter(messages)
    except AIProviderError:
        logger.warning("OpenRouter not configured; text-only AI call skipped")
    except Exception as e:
        logger.error(f"OpenRouter text-only call failed: {e}")
    return ""


# backward-compat alias used by other modules
_call_ai_text = call_ai_text
