"""
Base Parser - Common parsing logic for all banks
"""
import re
from abc import ABC, abstractmethod
from datetime import date
from typing import Optional
import pandas as pd


class BaseBankParser(ABC):
    """Base class for bank-specific parsers."""

    def __init__(self):
        self.bank_name = "Unknown"

    @abstractmethod
    def get_column_mappings(self) -> dict:
        """
        Return bank-specific column name mappings.

        Returns:
            dict with keys: date_col, desc_col, debit_col, credit_col,
            amount_col, ref_col, balance_col, type_col
        """
        pass

    @abstractmethod
    def extract_vendor(self, description: str, reference: Optional[str]) -> Optional[str]:
        """Extract vendor/recipient name from description or reference."""
        pass

    @abstractmethod
    def normalize_description(
        self,
        description: str,
        reference: Optional[str],
        vendor: Optional[str],
        tx_type: str
    ) -> str:
        """Generate clean description from available data."""
        pass

    def parse_amount(self, val: object) -> float:
        """
        Parse amount from various formats.
        '10,000.00'  → 10000.0
        '(1,234.56)' → 1234.56   (debit notation)
        '₦50,000'    → 50000.0
        """
        s = str(val or "").strip()
        if not s or s in ("--", "-", "—", "N/A", "n/a", "nil", ""):
            return 0.0
        s = re.sub(r"[₦$€£¥\s]", "", s)
        s = s.replace(",", "")
        s = re.sub(r"\s*(DR|DB|CR|Cr|Dr)$", "", s, flags=re.IGNORECASE)
        if s.startswith("(") and s.endswith(")"):
            s = s[1:-1]
        try:
            return abs(float(s))
        except ValueError:
            return 0.0

    def parse_date(self, raw_date) -> Optional[date]:
        """Parse date from various formats."""
        if raw_date is None or (isinstance(raw_date, float) and pd.isna(raw_date)):
            return None

        raw_date_str = re.sub(r"[\r\n]+", "", str(raw_date)).strip()

        # ISO format (year-first)
        if re.match(r"\d{4}[-/]", raw_date_str):
            tx_date = pd.to_datetime(raw_date_str, dayfirst=False, errors="coerce")
        else:
            tx_date = pd.to_datetime(raw_date_str, dayfirst=True, errors="coerce")

        if pd.isna(tx_date):
            # Try extracting just the date part
            m = re.match(r"(\d{4}-\d{1,2}-\d{1,2})", raw_date_str)
            if m:
                tx_date = pd.to_datetime(m.group(1), dayfirst=False, errors="coerce")

        return tx_date.date() if not pd.isna(tx_date) else None

    def clean_text(self, text: str) -> str:
        """Clean multi-line text and extra spaces."""
        if not text:
            return ""
        text = re.sub(r"[\r\n]+", " ", text)
        text = re.sub(r"\s{2,}", " ", text)
        return text.strip()
