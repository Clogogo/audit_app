"""
Generic Bank Parser
Fallback parser for all Nigerian banks (Access, GTBank, UBA, Zenith, etc.)
"""
import re
from typing import Optional
from .base_parser import BaseBankParser


class GenericParser(BaseBankParser):
    """
    Generic parser for Nigerian bank statements.
    Works with: Access, GTBank, UBA, Zenith, First Bank, Fidelity, Union, Stanbic, etc.
    """

    def __init__(self, bank_name: str = "Unknown"):
        super().__init__()
        self.bank_name = bank_name

    def get_column_mappings(self) -> dict:
        """
        Comprehensive column name variations covering all Nigerian banks.
        """
        return {
            "date_aliases": {
                "date", "trans date", "transaction date", "value date", "txn date",
                "posting date", "booking date", "settlement date", "created at",
                "trans. date", "txndate",
            },
            "desc_aliases": {
                "narration", "description", "memo", "details", "particulars",
                "remarks", "narrative", "trans desc", "payment details",
                "transaction description", "payment narration", "beneficiary",
                "narr", "desc", "naration", "narrations",  # typos
                "transaction details", "txn details", "payment description",
                "purpose", "transaction narration",
            },
            "debit_aliases": {
                "debit", "debit(₦)", "debit(ngn)", "dr", "dr amount",
                "withdrawal", "withdrawals", "amount out", "paid out", "money out",
                "charges",
            },
            "credit_aliases": {
                "credit", "credit(₦)", "credit(ngn)", "cr", "cr amount",
                "deposit", "deposits", "amount in", "paid in", "money in",
                "receipts",
            },
            "amount_aliases": {
                "amount", "transaction amount", "txn amount", "net amount",
                "debit/credit", "value",
            },
            "ref_aliases": {
                "reference", "ref", "transaction ref", "txn ref",
                "transaction id", "txn id", "trace no", "receipt no",
                "session id",
            },
            "balance_aliases": {
                "balance", "running balance", "ledger balance", "available balance",
                "bal", "closing balance", "balance after", "bal. after",
                "wallet balance", "account balance",
            },
            "type_aliases": {
                "type", "transaction type", "txn type", "dr/cr", "cr/dr",
                "direction", "flow", "transaction nature", "trans type",
            },
        }

    def extract_vendor(self, description: str, reference: Optional[str]) -> Optional[str]:
        """Extract vendor from description using common Nigerian bank formats."""
        if not description:
            return None

        # Common Nigerian bank patterns
        patterns = [
            r"(?:Transfer|Trf|TRF|Trfr|Tfr)\s+(?:to|TO)\s+([A-Z][A-Za-z0-9\s\.\-]+?)(?:\s+\||$)",
            r"(?:Payment|Pmt|PMT)\s+(?:to|TO)\s+([A-Z][A-Za-z0-9\s\.\-]+?)(?:\s+\||$)",
            r"(?:Transfer|Trf|TRF|Trfr|Tfr)\s+(?:from|FROM|frm|FRM)\s+([A-Z][A-Za-z0-9\s\.\-]+?)(?:\s+\||$)",
            r"(?:Received|Rcvd|RCV|Rcv)\s+(?:from|FROM|frm|FRM)\s+([A-Z][A-Za-z0-9\s\.\-]+?)(?:\s+\||$)",
            # Pipe-separated format
            r"(?:Transfer|Trf)\s+(?:to|from)\s+([^|]+)\|",
        ]

        for pattern in patterns:
            m = re.search(pattern, description, re.IGNORECASE)
            if m:
                vendor = m.group(1).strip()
                vendor = re.sub(r"[\s\|]+$", "", vendor).strip()
                vendor = re.sub(r"\s{2,}", " ", vendor)
                if len(vendor) > 2:
                    return vendor

        # Extract from pipe-separated descriptions
        if "|" in description:
            parts = [p.strip() for p in description.split("|")]
            for part in parts:
                if part and not re.match(r"^\d+$", part) and len(part) > 2:
                    return part

        return None

    def normalize_description(
        self,
        description: str,
        reference: Optional[str],
        vendor: Optional[str],
        tx_type: str
    ) -> str:
        """Generate clean description for generic bank transaction."""
        if description and len(description) > 2:
            return description

        # Generate from available data
        if vendor:
            return f"{'Received from' if tx_type == 'credit' else 'Payment to'} {vendor}"

        if reference and "|" in reference:
            parts = [p.strip() for p in reference.split("|")]
            non_numeric = [p for p in parts if p and not re.match(r"^\d+$", p)]
            if non_numeric:
                return non_numeric[0]

        if reference:
            return reference

        return "Credit transaction" if tx_type == "credit" else "Debit transaction"
