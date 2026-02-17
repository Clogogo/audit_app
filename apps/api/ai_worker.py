"""
AI Worker — OpenRouter provider
  Model: qwen/qwen2.5-vl-72b-instruct:free  (OPENROUTER_MODEL env var to override)
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
import threading
import time
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)


# ── Custom exceptions ────────────────────────────────────────────────────────

class OpenRouterRateLimitError(Exception):
    """Raised when OpenRouter returns HTTP 429."""


class AIProviderError(Exception):
    """Raised when no AI provider is available."""


# ── Configuration ────────────────────────────────────────────────────────────

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL   = os.getenv("OPENROUTER_MODEL", "qwen/qwen3-vl-30b-a3b-thinking")
OPENROUTER_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"

PDF_VISION_MAX_PAGES = int(os.getenv("PDF_VISION_MAX_PAGES", "3"))
PDF_VISION_MAX_TOTAL_B64_CHARS = int(os.getenv("PDF_VISION_MAX_TOTAL_B64_CHARS", "6000000"))

# Rate limiter — free tier: 20 RPM → 3s between requests
_OR_INTERVAL   = 3.0
_or_lock       = threading.Lock()
_or_last: float = 0.0


def _or_acquire() -> None:
    global _or_last
    with _or_lock:
        wait = _OR_INTERVAL - (time.monotonic() - _or_last)
        if wait > 0:
            logger.info(f"OpenRouter rate-limiter: sleeping {wait:.1f}s")
            time.sleep(wait)
        _or_last = time.monotonic()


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
Salary, Freelance, Investment, Business, Loans, Other>",
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
Salary, Freelance, Investment, Business, Loans, Other>",
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


def _pdf_pages_as_b64_images(file_path: str) -> list[tuple[str, str]]:
    """
    Render each PDF page to a PNG image using PyMuPDF (no poppler needed).
    Returns list of (mime_type, base64_string) tuples, one per page.
    Limited to first N pages to stay within token/time limits.
    """
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(file_path)
        images = []
        total_b64_chars = 0
        try:
            max_pages = max(1, PDF_VISION_MAX_PAGES)
            for page_num in range(min(len(doc), max_pages)):
                page = doc[page_num]
                # 1.5x zoom keeps payload smaller and faster on free-tier instances
                mat = fitz.Matrix(1.5, 1.5)
                pix = page.get_pixmap(matrix=mat)
                png_bytes = pix.tobytes("png")
                b64 = base64.b64encode(png_bytes).decode()

                projected = total_b64_chars + len(b64)
                if projected > PDF_VISION_MAX_TOTAL_B64_CHARS:
                    logger.warning(
                        "Stopping PDF vision render at page %s due to payload cap (%s chars)",
                        page_num + 1,
                        PDF_VISION_MAX_TOTAL_B64_CHARS,
                    )
                    break

                images.append(("image/png", b64))
                total_b64_chars = projected
                logger.info(f"PyMuPDF rendered page {page_num + 1}/{len(doc)} ({len(png_bytes):,} bytes)")
        finally:
            doc.close()
        return images
    except ImportError:
        logger.warning("PyMuPDF not installed; cannot render PDF as images")
        return []
    except Exception as e:
        logger.warning(f"PyMuPDF PDF rendering failed: {e}")
        return []


# ── OpenRouter provider ───────────────────────────────────────────────────────

def _build_messages(
    prompt: str,
    file_path: str | None,
    mime_type: str | None,
    pre_extracted_pdf_text: str | None = None,
) -> list[dict]:
    """
    Build the OpenAI-style messages list.
    - PDF: extract text, send as plain text message
    - Image: send as base64 image_url content part
    - None (text-only): send prompt as plain text
    """
    if file_path is None or mime_type is None:
        return [{"role": "user", "content": prompt}]

    if "pdf" in mime_type.lower():
        text = pre_extracted_pdf_text if pre_extracted_pdf_text is not None else _extract_pdf_text(file_path)
        if text and len(text) >= 50:
            # Text-based PDF — send as plain text (up to 15000 chars to cover large statements)
            combined = f"{prompt}\n\nDocument text:\n{text[:15000]}"
            return [{"role": "user", "content": combined}]
        # Scanned / image-only PDF — render pages with PyMuPDF and send as images
        logger.info("Text extraction insufficient; falling back to PyMuPDF vision rendering")
        page_images = _pdf_pages_as_b64_images(file_path)
        if not page_images:
            logger.error("PyMuPDF fallback also failed — cannot process this PDF")
            return []
        content: list[dict] = [{"type": "text", "text": prompt}]
        for mime, b64 in page_images:
            content.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})
        return [{"role": "user", "content": content}]

    # Image — use vision content parts
    b64 = _read_image_b64(file_path)
    return [{
        "role": "user",
        "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{b64}"}},
        ],
    }]


def _call_openrouter(messages: list[dict]) -> str:
    """
    Call OpenRouter API.
    Raises OpenRouterRateLimitError on HTTP 429.
    Returns raw text response or "" on failure.
    """
    if not OPENROUTER_API_KEY:
        raise AIProviderError(
            "OPENROUTER_API_KEY is not set. Add it to your environment variables."
        )

    _or_acquire()

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://audit-app-yw5z.onrender.com",
        "X-Title": "FinanceAudit",
    }
    body = {
        "model": OPENROUTER_MODEL,
        "messages": messages,
        "temperature": 0.1,
        "max_tokens": 2048,
    }
    try:
        # Keep timeout below common edge/proxy limits to avoid empty-reply failures.
        with httpx.Client(timeout=55.0) as c:
            resp = c.post(OPENROUTER_ENDPOINT, headers=headers, json=body)
            resp.raise_for_status()
            data = resp.json()
        text = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        )
        logger.info(f"OpenRouter response preview: {text[:200]}...")
        return text
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 429:
            raise OpenRouterRateLimitError(
                "Rate limit reached. Please wait a moment and try again."
            )
        logger.error(f"OpenRouter HTTP error {e.response.status_code}: {e.response.text[:300]}")
        return ""
    except OpenRouterRateLimitError:
        raise
    except Exception as e:
        logger.error(f"OpenRouter call failed: {e}")
        return ""


# ── Public API ───────────────────────────────────────────────────────────────

def get_provider_status() -> dict:
    """Return current provider availability for the health endpoint."""
    configured = bool(OPENROUTER_API_KEY)
    return {
        "provider": f"OpenRouter / {OPENROUTER_MODEL}" if configured else "None",
        "model": OPENROUTER_MODEL if configured else "",
        "configured": configured,
        "ollama_available": False,
    }


def process_file(file_path: str, mime_type: str) -> tuple[str, dict]:
    """Single-transaction extraction. Returns (ocr_text, ai_result_dict)."""
    is_pdf = "pdf" in mime_type.lower()
    ocr_text = _extract_pdf_text(file_path) if is_pdf else f"[Image — {Path(file_path).stat().st_size:,} bytes]"

    messages = _build_messages(
        SINGLE_SCHEMA,
        file_path,
        mime_type,
        pre_extracted_pdf_text=ocr_text if is_pdf else None,
    )
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

    messages = _build_messages(
        BATCH_SCHEMA,
        file_path,
        mime_type,
        pre_extracted_pdf_text=ocr_text if is_pdf else None,
    )
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
    if not OPENROUTER_API_KEY:
        logger.warning("OPENROUTER_API_KEY not set; text-only AI call skipped")
        return ""

    try:
        messages = _build_messages(prompt, None, None)
        return _call_openrouter(messages)
    except OpenRouterRateLimitError:
        logger.warning("OpenRouter rate limit on text-only call — skipping")
    except Exception as e:
        logger.error(f"OpenRouter text-only call failed: {e}")
    return ""


# backward-compat alias used by other modules
_call_ai_text = call_ai_text
