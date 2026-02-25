"""
OPay Bank Parser
Handles OPay/Opera Pay statement formats
"""
import re
from typing import Optional
from .base_parser import BaseBankParser


class OPayParser(BaseBankParser):
    """Parser for OPay bank statements."""

    def __init__(self):
        super().__init__()
        self.bank_name = "OPay"

    def get_column_mappings(self) -> dict:
        """OPay column name variations."""
        return {
            "date_aliases": {"date", "value date", "transaction date", "trans date"},
            "desc_aliases": {"narration", "description", "memo", "details"},
            "debit_aliases": {"debit", "money out", "paid out"},
            "credit_aliases": {"credit", "money in", "paid in"},
            "amount_aliases": {"amount", "value"},
            "ref_aliases": {"reference", "transaction id", "txn id"},
            "balance_aliases": {"wallet balance", "balance", "balance after"},
            "type_aliases": {"type", "direction"},
        }

    def extract_vendor(self, description: str, reference: Optional[str]) -> Optional[str]:
        """Extract vendor from OPay description."""
        if not description:
            return None

        # OPay-specific patterns
        patterns = [
            r"(?:Transfer|Trf)\s+(?:to|TO)\s+([A-Z][A-Za-z0-9\s\.\-]+?)(?:\s+\||$)",
            r"(?:Transfer|Trf)\s+(?:from|FROM)\s+([A-Z][A-Za-z0-9\s\.\-]+?)(?:\s+\||$)",
            r"(?:Payment|Pmt)\s+(?:to|TO)\s+([A-Z][A-Za-z0-9\s\.\-]+?)(?:\s+\||$)",
            r"(?:Received)\s+(?:from|FROM)\s+([A-Z][A-Za-z0-9\s\.\-]+?)(?:\s+\||$)",
        ]

        for pattern in patterns:
            m = re.search(pattern, description, re.IGNORECASE)
            if m:
                vendor = m.group(1).strip()
                vendor = re.sub(r"[\s\|]+$", "", vendor)
                if len(vendor) > 2:
                    return vendor

        # Check for OWealth transfers (internal)
        if "owealth" in description.lower():
            return "OWealth"

        return None

    def normalize_description(
        self,
        description: str,
        reference: Optional[str],
        vendor: Optional[str],
        tx_type: str
    ) -> str:
        """Generate clean description for OPay transaction."""
        # OPay uses single-letter codes sometimes (e.g., "T" for Transfer)
        if len(description) <= 2:
            if vendor:
                return f"{'Received from' if tx_type == 'credit' else 'Payment to'} {vendor}"
            if reference:
                return f"{description}: {reference}" if description else reference
            return "Credit transaction" if tx_type == "credit" else "Debit transaction"

        if description:
            return description

        # Generate from available data
        if vendor:
            return f"{'Received from' if tx_type == 'credit' else 'Payment to'} {vendor}"

        return "Credit transaction" if tx_type == "credit" else "Debit transaction"

    def is_owealth_transaction(self, description: str) -> bool:
        """Check if transaction is OWealth (savings) related."""
        if not description:
            return False
        desc_lower = description.lower()
        return any(keyword in desc_lower for keyword in [
            "owealth",
            "auto-save to owealth",
            "auto save to owealth",
            "owealth withdrawal",
            "owealth balance",
        ])
