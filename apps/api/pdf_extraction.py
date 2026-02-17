"""
Enhanced PDF Bank Statement Extraction
Provides accurate extraction of bank statements with structure detection,
table parsing, and intelligent validation.
"""
import io
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List, Tuple, Any

import pdfplumber
import pandas as pd
from pdf2image import convert_from_path
import pytesseract

logger = logging.getLogger(__name__)
# Cache compiled regex patterns to avoid recompilation on each use
_REGEX_CACHE = {
    'date_formats': [
        re.compile(r'day', re.IGNORECASE),
        re.compile(r'month', re.IGNORECASE),
    ],
    'currency': re.compile(r'[₦N$£€\s]'),
    'date_parts': re.compile(r'(\d{4})-(\d{1,2})-(\d{1,2})')
}

class PDFExtractionError(Exception):
    """Raised when PDF extraction fails."""
    pass


class StatementMetadata:
    """Holds extracted statement metadata."""
    def __init__(self):
        self.statement_date: Optional[str] = None
        self.account_number: Optional[str] = None
        self.account_holder: Optional[str] = None
        self.bank_name: Optional[str] = None
        self.opening_balance: Optional[float] = None
        self.closing_balance: Optional[float] = None
        self.currency: str = "NGN"
        self.period_start: Optional[str] = None
        self.period_end: Optional[str] = None


class TableExtractor:
    """Extracts structured data from PDF tables."""
    
    def __init__(self, pdf_path: str):
        self.pdf_path = pdf_path
        self.metadata = StatementMetadata()
        self.transactions: List[Dict[str, Any]] = []
    
    def extract(self) -> Tuple[StatementMetadata, List[Dict[str, Any]]]:
        """
        Main extraction method. Returns (metadata, transactions).
        """
        try:
            with pdfplumber.open(self.pdf_path) as pdf:
                # Try structured table extraction first
                result = self._extract_from_tables(pdf)
                if result and len(result) > 0:
                    return self.metadata, result
                
                # Fallback to text-based extraction
                logger.info("Table extraction yielded no results, falling back to OCR")
                result = self._extract_from_ocr(pdf)
                return self.metadata, result
        except Exception as e:
            logger.error(f"PDF extraction failed: {e}")
            raise PDFExtractionError(f"Failed to extract PDF: {e}")
    
    def _extract_from_tables(self, pdf) -> List[Dict[str, Any]]:
        """
        Extract transactions from structured tables in PDF.
        pdfplumber excels at finding tables in bank statements.
        """
        transactions = []
        
        for page_num, page in enumerate(pdf.pages, 1):
            logger.info(f"Processing page {page_num}: extracting tables")
            
            # Extract text for metadata (header/footer info)
            page_text = page.extract_text()
            self._extract_metadata_from_text(page_text, page_num == 1)
            
            # Find all tables on this page
            tables = page.extract_tables()
            if not tables:
                logger.debug(f"No tables found on page {page_num}")
                continue
            
            for table_idx, table in enumerate(tables):
                logger.info(f"Found table {table_idx + 1} on page {page_num}")
                extracted = self._parse_table(table, page_num)
                transactions.extend(extracted)
        
        # Remove duplicates and sort
        transactions = self._deduplicate_transactions(transactions)
        transactions.sort(key=lambda x: x.get("date", ""))
        
        return transactions
    
    def _parse_table(self, table: List[List[str]], page_num: int) -> List[Dict[str, Any]]:
        """Parse a single table into transaction records."""
        if not table or len(table) < 2:
            return []
        
        # Convert to DataFrame for easier processing
        try:
            df = pd.DataFrame(table[1:], columns=table[0])
        except Exception as e:
            logger.warning(f"Failed to parse table on page {page_num}: {e}")
            return []
        
        # Standardize column names
        df.columns = [self._normalize_column_name(col) for col in df.columns]
        
        logger.debug(f"Table columns: {list(df.columns)}")
        
        transactions = []
        for idx, row in df.iterrows():
            tx = self._parse_table_row(row, idx)
            if tx and self._is_valid_transaction(tx):
                transactions.append(tx)
        
        logger.info(f"Parsed {len(transactions)} transactions from table on page {page_num}")
        return transactions
    
    def _normalize_column_name(self, col: str) -> str:
        """Normalize column names to standard format."""
        if not col:
            return "unknown"
        
        normalized = col.lower().strip()
        
        # Remove common suffixes/prefixes
        normalized = re.sub(r'\s*\(.*?\)\s*', '', normalized)
        normalized = re.sub(r'\s*\[.*?\]\s*', '', normalized)
        
        return normalized
    
    def _parse_table_row(self, row: pd.Series, idx: int) -> Optional[Dict[str, Any]]:
        """Parse a single table row into a transaction record."""
        # Skip empty rows
        if row.isna().all() or all(str(v).strip() == "" for v in row):
            return None
        
        tx = {
            "row_index": idx,
            "source": "table_extraction",
        }
        
        # Extract date
        date_val = self._extract_date_from_row(row)
        if date_val:
            tx["date"] = date_val
        
        # Extract description/narration
        desc = self._extract_description_from_row(row)
        if desc:
            tx["description"] = desc
        
        # Extract amounts
        debit, credit = self._extract_amounts_from_row(row)
        
        if debit:
            tx["amount"] = debit
            tx["amount_type"] = "debit"
        elif credit:
            tx["amount"] = credit
            tx["amount_type"] = "credit"
        else:
            # No amount found — skip this row
            return None
        
        # Extract balance if available
        balance = self._extract_balance_from_row(row)
        if balance:
            tx["balance_after"] = balance
        
        # Extract reference
        ref = self._extract_reference_from_row(row)
        if ref:
            tx["reference"] = ref
        
        return tx
    
    def _extract_date_from_row(self, row: pd.Series) -> Optional[str]:
        """Extract date from row, searching common column names."""
        date_cols = ["date", "trans_date", "value_date", "posting_date", "txn_date"]
        
        for col in date_cols:
            if col in row.index:
                val = str(row[col]).strip()
                if val and val.lower() != "date":
                    parsed = self._parse_date(val)
                    if parsed:
                        return parsed
        
        return None
    
    def _extract_description_from_row(self, row: pd.Series) -> Optional[str]:
        """Extract transaction description/narration."""
        desc_cols = ["description", "narration", "memo", "details", "particulars", "remarks"]
        
        for col in desc_cols:
            if col in row.index:
                val = str(row[col]).strip()
                if val and len(val) > 2 and val.lower() not in ["na", "n/a", "null"]:
                    return val
        
        return None
    
    def _extract_amounts_from_row(self, row: pd.Series) -> Tuple[Optional[float], Optional[float]]:
        """Extract debit and credit amounts."""
        debit = None
        credit = None
        
        # Try paired debit/credit columns
        debit_cols = ["debit", "dr", "withdrawal", "paid_out"]
        credit_cols = ["credit", "cr", "deposit", "paid_in"]
        
        for col in debit_cols:
            if col in row.index:
                val = self._parse_amount(str(row[col]))
                if val:
                    debit = val
                    break
        
        for col in credit_cols:
            if col in row.index:
                val = self._parse_amount(str(row[col]))
                if val:
                    credit = val
                    break
        
        # If no paired columns, try single "amount" column with direction
        if not debit and not credit:
            amount_cols = ["amount", "transaction_amount", "txn_amount"]
            type_cols = ["type", "dr_cr", "direction"]
            
            amount_val = None
            for col in amount_cols:
                if col in row.index:
                    amount_val = self._parse_amount(str(row[col]))
                    break
            
            if amount_val:
                type_val = None
                for col in type_cols:
                    if col in row.index:
                        type_val = str(row[col]).lower().strip()
                        break
                
                if type_val and type_val in ["dr", "debit", "d"]:
                    debit = amount_val
                elif type_val and type_val in ["cr", "credit", "c"]:
                    credit = amount_val
                else:
                    # Default: assume credit if no direction
                    credit = amount_val
        
        return debit, credit
    
    def _extract_balance_from_row(self, row: pd.Series) -> Optional[float]:
        """Extract running balance."""
        balance_cols = ["balance", "running_balance", "ledger_balance", "bal"]
        
        for col in balance_cols:
            if col in row.index:
                val = self._parse_amount(str(row[col]))
                if val:
                    return val
        
        return None
    
    def _extract_reference_from_row(self, row: pd.Series) -> Optional[str]:
        """Extract transaction reference/ID."""
        ref_cols = ["reference", "ref", "transaction_id", "txn_id", "receipt_no"]
        
        for col in ref_cols:
            if col in row.index:
                val = str(row[col]).strip()
                if val and len(val) > 0:
                    return val
        
        return None
    
    def _extract_metadata_from_text(self, text: str, is_first_page: bool):
        """Extract metadata (account number, bank name, balances) from text."""
        if not text:
            return
        
        # Extract account number (various formats: 0000000000, 00-00-00-00)
        acct_patterns = [
            r'account\s*(?:no|number)?\s*[:\-]?\s*([0-9]{10,20})',
            r'a/c\s*[:\-]?\s*([0-9]{10,20})',
            r'acct\s*[:\-]?\s*([0-9]{10,20})',
        ]
        for pattern in acct_patterns:
            acct_match = re.search(pattern, text, re.IGNORECASE)
            if acct_match:
                self.metadata.account_number = re.sub(r'[\s\-]', '', acct_match.group(1).strip())
                break
        
        # Extract account holder name
        holder_patterns = [
            r'account\s*(?:holder|name)\s*[:\-]?\s*([A-Z][A-Za-z\s/]{3,50})',
            r'registered\s+name\s*[:\-]?\s*([A-Z][A-Za-z\s/]{3,50})',
        ]
        for pattern in holder_patterns:
            holder_match = re.search(pattern, text, re.IGNORECASE)
            if holder_match:
                name = holder_match.group(1).strip()
                name = re.sub(r'[^\w\s/\-]$', '', name)
                if len(name) > 3:
                    self.metadata.account_holder = name
                    break
        
        # Extract bank name with comprehensive patterns
        bank_patterns = [
            (r'access\s+bank', 'Access Bank'),
            (r'gtbank|guaranty\s+trust', 'GTBank'),
            (r'uba|united\s+bank\s+for\s+africa', 'UBA'),
            (r'zenith\s+bank', 'Zenith Bank'),
            (r'first\s+bank(?:\s+of\s+nigeria)?', 'First Bank'),
            (r'stanbic', 'Stanbic'),
            (r'fcmb|fidelity\s+bank', 'FCMB'),
            (r'moniepoint', 'Moniepoint'),
            (r'opay', 'OPay'),
            (r'kuda', 'Kuda'),
            (r'ecobank', 'Ecobank'),
            (r'polaris\s+bank', 'Polaris Bank'),
            (r'wema\s+bank', 'Wema Bank'),
            (r'union\s+bank', 'Union Bank'),
            (r'heritage\s+bank', 'Heritage Bank'),
        ]
        text_lower = text.lower()
        for pattern, bank_name in bank_patterns:
            if re.search(pattern, text_lower, re.IGNORECASE):
                self.metadata.bank_name = bank_name
                break
        
        # Extract opening/closing balances
        opening_match = re.search(r'opening\s+balance\s*[:\-]?\s*[₦N$]?\s*([\d,]+\.?\d*)', text, re.IGNORECASE)
        if opening_match:
            self.metadata.opening_balance = self._parse_amount(opening_match.group(1))
        
        closing_match = re.search(r'closing\s+balance\s*[:\-]?\s*[₦N$]?\s*([\d,]+\.?\d*)', text, re.IGNORECASE)
        if closing_match:
            self.metadata.closing_balance = self._parse_amount(closing_match.group(1))
        
        # Extract statement period
        if is_first_page:
            period_match = re.search(
                r'(?:statement\s+)?period\s*[:\-]?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\s+(?:to|-)?\s+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})',
                text, re.IGNORECASE
            )
            if period_match:
                try:
                    self.metadata.period_start = self._parse_date(period_match.group(1))
                    self.metadata.period_end = self._parse_date(period_match.group(2))
                except:
                    pass
    
    def _extract_from_ocr(self, pdf) -> List[Dict[str, Any]]:
        """
        Fallback: Extract using OCR for scanned PDFs.
        """
        transactions = []
        
        try:
            images = convert_from_path(self.pdf_path, dpi=200)
            
            for page_num, image in enumerate(images, 1):
                logger.info(f"OCR processing page {page_num}/{len(images)}")
                text = pytesseract.image_to_string(image, lang='eng')
                
                # Extract metadata from first page
                if page_num == 1:
                    self._extract_metadata_from_text(text, True)
                
                # Try to extract transactions from OCR text
                extracted = self._extract_transactions_from_ocr_text(text)
                transactions.extend(extracted)
        except Exception as e:
            logger.error(f"OCR extraction failed: {e}")
        
        return transactions
    
    def _extract_transactions_from_ocr_text(self, text: str) -> List[Dict[str, Any]]:
        """
        Parse transaction lines from OCR text.
        Looks for date + amount + description patterns.
        """
        transactions = []
        
        # Split by lines
        lines = text.split('\n')
        
        for line in lines:
            line = line.strip()
            if not line or len(line) < 10:
                continue
            
            tx = self._parse_ocr_line(line)
            if tx and self._is_valid_transaction(tx):
                transactions.append(tx)
        
        return transactions
    
    def _parse_ocr_line(self, line: str) -> Optional[Dict[str, Any]]:
        """
        Parse a single OCR line into a transaction.
        Expected format: DATE DESCRIPTION DEBIT CREDIT BALANCE
        """
        # Pattern: date at start, amounts (with or without currency symbol)
        pattern = r'^(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\s+(.+?)\s+([\d,]+\.?\d*)\s+([\d,]+\.?\d*)?\s*([\d,]+\.?\d*)?'
        
        match = re.match(pattern, line)
        if not match:
            return None
        
        date_str, desc, amount1, amount2, balance = match.groups()
        
        tx = {
            "source": "ocr_extraction",
            "description": desc.strip(),
        }
        
        # Parse date
        parsed_date = self._parse_date(date_str)
        if parsed_date:
            tx["date"] = parsed_date
        
        # Determine if amount1 is debit or credit
        val1 = self._parse_amount(amount1)
        val2 = self._parse_amount(amount2) if amount2 else None
        
        if val1:
            if val2:
                # Both amounts present — first is often debit, second credit
                tx["debit"] = val1
                tx["credit"] = val2
                tx["amount"] = val2
                tx["amount_type"] = "credit"
            else:
                # Single amount — assume credit
                tx["amount"] = val1
                tx["amount_type"] = "credit"
        
        if balance:
            tx["balance_after"] = self._parse_amount(balance)
        
        return tx
    
    def _is_valid_transaction(self, tx: Dict[str, Any]) -> bool:
        """Check if transaction has minimum required fields."""
        return "amount" in tx and tx.get("amount") and tx.get("date")
    
    def _parse_date(self, date_str: str) -> Optional[str]:
        """Parse date string to YYYY-MM-DD format. Optimized with early returns."""
        if not date_str or not isinstance(date_str, str):
            return None
        
        date_str = date_str.strip()
        
        # Fast path: already in YYYY-MM-DD format
        if _REGEX_CACHE['date_parts'].match(date_str):
            return date_str
        
        # Common date formats (ordered by likelihood)
        formats = [
            "%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%Y/%m/%d",
            "%d/%m/%y", "%d-%m-%y", "%m/%d/%Y", "%m-%d-%Y",
            "%m/%d/%y", "%m-%d-%y", "%d %b %Y", "%d %B %Y",
        ]
        
        for fmt in formats:
            try:
                dt = datetime.strptime(date_str, fmt)
                return dt.strftime("%Y-%m-%d")
            except ValueError:
                continue
        
        return None
    
    def _parse_amount(self, amount_str: str) -> Optional[float]:
        """Parse amount string to float. Optimized for performance."""
        if not amount_str or not isinstance(amount_str, str):
            return None
        
        amount_str = amount_str.strip()
        
        # Fast return for common null values
        if amount_str in ("na", "n/a", "null", "-", ""):
            return None
        
        # Remove currency symbols and whitespace using cached regex
        amount_str = _REGEX_CACHE['currency'].sub('', amount_str)
        
        # Remove commas in one pass
        amount_str = amount_str.replace(',', '').strip()
        
        # Fast validation
        if not amount_str:
            return None
        
        try:
            val = float(amount_str)
            return val if val > 0 else None
        except ValueError:
            return None
    
    def _deduplicate_transactions(self, transactions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Remove duplicate transactions efficiently using reference or signature."""
        seen = set()
        unique = []
        
        for tx in transactions:
            # Prefer reference if available (more reliable)
            ref = tx.get("reference")
            if ref:
                sig = (tx.get("date"), ref)
            else:
                # Fallback to (date + amount + description prefix)
                sig = (tx.get("date"), tx.get("amount"), tx.get("description", "")[:20])
            
            if sig not in seen:
                seen.add(sig)
                unique.append(tx)
        
        return unique


def extract_bank_statement_pdf(pdf_path: str, cleanup: bool = True) -> Tuple[StatementMetadata, List[Dict[str, Any]]]:
    """
    Main entry point: Extract bank statement from PDF.
    
    Args:
        pdf_path: Path to the PDF file
        cleanup: Whether to delete the PDF file after extraction (default True)
    
    Returns:
        (metadata, transactions): Statement metadata and list of transactions
    
    Raises:
        PDFExtractionError: If extraction fails
    """
    pdf = Path(pdf_path)
    
    try:
        extractor = TableExtractor(pdf_path)
        return extractor.extract()
    except PDFExtractionError:
        raise
    finally:
        # Always cleanup, even on success or failure
        if cleanup and pdf.exists():
            try:
                pdf.unlink()
                logger.debug(f"Cleaned up temporary file: {pdf_path}")
            except Exception as e:
                logger.warning(f"Could not delete temporary file {pdf_path}: {e}")
