"""
DataFrame parsing and normalization for bank statements.
Converts raw DataFrames (from CSV/Excel/PDF) into structured transaction dictionaries.
"""
import logging
import re
from typing import Optional

import pandas as pd

from .statement_config import (
    DATE_ALIASES,
    VALUE_DATE_ALIASES,
    DESC_ALIASES,
    DESC_PRIORITY_ALIASES,
    DEBIT_ALIASES,
    CREDIT_ALIASES,
    AMOUNT_ALIASES,
    REF_ALIASES,
    BALANCE_ALIASES,
    TYPE_ALIASES,
    HEADER_CELL_VALUES,
    find_column,
    parse_amount,
    infer_direction,
)

logger = logging.getLogger(__name__)


# ── Core DataFrame normalizer ─────────────────────────────────────────────────


def normalize_dataframe(df: pd.DataFrame, bank_name: str = None) -> list[dict]:
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

    Args:
        df: Raw DataFrame with bank transaction data
        bank_name: Optional bank name for bank-specific parsing logic

    Returns:
        List of transaction dictionaries with standardized fields
    """
    if df.empty:
        return []

    cols = list(df.columns)

    # ── 1. Prefer Value Date (settlement date) when available ─────────────────
    value_date_col = find_column(cols, VALUE_DATE_ALIASES, priority_aliases=None)
    date_col = value_date_col or find_column(cols, DATE_ALIASES, priority_aliases=None)

    desc_col = find_column(cols, DESC_ALIASES, priority_aliases=DESC_PRIORITY_ALIASES)
    debit_col = find_column(cols, DEBIT_ALIASES, priority_aliases=None)
    credit_col = find_column(cols, CREDIT_ALIASES, priority_aliases=None)
    amount_col = find_column(cols, AMOUNT_ALIASES, priority_aliases=None)
    ref_col = find_column(cols, REF_ALIASES, priority_aliases=None)
    balance_col = find_column(cols, BALANCE_ALIASES, priority_aliases=None)
    type_col = find_column(cols, TYPE_ALIASES, priority_aliases=None)

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
            if raw_date_str.lower() in HEADER_CELL_VALUES:
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
            raw_desc = row.get(desc_col) if desc_col else None

            # Handle pandas NaN/None values
            if raw_desc is None or (isinstance(raw_desc, float) and pd.isna(raw_desc)):
                description = ""
            else:
                description = str(raw_desc).strip()
                # Clean up multi-line descriptions (PDF artifacts)
                description = re.sub(r"[\r\n]+", " ", description).strip()

            # Skip section headers / separator rows (e.g. "-// Debits", "---")
            from .statement_config import SEPARATOR_RE
            if description and SEPARATOR_RE.match(description):
                continue

            # ── Reference Extraction ──────────────────────────────────
            reference: Optional[str] = None

            if ref_col:
                raw_ref = row.get(ref_col)
                if raw_ref is not None and not (isinstance(raw_ref, float) and pd.isna(raw_ref)):
                    # Collapse multi-line reference cells (PDF extraction artefact)
                    reference = re.sub(r"[\r\n]+", " ", str(raw_ref)).strip() or None

            # ── Vendor Extraction (using bank-specific parser) ───────────
            # Extract embedded references from pipe-separated descriptions first
            if description and "|" in description and not reference:
                parts = [p.strip() for p in description.split("|")]
                for part in parts:
                    # Look for reference-like patterns (numbers, alphanumeric codes)
                    if re.match(r"^[A-Za-z]{2,3}\d{4,}", part):  # e.g., "oa8699"
                        reference = part
                        break
                    elif re.match(r"^\d{8,}", part):  # e.g., "14201290534"
                        reference = part
                        break

            # Extract vendor from description using simple heuristics
            vendor_name: Optional[str] = None
            if description:
                for pattern in [
                    r"Transfer\s+(?:to|from)\s+([A-Z][A-Z\s]+?)(?:\s+\||$)",
                    r"Payment\s+(?:to|from)\s+([A-Z][A-Z\s]+?)(?:\s+\||$)",
                    r"(?:to|from)\s+([A-Z][A-Z\s]+?)(?:\s+\||$)",
                ]:
                    m = re.search(pattern, description, re.IGNORECASE)
                    if m:
                        vendor_name = m.group(1).strip()
                        # Remove trailing single capital letters (e.g., "JOHN A" → "JOHN")
                        vendor_name = re.sub(r"\s+[A-Z]$", "", vendor_name).strip()
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
            amount = 0.0
            tx_type = "debit"
            # Track whether amount came from a dedicated split column or a
            # shared single-amount column. The balance==amount sanity check
            # should only fire for the shared-column case, because when
            # separate Debit/Credit columns exist the amounts are correct
            # and coincidentally matching the running balance is expected
            # (especially on the opening rows of a statement).
            _amount_from_split_col = False

            if debit_col and credit_col:
                debit = parse_amount(row.get(debit_col, 0))
                credit = parse_amount(row.get(credit_col, 0))
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
                _amount_from_split_col = True

            elif credit_col and not debit_col:
                credit = parse_amount(row.get(credit_col, 0))
                if credit <= 0:
                    continue
                amount, tx_type = credit, "credit"
                _amount_from_split_col = True

            elif debit_col and not credit_col:
                debit = parse_amount(row.get(debit_col, 0))
                if debit <= 0:
                    continue
                amount, tx_type = debit, "debit"
                _amount_from_split_col = True

            elif amount_col:
                raw_val = str(row.get(amount_col, "") or "").strip()
                val = parse_amount(raw_val)
                if val == 0:
                    continue
                raw_clean = re.sub(r"[₦$€£,\s]", "", raw_val)
                if re.search(r"CR$", raw_clean, re.IGNORECASE) or raw_clean.startswith("+"):
                    tx_type = "credit"
                elif re.search(r"(DR|DB)$", raw_clean, re.IGNORECASE) or \
                        raw_clean.startswith("-") or raw_clean.startswith("("):
                    tx_type = "debit"
                else:
                    tx_type = infer_direction(description)
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
                curr_balance = parse_amount(row.get(balance_col, 0))
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
                curr_balance = parse_amount(row.get(balance_col, 0))
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

            # ── Fallback description (if empty) ───────────────────────────
            # If description is empty, generate a sensible default
            if not description:
                description = "Credit transaction" if tx_type == "credit" else "Debit transaction"

            # ── Sanity: reject rows where amount == running balance ───────
            # Only apply when the amount came from a shared single-amount
            # column (not from split Debit/Credit columns), because with split
            # columns the amounts are definitively correct and coincidentally
            # equalling the running balance is expected on the opening rows.
            if balance_col and not _amount_from_split_col:
                curr_bal_check = parse_amount(row.get(balance_col, 0))
                if curr_bal_check > 0 and abs(amount - curr_bal_check) < 0.02:
                    logger.warning(
                        f"Skipping row: amount {amount} equals running balance "
                        f"{curr_bal_check} — likely balance column mis-read as amount"
                    )
                    continue

            rows.append({
                "date": tx_date.date(),
                "description": description,
                "amount": round(amount, 2),
                "transaction_type": tx_type,
                "reference": reference,
                "vendor": vendor_name,  # Extracted recipient/merchant name
            })

        except Exception as e:
            import traceback
            logger.debug(f"Row parse failed: {e}\n{traceback.format_exc()}")
            continue

    return rows


# ── Header row scanner ─────────────────────────────────────────────────────────


def find_header_row_index(df: pd.DataFrame) -> Optional[int]:
    """
    Find the first row that looks like a column header.
    Requires at least one date-like keyword AND one amount/narration keyword.
    Uses the same alias sets as find_column so they are always in sync.

    Args:
        df: Raw DataFrame to scan

    Returns:
        Zero-based index of header row, or None if not found
    """
    # Derive from the same alias sets used for column mapping
    date_kws = DATE_ALIASES | VALUE_DATE_ALIASES
    amount_kws = (
        DEBIT_ALIASES | CREDIT_ALIASES | AMOUNT_ALIASES | DESC_ALIASES
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


def replace_blank_column_names(df: pd.DataFrame) -> pd.DataFrame:
    """
    Replace blank/NaN column names with _col_N placeholders.
    This is different from clean_columns() which normalizes existing names.

    Args:
        df: DataFrame with potentially blank column names

    Returns:
        DataFrame with all columns named
    """
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
