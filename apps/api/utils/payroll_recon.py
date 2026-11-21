"""Payroll schedule reconciliation.

Parses an uploaded Excel/CSV payroll schedule (who should have been paid how
much) and compares it with the Salary and Wages expense transactions actually
recorded in the bank account. Pure functions — no database writes.

Money is compared in integer kobo. A payment within ₦100 of what the schedule
says (strictly less than ₦100 apart) counts as paid in full.
"""
import csv
import math
import re
import zipfile
from collections import Counter
from dataclasses import dataclass, replace
from datetime import date
from io import BytesIO, StringIO
from typing import Any, Optional, Sequence

from routers.payroll import _name_matches_text, _normalize_name_tokens

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
    """A row that is not in the reconciliation. `ignored` rows look like labels
    or totals (expected); the rest are problems. Either way the row is listed
    with its text so nobody vanishes silently."""
    row_number: int
    reason: str
    ignored: bool = False
    label: str = ""


@dataclass(frozen=True)
class ParsedSchedule:
    rows: list[ScheduleRow]
    skipped: list[SkippedRow]
    notes: list[str]


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


def _load_delimited(content: bytes, delimiter: str) -> list[list[Any]]:
    if b"\x00" in content:
        raise ScheduleError("That doesn't look like a CSV text file.")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("latin-1")
    grid: list[list[Any]] = []
    filled = 0
    try:
        for row in csv.reader(StringIO(text), delimiter=delimiter):
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
        return _load_delimited(content, ",")
    if lower.endswith(".tsv"):  # rows pasted from Excel/Sheets arrive tab-separated
        return _load_delimited(content, "\t")
    raise ScheduleError("Unsupported file type — upload an .xlsx or .csv file, or paste rows from Excel.")


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


# ── Money-shaped cells (used when a sheet has no header row) ──────────────────

MAX_PLAIN_MONEY = 1e8      # bigger bare numbers/digit runs are account numbers, not pay
_LONG_DIGITS = re.compile(r"\d{9,}")


def _looks_like_money(value: Any) -> bool:
    if value is None or isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return 0 <= value < MAX_PLAIN_MONEY
    text = _cell_text(value)
    if not text or _LONG_DIGITS.fullmatch(text):
        return False
    try:
        _parse_amount(text)
    except ValueError:
        return False
    return True


def _is_name_like(value: Any) -> bool:
    text = _cell_text(value)
    return isinstance(value, str) and len(re.findall(r"[A-Za-z]", text)) >= 2 and not _looks_like_money(text)


def _is_account_cell(value: Any) -> bool:
    if isinstance(value, bool) or _looks_like_money(value):
        return False
    if isinstance(value, (int, float)):
        return float(value).is_integer() and value >= MAX_PLAIN_MONEY
    return bool(_LONG_DIGITS.fullmatch(_cell_text(value)))


def _column_letter(index: int) -> str:
    letters, n = "", index + 1
    while n:
        n, rem = divmod(n - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def _no_columns_error() -> ScheduleError:
    return ScheduleError(
        f"Could not find name and amount columns in the first {HEADER_SCAN_ROWS} rows. "
        "Add a header row such as 'Name' and 'Amount'."
    )


def _infer_layout(grid: Sequence[Sequence[Any]]) -> tuple[tuple[int, int, int, Optional[int]], list[str]]:
    """Column layout for a sheet with no header row, from the shape of the data:
    the name is the leftmost mostly-text column, the amount to pay is the
    rightmost column that is money on most payable rows (net pay comes after
    basic/deductions/bonus), and the account is a column of long digit runs."""
    width = max((len(r) for r in grid), default=0)
    text_counts = [sum(_is_name_like(_cell_at(r, c)) for r in grid) for c in range(width)]
    if not text_counts or max(text_counts) == 0:
        raise _no_columns_error()
    # Among the mostly-text columns the name column has the most distinct values
    # (a repeated title/bank column has few); ties go to the leftmost.
    def distinct(c: int) -> int:
        return len({_cell_text(_cell_at(r, c)).lower() for r in grid if _is_name_like(_cell_at(r, c))})
    name_col = max((c for c, n in enumerate(text_counts) if n >= max(text_counts) / 2), key=lambda c: (distinct(c), -c))

    data = [
        r for r in grid
        if _is_name_like(_cell_at(r, name_col))
        and any(_looks_like_money(_cell_at(r, c)) for c in range(width) if c != name_col)
    ]
    if not data:
        raise _no_columns_error()
    money = [sum(_looks_like_money(_cell_at(r, c)) for r in data) if c != name_col else 0 for c in range(width)]
    need = max(1, math.ceil(len(data) / 2))
    amount_cols = [c for c, n in enumerate(money) if n >= need]
    if not amount_cols:
        raise _no_columns_error()
    amount_col = amount_cols[-1]

    accounts = [
        (sum(_is_account_cell(_cell_at(r, c)) for r in data), c)
        for c in range(width) if c not in (name_col, amount_col)
    ]
    best = max(accounts, default=(0, None))
    account_col = best[1] if best[0] >= max(1, math.ceil(0.4 * len(data))) else None

    notes = [
        f"No header row found — using column {_column_letter(name_col)} as the name, "
        f"column {_column_letter(amount_col)} as the amount to pay (net pay)"
        + (f" and column {_column_letter(account_col)} as the account number." if account_col is not None else ".")
    ]
    for c in range(amount_col + 1, width):
        if money[c] > 0:
            notes.append(
                f"Column {_column_letter(c)} has amounts on only {money[c]} of {len(data)} rows, so column "
                f"{_column_letter(amount_col)} was used instead — check that is the right column."
            )
    return (-1, name_col, amount_col, account_col), notes


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


def _detect_header(grid: Sequence[Sequence[Any]]) -> tuple[tuple[int, int, int, Optional[int]], list[str]]:
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
            return found, []
        fallback = fallback or found
    if fallback:  # a header with nothing usable below it: the sheet may be header-less after all
        try:
            return _infer_layout(grid)
        except ScheduleError:
            return fallback, []
    return _infer_layout(grid)


# ── Parsing ───────────────────────────────────────────────────────────────────

def parse_schedule_full(content: bytes, filename: str) -> ParsedSchedule:
    """Payable rows, every row left out (with why and its text), and notes about
    how columns were chosen when the sheet had no header row."""
    grid = _load_grid(content, filename)
    (header_idx, name_col, amount_col, account_col), notes = _detect_header(grid)

    rows: list[ScheduleRow] = []
    skipped: list[SkippedRow] = []
    for number, raw in enumerate(grid[header_idx + 1:], start=header_idx + 2):
        texts = [_cell_text(c) for c in raw]
        if not any(texts):
            continue
        name = _cell_text(_cell_at(raw, name_col))
        label = (name or next(t for t in texts if t))[:60]

        def ignore(reason: str) -> None:
            skipped.append(SkippedRow(number, reason, ignored=True, label=label))

        # A footer is a label in the name cell, or a label elsewhere on a row
        # with no name. A status/remarks cell saying "Approved" must not hide
        # a real staff row.
        if _FOOTER.match(name) or (not name and any(_FOOTER.match(t) for t in texts if t)):
            ignore("Looks like a totals or sign-off row")
            continue
        amount_cell = _cell_at(raw, amount_col)
        if name and not any(t for i, t in enumerate(texts) if i != name_col):
            ignore("Looks like a section label (a name with no other values)")
            continue
        if not name:
            if sum(_looks_like_money(c) for c in raw) >= 2:
                ignore("Looks like a totals row (numbers but no name)")
            elif _cell_text(amount_cell):
                skipped.append(SkippedRow(number, "Missing name", label=label))
            continue
        try:
            amount = _parse_amount(amount_cell)
        except ValueError:
            skipped.append(SkippedRow(number, "Amount is blank or not a plain number", label=label))
            continue
        if amount <= 0:
            skipped.append(SkippedRow(number, "Amount must be greater than zero", label=label))
            continue
        rows.append(ScheduleRow(number, name, round(amount, 2), _parse_account(_cell_at(raw, account_col))))

    if not rows:
        problems = [r for r in skipped if not r.ignored]
        hint = f" {len(problems)} row(s) were skipped (row {problems[0].row_number}: {problems[0].reason})." if problems else ""
        raise ScheduleError("No payable rows found in the schedule." + hint)
    return ParsedSchedule(rows, skipped, notes)


def parse_schedule_with_skips(content: bytes, filename: str) -> tuple[list[ScheduleRow], list[SkippedRow]]:
    parsed = parse_schedule_full(content, filename)
    return parsed.rows, parsed.skipped


def parse_schedule(content: bytes, filename: str) -> list[ScheduleRow]:
    return parse_schedule_with_skips(content, filename)[0]


# ── Reconciliation ────────────────────────────────────────────────────────────

PAID_TOLERANCE_KOBO = 10_000    # a gap under ₦100 still counts as paid in full
AMBIGUOUS_NOTE = "Several schedule rows could match the same payment — review manually."


def _cents(amount: float) -> int:
    return round(amount * 100)


def within_tolerance(difference_cents: int) -> bool:
    return abs(difference_cents) < PAID_TOLERANCE_KOBO


def _tx_text(tx: Any) -> str:
    return f"{tx.vendor or ''} {tx.description or ''}"


def _has_account(text: str, account: str) -> bool:
    return re.search(rf"(?<!\d){re.escape(account)}(?!\d)", text) is not None


def _name_variants(name: str) -> list[str]:
    """The full name plus the parts outside and inside brackets, e.g.
    'EXTRA LESSONS (JOY ADA OKO)' also matches a payment to 'JOY ADA OKO'."""
    parts = [name, re.sub(r"\([^)]*\)", " ", name), *re.findall(r"\(([^)]*)\)", name)]
    return list(dict.fromkeys(p.strip() for p in parts if p.strip()))


def _candidates(row: ScheduleRow, transactions: Sequence[Any]) -> tuple[list[Any], list[Any]]:
    """(payments to the row's account number, payments whose name matches the row).
    Kept apart so a stale or shared account number can never hide a payment that
    the name on the transfer identifies."""
    by_account: list[Any] = []
    if row.account_number:
        key = _account_key(row.account_number)
        by_account = [
            t for t in transactions
            if _has_account(_tx_text(t), row.account_number)
            or (key is not None and _account_key(parse_payment_recipient(t.description)[2]) == key)
        ]
    variants = _name_variants(row.name)
    by_name = [t for t in transactions if any(_name_matches_text(v, _tx_text(t)) for v in variants)]
    return by_account, by_name


def _status(difference_cents: int, any_paid: bool) -> str:
    if not any_paid:
        return "not_paid"
    if within_tolerance(difference_cents):
        return "matched"
    return "underpaid" if difference_cents < 0 else "overpaid"


def parse_payment_recipient(description: Optional[str]) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """(name, bank, account) from a bank narration such as
    'Transfer to PATRICIA OGOGO | OPay | 7038692765 | August Salary'.
    Masked (955****234) or placeholder accounts come back as None."""
    parts = [p.strip() for p in (description or "").split("|")]
    if len(parts) < 3 or not parts[0].lower().startswith("transfer to "):
        return None, None, None
    account = parts[2] if re.fullmatch(r"\d+", parts[2]) and _account_key(parts[2]) else None
    return parts[0][len("transfer to "):].strip() or None, parts[1] or None, account


def check_account(directory_account: Optional[str], paid_account: Optional[str]) -> Optional[str]:
    """The bank is the truth: compare the account it paid with the directory's.
    None when we cannot read the paid account; 'missing' / 'differs' / 'ok' otherwise."""
    if not paid_account:
        return None
    directory = _account_key(directory_account)
    if directory is None:
        return "missing"
    return "ok" if directory == _account_key(paid_account) else "differs"


def _suggestion(tx: Any) -> dict[str, Any]:
    _, bank, account = parse_payment_recipient(tx.description)
    return {"id": tx.id, "date": tx.date.isoformat(), "amount": round(tx.amount, 2), "vendor": tx.vendor,
            "account": account, "bank": bank}


def _build_line(
    row: ScheduleRow, chosen: Sequence[Any], note: Optional[str], extras: Sequence[Any] = (),
    suggestions: Sequence[Any] = (),
) -> dict[str, Any]:
    _, paid_bank, paid_account = parse_payment_recipient(chosen[0].description) if chosen else (None, None, None)
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
        # Further payments that also look like this person's but were not used: a
        # row that is already paid and still has these may have been paid twice.
        "extra_payment_ids": [t.id for t in extras],
        "extra_paid_amount": sum(_cents(t.amount) for t in extras) / 100,
        # What the bank actually paid (the truth for account number and bank)
        "paid_account": paid_account,
        "paid_bank": paid_bank,
        # Unpaid row + an unclaimed payment of about the same amount: maybe this one
        "suggested_payments": [_suggestion(t) for t in suggestions],
    }


def _tx_summary(tx: Any) -> dict[str, Any]:
    day: date = tx.date
    _, bank, account = parse_payment_recipient(tx.description)
    return {
        "id": tx.id, "date": day.isoformat(), "amount": round(tx.amount, 2),
        "description": tx.description, "vendor": tx.vendor, "account": account, "bank": bank,
    }


def _assign(
    rows: Sequence[ScheduleRow], ordered: Sequence[Any],
) -> tuple[dict[int, list[Any]], dict[int, str], list[list[Any]]]:
    """Two passes so a loose name match can never steal another row's payment.

    Pass 1 gives each row a payment that matches it by account/name AND is
    within the ₦100 tolerance (the closest one wins). Pass 2 handles partial/split payments on what is left, but only
    gives a payment to a row when no other unresolved row could claim it; a
    contested payment is left unassigned and flagged instead of guessed."""
    hits = [_candidates(row, ordered) for row in rows]
    candidates = [sorted({t.id: t for t in by_acct + by_name}.values(), key=lambda t: (t.date, t.id)) for by_acct, by_name in hits]
    assigned: dict[int, list[Any]] = {i: [] for i in range(len(rows))}
    used: set[int] = set()

    def take(i: int, pool: list[Any]) -> None:
        row = rows[i]
        near = [t for t in pool if t.id not in used and within_tolerance(_cents(t.amount) - _cents(row.amount))]
        if near and not assigned[i]:
            best = min(near, key=lambda t: (abs(_cents(t.amount) - _cents(row.amount)), t.date, t.id))
            assigned[i] = [best]
            used.add(best.id)

    # Rows with an account number go first so a looser name-only row can't take
    # their payment. First the payments whose NAME matches (a payment that names
    # Bob is Bob's even if Alice shares his account number), then payments to the
    # row's account under another name (staff paid into a relative's account).
    order = sorted(range(len(rows)), key=lambda k: 0 if rows[k].account_number else 1)
    for i in order:
        take(i, hits[i][1])
    for i in order:
        take(i, hits[i][0])

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
    return assigned, notes, candidates


def reconcile(rows: Sequence[ScheduleRow], transactions: Sequence[Any]) -> dict[str, Any]:
    """Match schedule rows to transactions; each transaction pays at most one row."""
    ordered = sorted(transactions, key=lambda t: (t.date, t.id))
    assigned, notes, candidates = _assign(rows, ordered)
    used = {t.id for txs in assigned.values() for t in txs}
    leftovers = [t for t in ordered if t.id not in used]

    def fits(t: Any, row: ScheduleRow) -> bool:
        return within_tolerance(_cents(t.amount) - _cents(row.amount))

    # A payment is only suggested when exactly one unpaid row could take it,
    # otherwise the user could save the same account onto the wrong person.
    unpaid_rows = [row for i, row in enumerate(rows) if not assigned[i]]
    fit_counts = Counter(t.id for t in leftovers for row in unpaid_rows if fits(t, row))

    def suggestions(i: int, row: ScheduleRow) -> list[Any]:
        if assigned[i]:
            return []
        return [t for t in leftovers if fits(t, row) and fit_counts[t.id] == 1][:3]

    lines = [
        _build_line(row, assigned[i], notes.get(i),
                    [t for t in candidates[i] if t.id not in used] if assigned[i] else [], suggestions(i, row))
        for i, row in enumerate(rows)
    ]
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


# ── Linking schedule rows to the staff directory ──────────────────────────────

def _account_key(value: Optional[str]) -> Optional[str]:
    """Digits only, leading zeros dropped (Excel loses them), or None if too short."""
    digits = re.sub(r"\D", "", value or "")
    # an all-zero number is a placeholder, not an account
    return (digits.lstrip("0") or None) if len(digits) >= MIN_ACCOUNT_DIGITS else None


def _link_unambiguous(candidates: dict[int, list[ScheduleRow]], links: dict[int, ScheduleRow], used: set[int]) -> None:
    """Link a staff member to a row only when it is that staff member's single
    candidate AND no other staff member is a candidate for the same row."""
    claims = Counter(r.row_number for rows in candidates.values() for r in rows)
    for staff_id, rows in candidates.items():
        if len(rows) == 1 and claims[rows[0].row_number] == 1:
            links[staff_id] = rows[0]
            used.add(rows[0].row_number)


def _names_match(staff_name: str, row_name: str) -> bool:
    return any(
        _name_matches_text(a, b) or _name_matches_text(b, a)
        for a in _name_variants(staff_name) for b in _name_variants(row_name)
    )


def link_staff_to_rows(staff: Sequence[Any], rows: Sequence[ScheduleRow]) -> dict[int, ScheduleRow]:
    """Which schedule row belongs to which staff member (staff id -> row).

    Account number first, then an identical set of name words, then a fuzzy
    name match. Each step only links unambiguous pairs, and a row is never
    used twice; anything unclear is left unlinked for a person to look at."""
    links: dict[int, ScheduleRow] = {}
    used: set[int] = set()

    by_account = {
        s.id: [r for r in rows if _account_key(r.account_number) == key]
        for s in staff if (key := _account_key(getattr(s, "account_number", None)))
    }
    _link_unambiguous(by_account, links, used)

    def open_rows() -> list[ScheduleRow]:
        return [r for r in rows if r.row_number not in used]

    pending = lambda: [s for s in staff if s.id not in links]  # noqa: E731
    same_words = {
        s.id: [r for r in open_rows() if (words := frozenset(_normalize_name_tokens(s.full_name))) and words == frozenset(_normalize_name_tokens(r.name))]
        for s in pending()
    }
    _link_unambiguous(same_words, links, used)

    fuzzy = {s.id: [r for r in open_rows() if _names_match(s.full_name, r.name)] for s in pending()}
    _link_unambiguous(fuzzy, links, used)
    return links


def link_and_fill(
    rows: Sequence[ScheduleRow], staff: Sequence[Any],
) -> tuple[list[ScheduleRow], dict[int, ScheduleRow], dict[int, str]]:
    """Link staff to rows, then give a row that has no account number the one in
    the staff directory, so its bank payment can be found even when the name on
    the transfer is someone else's. Returns (rows with accounts filled,
    staff id -> row, row number -> 'sheet' | 'directory')."""
    links = link_staff_to_rows(staff, rows)
    owner = {row.row_number: s for s in staff if (row := links.get(s.id)) is not None}
    filled: list[ScheduleRow] = []
    sources: dict[int, str] = {}
    for row in rows:
        directory = re.sub(r"\D", "", getattr(owner.get(row.row_number), "account_number", None) or "")
        if row.account_number:
            sources[row.row_number] = "sheet"
            filled.append(row)
        elif _account_key(directory):
            sources[row.row_number] = "directory"
            filled.append(replace(row, account_number=directory))
        else:
            filled.append(row)
    return filled, links, sources
