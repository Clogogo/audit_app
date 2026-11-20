"""Payroll schedule reconciliation.

Parses an uploaded Excel/CSV payroll schedule (who should have been paid how
much) and compares it with the Salary and Wages expense transactions actually
recorded in the bank account. Pure functions — no database writes.

Money is compared in integer kobo, never with a float tolerance: a one-kobo
shortfall is a real difference.
"""
import csv
import math
import re
import zipfile
from collections import Counter
from dataclasses import dataclass
from datetime import date
from io import BytesIO, StringIO
from typing import Any, Optional, Sequence

from routers.payroll import _name_matches_text

HEADER_SCAN_ROWS = 20                       # title/blank rows allowed above the header
HEADER_CONFIRM_ROWS = 10                    # rows below a header that must hold real data
MAX_SCHEDULE_ROWS = 2_000                   # non-blank rows; a school payroll is hundreds, not millions
MAX_GRID_ROWS = 10 * MAX_SCHEDULE_ROWS      # hard stop on blank/formatted rows so memory stays bounded
MAX_COLUMNS = 50                            # columns read per row
MAX_AMOUNT = 1e13                           # anything larger is a typo, not a salary
MAX_UNCOMPRESSED_BYTES = 30 * 1024 * 1024   # zip-bomb guard (the upload cap is on compressed size)
NUBAN_LENGTH = 10
MIN_ACCOUNT_DIGITS = 6

_NAME_TOKENS = {"staff", "teacher", "employee", "beneficiary", "payee"}
_NOT_NAME_TOKENS = {"bank", "account", "acct", "acc", "id", "code", "no", "number", "school", "class", "subject"}
_AMOUNT_KEYWORDS = ("net", "amount", "salary", "pay", "total")
_NOT_AMOUNT_TOKENS = {"date", "account", "acct", "number", "no", "id", "status", "bank"}
_ACCOUNT_WORDS = {"acct", "acc", "account", "nuban"}
_ACCOUNT_QUALIFIERS = {"no", "number", "num", "nuban", "acct"}

_FOOTER = re.compile(r"^\s*((grand\s+|sub\s*)?total|approved|prepared|checked|authori[sz]ed|signed)\b", re.I)
_CURRENCY_PREFIX = re.compile(r"^(?:NGN|USD|N|₦|\$)\s*", re.I)
_PLAIN_NUMBER = re.compile(r"^\d+(?:\.\d+)?$")
_GROUPED_NUMBER = re.compile(r"^\d{1,3}(?:,\d{3})+(?:\.\d+)?$")


class ScheduleError(ValueError):
    """The uploaded schedule can't be read; the message is safe to show users."""


@dataclass(frozen=True)
class ScheduleRow:
    row_number: int
    name: str
    amount: float
    account_number: Optional[str]


@dataclass(frozen=True)
class SkippedRow:
    row_number: int
    reason: str


# ── Reading the file ──────────────────────────────────────────────────────────

def _too_many_rows() -> ScheduleError:
    return ScheduleError(f"Schedule has too many rows (limit {MAX_SCHEDULE_ROWS}).")


def _load_xlsx(content: bytes) -> list[list[Any]]:
    from openpyxl import load_workbook
    try:
        with zipfile.ZipFile(BytesIO(content)) as zf:
            if sum(info.file_size for info in zf.infolist()) > MAX_UNCOMPRESSED_BYTES:
                raise ScheduleError("Excel file is too large once unpacked.")
        wb = load_workbook(BytesIO(content), read_only=True, data_only=True)
        try:
            grid: list[list[Any]] = []
            filled = 0
            for row in wb.worksheets[0].iter_rows(values_only=True):
                cells = list(row)[:MAX_COLUMNS]
                grid.append(cells)
                filled += any(c is not None and str(c).strip() for c in cells)
                if filled > MAX_SCHEDULE_ROWS or len(grid) > MAX_GRID_ROWS:
                    raise _too_many_rows()
            return grid
        finally:
            wb.close()
    except ScheduleError:
        raise
    except Exception as exc:  # corrupt zip, bad xml, encrypted file, ...
        raise ScheduleError("Could not read the Excel file — is it a valid .xlsx?") from exc


def _load_csv(content: bytes) -> list[list[Any]]:
    if b"\x00" in content:
        raise ScheduleError("That doesn't look like a CSV text file.")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("latin-1")
    grid: list[list[Any]] = []
    filled = 0
    try:
        for row in csv.reader(StringIO(text)):
            cells = list(row)[:MAX_COLUMNS]
            grid.append(cells)
            filled += any(c.strip() for c in cells)
            if filled > MAX_SCHEDULE_ROWS or len(grid) > MAX_GRID_ROWS:
                raise _too_many_rows()
    except csv.Error as exc:
        raise ScheduleError("Could not read the CSV file — it may be malformed.") from exc
    return grid


def _load_grid(content: bytes, filename: str) -> list[list[Any]]:
    lower = filename.lower()
    if lower.endswith((".xlsx", ".xlsm")):
        return _load_xlsx(content)
    if lower.endswith(".csv"):
        return _load_csv(content)
    raise ScheduleError("Unsupported file type — upload an .xlsx or .csv file.")


# ── Cells ─────────────────────────────────────────────────────────────────────

def _cell_text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _cell_at(row: Sequence[Any], index: Optional[int]) -> Any:
    return row[index] if index is not None and index < len(row) else None


def _bounded(number: float) -> float:
    if not math.isfinite(number) or abs(number) >= MAX_AMOUNT:
        raise ValueError("amount out of range")
    return number


def _parse_amount(value: Any) -> float:
    """Strict: plain or comma-grouped numbers with an optional currency prefix.
    Anything ambiguous ('1.234,50', 'N50k', '1e5') raises ValueError."""
    if isinstance(value, bool):
        raise ValueError("boolean")
    if isinstance(value, (int, float)):
        return _bounded(float(value))
    text = _cell_text(value)
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1].strip()
    text = _CURRENCY_PREFIX.sub("", text)
    if text.startswith("-"):
        negative, text = True, text[1:].strip()
    if not (_PLAIN_NUMBER.match(text) or _GROUPED_NUMBER.match(text)):
        raise ValueError(f"unreadable amount: {text!r}")
    number = _bounded(float(text.replace(",", "")))
    return -number if negative else number


def _parse_account(value: Any) -> Optional[str]:
    """Digits of an account number. Excel stores numeric cells without leading
    zeros, so a 9-digit number is a 10-digit NUBAN that lost its leading 0."""
    was_numeric = isinstance(value, (int, float)) and not isinstance(value, bool)
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    digits = re.sub(r"\D", "", _cell_text(value))
    if was_numeric and len(digits) == NUBAN_LENGTH - 1:
        digits = digits.zfill(NUBAN_LENGTH)
    return digits if len(digits) >= MIN_ACCOUNT_DIGITS else None


# ── Header detection ──────────────────────────────────────────────────────────

def _tokens(header: str) -> set[str]:
    return set(re.findall(r"[a-z]+", header.lower()))


def _find_name_column(headers: Sequence[str]) -> Optional[int]:
    toks = [_tokens(h) for h in headers]
    tiers = (
        lambda t: "name" in t and not t & _NOT_NAME_TOKENS,        # "Staff Name", "Name"
        lambda t: bool(t & _NAME_TOKENS) and not t & _NOT_NAME_TOKENS,  # "Teacher", "Beneficiary"
        lambda t: "name" in t and "bank" not in t,                 # "Account Name" as a last resort
    )
    for matches in tiers:
        for idx, t in enumerate(toks):
            if matches(t):
                return idx
    return None


def _find_amount_column(headers: Sequence[str]) -> Optional[int]:
    lowered = [h.lower() for h in headers]
    for kw in _AMOUNT_KEYWORDS:
        for idx, h in enumerate(lowered):
            if kw in h and not _tokens(h) & _NOT_AMOUNT_TOKENS:
                return idx
    return None


def _find_account_column(headers: Sequence[str]) -> Optional[int]:
    for idx, header in enumerate(headers):
        t = _tokens(header)
        if not t & _ACCOUNT_WORDS or "name" in t:
            continue
        if t & _ACCOUNT_QUALIFIERS or t == {"account"} or "beneficiary" in t:
            return idx
    return None


def _has_data_below(grid: Sequence[Sequence[Any]], header_idx: int, name_col: int, amount_col: int) -> bool:
    for row in grid[header_idx + 1: header_idx + 1 + HEADER_CONFIRM_ROWS]:
        try:
            if _cell_text(_cell_at(row, name_col)) and _parse_amount(_cell_at(row, amount_col)) > 0:
                return True
        except ValueError:
            continue
    return False


def _detect_header(grid: Sequence[Sequence[Any]]) -> tuple[int, int, int, Optional[int]]:
    """Prefer the first header row that has real data under it; fall back to the
    first keyword match so an empty schedule reports 'no payable rows'."""
    fallback: Optional[tuple[int, int, int, Optional[int]]] = None
    for i, row in enumerate(grid[:HEADER_SCAN_ROWS]):
        headers = [_cell_text(c) for c in row]
        name_col, amount_col = _find_name_column(headers), _find_amount_column(headers)
        if name_col is None or amount_col is None or name_col == amount_col:
            continue
        found = (i, name_col, amount_col, _find_account_column(headers))
        if _has_data_below(grid, i, name_col, amount_col):
            return found
        fallback = fallback or found
    if fallback:
        return fallback
    raise ScheduleError(
        f"Could not find name and amount columns in the first {HEADER_SCAN_ROWS} rows. "
        "Add a header row such as 'Name' and 'Amount'."
    )


# ── Parsing ───────────────────────────────────────────────────────────────────

def parse_schedule_with_skips(content: bytes, filename: str) -> tuple[list[ScheduleRow], list[SkippedRow]]:
    """Payable rows plus the rows that were skipped (with why), so a person
    can't silently vanish from the reconciliation. Totals/footers aren't
    reported — they are expected."""
    grid = _load_grid(content, filename)
    header_idx, name_col, amount_col, account_col = _detect_header(grid)

    rows: list[ScheduleRow] = []
    skipped: list[SkippedRow] = []
    for number, raw in enumerate(grid[header_idx + 1:], start=header_idx + 2):
        texts = [_cell_text(c) for c in raw]
        if not any(texts):
            continue
        name = _cell_text(_cell_at(raw, name_col))
        # A footer is a label in the name cell, or a label elsewhere on a row
        # with no name. A status/remarks cell saying "Approved" must not hide
        # a real staff row.
        if _FOOTER.match(name) or (not name and any(_FOOTER.match(t) for t in texts if t)):
            continue
        amount_cell = _cell_at(raw, amount_col)
        if not name:
            if _cell_text(amount_cell):
                skipped.append(SkippedRow(number, "Missing name"))
            continue
        try:
            amount = _parse_amount(amount_cell)
        except ValueError:
            skipped.append(SkippedRow(number, "Amount is blank or not a plain number"))
            continue
        if amount <= 0:
            skipped.append(SkippedRow(number, "Amount must be greater than zero"))
            continue
        rows.append(ScheduleRow(number, name, round(amount, 2), _parse_account(_cell_at(raw, account_col))))

    if not rows:
        hint = f" {len(skipped)} row(s) were skipped (row {skipped[0].row_number}: {skipped[0].reason})." if skipped else ""
        raise ScheduleError("No payable rows found in the schedule." + hint)
    return rows, skipped


def parse_schedule(content: bytes, filename: str) -> list[ScheduleRow]:
    return parse_schedule_with_skips(content, filename)[0]


# ── Reconciliation ────────────────────────────────────────────────────────────

AMBIGUOUS_NOTE = "Several schedule rows could match the same payment — review manually."


def _cents(amount: float) -> int:
    return round(amount * 100)


def _tx_text(tx: Any) -> str:
    return f"{tx.vendor or ''} {tx.description or ''}"


def _has_account(text: str, account: str) -> bool:
    return re.search(rf"(?<!\d){re.escape(account)}(?!\d)", text) is not None


def _candidates(row: ScheduleRow, transactions: Sequence[Any]) -> list[Any]:
    """Transactions plausibly paying this row — account number wins over name."""
    if row.account_number:
        by_account = [t for t in transactions if _has_account(_tx_text(t), row.account_number)]
        if by_account:
            return by_account
    return [t for t in transactions if _name_matches_text(row.name, _tx_text(t))]


def _status(difference_cents: int, any_paid: bool) -> str:
    if not any_paid:
        return "not_paid"
    if difference_cents == 0:
        return "matched"
    return "underpaid" if difference_cents < 0 else "overpaid"


def _build_line(row: ScheduleRow, chosen: Sequence[Any], note: Optional[str]) -> dict[str, Any]:
    paid_cents = sum(_cents(t.amount) for t in chosen)
    diff_cents = paid_cents - _cents(row.amount)
    return {
        "row_number": row.row_number,
        "name": row.name,
        "account_number": row.account_number,
        "expected_amount": row.amount,
        "paid_amount": paid_cents / 100,
        "difference": diff_cents / 100,
        "status": _status(diff_cents, bool(chosen)),
        "transaction_ids": [t.id for t in chosen],
        "paid_to": chosen[0].vendor if chosen else None,
        "paid_date": max(t.date for t in chosen).isoformat() if chosen else None,
        "note": note,
    }


def _tx_summary(tx: Any) -> dict[str, Any]:
    day: date = tx.date
    return {
        "id": tx.id, "date": day.isoformat(), "amount": round(tx.amount, 2),
        "description": tx.description, "vendor": tx.vendor,
    }


def _assign(rows: Sequence[ScheduleRow], ordered: Sequence[Any]) -> tuple[dict[int, list[Any]], dict[int, str]]:
    """Two passes so a loose name match can never steal another row's payment.

    Pass 1 gives each row a payment that matches it by account/name AND to the
    kobo. Pass 2 handles partial/split payments on what is left, but only
    gives a payment to a row when no other unresolved row could claim it; a
    contested payment is left unassigned and flagged instead of guessed."""
    candidates = [_candidates(row, ordered) for row in rows]
    assigned: dict[int, list[Any]] = {i: [] for i in range(len(rows))}
    used: set[int] = set()

    # Rows with an account number go first: that match is stronger than a name
    # match, so a looser name-only row can't take their payment.
    for i in sorted(range(len(rows)), key=lambda k: 0 if rows[k].account_number else 1):
        row = rows[i]
        exact = next((t for t in candidates[i] if t.id not in used and _cents(t.amount) == _cents(row.amount)), None)
        if exact is not None:
            assigned[i] = [exact]
            used.add(exact.id)

    unresolved = [i for i in assigned if not assigned[i]]
    open_candidates = {i: [t for t in candidates[i] if t.id not in used] for i in unresolved}
    # Count every row's interest, resolved or not: a payment that a resolved row
    # also matches (e.g. an extra payment to the same person) is contested.
    claims = Counter(t.id for i in assigned for t in candidates[i] if t.id not in used)
    notes: dict[int, str] = {}
    for i in unresolved:
        sole = [t for t in open_candidates[i] if claims[t.id] == 1]
        if len(sole) < len(open_candidates[i]):
            notes[i] = AMBIGUOUS_NOTE
        assigned[i] = sole
    return assigned, notes


def reconcile(rows: Sequence[ScheduleRow], transactions: Sequence[Any]) -> dict[str, Any]:
    """Match schedule rows to transactions; each transaction pays at most one row."""
    ordered = sorted(transactions, key=lambda t: (t.date, t.id))
    assigned, notes = _assign(rows, ordered)
    lines = [_build_line(row, assigned[i], notes.get(i)) for i, row in enumerate(rows)]

    used = {t.id for txs in assigned.values() for t in txs}
    leftovers = [t for t in ordered if t.id not in used]
    count = lambda status: sum(1 for ln in lines if ln["status"] == status)  # noqa: E731
    summary = {
        "rows": len(lines),
        "matched": count("matched"),
        "underpaid": count("underpaid"),
        "overpaid": count("overpaid"),
        "not_paid": count("not_paid"),
        "expected_total": sum(_cents(r.amount) for r in rows) / 100,
        "paid_total": sum(_cents(ln["paid_amount"]) for ln in lines) / 100,
        "unmatched_payments": len(leftovers),
        "unmatched_total": sum(_cents(t.amount) for t in leftovers) / 100,
    }
    return {"lines": lines, "unmatched_transactions": [_tx_summary(t) for t in leftovers], "summary": summary}
