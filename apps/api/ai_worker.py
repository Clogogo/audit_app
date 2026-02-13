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
OLLAMA_VISION_FALLBACK = "moondream"  # smaller, faster fallback for vision
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
Use null for any field you cannot clearly see in the document — do NOT guess or invent values.

{
  "amount": <total amount as a number, e.g. 42.50>,
  "currency": "<3-letter ISO code, e.g. NGN, USD>",
  "date": "<YYYY-MM-DD>",
  "vendor": "<business or person name>",
  "category": "<one of: Food & Dining, Transportation, Shopping, Entertainment, \
Bills & Utilities, Healthcare, Travel, Education, School Fees, Housing, Administration, \
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
Bills & Utilities, Healthcare, Travel, Education, School Fees, Housing, Administration, \
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
    # Remove thinking/reasoning tags
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL)
    raw = re.sub(r"<reasoning>.*?</reasoning>", "", raw, flags=re.DOTALL)
    
    # Remove markdown code blocks
    raw = re.sub(r"```(?:json)?\s*", "", raw)
    raw = re.sub(r"```", "", raw)
    
    # Remove common prefix phrases
    raw = re.sub(r"^(?:Here's|Here is|The|This is)\s+(?:the|a)?\s+(?:JSON|json|extracted)?.*?[:\n]", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"^(?:Based on|From|According to)\s+(?:the|this)?.*?[:\n]", "", raw, flags=re.IGNORECASE)
    
    return raw.strip()


# ── File helpers ─────────────────────────────────────────────────────────────

def _read_image_b64(file_path: str) -> str:
    return base64.b64encode(Path(file_path).read_bytes()).decode()


def _extract_pdf_text(file_path: str) -> str:
    """
    Extract text from PDF using pdfplumber.
    Falls back to OCR if no text is found (handles scanned PDFs).
    """
    try:
        import pdfplumber
        texts = []
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                t = page.extract_text()
                if t:
                    texts.append(t)
        
        result = "\n".join(texts).strip()
        
        # If no text found, try OCR (this is a scanned/image PDF)
        if not result or len(result) < 50:
            logger.info("pdfplumber found no text, attempting OCR for scanned PDF")
            result = _extract_pdf_text_ocr(file_path)
        
        return result
    except Exception as e:
        logger.error(f"pdfplumber failed: {e}")
        return ""


def _extract_pdf_text_ocr(file_path: str) -> str:
    """
    Extract text from scanned PDF using OCR (pytesseract).
    Falls back silently if tesseract is not installed.
    """
    try:
        from pdf2image import convert_from_path
        import pytesseract
        
        # Convert PDF pages to images
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
        logger.warning(
            "OCR libraries not installed. Install with: "
            "pip install pytesseract pdf2image && brew install tesseract"
        )
        return ""
    except Exception as e:
        logger.warning(f"OCR extraction failed: {e}")
        return ""


# ── Ollama provider ──────────────────────────────────────────────────────────

def _ollama_available() -> bool:
    try:
        with httpx.Client(timeout=3.0) as c:
            r = c.get(f"{OLLAMA_URL}/api/tags")
            return r.status_code == 200
    except Exception:
        return False


def _ollama_model_exists(model_name: str) -> bool:
    """Check if a specific Ollama model is available."""
    try:
        with httpx.Client(timeout=3.0) as c:
            r = c.get(f"{OLLAMA_URL}/api/tags")
            if r.status_code == 200:
                models = r.json().get("models", [])
                return any(model_name in m.get("name", "") for m in models)
    except Exception:
        pass
    return False


def _call_ollama(prompt: str, file_path: str, mime_type: str, retry_with_fallback: bool = True) -> str:
    """
    Route to the right Ollama model based on file type:
      - Images → OLLAMA_VISION_MODEL with base64 image (with moondream fallback)
      - PDFs   → OLLAMA_TEXT_MODEL with extracted text
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
            "options": {"temperature": 0.1, "num_predict": 2048}
        }
        logger.info(f"Ollama PDF → text model ({model})")
    else:
        # Try primary vision model first
        b64 = _read_image_b64(file_path)
        model = OLLAMA_VISION_MODEL
        
        # Enhanced prompt with clearer formatting instructions
        enhanced_prompt = f"""You are analyzing a financial document image that may contain handwritten or printed text.

STEPS:
1. Examine the ENTIRE image carefully
2. Identify if this is a TABLE with multiple rows
3. For handwritten text, read each character slowly and carefully
4. Extract ALL visible data by scanning from top to bottom

{prompt}

FORMATTING REQUIREMENTS:
- Output MUST be valid JSON only
- Start your response with [ for arrays or {{ for objects
- End with ] or }}
- No text before the JSON
- No text after the JSON
- No markdown code blocks like ```json
- No explanations

Start your response now:"""
        
        body = {
            "model": model,
            "prompt": enhanced_prompt,
            "images": [b64],
            "stream": False,
            "options": {"temperature": 0.1, "num_predict": 2048}
        }
        logger.info(f"Ollama image → vision model ({model})")

    try:
        with httpx.Client(timeout=120.0) as c:
            resp = c.post(f"{OLLAMA_URL}/api/generate", json=body)
            resp.raise_for_status()
            result = resp.json().get("response", "")
            
            # Log first 200 chars for debugging
            logger.info(f"Ollama response preview: {result[:200]}...")
            
            # If response is empty or doesn't contain JSON markers, try fallback for images
            if not is_pdf and retry_with_fallback and (not result or not _contains_json(result)):
                if _ollama_model_exists(OLLAMA_VISION_FALLBACK):
                    logger.warning(f"{model} produced no JSON, trying {OLLAMA_VISION_FALLBACK}")
                    body["model"] = OLLAMA_VISION_FALLBACK
                    resp = c.post(f"{OLLAMA_URL}/api/generate", json=body)
                    resp.raise_for_status()
                    result = resp.json().get("response", "")
                    logger.info(f"Fallback model response preview: {result[:200]}...")
            
            return result
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


# ── Text-only dispatcher (no file/image) ─────────────────────────────────────

def _call_ai_text(prompt: str) -> str:
    """
    Call AI with a plain-text prompt only — no file or image involved.
    Used for batch categorization and other text-only tasks.

    Tries Ollama text model first (llama3.2:1b), falls back to Gemini.
    Returns "" if both fail (never raises).
    """
    if _ollama_available():
        try:
            body = {
                "model": OLLAMA_TEXT_MODEL,
                "prompt": prompt,
                "stream": False,
            }
            with httpx.Client(timeout=60.0) as c:
                resp = c.post(f"{OLLAMA_URL}/api/generate", json=body)
                resp.raise_for_status()
                result = resp.json().get("response", "")
            if result and _contains_json(result):
                logger.info(f"Ollama text-only call succeeded ({OLLAMA_TEXT_MODEL})")
                return result
            logger.warning("Ollama text-only call returned no JSON — falling back to Gemini")
        except Exception as e:
            logger.warning(f"Ollama text-only call failed: {e}")

    if not GEMINI_API_KEY or GEMINI_API_KEY == "your_gemini_api_key_here":
        logger.warning("Gemini not configured; text-only AI call skipped")
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
            logger.warning("Gemini rate limit on text-only call — skipping AI categorization")
        else:
            logger.error(f"Gemini text-only error {e.response.status_code}: {e.response.text[:200]}")
    except Exception as e:
        logger.error(f"Gemini text-only call failed: {e}")
    return ""


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
    logger.info(f"Raw AI response length: {len(raw)} chars")
    
    cleaned = _clean_json(raw)
    logger.info(f"Cleaned response preview: {cleaned[:300]}")
    
    # Try to extract JSON object with more lenient pattern
    match = re.search(r"\{[\s\S]*?\}", cleaned, re.DOTALL)
    result = {}
    if match:
        try:
            result = json.loads(match.group())
            logger.info(f"Successfully parsed JSON with keys: {list(result.keys())}")
        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error: {e}. Matched text: {match.group()[:200]}")
            # Try to fix common JSON issues
            try:
                fixed = match.group().replace("\n", " ").replace("\r", "")
                fixed = re.sub(r",\s*([}\]])", r"\1", fixed)  # Remove trailing commas
                result = json.loads(fixed)
                logger.info(f"Successfully parsed JSON after fixes")
            except:
                pass
    else:
        logger.warning(f"No JSON object found in response. Full cleaned text: {cleaned[:500]}")
    
    return ocr_text, result


def process_file_batch(file_path: str, mime_type: str) -> tuple[str, list[dict]]:
    """
    Multi-row extraction for registers, statements, invoices.
    Returns (ocr_text, list_of_transaction_dicts).
    """
    is_pdf = "pdf" in mime_type.lower()
    ocr_text = _extract_pdf_text(file_path) if is_pdf else f"[Image — {Path(file_path).stat().st_size:,} bytes]"

    raw = _call_ai(BATCH_SCHEMA, file_path, mime_type)
    logger.info(f"Batch extraction raw response length: {len(raw)} chars")
    
    cleaned = _clean_json(raw)
    logger.info(f"Batch cleaned response preview: {cleaned[:500]}")

    # Strategy 1: Try to find and parse JSON array
    arr_match = re.search(r"\[[\s\S]*?\]", cleaned, re.DOTALL)
    if arr_match:
        json_text = arr_match.group()
        # Try multiple parsing strategies
        for attempt, fixer in enumerate([
            lambda x: x,  # As-is
            lambda x: x.replace("\n", " ").replace("\r", ""),  # Remove line breaks
            lambda x: re.sub(r",\s*([}\]])", r"\1", x),  # Remove trailing commas
            lambda x: re.sub(r",\s*([}\]])", r"\1", x.replace("\n", " ")),  # Both fixes
            lambda x: re.sub(r"([}\]])\s*([{\[])", r"\1,\2", x),  # Add missing commas between objects
        ], start=1):
            try:
                fixed = fixer(json_text)
                items = json.loads(fixed)
                if isinstance(items, list) and items:
                    logger.info(f"Successfully parsed {len(items)} items (attempt {attempt})")
                    return ocr_text, items
            except json.JSONDecodeError as e:
                if attempt <= 5:
                    logger.debug(f"Parse attempt {attempt} failed: {e}")
                continue
    
    # Strategy 2: Try to extract multiple objects and combine into array
    obj_matches = re.finditer(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", cleaned)
    objects = []
    for match in obj_matches:
        try:
            obj = json.loads(match.group())
            if isinstance(obj, dict) and obj:  # Valid non-empty dict
                objects.append(obj)
        except json.JSONDecodeError:
            continue
    
    if objects:
        logger.info(f"Extracted {len(objects)} objects from response")
        return ocr_text, objects

    # Strategy 3: Fall back to single object wrapped in array
    obj_match = re.search(r"\{[\s\S]*?\}", cleaned, re.DOTALL)
    if obj_match:
        try:
            obj = json.loads(obj_match.group())
            if isinstance(obj, dict) and obj:
                logger.info(f"Parsed single object as batch, wrapping in array")
                return ocr_text, [obj]
        except json.JSONDecodeError:
            pass

    logger.warning(f"No valid JSON found in batch response. Full cleaned: {cleaned[:800]}")
    return ocr_text, []
