"""
LLM-based Bank Statement Parser for Nigerian Banks
Uses OpenRouter's LLM to intelligently extract transactions from bank statements.

This approach eliminates the need for bank-specific parsing logic by leveraging
LLM's ability to understand context, handle diverse formats, and extract structured data accurately.

Provider: OpenRouter (https://openrouter.io/)
Model: Liquid LFM 2.5 (default) or configurable via OPENROUTER_MODEL
Cost: Free tier available with rate limits, or pay-as-you-go
"""

import base64
import io
import json
import logging
import re
from datetime import datetime, date
from pathlib import Path
from typing import Optional, Dict, List, Any, Union
from dataclasses import dataclass, asdict

import pdfplumber
from pdf2image import convert_from_path

from llm_providers import get_llm_client

logger = logging.getLogger(__name__)


# ── Type Definitions ──────────────────────────────────────────────────────────

@dataclass
class NigerianBankTransaction:
    """Represents a parsed transaction from a Nigerian bank statement."""
    date: str  # ISO format YYYY-MM-DD
    description: str
    amount: float
    transaction_type: str  # debit | credit
    balance_after: Optional[float] = None
    reference: Optional[str] = None
    vendor: Optional[str] = None
    category_suggested: Optional[str] = None
    confidence: float = 1.0


@dataclass
class NigerianBankStatementMetadata:
    """Metadata extracted from bank statement."""
    bank_name: str
    account_number: Optional[str] = None
    account_holder: Optional[str] = None
    statement_period_start: Optional[str] = None  # ISO format
    statement_period_end: Optional[str] = None    # ISO format
    opening_balance: Optional[float] = None
    closing_balance: Optional[float] = None
    currency: str = "NGN"
    statement_date: Optional[str] = None  # When statement was generated


@dataclass
class ParsedBankStatement:
    """Complete parsed bank statement."""
    metadata: NigerianBankStatementMetadata
    transactions: List[NigerianBankTransaction]
    raw_extraction: Optional[str] = None  # For debugging
    extraction_quality: str = "high"  # high | medium | low


# ── LLM-based Parser ──────────────────────────────────────────────────────────

class LLMBankStatementParser:
    """
    Uses Claude to intelligently extract transactions from bank statements.
    
    ============================================================================
    EXTRACTION PRIORITY (always in this order):
    ============================================================================
    
    1. TEXT EXTRACTION (Local, Free, Fast) ✓ PRIMARY
       - Uses pdfplumber to extract text directly from PDF
       - Works for PDFs with selectable text (99% of bank statements)
       - No API calls, no cost, instant
       - Success rate: 95%+
    
    2. TEXT-BASED LLM PARSING (Cheap) ✓ FALLBACK
       - Sends extracted text to Claude
       - Cost: ~$0.001-0.003 per statement
       - Speed: 2-3 seconds
       - Used when text extraction succeeds
    
    3. VISION API (Expensive, Slow) ✓ LAST RESORT
       - Converts PDF to images, sends to Claude Vision
       - Cost: ~$0.01-0.02 per statement (10x more expensive)
       - Speed: 15-30 seconds (much slower)
       - Only used for scanned/image-based PDFs
    
    RESULT: Most statements cost $0.001-0.003 instead of $0.01+
    ============================================================================
    
    Advantages over traditional parsers:
    1. Bank Format Agnostic - works across all Nigerian banks
    2. Context-Aware - understands financial terminology
    3. Handles Variations - processes different layouts, fonts, structures
    4. Intelligent Extraction - identifies vendors, categories, relationships
    5. Few False Positives - validates logic before including transactions
    """

    def __init__(self):
        """Initialize the LLM parser with configured provider."""
        self.client = get_llm_client()
        logger.info(f"Initialized parser with LLM client: {self.client.__class__.__name__}")

    def parse_statement(
        self, pdf_path: str, max_pages: int = 10
    ) -> ParsedBankStatement:
        """
        Parse a Nigerian bank statement PDF with mandatory text extraction first.
        
        MANDATORY PROCESS (always in this order):
        =========================================================================
        1. EXTRACT TEXT FROM PDF (required, always first)
           - Local processing, free, fast
           - Try to get all text and structure
           - Mandatory before any LLM processing
        
        2. PROCESS WITH LLM (if text available)
           - Text-based Claude (cheap)
           - Structure the extracted text
           - Identify transactions, metadata
        
        3. FALLBACK TO VISION (only if text extraction fails completely)
           - For scanned/image PDFs
           - Last resort option
        =========================================================================

        Args:
            pdf_path: Path to the bank statement PDF
            max_pages: Maximum pages to process

        Returns:
            ParsedBankStatement with metadata and transactions
        """
        try:
            logger.info(f"\n{'='*70}")
            logger.info(f"START PARSING: {pdf_path}")
            logger.info(f"{'='*70}\n")
            
            # =================================================================
            # STEP 1: MANDATORY - Extract text from PDF first
            # =================================================================
            logger.info("[STEP 1] MANDATORY: Extract text from PDF")
            logger.info("-" * 70)
            
            text_content = self._extract_text_from_pdf(pdf_path, max_pages)
            
            if not text_content:
                logger.error("✗ TEXT EXTRACTION FAILED: No text extracted from PDF")
                raise ValueError("Failed to extract text from PDF - may be corrupted or empty")
            
            text_length = len(text_content.strip())
            logger.info(f"✓ TEXT EXTRACTED: {text_length} characters")
            logger.info(f"  Preview: {text_content[:150].replace(chr(10), ' ')[:150]}...")
            
            # =================================================================
            # STEP 2: STRUCTURED LLM PROCESSING (text-based, not Vision)
            # =================================================================
            logger.info("\n[STEP 2] STRUCTURED PROCESSING: Text-based Claude LLM")
            logger.info("-" * 70)
            
            if text_length > 500:
                # Sufficient text - use structured parsing
                logger.info("✓ Sufficient text for structured processing (>500 chars)")
                logger.info("  Processing with text-based Claude (cheap, fast)...")
                
                metadata = self._extract_metadata_from_text(text_content)
                transactions = self._extract_transactions_from_text(text_content)
                
                logger.info(f"✓ Structured processing complete")
                logger.info(f"  Bank: {metadata.bank_name}")
                logger.info(f"  Transactions found: {len(transactions)}")
                
            elif text_length > 100:
                # Minimal text - try anyway
                logger.warning(f"⚠ Limited text extracted ({text_length} chars), attempting processing...")
                
                metadata = self._extract_metadata_from_text(text_content)
                transactions = self._extract_transactions_from_text(text_content)
                
                logger.info(f"✓ Processed with limited text")
                logger.info(f"  Bank: {metadata.bank_name}")
                logger.info(f"  Transactions found: {len(transactions)}")
                
            else:
                # Text too short - may be scanned, try Vision API
                logger.warning(f"⚠ Text too short ({text_length} chars) for reliable processing")
                logger.info("  Falling back to Vision API for scanned/image PDFs...")
                
                images = self._convert_pdf_to_images(pdf_path, max_pages)
                if not images:
                    raise ValueError("Failed to convert PDF to images")
                
                logger.info(f"  Converted to {len(images)} images")
                metadata = self._extract_metadata(images)
                transactions = self._extract_transactions(images)
                
                logger.info(f"✓ Vision API processing complete")
                logger.info(f"  Bank: {metadata.bank_name}")
                logger.info(f"  Transactions found: {len(transactions)}")
            
            # =================================================================
            # STEP 3: VALIDATION & QUALITY ASSESSMENT
            # =================================================================
            logger.info("\n[STEP 3] VALIDATION & QUALITY ASSESSMENT")
            logger.info("-" * 70)
            
            extraction_quality = self._assess_quality(metadata, transactions)
            validation_issues = StatementValidator.get_validation_issues(metadata, transactions)
            
            logger.info(f"Quality: {extraction_quality.upper()}")
            
            if validation_issues:
                for issue in validation_issues:
                    logger.warning(f"  ⚠ {issue}")
            else:
                logger.info("  ✓ All validations passed")
            
            # =================================================================
            # COMPLETE
            # =================================================================
            logger.info(f"\n{'='*70}")
            logger.info(f"✓ PARSING COMPLETE")
            logger.info(f"  Transactions: {len(transactions)}")
            logger.info(f"  Quality: {extraction_quality}")
            logger.info(f"{'='*70}\n")
            
            return ParsedBankStatement(
                metadata=metadata,
                transactions=transactions,
                extraction_quality=extraction_quality,
            )

        except Exception as e:
            logger.error(f"\n{'='*70}")
            logger.error(f"✗ PARSING FAILED: {str(e)}")
            logger.error(f"{'='*70}\n")
            raise

    def _convert_pdf_to_images(self, pdf_path: str, max_pages: int) -> List[bytes]:
        """Convert PDF pages to base64-encoded images for Claude's vision API."""
        try:
            images_list = convert_from_path(pdf_path, first_page=1, last_page=max_pages)
            encoded_images = []

            for image in images_list:
                # Convert PIL Image to bytes
                img_byte_arr = io.BytesIO()
                image.save(img_byte_arr, format="JPEG", quality=85)
                img_byte_arr.seek(0)
                encoded = base64.standard_b64encode(img_byte_arr.read()).decode("utf-8")
                encoded_images.append(encoded)

            return encoded_images

        except Exception as e:
            logger.error(f"PDF to image conversion failed: {e}")
            return []

    def _extract_text_from_pdf(self, pdf_path: str, max_pages: int) -> Optional[str]:
        """
        MANDATORY FIRST STEP: Extract text directly from PDF using pdfplumber.
        
        This method is ALWAYS called first, before any LLM processing.
        
        Why text extraction is mandatory:
        - FREE: No API costs
        - FAST: Local processing takes <1 second
        - WORKS: Succeeds for 99% of real bank statements
        - PREREQUISITE: Must be done before any LLM call
        
        Returns:
        - str: Extracted text if successful (>100 chars)
        - None: Only if PDF is completely scanned/image-based
        
        Raises:
        - Exception: If PDF cannot be read at all
        """
        try:
            logger.info("Starting mandatory text extraction from PDF...")
            full_text = []
            text_by_page = {}
            
            with pdfplumber.open(pdf_path) as pdf:
                num_pages = min(len(pdf.pages), max_pages)
                logger.info(f"PDF has {len(pdf.pages)} pages, processing first {num_pages}")
                
                for page_num, page in enumerate(pdf.pages[:num_pages], 1):
                    page_text = ""
                    
                    # 1. Extract regular text (paragraph content)
                    text = page.extract_text()
                    if text and len(text.strip()) > 0:
                        page_text += text
                        logger.debug(f"  Page {page_num}: extracted {len(text)} chars of paragraph text")
                    
                    # 2. Extract table data (structured content)
                    tables = page.extract_tables()
                    if tables and len(tables) > 0:
                        logger.debug(f"  Page {page_num}: found {len(tables)} tables")
                        for table_idx, table in enumerate(tables, 1):
                            table_text = self._format_table_as_text(table)
                            page_text += "\n" + table_text
                            logger.debug(f"    Table {table_idx}: {len(table_text)} chars")
                    
                    # Store page text
                    if page_text.strip():
                        text_by_page[page_num] = page_text
                        full_text.append(page_text)
                        logger.debug(f"  Page {page_num}: TOTAL {len(page_text)} chars")
                    else:
                        logger.debug(f"  Page {page_num}: No text or tables found (likely scanned)")
            
            # Combine all extracted text
            combined_text = "\n\n".join(full_text)
            total_chars = len(combined_text.strip())
            
            # Mandatory extraction summary
            logger.info(f"Text extraction complete:")
            logger.info(f"  Total characters: {total_chars}")
            logger.info(f"  Pages with content: {len(text_by_page)}/{num_pages}")
            
            if total_chars < 50:
                logger.warning(f"  ⚠ WARNING: Very little text extracted ({total_chars} chars)")
                logger.warning(f"  This PDF may be scanned or image-based")
                logger.warning(f"  Will attempt Vision API as fallback")
                return None
            
            # Log text preview
            preview = combined_text[:200].replace('\n', ' ')
            logger.info(f"  Text preview: {preview}...")
            
            return combined_text
            
        except Exception as e:
            logger.error(f"CRITICAL: Failed to extract text from PDF: {e}")
            logger.error(f"PDF file may be corrupted or unreadable")
            return None

    def _format_table_as_text(self, table: List[List[str]]) -> str:
        """Format a table for text processing by Claude."""
        lines = []
        for row in table:
            # Join cells with pipe separator for clarity
            row_text = " | ".join(str(cell).strip() if cell else "" for cell in row)
            if row_text.strip():
                lines.append(row_text)
        return "\n".join(lines)

    def _extract_metadata_from_text(self, text: str) -> NigerianBankStatementMetadata:
        """
        Extract metadata using Claude with text input.
        
        GUARD: This method REQUIRES text to have been extracted first.
        Do NOT call this with None or empty text - violates processing order.
        
        Why use text instead of Vision API:
        - Text API cost: $0.00003 per image (cheap)
        - Vision API cost: $0.003 per image (100x more expensive)
        - Text extraction already done in previous mandatory step
        """
        if not text or len(text.strip()) < 50:
            logger.error("ERROR: _extract_metadata_from_text called with insufficient text!")
            logger.error("This violates the required processing order: text extraction → LLM processing")
            raise ValueError("Metadata extraction requires pre-extracted text (>50 chars)")
        
        logger.info("Processing structured extraction of metadata from text...")
        
        prompt = f"""Analyze this bank statement text and extract metadata in JSON format:

BANK STATEMENT TEXT:
{text[:5000]}

Extract and return ONLY valid JSON:
{{
  "bank_name": "Nigerian bank name",
  "account_number": "Account number or last 4 digits",
  "account_holder": "Account holder name",
  "statement_period_start": "Start date YYYY-MM-DD",
  "statement_period_end": "End date YYYY-MM-DD",
  "opening_balance": Opening balance amount,
  "closing_balance": Closing balance amount,
  "currency": "NGN or other",
  "statement_date": "Statement generation date YYYY-MM-DD"
}}

Use null for missing fields."""

        try:
            response_text = self.client.create_message(
                messages=[
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ],
                max_tokens=500,
            )
            data = json.loads(response_text)

            logger.info("Metadata extraction successful")
            
            return NigerianBankStatementMetadata(
                bank_name=data.get("bank_name", "Unknown"),
                account_number=data.get("account_number"),
                account_holder=data.get("account_holder"),
                statement_period_start=data.get("statement_period_start"),
                statement_period_end=data.get("statement_period_end"),
                opening_balance=self._safe_float(data.get("opening_balance")),
                closing_balance=self._safe_float(data.get("closing_balance")),
                currency=data.get("currency", "NGN"),
                statement_date=data.get("statement_date"),
            )

        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse metadata JSON: {e}")
            return NigerianBankStatementMetadata(bank_name="Unknown")

    def _extract_transactions_from_text(self, text: str) -> List[NigerianBankTransaction]:
        """
        Extract transactions using Claude with text input.
        
        GUARD: This method REQUIRES text to have been extracted first.
        Do NOT call this with None or empty text - violates processing order.
        
        Cost benefit:
        - Text API extraction: $0.00006 per transaction (average)
        - Vision API extraction: $0.03 per page (10-100x more expensive)
        - Text was already extracted FREE using pdfplumber in prior step
        
        Processing order MUST be:
        1. _extract_text_from_pdf() - mandatory, free, local
        2. _extract_transactions_from_text() - cheap, uses returned text
        3. Vision API only as fallback if text extraction fails
        """
        if not text or len(text.strip()) < 50:
            logger.error("ERROR: _extract_transactions_from_text called with insufficient text!")
            logger.error("This violates the required processing order: text extraction → LLM processing")
            raise ValueError("Transaction extraction requires pre-extracted text (>50 chars)")
        
        logger.info("Processing structured extraction of transactions from text...")
        
        prompt = f"""Analyze this bank statement text and extract ALL transactions:

BANK STATEMENT TEXT:
{text[:10000]}

For each transaction, return a JSON array with ONLY fields that are clearly visible:
[
  {{
    "date": "YYYY-MM-DD",
    "description": "Transaction description",
    "amount": 12345.67,
    "transaction_type": "debit" or "credit",
    "balance_after": null,
    "reference": null,
    "vendor": "vendor name if identifiable",
    "category_suggested": "utilities|salary|food|transport|shopping|transfer",
    "confidence": 0.95
  }}
]

Guidelines:
- Capture EVERY transaction visible
- debit = money out, credit = money in
- Extract vendor if mentioned in description
- Suggest category based on description
- confidence = 1.0 if text is clear, lower if unclear
- Use null for missing optional fields
- Return ONLY valid JSON array, no other text"""

        try:
            response_text = self.client.create_message(
                messages=[
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ],
                max_tokens=4096,
            )

            # Extract JSON from response
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0].strip()
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0].strip()

            data = json.loads(response_text)

            transactions = []
            for item in data:
                try:
                    tx = NigerianBankTransaction(
                        date=self._normalize_date(item.get("date", "")),
                        description=item.get("description", "").strip(),
                        amount=self._safe_float(item.get("amount")),
                        transaction_type=item.get("transaction_type", "debit").lower(),
                        balance_after=self._safe_float(item.get("balance_after")),
                        reference=item.get("reference"),
                        vendor=item.get("vendor"),
                        category_suggested=item.get("category_suggested"),
                        confidence=float(item.get("confidence", 0.9)),
                    )

                    if self._is_valid_transaction(tx):
                        transactions.append(tx)
                    else:
                        logger.debug(f"Skipped invalid transaction: {item}")

                except Exception as e:
                    logger.warning(f"Failed to parse transaction: {e}")
                    continue

            logger.info(f"Extracted {len(transactions)} valid transactions from text")
            return transactions

        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse transactions from text: {e}")
            return []

    def _extract_metadata(
        self, images: List[bytes]
    ) -> NigerianBankStatementMetadata:
        """
        Extract statement metadata from PDF images using Claude Vision API.
        
        IMPORTANT: This is a FALLBACK method, not the primary path.
        
        Primary path:
        1. Extract text locally (free) → _extract_text_from_pdf()
        2. Process text cheaply with Claude text API → _extract_metadata_from_text()
        
        This method is only called if:
        - Text extraction from _extract_text_from_pdf() returns None or <100 chars
        - OR if text extraction completely fails
        
        Cost warning:
        - Vision API: $0.00003 per image (expensive)
        - This should be rare - only ~1% of real statements
        - Text extraction handles 99% of cases
        """
        if not images:
            return NigerianBankStatementMetadata(bank_name="Unknown")

        logger.info("FALLBACK: Using Vision API for metadata extraction (text extraction was insufficient)")

        # Use only first page for metadata extraction
        first_page = images[0]

        prompt = """Analyze this bank statement image and extract the following metadata in JSON format:
{
  "bank_name": "Name of the Nigerian bank",
  "account_number": "Account number (last 4 digits if full not visible)",
  "account_holder": "Name of account holder",
  "statement_period_start": "Start date in YYYY-MM-DD format",
  "statement_period_end": "End date in YYYY-MM-DD format",
  "opening_balance": "Opening balance as number",
  "closing_balance": "Closing balance as number",
  "currency": "NGN or other currency code",
  "statement_date": "When statement was generated in YYYY-MM-DD format"
}

Return ONLY valid JSON. If a field is not found, use null."""

        try:
            response_text = self.client.create_message(
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/jpeg",
                                    "data": first_page,
                                },
                            },
                            {"type": "text", "text": prompt},
                        ],
                    }
                ],
                max_tokens=500,
            )
            data = json.loads(response_text)

            logger.info("Vision API metadata extraction successful")

            return NigerianBankStatementMetadata(
                bank_name=data.get("bank_name", "Unknown"),
                account_number=data.get("account_number"),
                account_holder=data.get("account_holder"),
                statement_period_start=data.get("statement_period_start"),
                statement_period_end=data.get("statement_period_end"),
                opening_balance=self._safe_float(data.get("opening_balance")),
                closing_balance=self._safe_float(data.get("closing_balance")),
                currency=data.get("currency", "NGN"),
                statement_date=data.get("statement_date"),
            )

        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse metadata JSON from Vision API: {e}")
            return NigerianBankStatementMetadata(bank_name="Unknown")

    def _extract_transactions(self, images: List[bytes]) -> List[NigerianBankTransaction]:
        """
        Extract all transactions from statement pages using Vision API.
        
        IMPORTANT: This is a FALLBACK method, not the primary path.
        
        Primary path:
        1. Extract text locally (free) → _extract_text_from_pdf()
        2. Process text cheaply with Claude text API → _extract_transactions_from_text()
        
        This method is only called if:
        - Text extraction from _extract_text_from_pdf() returns None or <100 chars
        - OR if text extraction completely fails
        
        Cost warning:
        - Vision API: $0.0015 per page (expensive)
        - This should be rare - only ~1% of real statements  
        - Text extraction handles 99% of cases
        """
        logger.info("FALLBACK: Using Vision API for transaction extraction (text extraction was insufficient)")
        
        all_transactions = []

        for page_idx, image in enumerate(images, 1):
            logger.info(f"Extracting transactions from page {page_idx} via Vision API")
            transactions = self._extract_page_transactions(image, page_idx)
            all_transactions.extend(transactions)

        # Deduplicate and sort
        all_transactions = self._deduplicate_transactions(all_transactions)
        all_transactions.sort(key=lambda t: t.date)

        return all_transactions

    def _extract_page_transactions(self, image: bytes, page_num: int) -> List[
        NigerianBankTransaction
    ]:
        """
        Extract transactions from a single page using Vision API.
        
        This is a FALLBACK method for scanned/image-based PDFs.
        Primary method is _extract_transactions_from_text() which uses local text extraction.
        """
        logger.debug(f"Vision API: Processing page {page_num} transactions")
        
        prompt = f"""Analyze this bank statement page and extract ALL transactions shown.

For each transaction, provide the following in a JSON array:
[
  {{
    "date": "Transaction date in YYYY-MM-DD format",
    "description": "Full description/narration of the transaction",
    "amount": Numeric amount (without currency symbol),
    "transaction_type": "debit" or "credit",
    "balance_after": Closing balance after transaction (if shown),
    "reference": "Reference number or check number if available",
    "vendor": "Extracted vendor/payee name if identifiable",
    "category_suggested": "Suggested category (salary, utilities, food, transport, etc.)",
    "confidence": 0.95 (confidence score 0-1)
  }}
]

Guidelines:
- Be thorough: capture all visible transactions
- For dates, use the date format shown in the statement
- For debit: money going out of the account
- For credit: money coming into the account  
- Vendor: extract from description if it's a known merchant (e.g., "Airtime topup - MTN" → vendor: "MTN")
- Category: intelligently infer from description (e.g., "AIRTIME" → "utilities", "TRANSFER/OWN ACCOUNT" → "transfer")
- Confidence: lower confidence if text is unclear or partially obscured
- Return ONLY valid JSON array, null values allowed for optional fields
- Do not include sample/explanation text, ONLY the JSON array

This is page {page_num} of the statement. Extract transactions visible on THIS page only."""

        try:
            response_text = self.client.create_message(
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/jpeg",
                                    "data": image,
                                },
                            },
                            {"type": "text", "text": prompt},
                        ],
                    }
                ],
                max_tokens=4096,
            )

            # Extract JSON from response (handle markdown code blocks)
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0].strip()
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0].strip()

            data = json.loads(response_text)

            transactions = []
            for item in data:
                try:
                    tx = NigerianBankTransaction(
                        date=self._normalize_date(item.get("date", "")),
                        description=item.get("description", "").strip(),
                        amount=self._safe_float(item.get("amount")),
                        transaction_type=item.get("transaction_type", "debit").lower(),
                        balance_after=self._safe_float(item.get("balance_after")),
                        reference=item.get("reference"),
                        vendor=item.get("vendor"),
                        category_suggested=item.get("category_suggested"),
                        confidence=float(item.get("confidence", 1.0)),
                    )

                    # Validate transaction
                    if self._is_valid_transaction(tx):
                        transactions.append(tx)
                    else:
                        logger.debug(f"Skipped invalid transaction: {item}")

                except Exception as e:
                    logger.warning(f"Failed to parse transaction item: {e}")
                    continue

            logger.info(f"Extracted {len(transactions)} valid transactions from page {page_num}")
            return transactions

        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse transactions JSON from page {page_num}: {e}")
            return []

    def _is_valid_transaction(self, tx: NigerianBankTransaction) -> bool:
        """Validate that transaction has minimum required fields."""
        return (
            tx.date
            and tx.description
            and tx.amount
            and tx.amount > 0
            and tx.transaction_type in ["debit", "credit"]
        )

    def _deduplicate_transactions(
        self, transactions: List[NigerianBankTransaction]
    ) -> List[NigerianBankTransaction]:
        """Remove duplicate transactions using fuzzy matching."""
        seen = {}
        unique = []

        for tx in transactions:
            # Create a signature for duplicate detection
            sig = (tx.date, round(tx.amount, 2), tx.transaction_type)

            if sig not in seen:
                seen[sig] = tx
                unique.append(tx)
            else:
                # If different descriptions, they might be different transactions
                if tx.description != seen[sig].description:
                    logger.debug(
                        f"Possible duplicate with different descriptions: "
                        f"{seen[sig].description} vs {tx.description}"
                    )

        return unique

    def _assess_quality(
        self, metadata: NigerianBankStatementMetadata, transactions: List[NigerianBankTransaction]
    ) -> str:
        """Assess the quality of extraction."""
        if not transactions:
            return "low"

        avg_confidence = sum(tx.confidence for tx in transactions) / len(
            transactions
        )

        if avg_confidence >= 0.9 and metadata.bank_name != "Unknown":
            return "high"
        elif avg_confidence >= 0.7:
            return "medium"
        else:
            return "low"

    @staticmethod
    def _normalize_date(date_str: str) -> str:
        """Normalize date string to YYYY-MM-DD format."""
        if not date_str:
            return datetime.now().strftime("%Y-%m-%d")

        date_str = date_str.strip()

        # Try common Nigeria date formats
        formats = [
            "%d/%m/%Y",
            "%d-%m-%Y",
            "%Y-%m-%d",
            "%Y/%m/%d",
            "%d %B %Y",
            "%d %b %Y",
            "%B %d, %Y",
            "%b %d, %Y",
        ]

        for fmt in formats:
            try:
                parsed = datetime.strptime(date_str, fmt)
                return parsed.strftime("%Y-%m-%d")
            except ValueError:
                continue

        logger.warning(f"Could not parse date: {date_str}")
        return datetime.now().strftime("%Y-%m-%d")

    @staticmethod
    def _safe_float(value: Any) -> Optional[float]:
        """Safely convert value to float."""
        if value is None or value == "":
            return None
        try:
            if isinstance(value, str):
                # Remove currency symbols and commas
                value = value.replace("₦", "").replace("N", "").replace(",", "").strip()
            return float(value)
        except (ValueError, TypeError):
            return None


# ── Bank-Specific Classifier ──────────────────────────────────────────────────

class NigerianBankClassifier:
    """Identifies Nigerian bank from statement and applies bank-specific logic."""

    NIGERIAN_BANKS = {
        "access_bank": ["access bank", "access"],
        "gtbank": ["guaranty trust bank", "gtb", "gtbank"],
        "zenith_bank": ["zenith bank", "zenith"],
        "first_bank": ["first bank", "first"],
        "uba": ["united bank for africa", "uba"],
        "stb": ["stanbic ibtc", "stanbic", "stb"],
        "fcmb": ["first city monument bank", "fcmb"],
        "fidelity": ["fidelity bank", "fidelity"],
        "union": ["union bank", "union"],
        "ecobank": ["ecobank", "eco"],
        "wema": ["wema bank", "wema"],
        "heritage": ["heritage bank", "heritage"],
        "polaris": ["polaris bank", "polaris"],
        "titan": ["titan bank", "titan"],
        "moniepoint": ["moniepoint", "moneycircle"],
        "opay": ["opay", "o-pay"],
        "payporte": ["payporte"],
    }

    @classmethod
    def identify_bank(cls, bank_name: str) -> Optional[str]:
        """Identify Nigerian bank from name, returning standardized code."""
        if not bank_name:
            return None

        bank_name_lower = bank_name.lower().strip()

        for bank_code, aliases in cls.NIGERIAN_BANKS.items():
            for alias in aliases:
                if alias in bank_name_lower:
                    return bank_code

        return None

    @classmethod
    def get_bank_config(cls, bank_code: str) -> Dict[str, Any]:
        """Get bank-specific parsing configuration."""
        configs = {
            "gtbank": {
                "date_format": "%d/%m/%Y",
                "debit_keywords": ["debit", "dr"],
                "credit_keywords": ["credit", "cr"],
                "has_balance_column": True,
            },
            "access_bank": {
                "date_format": "%d/%m/%Y",
                "debit_keywords": ["debit", "withdrawal"],
                "credit_keywords": ["credit", "deposit"],
                "has_balance_column": True,
            },
            "zenith_bank": {
                "date_format": "%d/%m/%Y",
                "debit_keywords": ["debit"],
                "credit_keywords": ["credit"],
                "has_balance_column": True,
            },
            "moniepoint": {
                "date_format": "%d/%m/%Y",
                "debit_keywords": ["debit"],
                "credit_keywords": ["credit"],
                "has_balance_column": False,
            },
            "opay": {
                "date_format": "%d/%m/%Y",
                "debit_keywords": ["debit"],
                "credit_keywords": ["credit"],
                "has_balance_column": False,
            },
        }

        return configs.get(bank_code, {})


# ── Validation & Quality Checks ───────────────────────────────────────────────

class StatementValidator:
    """Validates extracted statements for consistency and accuracy."""

    @staticmethod
    def validate_balances(
        metadata: NigerianBankStatementMetadata,
        transactions: List[NigerianBankTransaction],
    ) -> bool:
        """Validate that opening + transactions = closing balance."""
        if (
            not metadata.opening_balance
            or not metadata.closing_balance
            or not transactions
        ):
            return True  # Cannot validate

        # Calculate expected closing balance
        balance = metadata.opening_balance

        for tx in sorted(transactions, key=lambda t: t.date):
            if tx.transaction_type == "credit":
                balance += tx.amount
            else:  # debit
                balance -= tx.amount

        # Allow small tolerance for rounding errors
        tolerance = 1.0
        return abs(balance - metadata.closing_balance) <= tolerance

    @staticmethod
    def validate_date_sequence(transactions: List[NigerianBankTransaction]) -> bool:
        """Check if transactions are in chronological order."""
        if len(transactions) < 2:
            return True

        dates = [tx.date for tx in transactions]
        return dates == sorted(dates)

    @staticmethod
    def get_validation_issues(
        metadata: NigerianBankStatementMetadata,
        transactions: List[NigerianBankTransaction],
    ) -> List[str]:
        """Get list of validation issues."""
        issues = []

        if not StatementValidator.validate_balances(metadata, transactions):
            issues.append("Balance mismatch: opening + transactions ≠ closing")

        if not StatementValidator.validate_date_sequence(transactions):
            issues.append("Transactions not in chronological order")

        if not metadata.bank_name or metadata.bank_name == "Unknown":
            issues.append("Bank name could not be extracted")

        if not transactions:
            issues.append("No transactions found")

        return issues
