"""
Statement Parsing Configuration
Contains all column aliases and constants used for parsing bank statements.
"""
import re
from typing import Optional

# ── Known column aliases ───────────────────────────────────────────────────────

DATE_ALIASES = {
    "date", "trans date", "transaction date", "value date", "txn date",
    "posting date", "booking date", "settlement date", "created at",
    "trans. date", "txndate",
}

# Value Date (settlement / effective date) is preferred over posting/transaction date
# when both columns are present — it captures when the balance actually moved.
VALUE_DATE_ALIASES = {"value date", "val date", "value dt", "settlement date"}

# Priority: prefer detailed columns over generic single-word fields like "beneficiary"
# Narration usually contains full transaction details, while beneficiary is just a name
DESC_PRIORITY_ALIASES = {
    "transaction details", "payment details", "txn details",
    "description", "transaction description", "payment description",
    "details", "particulars",
    "narration", "payment narration", "transaction narration",
}

DESC_ALIASES = {
    "transaction details", "payment details", "txn details",
    "description", "transaction description", "payment description",
    "details", "particulars", "remarks", "memo", "purpose",
    "trans desc", "beneficiary", "narrative",
    "narration", "payment narration", "transaction narration",
    "narr", "desc", "naration", "narrations",
}

DEBIT_ALIASES = {
    "debit", "debit(₦)", "debit(ngn)", "dr", "dr amount",
    "withdrawal", "withdrawals", "amount out", "paid out", "money out",
    "charges",
}

CREDIT_ALIASES = {
    "credit", "credit(₦)", "credit(ngn)", "cr", "cr amount",
    "deposit", "deposits", "amount in", "paid in", "money in",
    "receipts",
}

AMOUNT_ALIASES = {
    "amount", "transaction amount", "txn amount", "net amount",
    "debit/credit", "value",
}

REF_ALIASES = {
    "reference", "ref", "transaction ref", "txn ref",
    "transaction id", "txn id", "trace no", "receipt no",
    "session id",
}

BALANCE_ALIASES = {
    "balance", "running balance", "ledger balance", "available balance",
    "bal", "closing balance",
    # OPay / mobile-banking variants
    "balance after", "bal. after", "wallet balance", "account balance",
    "balance b/f", "balance c/f", "outstanding balance",
}

# OPay and some other banks have a dedicated direction column
TYPE_ALIASES = {
    "type", "transaction type", "txn type", "dr/cr", "cr/dr",
    "direction", "flow", "transaction nature", "trans type",
}

# Rows whose description matches this pattern are section headers, not transactions
SEPARATOR_RE = re.compile(r'^-{2,}|^={2,}|^-//', re.IGNORECASE)

# Values in the date cell that mean the row is still a header
HEADER_CELL_VALUES = {
    "date", "trans date", "value date", "transaction date", "txn date",
    "posting date",
}

# PDF date pattern for transaction extraction
DATE_PATTERN = (
    r"(?:"
    # ISO datetime: 2026-01-02T18:35:21 or 2026-01-02T18:\n35:21
    r"\d{4}-\d{2}-\d{2}T\d{2}:[\n\r]?\d{2}"
    r"|"
    r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}"
    r"|"
    r"\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{2,4}"
    r")"
)


# ── Helper Functions ──────────────────────────────────────────────────────────

def find_column(columns: list[str], aliases: set[str], priority_aliases: Optional[set[str]] = None) -> Optional[str]:
    """
    Return the first column name that matches any alias (case-insensitive).
    If priority_aliases is provided, check those first.
    """
    # First pass: check priority aliases
    if priority_aliases:
        for col in columns:
            norm = col.lower().strip()
            if norm in priority_aliases:
                return col
            # Also check if any priority alias is a substring of the column name
            if any(a in norm for a in priority_aliases if len(a) > 3):
                return col
    
    # Second pass: check all aliases
    for col in columns:
        norm = col.lower().strip()
        if norm in aliases:
            return col
        # Also check if any alias is a substring of the column name
        if any(a in norm for a in aliases if len(a) > 3):
            return col
    return None


def parse_amount(val: object) -> float:
    """
    Robustly parse bank amount strings:
      '10,000.00'  → 10000.0
      '(1,234.56)' → 1234.56   (debit notation)
      '₦50,000'    → 50000.0
      '500.00 DR'  → 500.0
      '--' / ''    → 0.0
      NaN / 'nan'  → 0.0
    """
    s = str(val or "").strip()
    if not s or s.lower() in ("nan", "--", "-", "—", "N/A", "n/a", "nil", ""):
        return 0.0
    s = re.sub(r"[₦$€£¥\s]", "", s)
    s = s.replace(",", "")
    s = re.sub(r"\s*(DR|DB|CR|Cr|Dr)$", "", s, flags=re.IGNORECASE)
    if s.startswith("(") and s.endswith(")"):
        s = s[1:-1]
    try:
        result = float(s)
        # Check if result is NaN and return 0 instead
        if result != result:  # NaN is not equal to itself
            return 0.0
        return abs(result)
    except ValueError:
        return 0.0


def infer_direction(description: str) -> str:
    """Heuristically decide debit vs credit from description keywords."""
    desc = description.lower()
    credit_score = sum(1 for k in (
        "transfer from", "received from", "credit", "deposit", "inflow",
        "reversal", "refund", "salary", "lodgment", "direct credit",
        "payment received",
    ) if k in desc)
    debit_score = sum(1 for k in (
        "transfer to", "payment to", "debit", "withdrawal", "pos", "atm",
        "charges", "fee", "purchase", "airtime", "standing order",
        "direct debit",
    ) if k in desc)
    return "credit" if credit_score > debit_score else "debit"


def clean_columns(df) -> 'DataFrame':
    """Clean and normalize DataFrame column names."""
    import pandas as pd
    df = df.copy()
    new_cols = []
    for c in df.columns:
        s = str(c).strip().lower()
        # Replace internal whitespace/punctuation with single space
        s = re.sub(r"\s+", " ", s)
        s = re.sub(r"[,;:\._]+", " ", s)
        s = s.strip(" -")
        new_cols.append(s)
    df.columns = new_cols
    return df
