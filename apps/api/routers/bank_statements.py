"""
Bank statement import: CSV, Excel, PDF
Clean, reliable parser targeting Nigerian bank formats (Moniepoint, OPay, Access, GTBank, etc.)
"""
import io
import json
import logging
import re
import uuid
import zipfile
from datetime import date
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from database import get_db
from models import BankStatement, BankTransaction, Transaction, AuditLog
from schemas import (
    BankStatementOut, BankTransactionOut,
    StatementImportItem, StatementImportRequest, StatementImportResult, TransactionOut,
)
import ai_worker

router = APIRouter(prefix="/bank-statements", tags=["bank-statements"])

BASE_DIR = Path(__file__).parent.parent.parent.parent
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)


# ── Known column aliases ───────────────────────────────────────────────────────

_DATE_ALIASES   = {
    "date", "trans date", "transaction date", "value date", "txn date",
    "posting date", "booking date", "settlement date", "created at",
    "trans. date", "txndate",
}
# Value Date (settlement / effective date) is preferred over posting/transaction date
# when both columns are present — it captures when the balance actually moved.
_VALUE_DATE_ALIASES = {"value date", "val date", "value dt", "settlement date"}
_DESC_ALIASES   = {
    "narration", "description", "memo", "details", "particulars",
    "remarks", "narrative", "trans desc", "payment details",
    "transaction description", "payment narration", "beneficiary",
    "narr", "desc",
}
_DEBIT_ALIASES  = {
    "debit", "debit(₦)", "debit(ngn)", "dr", "dr amount",
    "withdrawal", "withdrawals", "amount out", "paid out", "money out",
    "charges",
}
_CREDIT_ALIASES = {
    "credit", "credit(₦)", "credit(ngn)", "cr", "cr amount",
    "deposit", "deposits", "amount in", "paid in", "money in",
    "receipts",
}
_AMOUNT_ALIASES = {
    "amount", "transaction amount", "txn amount", "net amount",
    "debit/credit", "value",
}
_REF_ALIASES    = {
    "reference", "ref", "transaction ref", "txn ref",
    "transaction id", "txn id", "trace no", "receipt no",
    "session id",
}
_BALANCE_ALIASES = {
    "balance", "running balance", "ledger balance", "available balance",
    "bal", "closing balance",
    # OPay / mobile-banking variants
    "balance after", "bal. after", "wallet balance", "account balance",
    "balance b/f", "balance c/f", "outstanding balance",
}
# OPay and some other banks have a dedicated direction column
_TYPE_ALIASES = {
    "type", "transaction type", "txn type", "dr/cr", "cr/dr",
    "direction", "flow", "transaction nature", "trans type",
}

# Rows whose description matches this pattern are section headers, not transactions
_SEPARATOR_RE = re.compile(r'^-{2,}|^={2,}|^-//', re.IGNORECASE)

# Values in the date cell that mean the row is still a header
_HEADER_CELL_VALUES = {
    "date", "trans date", "value date", "transaction date", "txn date",
    "posting date",
}


def _find_col(columns: list[str], aliases: set[str]) -> Optional[str]:
    """Return the first column name that matches any alias (case-insensitive)."""
    for col in columns:
        norm = col.lower().strip()
        if norm in aliases:
            return col
        # Also check if any alias is a substring of the column name
        if any(a in norm for a in aliases if len(a) > 3):
            return col
    return None


# ── Amount parsing ────────────────────────────────────────────────────────────

def _parse_amount(val: object) -> float:
    """
    Robustly parse bank amount strings:
      '10,000.00'  → 10000.0
      '(1,234.56)' → 1234.56   (debit notation)
      '₦50,000'    → 50000.0
      '500.00 DR'  → 500.0
      '--' / ''    → 0.0
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


def _infer_direction(description: str) -> str:
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


# ── Smart category / type suggestion ─────────────────────────────────────────
#
# Two-tier approach:
#   1. Instant keyword rules (covers ~85 % of Nigerian bank statement rows)
#   2. AI batch call for anything that lands on "Other"
#
# The keyword table maps category → list of substrings to look for in the
# transaction description (case-insensitive).  Order matters — the FIRST match
# in the list wins.  Transfer and income patterns are checked before expense
# patterns so a "salary" credit is never mis-classified as an expense.

_TRANSFER_KEYWORDS = [
    "auto-save to owealth", "auto save to owealth",
    "owealth withdrawal", "owealth balance",
    "own account transfer", "own-account transfer",
    "inter-account", "internal transfer", "self transfer",
    "wallet to wallet", "wallet transfer",
]

# (category, forced_type) pairs — checked first for income-only categories
_INCOME_KEYWORD_MAP: list[tuple[str, list[str]]] = [
    ("Salary",     ["salary", "salaries", "payroll", "monthly pay", "remuneration",
                    "staff pay", "wages", "pay day"]),
    ("Investment", ["interest earn", "owealth interest", "investment income", "dividend",
                    "fixed deposit return", "savings interest", "interest credit",
                    "treasury", "lien release", "yield"]),
    ("Freelance",  ["freelance", "upwork", "fiverr", "gig income", "contract pay"]),
    ("Gift",       ["gift received", "cash gift"]),
    ("Refund",     ["refund", "reversal", "chargeback", "return credit",
                    "clawback reversal"]),
    ("Business",   ["sales proceed", "business income", "revenue credit"]),
]

# Expense/neutral categories (type follows the bank direction — debit=expense, credit=income)
_NEUTRAL_KEYWORD_MAP: list[tuple[str, list[str]]] = [
    ("Food & Dining",       ["restaurant", "eatery", "kitchen", "bakery", "pastry",
                              "fast food", "pizza", "burger", "shawarma", "suya",
                              "indomie", "groceries", "supermarket", "shoprite", "spar",
                              "kfc", "chicken republic", "mr biggs", "domino", "cafe",
                              "coldstone", "ice cream", "food", "canteen", "cafeteria"]),
    ("Transportation",      ["uber", "bolt", "taxify", "transport", "bus fare",
                              "fare", "petrol", "diesel", "fuel station", "car wash",
                              "parking", "toll gate", "logistics", "dispatch", "ride"]),
    ("Shopping",            ["jumia", "konga", "amazon", "aliexpress", "shopping",
                              "purchase", "market", "store", "mall", "clothes",
                              "fashion", "shoes", "bag", "accessories"]),
    ("Bills & Utilities",   ["electricity", "nepa", "phcn", "electric bill",
                              "water bill", "water rate", "dstv", "startimes", "gotv",
                              "cable tv", "internet", "broadband", "wifi", "wi-fi",
                              "airtime", "data subscription", "data purchase",
                              "recharge", "postpaid", "prepaid", "utility", "gas bill",
                              "power bill", "mtn", "airtel", "glo", "9mobile",
                              "etisalat", "subscription"]),
    ("Housing",             ["rent", "landlord", "house rent", "estate",
                              "apartment rent", "mortgage", "property", "agency fee",
                              "caution fee", "agreement fee"]),
    ("Healthcare",          ["hospital", "pharmacy", "chemist", "medicine", "doctor",
                              "clinic", "medical", "drug", "treatment", "lab test",
                              "laboratory", "prescription", "health insurance",
                              "health fee"]),
    ("Education",           ["school fees", "tuition", "school fee", "exam fee",
                              "university", "college", "academy", "course fee",
                              "training fee", "tutorial", "lesson"]),
    ("Travel",              ["hotel", "airbnb", "flight", "airline", "airport",
                              "visa fee", "travel", "booking", "accommodation",
                              "vacation", "holiday"]),
    ("Entertainment",       ["netflix", "spotify", "apple music", "youtube premium",
                              "cinema", "movie ticket", "game", "sport", "gym",
                              "event ticket", "concert"]),
    ("Bank Charges & Fees", ["bank charge", "stamp duty", "sms alert",
                              "card maintenance", "maintenance fee", "commission",
                              "transfer fee", "transaction fee", "service charge",
                              "account maintenance", "atm fee", "pos fee",
                              "interbank fee", "vat on", "withholding"]),
    ("Internal Transfer",   ["auto-save", "owealth", "own account"]),
]


def _suggest_category_keyword(description: str, tx_type: str) -> tuple[str, str]:
    """
    Return (category, suggested_type) using keyword rules.

    Priority:
      1. Transfer patterns → ("Internal Transfer", "transfer")
      2. Income-specific patterns → (category, "income")
      3. Neutral patterns → (category, "income" if credit else "expense")
      4. Fall-through → ("Other", "income" if credit else "expense")
    """
    desc = description.lower()
    default_type = "income" if tx_type == "credit" else "expense"

    # 1. Transfer
    if any(p in desc for p in _TRANSFER_KEYWORDS):
        return "Internal Transfer", "transfer"

    # 2. Income-only categories
    for cat, patterns in _INCOME_KEYWORD_MAP:
        if any(p in desc for p in patterns):
            return cat, "income"

    # 3. Neutral categories
    for cat, patterns in _NEUTRAL_KEYWORD_MAP:
        if any(p in desc for p in patterns):
            return cat, default_type

    return "Other", default_type


def _ai_suggest_categories_batch(rows: list[dict]) -> list[dict]:
    """
    For rows whose keyword-based category is still "Other", ask the AI to
    suggest a category and type in a single batch request.

    Returns the same rows list with 'suggested_category' and 'suggested_type'
    updated where the AI provided a confident answer.
    Falls back silently on any AI failure.
    """
    import httpx

    # Only send rows where we don't already have a specific category
    undecided_idx = [
        i for i, r in enumerate(rows) if r.get("suggested_category") == "Other"
    ]
    if not undecided_idx:
        return rows

    items = [
        {"i": i, "desc": rows[i]["description"], "dir": rows[i]["transaction_type"]}
        for i in undecided_idx
    ]

    prompt = (
        "You are a Nigerian bank statement categorizer.\n"
        "For each transaction below, return ONLY a JSON array with objects:\n"
        '  {"i": <index>, "category": "<category>", "type": "<expense|income|transfer>"}\n\n'
        "Valid categories: Food & Dining, Transportation, Shopping, Entertainment, "
        "Bills & Utilities, Healthcare, Travel, Education, Housing, Salary, Freelance, "
        "Investment, Business, Bank Charges & Fees, Internal Transfer, Refund, Gift, Other\n\n"
        "Rules:\n"
        "- 'salary', 'payroll' → Salary / income\n"
        "- 'electricity', 'nepa', 'dstv', 'airtime', 'internet' → Bills & Utilities / expense\n"
        "- 'uber', 'fuel', 'petrol', 'bolt', 'fare' → Transportation / expense\n"
        "- 'auto-save', 'owealth', 'own account' → Internal Transfer / transfer\n"
        "- 'refund', 'reversal' → Refund / income\n"
        "- 'bank charge', 'stamp duty', 'commission' → Bank Charges & Fees / expense\n"
        "- Debits (dir=debit) are usually expenses; credits (dir=credit) are usually income\n"
        "- Only extract data visible in the description. Do NOT guess.\n\n"
        "Transactions:\n"
        + json.dumps(items, ensure_ascii=False)
        + "\n\nReturn JSON array only, no explanation:"
    )

    try:
        raw = ai_worker._call_ai_text(prompt)
        raw = ai_worker._clean_json(raw)
        arr_match = re.search(r"\[[\s\S]*\]", raw)
        if not arr_match:
            return rows
        suggestions = json.loads(arr_match.group())
        for s in suggestions:
            idx = int(s.get("i", -1))
            if 0 <= idx < len(rows):
                cat = str(s.get("category", "Other")).strip()
                typ = str(s.get("type", "")).strip().lower()
                if cat and cat != "Other":
                    rows[idx]["suggested_category"] = cat
                if typ in ("expense", "income", "transfer"):
                    rows[idx]["suggested_type"] = typ
    except Exception as e:
        logger.warning(f"AI batch categorization failed: {e}")

    return rows


# ── Core normalizer ───────────────────────────────────────────────────────────

def _normalize_df(df: pd.DataFrame) -> list[dict]:
    """
    Map DataFrame columns to roles by name, then extract transactions row by row.
    Handles Moniepoint, OPay, Access Bank, GTBank, and similar CSV/Excel formats.

    Structured parsing rules:
    1. Prefer "Value Date" (settlement date) over "Trans. Date" when both are present —
       it captures when the balance actually moved.
    2. Use the "Balance After" column to verify direction: if the balance drops after
       this row the money went out (debit); if it rises, money came in (credit).
    3. Pure-digit strings (≥10 digits, no letters) in the narration column are
       reference/session IDs — preserve them in the reference field but do not use
       them as the human-readable description.
    4. Moniepoint _CREDIT_N / _DEBIT_N reference suffixes are the most reliable
       direction signal and override everything else.
    """
    if df.empty:
        return []

    cols = list(df.columns)

    # ── 1. Prefer Value Date (settlement date) when available ─────────────────
    value_date_col = _find_col(cols, _VALUE_DATE_ALIASES)
    date_col       = value_date_col or _find_col(cols, _DATE_ALIASES)

    desc_col    = _find_col(cols, _DESC_ALIASES)
    debit_col   = _find_col(cols, _DEBIT_ALIASES)
    credit_col  = _find_col(cols, _CREDIT_ALIASES)
    amount_col  = _find_col(cols, _AMOUNT_ALIASES)
    ref_col     = _find_col(cols, _REF_ALIASES)
    balance_col = _find_col(cols, _BALANCE_ALIASES)
    type_col    = _find_col(cols, _TYPE_ALIASES)

    # Don't treat the type column as debit/credit/amount
    for _tc in (debit_col, credit_col, amount_col):
        if _tc and type_col and _tc == type_col:
            type_col = None
            break

    # Never treat the balance/running-balance column as debit or credit
    if balance_col:
        if debit_col == balance_col:
            debit_col = None
        if credit_col == balance_col:
            credit_col = None
        if amount_col == balance_col:
            amount_col = None

    if value_date_col:
        logger.info(
            f"Column map → date={value_date_col!r} (value date), desc={desc_col!r}, "
            f"debit={debit_col!r}, credit={credit_col!r}, "
            f"amount={amount_col!r}, ref={ref_col!r}, balance={balance_col!r}"
        )
    else:
        logger.info(
            f"Column map → date={date_col!r}, desc={desc_col!r}, "
            f"debit={debit_col!r}, credit={credit_col!r}, "
            f"amount={amount_col!r}, ref={ref_col!r}, balance={balance_col!r}"
        )

    if not date_col:
        logger.warning("No date column identified — skipping DataFrame")
        return []

    # ── 2. Track running balance for direction verification ───────────────────
    prev_balance: Optional[float] = None

    rows: list[dict] = []

    for _, row in df.iterrows():
        try:
            # ── Date ──────────────────────────────────────────────────
            raw_date = row.get(date_col)
            if raw_date is None or (isinstance(raw_date, float) and pd.isna(raw_date)):
                continue
            # Normalize multi-line PDF cells like "2026-01-02T18:\n35:21"
            raw_date_str = re.sub(r"[\r\n]+", "", str(raw_date)).strip()
            # Skip rows where the date cell still contains a header value
            if raw_date_str.lower() in _HEADER_CELL_VALUES:
                continue
            # For ISO/YYYY-MM-DD dates (year-first), dayfirst=True incorrectly swaps month/day.
            # Use dayfirst=False for year-first formats; dayfirst=True only for DD/MM/YYYY.
            if re.match(r"\d{4}[-/]", raw_date_str):
                tx_date = pd.to_datetime(raw_date_str, dayfirst=False, errors="coerce")
            else:
                tx_date = pd.to_datetime(raw_date_str, dayfirst=True, errors="coerce")
            if pd.isna(tx_date):
                # Try extracting just the date part (handles "2026-01-02T18:35:21")
                m = re.match(r"(\d{4}-\d{1,2}-\d{1,2})", raw_date_str)
                if m:
                    tx_date = pd.to_datetime(m.group(1), dayfirst=False, errors="coerce")
            if pd.isna(tx_date):
                continue

            # ── Description ───────────────────────────────────────────
            description = str(row.get(desc_col, "") or "").strip() if desc_col else ""
            
            # Clean up multi-line descriptions (PDF artifacts)
            description = re.sub(r"[\r\n]+", " ", description).strip()

            # Skip section headers / separator rows (e.g. "-// Debits", "---")
            if _SEPARATOR_RE.match(description):
                continue

            # ── Reference & Vendor Extraction ─────────────────────────
            # Parse reference early so we can fall back on it for pure-digit descriptions
            reference: Optional[str] = None
            vendor_name: Optional[str] = None
            
            if ref_col:
                raw_ref = str(row.get(ref_col, "") or "").strip()
                # Collapse multi-line reference cells (PDF extraction artefact)
                reference = re.sub(r"[\r\n]+", " ", raw_ref).strip() or None
            
            # Extract vendor/recipient from description patterns:
            # "Transfer to JOHN DOE" → vendor: "JOHN DOE"
            # "Payment to SHOPRITE" → vendor: "SHOPRITE"  
            # "Transfer from MARY JANE" → vendor: "MARY JANE"
            vendor_patterns = [
                r"Transfer\s+to\s+([A-Z][A-Z\s]+?)(?:\s+\||$)",
                r"Payment\s+to\s+([A-Z][A-Z\s]+?)(?:\s+\||$)",
                r"Transfer\s+from\s+([A-Z][A-Z\s]+?)(?:\s+\||$)",
                r"Received\s+from\s+([A-Z][A-Z\s]+?)(?:\s+\||$)",
            ]
            for pattern in vendor_patterns:
                m = re.search(pattern, description, re.IGNORECASE)
                if m:
                    vendor_name = m.group(1).strip()
                    # Remove trailing incomplete words (artifacts from truncation)
                    vendor_name = re.sub(r"\s+[A-Z]$", "", vendor_name).strip()
                    break
            
            # Extract embedded references from pipe-separated descriptions:
            # "Electricity | 14201290534 | caprico" → extract "14201290534" as reference
            if "|" in description and not reference:
                parts = [p.strip() for p in description.split("|")]
                for part in parts:
                    # Look for reference-like patterns (numbers, alphanumeric codes)
                    if re.match(r"^[A-Za-z]{2,3}\d{4,}", part):  # e.g., "oa8699"
                        reference = part
                        break
                    elif re.match(r"^\d{8,}", part):  # e.g., "14201290534"
                        reference = part
                        break

            # ── 3. Digit-only description cleanup ─────────────────────
            # Narration cells that are purely numeric (≥10 digits, no letters) are
            # session/reference IDs, not human-readable descriptions.
            # Preserve them in the reference field; clear description so it gets a
            # meaningful label later.
            desc_digits_only = bool(re.match(r"^\d[\d\s\-]{9,}$", description))
            if desc_digits_only:
                if not reference:
                    reference = re.sub(r"[\s\-]", "", description)  # compact the digits
                description = ""  # will be populated below

            # ── Amount & direction ────────────────────────────────────
            amount  = 0.0
            tx_type = "debit"

            if debit_col and credit_col:
                debit  = _parse_amount(row.get(debit_col,  0))
                credit = _parse_amount(row.get(credit_col, 0))
                if credit > 0 and debit == 0:
                    amount, tx_type = credit, "credit"
                elif debit > 0 and credit == 0:
                    amount, tx_type = debit, "debit"
                elif credit > 0:
                    amount, tx_type = credit, "credit"
                elif debit > 0:
                    amount, tx_type = debit, "debit"
                else:
                    continue  # Both zero → skip (likely a header or total row)

            elif credit_col and not debit_col:
                credit = _parse_amount(row.get(credit_col, 0))
                if credit <= 0:
                    continue
                amount, tx_type = credit, "credit"

            elif debit_col and not credit_col:
                debit = _parse_amount(row.get(debit_col, 0))
                if debit <= 0:
                    continue
                amount, tx_type = debit, "debit"

            elif amount_col:
                raw_val = str(row.get(amount_col, "") or "").strip()
                val = _parse_amount(raw_val)
                if val == 0:
                    continue
                raw_clean = re.sub(r"[₦$€£,\s]", "", raw_val)
                if re.search(r"CR$", raw_clean, re.IGNORECASE) or raw_clean.startswith("+"):
                    tx_type = "credit"
                elif re.search(r"(DR|DB)$", raw_clean, re.IGNORECASE) or \
                        raw_clean.startswith("-") or raw_clean.startswith("("):
                    tx_type = "debit"
                else:
                    tx_type = _infer_direction(description)
                amount = val

            else:
                continue  # Cannot determine amount

            # ── Override direction from dedicated type column (e.g. OPay) ──
            if type_col:
                type_val = str(row.get(type_col, "") or "").lower().strip()
                if any(k in type_val for k in ("credit", " cr", "money in", "deposit", "inflow", "received")):
                    tx_type = "credit"
                elif any(k in type_val for k in ("debit", " dr", "money out", "withdrawal", "payment", "transfer out", "charge")):
                    tx_type = "debit"

            # ── 2. Balance-after direction verification ────────────────
            # Compare current balance to the previous row's balance.
            # If the balance dropped → debit; if it rose → credit.
            # Only applied when there is no explicit debit/credit column split
            # and no dedicated type column (those are more authoritative).
            if balance_col and not (debit_col and credit_col) and not type_col:
                curr_balance = _parse_amount(row.get(balance_col, 0))
                if curr_balance > 0 and prev_balance is not None and prev_balance > 0:
                    delta = curr_balance - prev_balance
                    # Only override if the balance change is meaningful (> ₦1)
                    if delta < -1.0:
                        tx_type = "debit"
                    elif delta > 1.0:
                        tx_type = "credit"
                if curr_balance > 0:
                    prev_balance = curr_balance
            elif balance_col:
                # Still track balance even when we don't use it for direction
                curr_balance = _parse_amount(row.get(balance_col, 0))
                if curr_balance > 0:
                    prev_balance = curr_balance

            # ── Moniepoint reference suffix overrides direction ────────
            # Moniepoint appends _CREDIT_N or _DEBIT_N to every reference.
            # This is the most reliable signal and overrides everything above.
            if reference:
                if re.search(r"_CREDIT_\d+$", reference, re.IGNORECASE):
                    tx_type = "credit"
                elif re.search(r"_DEBIT_\d+$", reference, re.IGNORECASE):
                    tx_type = "debit"

            # ── Enrich very short / empty descriptions ─────────────────
            # OPay uses single-letter codes like "T" (Transfer) as the narration
            if len(description) <= 2 and reference:
                description = f"{description}: {reference}" if description else reference
            elif not description:
                description = "Credit transaction" if tx_type == "credit" else "Debit transaction"

            # ── Sanity: reject rows where amount == running balance ───────
            # If the parsed amount exactly matches the current running
            # balance it almost certainly means the balance column was
            # mistakenly read as the transaction amount.
            if balance_col:
                curr_bal_check = _parse_amount(row.get(balance_col, 0))
                if curr_bal_check > 0 and abs(amount - curr_bal_check) < 0.02:
                    logger.warning(
                        f"Skipping row: amount {amount} equals running balance "
                        f"{curr_bal_check} — likely balance column mis-read as amount"
                    )
                    continue

            rows.append({
                "date":             tx_date.date(),
                "description":      description,
                "amount":           round(amount, 2),
                "transaction_type": tx_type,
                "reference":        reference,
                "vendor":           vendor_name,  # Extracted recipient/merchant name
            })

        except Exception:
            continue

    return rows


# ── Header row scanner ─────────────────────────────────────────────────────────

def _find_header_row_idx(df: pd.DataFrame) -> Optional[int]:
    """
    Find the first row that looks like a column header.
    Requires at least one date-like keyword AND one amount/narration keyword.
    Uses the same alias sets as _find_col so they are always in sync.
    """
    # Derive from the same alias sets used for column mapping
    date_kws   = _DATE_ALIASES | _VALUE_DATE_ALIASES
    amount_kws = (
        _DEBIT_ALIASES | _CREDIT_ALIASES | _AMOUNT_ALIASES | _DESC_ALIASES
    )
    for idx, row in df.iterrows():
        cells = {
            str(c).lower().strip()
            for c in row
            if c is not None and str(c).strip() not in ("", "nan", "none")
        }
        if cells & date_kws and cells & amount_kws:
            return int(idx)  # type: ignore[arg-type]
    return None


def _clean_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Replace blank/NaN column names with _col_N placeholders."""
    new_cols = []
    for i, c in enumerate(df.columns):
        s = str(c).strip()
        if s.lower() in ("nan", "none", "") or s.startswith("Unnamed"):
            new_cols.append(f"_col_{i}")
        else:
            new_cols.append(s)
    df = df.copy()
    df.columns = new_cols  # type: ignore[assignment]
    return df


def _parse_dataframe(df_raw: pd.DataFrame) -> list[dict]:
    """
    Try to parse with the existing column names.
    If that yields nothing, scan for the actual header row first.
    """
    # Attempt 1: use existing columns
    df = _clean_columns(df_raw)
    rows = _normalize_df(df)
    if rows:
        return rows

    # Attempt 2: find the header row and slice from there
    header_idx = _find_header_row_idx(df_raw)
    if header_idx is None:
        logger.warning("Could not locate a header row in DataFrame")
        return []

    new_df = df_raw.iloc[header_idx + 1:].copy()
    new_df.columns = [str(v) for v in df_raw.iloc[header_idx]]
    new_df = _clean_columns(new_df)
    return _normalize_df(new_df)


# ── File type detection ───────────────────────────────────────────────────────

def _detect_file_type(content_type: str, filename: str) -> str:
    ct = (content_type or "").lower()
    fn = (filename or "").lower()
    if "pdf" in ct or fn.endswith(".pdf"):
        return "pdf"
    if "excel" in ct or "xlsx" in fn or "xls" in fn:
        return "excel"
    return "csv"


# ── XLSX XML patcher ──────────────────────────────────────────────────────────

def _fix_xlsx_xml(contents: bytes) -> bytes:
    """
    Patch invalid XML enum values that openpyxl rejects
    (e.g. vertical="Top" must be vertical="top").
    """
    try:
        buf_in  = io.BytesIO(contents)
        buf_out = io.BytesIO()
        with zipfile.ZipFile(buf_in, "r") as zin, \
             zipfile.ZipFile(buf_out, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                data = zin.read(item.filename)
                if item.filename == "xl/styles.xml":
                    text = data.decode("utf-8", errors="replace")
                    for bad, good in [
                        ('vertical="Top"',      'vertical="top"'),
                        ('vertical="Center"',   'vertical="center"'),
                        ('vertical="Bottom"',   'vertical="bottom"'),
                        ('horizontal="Left"',   'horizontal="left"'),
                        ('horizontal="Center"', 'horizontal="center"'),
                        ('horizontal="Right"',  'horizontal="right"'),
                    ]:
                        text = text.replace(bad, good)
                    data = text.encode("utf-8")
                zout.writestr(item, data)
        return buf_out.getvalue()
    except Exception:
        return contents


# ── CSV parser ────────────────────────────────────────────────────────────────

def _parse_csv(contents: bytes) -> list[dict]:
    """Try multiple encodings and separators."""
    for enc in ("utf-8", "latin-1", "cp1252"):
        for sep in (",", ";", "\t", "|"):
            try:
                df = pd.read_csv(
                    io.BytesIO(contents), encoding=enc,
                    sep=sep, engine="python",
                )
                if len(df.columns) >= 2:
                    rows = _parse_dataframe(df)
                    if rows:
                        logger.info(f"CSV parsed ({enc}, sep={sep!r}): {len(rows)} rows")
                        return rows
            except Exception:
                continue
    return []


# ── Excel parser ──────────────────────────────────────────────────────────────

def _parse_excel(contents: bytes) -> list[dict]:
    contents = _fix_xlsx_xml(contents)
    try:
        xl = pd.ExcelFile(io.BytesIO(contents))
    except Exception as e:
        logger.warning(f"ExcelFile open failed: {e}")
        return []

    for sheet in xl.sheet_names:
        try:
            df_raw = xl.parse(sheet, header=None)
            rows = _parse_dataframe(df_raw)
            if rows:
                logger.info(f"Excel sheet {sheet!r}: {len(rows)} rows")
                return rows
        except Exception as e:
            logger.warning(f"Excel sheet {sheet!r} failed: {e}")
            continue
    return []


# ── PDF parser ────────────────────────────────────────────────────────────────

_DATE_PATTERN = (
    r"(?:"
    # ISO datetime: 2026-01-02T18:35:21 or 2026-01-02T18:\n35:21
    r"\d{4}-\d{2}-\d{2}T\d{2}:[\n\r]?\d{2}"
    r"|"
    r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}"
    r"|"
    r"\d{4}[/-]\d{1,2}[/-]\d{1,2}"
    r"|"
    r"\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{2,4}"
    r"|"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4}"
    r")"
)
_DATE_RE   = re.compile(_DATE_PATTERN, re.IGNORECASE)
_AMOUNT_RE = re.compile(r"(?:[\₦$€£]?\s*[\d,]+(?:\.\d{1,2})?(?:\s*(?:DR|CR|DB))?|--)", re.IGNORECASE)


def _pdf_tables_to_rows(file_path: str) -> list[dict]:
    """
    Extract pdfplumber tables → DataFrames → normalizer.

    Handles two layouts:
      • Standard: multi-row tables with a header row.
      • Moniepoint-style: each transaction is its own 1-row table
        (pdfplumber sees each bordered row as a separate table).
        Layout: Date | Narration | Reference | Debit | Credit | Balance
    """
    import pdfplumber

    all_rows: list[dict] = []
    last_good_columns: Optional[list] = None  # reuse header from previous page

    # Collect Moniepoint-style single-row transaction tables separately
    single_tx_rows: list[list] = []

    _ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")

    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            for table in (page.extract_tables() or []):
                if not table:
                    continue

                # ── Moniepoint style: each tx is its own 1-row table ──────────
                if len(table) == 1 and len(table[0]) >= 4:
                    first_cell = re.sub(r"[\r\n]+", "", str(table[0][0] or "")).strip()
                    if _ISO_DATE_RE.match(first_cell):
                        single_tx_rows.append(table[0])
                        continue

                if len(table) < 2:
                    continue

                try:
                    # Strategy A: first row as header
                    df = pd.DataFrame(table[1:], columns=table[0])
                    rows = _parse_dataframe(df)

                    # Strategy B: treat entire table as data (scan for header inside)
                    if not rows:
                        df2 = pd.DataFrame(table)
                        rows = _parse_dataframe(df2)

                    # Strategy C: continuation page — reuse header from a previous page
                    if not rows and last_good_columns and len(table[0]) == len(last_good_columns):
                        df3 = pd.DataFrame(table, columns=last_good_columns)
                        rows = _parse_dataframe(df3)

                    if rows:
                        last_good_columns = list(table[0])
                        all_rows.extend(rows)
                except Exception:
                    continue

    # ── Assemble Moniepoint single-row tables ──────────────────────────────────
    if single_tx_rows:
        ncols = max(len(r) for r in single_tx_rows)
        # Standard Moniepoint column order: Date Narration Reference Debit Credit Balance
        moniepoint_cols = ["Date", "Narration", "Reference", "Debit", "Credit", "Balance"]
        cols = (moniepoint_cols + [f"_col_{i}" for i in range(len(moniepoint_cols), ncols)])[:ncols]
        df = pd.DataFrame(single_tx_rows, columns=cols)
        rows = _normalize_df(df)
        if rows:
            logger.info(f"Moniepoint single-row tables: {len(rows)} transactions")
            all_rows.extend(rows)

    return all_rows


def _pdf_text_heuristic(file_path: str) -> list[dict]:
    """
    Generic PDF text heuristic: scan each line for a leading date,
    then extract amounts and description from the rest of the line.
    """
    import pdfplumber

    all_lines: list[str] = []
    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            all_lines.extend(text.splitlines())

    rows: list[dict] = []
    for line in all_lines:
        line = line.strip()
        if len(line) < 10:
            continue
        m = _DATE_RE.match(line) or _DATE_RE.search(line[:50])
        if not m:
            continue

        remainder = line[m.end():]

        # ── Skip partial ISO timestamp lines ──────────────────────────
        # Moniepoint PDFs split "2026-01-02T18:35:21" across lines as:
        #   "2026-01-02T18:"  (old date pattern matches "2026-01-02",
        #   remainder = "T18:" → "18" would be misread as an amount)
        # Skip any line whose post-date content is only a time fragment.
        if re.match(r'^T\d{1,2}:[\d:]*\s*$', remainder):
            continue

        try:
            date_str = re.sub(r"[\r\n]+", "", m.group(0)).strip()
            # Use dayfirst=False for year-first (ISO) formats to avoid month/day swap
            if re.match(r"\d{4}[-/]", date_str):
                tx_date = pd.to_datetime(date_str, dayfirst=False, errors="coerce")
            else:
                tx_date = pd.to_datetime(date_str, dayfirst=True, errors="coerce")
            if pd.isna(tx_date):
                # Strip time component (e.g. "2026-01-02T18:35" → "2026-01-02")
                date_only = re.match(r"(\d{4}-\d{2}-\d{2})", date_str)
                if date_only:
                    tx_date = pd.to_datetime(date_only.group(1), dayfirst=False, errors="coerce")
            if pd.isna(tx_date):
                continue
        except Exception:
            continue

        amounts_raw   = _AMOUNT_RE.findall(remainder)
        amounts       = [_parse_amount(a) for a in amounts_raw if _parse_amount(a) > 0]
        if not amounts:
            continue

        # ── Prefer decimal amounts over bare large integers ────────────
        # Reference/session numbers (e.g. "260128992") are large integers
        # with no decimal point and no currency/DR/CR suffix.  Real
        # transaction amounts almost always include a decimal part
        # (e.g. "2.00", "18.00") or an explicit DR/CR suffix.
        # Filter to decimal-only candidates first; fall back to all amounts
        # only if that yields nothing.
        decimal_amounts = [
            _parse_amount(a) for a in amounts_raw
            if _parse_amount(a) > 0 and "." in a
        ]
        amounts = decimal_amounts if decimal_amounts else amounts

        description = _AMOUNT_RE.sub("", remainder)
        description = re.sub(r"\s{2,}", " ", description).strip()
        description = re.sub(r"^[\s|,;:]+|[\s|,;:]+$", "", description)

        tx_type = "debit"
        amount  = amounts[0]
        # Moniepoint reference suffix is the most reliable direction signal
        if re.search(r"_CREDIT_\d+", line, re.IGNORECASE):
            tx_type = "credit"
        elif re.search(r"_DEBIT_\d+", line, re.IGNORECASE):
            tx_type = "debit"
        elif amounts_raw:
            cr = [_parse_amount(a) for a in amounts_raw if re.search(r"CR$", a.strip(), re.IGNORECASE)]
            dr = [_parse_amount(a) for a in amounts_raw if re.search(r"(DR|DB)$", a.strip(), re.IGNORECASE)]
            if cr:
                amount, tx_type = cr[0], "credit"
            elif dr:
                amount, tx_type = dr[0], "debit"
            else:
                tx_type = _infer_direction(description)

        if not description:
            description = "Credit transaction" if tx_type == "credit" else "Debit transaction"

        rows.append({
            "date":             tx_date.date(),
            "description":      description,
            "amount":           round(amount, 2),
            "transaction_type": tx_type,
            "reference":        None,
        })

    return rows


def _pdf_moniepoint_text(file_path: str) -> list[dict]:
    """
    Moniepoint-specific text parser.

    Moniepoint PDFs render each transaction as a split-line block:
        2026-01-05T09:          ← date fragment
        [narration] [ref] [debit] [credit] [balance]   ← data line
        55:32                   ← time continuation

    This parser finds "data lines" (ending with 3 amounts) that contain a
    Moniepoint reference suffix (_CREDIT_N or _DEBIT_N), then walks backward
    through preceding lines to find the transaction date.
    """
    import pdfplumber

    # Data line: ends with three space-separated amounts (debit, credit, balance)
    _DATA_LINE_RE = re.compile(
        r'^(.*?)\s+'
        r'([\d,]+\.\d{2})\s+'   # debit
        r'([\d,]+\.\d{2})\s+'   # credit
        r'([\d,]+\.\d{2})\s*$', # balance
    )
    _REF_SUFFIX_RE = re.compile(r'_(?:CREDIT|DEBIT)_\d+', re.IGNORECASE)
    _ISO_DATE_IN_LINE_RE = re.compile(r'(\d{4}-\d{2}-\d{2})')

    rows: list[dict] = []

    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            lines = (page.extract_text() or "").splitlines()
            stripped = [l.strip() for l in lines]

            for i, line in enumerate(stripped):
                m = _DATA_LINE_RE.match(line)
                if not m:
                    continue
                narr_ref = m.group(1).strip()
                debit    = _parse_amount(m.group(2))
                credit   = _parse_amount(m.group(3))
                # group(4) is the running balance — ignore it

                # Only process Moniepoint-style lines (reference has _CREDIT_N / _DEBIT_N)
                if not _REF_SUFFIX_RE.search(narr_ref):
                    continue

                # Find the nearest date in preceding lines (scan back up to 10 lines)
                tx_date = None
                for j in range(i - 1, max(-1, i - 10), -1):
                    dm = _ISO_DATE_IN_LINE_RE.search(stripped[j])
                    if dm:
                        try:
                            tx_date = date.fromisoformat(dm.group(1))
                        except Exception:
                            pass
                        break

                if tx_date is None:
                    continue

                # Split narration from reference
                ref_m = _REF_SUFFIX_RE.search(narr_ref)
                if ref_m:
                    # Extend backwards to include the full reference token
                    ref_start = narr_ref.rfind(" ", 0, ref_m.start()) + 1
                    reference = narr_ref[ref_start:]
                    narration = narr_ref[:ref_start].strip()
                else:
                    reference, narration = None, narr_ref

                # Direction from reference suffix (most reliable signal)
                ref_upper = (reference or narr_ref).upper()
                if "_CREDIT_" in ref_upper:
                    tx_type = "credit"
                    amount  = credit if credit > 0 else debit
                else:
                    tx_type = "debit"
                    amount  = debit  if debit  > 0 else credit

                if amount <= 0:
                    continue

                if not narration:
                    narration = "Credit transaction" if tx_type == "credit" else "Debit transaction"

                rows.append({
                    "date":             tx_date,
                    "description":      narration,
                    "amount":           round(amount, 2),
                    "transaction_type": tx_type,
                    "reference":        reference,
                })

    return rows


def _dedup_rows(rows: list[dict]) -> list[dict]:
    """
    Remove exact duplicate rows.
    Key: (date, amount, reference) when reference is present (e.g. OPay unique IDs),
    otherwise fall back to (date, amount, description[:60]).
    This prevents collapsing two legitimately different transactions that happen to
    share the same amount and date but have different references.
    """
    seen: set[tuple] = set()
    unique: list[dict] = []
    for r in rows:
        ref = (r.get("reference") or "").strip()
        if ref:
            key: tuple = (r["date"], r["amount"], ref)
        else:
            key = (r["date"], r["amount"], r["description"][:60])
        if key not in seen:
            seen.add(key)
            unique.append(r)
    return unique


def _parse_pdf_statement(file_path: str) -> list[dict]:
    """
    Multi-strategy PDF parser.
    1. Table extraction (pdfplumber tables)
    2. Moniepoint multi-line text extraction (handles 1-row-per-table PDFs where some
       transactions are in bordered cells and others are plain text)
    3. Generic text heuristic fallback
    4. AI chunk-based fallback (last resort)
    """
    table_rows: list[dict] = []
    monie_rows: list[dict] = []
    text_rows:  list[dict] = []

    try:
        table_rows = _pdf_tables_to_rows(file_path)
        logger.info(f"PDF table parser: {len(table_rows)} rows")
    except Exception as e:
        logger.warning(f"PDF table parser failed: {e}")

    try:
        monie_rows = _pdf_moniepoint_text(file_path)
        logger.info(f"PDF Moniepoint text parser: {len(monie_rows)} rows")
    except Exception as e:
        logger.warning(f"PDF Moniepoint text parser failed: {e}")

    # If Moniepoint text parser found transactions, use it as the primary source
    # (it captures ALL transactions including those not in bordered table cells)
    if monie_rows:
        # Merge: Moniepoint text is the base; add any table rows not already covered
        # by (date, amount, tx_type) — this adds any bordered-cell transactions that
        # the text parser might have missed due to multi-line narration obfuscation
        existing = {(r["date"], round(r["amount"], 2), r["transaction_type"]) for r in monie_rows}
        for r in table_rows:
            key = (r["date"], round(r["amount"], 2), r["transaction_type"])
            if key not in existing:
                monie_rows.append(r)
                existing.add(key)
        rows = _dedup_rows(monie_rows)
        logger.info(f"PDF merged (monie+table): {len(rows)} unique rows")
        return rows

    try:
        text_rows = _pdf_text_heuristic(file_path)
        logger.info(f"PDF text heuristic: {len(text_rows)} rows")
    except Exception as e:
        logger.warning(f"PDF text heuristic failed: {e}")

    # Use whichever strategy found more transactions
    if table_rows and text_rows:
        if len(table_rows) >= len(text_rows) * 0.8:
            combined = table_rows
        else:
            combined = table_rows + text_rows
        rows = _dedup_rows(combined)
        logger.info(f"PDF combined: {len(rows)} unique rows (table={len(table_rows)}, text={len(text_rows)})")
        return rows

    if table_rows:
        return table_rows
    if text_rows:
        return text_rows

    # ── AI fallback (chunked, uses _call_ai which supports Gemini) ────────────
    logger.info("Falling back to AI-based PDF parsing (Ollama → Gemini if needed)")
    text = ai_worker._extract_pdf_text(file_path)
    if not text:
        return []

    # Process in 6000-char chunks with 500-char overlap to avoid missing transactions
    chunk_size = 6000
    overlap    = 500
    ai_rows: list[dict] = []
    offset = 0

    while offset < len(text):
        chunk = text[offset: offset + chunk_size]
        prompt = (
            "Extract all bank transactions from this bank statement text chunk.\n"
            "Return ONLY a JSON array — no explanation, no markdown.\n"
            "Each element must have exactly these keys:\n"
            "  date (YYYY-MM-DD), description (string), amount (positive number),\n"
            "  transaction_type (\"debit\" or \"credit\")\n"
            "IMPORTANT: Only extract data explicitly present in the text. "
            "Do NOT invent, guess, or hallucinate transactions.\n"
            "If no transactions are found in this chunk, return []\n\n"
            f"Statement text:\n{chunk}"
        )
        # Write chunk to a temp text file so _call_ai can route it correctly
        import tempfile, os as _os
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".txt", delete=False, encoding="utf-8"
            ) as tmp:
                tmp.write(prompt)
                tmp_path = tmp.name

            raw = ai_worker._call_ai(prompt, file_path, "application/pdf")
            raw = ai_worker._clean_json(raw)
            arr_match = re.search(r"\[[\s\S]*\]", raw)
            if arr_match:
                data = json.loads(arr_match.group())
                for item in data:
                    try:
                        ai_rows.append({
                            "date":             date.fromisoformat(item["date"]),
                            "description":      str(item.get("description", "")),
                            "amount":           abs(float(item.get("amount", 0))),
                            "transaction_type": item.get("transaction_type", "debit"),
                            "reference":        None,
                        })
                    except Exception:
                        continue
        except Exception as e:
            logger.warning(f"AI chunk offset={offset} failed: {e}")
        finally:
            if tmp_path and _os.path.exists(tmp_path):
                _os.unlink(tmp_path)

        offset += chunk_size - overlap
        if offset >= len(text):
            break

    return _dedup_rows(ai_rows)


# ── HTTP Endpoints ────────────────────────────────────────────────────────────

@router.post("", response_model=BankStatementOut, status_code=201)
async def upload_bank_statement(
    file: UploadFile = File(...),
    bank_name: str = Form(...),
    db: Session = Depends(get_db),
):
    contents  = await file.read()
    file_type = _detect_file_type(file.content_type or "", file.filename or "")

    ext         = Path(file.filename or "file").suffix
    stored_name = f"{uuid.uuid4().hex}{ext}"
    stored_path = UPLOAD_DIR / stored_name
    stored_path.write_bytes(contents)

    if file_type == "csv":
        rows = _parse_csv(contents)
    elif file_type == "excel":
        rows = _parse_excel(contents)
    else:
        rows = _parse_pdf_statement(str(stored_path))

    if not rows:
        raise HTTPException(
            422,
            "No transactions were parsed from this file. "
            "Check that the file is a valid bank statement with Date, "
            "Description and Amount/Debit/Credit columns.",
        )

    # ── Smart category / type suggestions ─────────────────────────────────────
    # Pass 1: fast keyword rules (covers ~85 % of common Nigerian bank descriptions)
    for r in rows:
        cat, stype = _suggest_category_keyword(r["description"], r["transaction_type"])
        r["suggested_category"] = cat
        r["suggested_type"] = stype

    # Pass 2: AI batch call for rows that keyword rules couldn't classify ("Other")
    rows = _ai_suggest_categories_batch(rows)

    stmt = BankStatement(
        bank_name=bank_name,
        file_path=str(stored_path),
        file_type=file_type,
        status="pending",
    )
    db.add(stmt)
    db.flush()

    for row in rows:
        db.add(BankTransaction(statement_id=stmt.id, **row))

    db.commit()
    db.refresh(stmt)

    out = BankStatementOut.model_validate(stmt)
    out.transaction_count = len(rows)
    out.matched_count = 0
    return out


@router.get("", response_model=list[BankStatementOut])
def list_bank_statements(db: Session = Depends(get_db)):
    statements = db.query(BankStatement).order_by(BankStatement.created_at.desc()).all()
    result = []
    for s in statements:
        out = BankStatementOut.model_validate(s)
        out.transaction_count = len(s.bank_transactions)
        out.matched_count = sum(1 for t in s.bank_transactions if t.match_status == "matched")
        result.append(out)
    return result


@router.delete("/{stmt_id}", status_code=204)
def delete_bank_statement(stmt_id: int, db: Session = Depends(get_db)):
    """
    Delete a bank statement and all its bank transactions.
    Recorded transactions that were created from this statement are kept.
    """
    stmt = db.get(BankStatement, stmt_id)
    if not stmt:
        raise HTTPException(404, "Statement not found")
    db.delete(stmt)  # cascade deletes all BankTransaction rows
    db.commit()


from pydantic import BaseModel as _PydanticBase

class _BatchDeleteRequest(_PydanticBase):
    ids: list[int]


@router.post("/batch-delete", status_code=200)
def batch_delete_bank_statements(body: _BatchDeleteRequest, db: Session = Depends(get_db)):
    """Delete multiple bank statements by ID."""
    deleted = 0
    for stmt_id in body.ids:
        stmt = db.get(BankStatement, stmt_id)
        if stmt:
            db.delete(stmt)
            deleted += 1
    db.commit()
    return {"deleted": deleted}


@router.get("/{stmt_id}/transactions", response_model=list[BankTransactionOut])
def list_bank_transactions(stmt_id: int, db: Session = Depends(get_db)):
    stmt = db.get(BankStatement, stmt_id)
    if not stmt:
        raise HTTPException(404, "Statement not found")
    return (
        db.query(BankTransaction)
        .filter(BankTransaction.statement_id == stmt_id)
        .order_by(BankTransaction.date)
        .all()
    )


def _find_duplicate_transaction(
    db: Session, item: StatementImportItem, bank_name: str,
    reference: Optional[str] = None,
) -> Optional[Transaction]:
    """
    Check if a matching Transaction already exists in the database.

    Priority:
    1. Reference match — if the bank transaction has a unique reference (e.g. OPay
       transaction ID), look for an existing Transaction whose description contains it.
    2. Exact date + exact amount + same bank — high-confidence duplicate.
    3. Exact date + exact amount (no bank info) — medium-confidence duplicate,
       only returned if there is exactly one candidate (ambiguous amounts on the
       same day are NOT auto-matched).
    """
    from sqlalchemy import func

    # ── 1. Reference-based match ───────────────────────────────────────────────
    if reference:
        ref_match = (
            db.query(Transaction)
            .filter(Transaction.description.contains(reference))
            .first()
        )
        if ref_match:
            return ref_match

    # ── 2 & 3. Exact date + exact amount ──────────────────────────────────────
    candidates = (
        db.query(Transaction)
        .filter(
            Transaction.date == item.date,
            func.abs(Transaction.amount - item.amount) <= 0.01,
        )
        .all()
    )
    if not candidates:
        return None

    # Prefer matches that also share the same bank (high confidence)
    bank_matches = [tx for tx in candidates if tx.bank and tx.bank.lower() == bank_name.lower()]
    if bank_matches:
        return bank_matches[0]

    # Only return an amount+date match if it is unambiguous (exactly one candidate)
    # Multiple transactions of the same amount on the same day are NOT auto-deduplicated
    if len(candidates) == 1:
        return candidates[0]

    return None


@router.post("/{stmt_id}/import-transactions", response_model=StatementImportResult, status_code=201)
def import_statement_transactions(
    stmt_id: int,
    req: StatementImportRequest,
    db: Session = Depends(get_db),
):
    """
    Convert selected BankTransactions into real Transactions.
    Automatically detects duplicates (same date ±1 day + same amount ±₦0.01)
    and links them to existing transactions for reconciliation instead of
    creating duplicates.
    """
    stmt = db.get(BankStatement, stmt_id)
    if not stmt:
        raise HTTPException(404, "Statement not found")

    saved_count      = 0
    reconciled_count = 0

    for item in req.items:
        bank_tx = db.get(BankTransaction, item.bank_transaction_id)
        if not bank_tx or bank_tx.statement_id != stmt_id:
            continue

        # ── Already matched (auto-match or manual) — skip entirely ────────
        # The bank transaction is already linked to a recorded transaction.
        # Do NOT create a new transaction; just count it as reconciled.
        if bank_tx.match_status == "matched" and bank_tx.matched_transaction_id:
            reconciled_count += 1
            continue

        # ── Duplicate check (reference, then exact date + amount) ─────────
        existing = _find_duplicate_transaction(db, item, stmt.bank_name, bank_tx.reference)

        if existing:
            # Link the bank transaction to the already-recorded transaction
            bank_tx.matched_transaction_id = existing.id
            bank_tx.match_status           = "matched"
            bank_tx.match_confidence       = 1.0
            db.add(AuditLog(
                entity_type="reconciliation",
                entity_id=bank_tx.id,
                action="match",
                new_values=json.dumps({
                    "bank_tx_id":      bank_tx.id,
                    "transaction_id":  existing.id,
                    "method":          "duplicate_import",
                    "reason":          "same date and amount already in transactions",
                }),
            ))
            reconciled_count += 1
            continue

        # ── No duplicate — create a new Transaction ───────────────────────
        # Use extracted vendor from bank transaction if not provided in import item
        tx_vendor = item.vendor or bank_tx.vendor
        
        tx = Transaction(
            type=item.type,
            amount=item.amount,
            currency=item.currency,
            category=item.category,
            description=item.description,
            date=item.date,
            vendor=tx_vendor,
            bank=stmt.bank_name,
        )
        db.add(tx)
        db.flush()

        # Link bank_tx to the new transaction
        bank_tx.matched_transaction_id = tx.id
        bank_tx.match_status           = "matched"
        bank_tx.match_confidence       = 1.0

        db.add(AuditLog(
            entity_type="transaction",
            entity_id=tx.id,
            action="create",
            new_values=json.dumps({
                "type":        item.type,
                "amount":      item.amount,
                "category":    item.category,
                "description": item.description,
                "date":        str(item.date),
                "bank":        stmt.bank_name,
                "source":      "statement_import",
            }),
        ))
        saved_count += 1

    db.commit()
    return StatementImportResult(
        saved=saved_count,
        reconciled=reconciled_count,
        statement_id=stmt_id,
    )
