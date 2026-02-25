"""
Moniepoint Bank Parser
Handles Moniepoint/TeamApt statement formats
"""
import re
from typing import Optional
from .base_parser import BaseBankParser


class MoniepointParser(BaseBankParser):
    """Parser for Moniepoint bank statements."""

    def __init__(self):
        super().__init__()
        self.bank_name = "Moniepoint"

    def get_column_mappings(self) -> dict:
        """Moniepoint column name variations."""
        return {
            "date_aliases": {"date", "value date", "trans date", "transaction date"},
            "desc_aliases": {"narration", "description", "details", "particulars"},
            "debit_aliases": {"debit", "dr", "withdrawal"},
            "credit_aliases": {"credit", "cr", "deposit"},
            "amount_aliases": {"amount", "value"},
            "ref_aliases": {"reference", "ref", "session id"},
            "balance_aliases": {"balance", "balance after"},
            "type_aliases": {"type", "transaction type"},
        }

    def extract_vendor(self, description: str, reference: Optional[str]) -> Optional[str]:
        """
        Extract vendor from Moniepoint description.
        Format: "Transfer to NAME | ref | details"
        """
        if not description:
            return None

        # Moniepoint patterns
        patterns = [
            r"(?:Transfer|Trf)\s+(?:to|TO)\s+([A-Z][A-Za-z0-9\s\.\-]+?)(?:\s+\||$)",
            r"(?:Transfer|Trf)\s+(?:from|FROM)\s+([A-Z][A-Za-z0-9\s\.\-]+?)(?:\s+\||$)",
            r"(?:Payment|Pmt)\s+(?:to|TO)\s+([A-Z][A-Za-z0-9\s\.\-]+?)(?:\s+\||$)",
        ]

        for pattern in patterns:
            m = re.search(pattern, description, re.IGNORECASE)
            if m:
                vendor = m.group(1).strip()
                vendor = re.sub(r"[\s\|]+$", "", vendor)
                if len(vendor) > 2:
                    return vendor

        # Try pipe-separated format
        if "|" in description:
            parts = [p.strip() for p in description.split("|")]
            for part in parts:
                if part and not re.match(r"^\d+$", part) and len(part) > 2:
                    # Check if it looks like a name (not a code)
                    if not re.match(r"^[A-Z]{2,3}\d", part):
                        return part

        return None

    def normalize_description(
        self,
        description: str,
        reference: Optional[str],
        vendor: Optional[str],
        tx_type: str
    ) -> str:
        """Generate clean description for Moniepoint transaction."""
        if description and len(description) > 2:
            return description

        # Empty description - generate from available data
        if vendor:
            return f"{'Received from' if tx_type == 'credit' else 'Payment to'} {vendor}"

        if reference and "|" in reference:
            # Extract meaningful part from pipe-separated reference
            parts = [p.strip() for p in reference.split("|")]
            non_numeric = [p for p in parts if p and not re.match(r"^\d+$", p)]
            if non_numeric:
                return non_numeric[0]

        return "Credit transaction" if tx_type == "credit" else "Debit transaction"

    def is_moniepoint_reference(self, reference: Optional[str]) -> bool:
        """Check if reference has Moniepoint-style suffix."""
        if not reference:
            return False
        return bool(re.search(r"_(?:CREDIT|DEBIT)_\d+$", reference, re.IGNORECASE))

    def determine_transaction_type(
        self,
        reference: Optional[str],
        debit_amount: float,
        credit_amount: float
    ) -> tuple[str, float]:
        """
        Determine transaction type from Moniepoint reference suffix.
        Returns: (tx_type, amount)
        """
        # Moniepoint reference suffix is most reliable
        if reference and "_CREDIT_" in reference.upper():
            return "credit", credit_amount if credit_amount > 0 else debit_amount
        elif reference and "_DEBIT_" in reference.upper():
            return "debit", debit_amount if debit_amount > 0 else credit_amount

        # Fall back to amount columns
        if credit_amount > 0 and debit_amount == 0:
            return "credit", credit_amount
        elif debit_amount > 0 and credit_amount == 0:
            return "debit", debit_amount
        elif credit_amount > 0:
            return "credit", credit_amount
        else:
            return "debit", debit_amount
