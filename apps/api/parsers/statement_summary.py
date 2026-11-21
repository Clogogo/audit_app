"""Read the opening/closing balance and total debit/credit a bank prints in its statement summary block
(e.g. Moniepoint's "Account Summary"). Best effort: anything not found is simply left out."""
import io
import logging
import re

import pandas as pd

logger = logging.getLogger(__name__)

_SEP = r"""[\s:;,|"']*"""
_NUMBER = r"(?:₦|NGN|N)?\s*(-?[\d,]*\.?\d+)"
_PATTERNS = {
    "opening_balance": re.compile(r"opening\s+balance\b" + _SEP + _NUMBER, re.I),
    "closing_balance": re.compile(r"closing\s+balance\b" + _SEP + _NUMBER, re.I),
    "total_debit": re.compile(r"total\s+debits?\b" + _SEP + _NUMBER, re.I),
    "total_credit": re.compile(r"total\s+credits?\b" + _SEP + _NUMBER, re.I),
}
_EDGE_LINES = 40   # the summary sits at the top (or bottom) of a statement, never in the middle of the transactions


def _find(lines: list[str]) -> dict[str, float]:
    found: dict[str, float] = {}
    for line in lines:
        for key, pattern in _PATTERNS.items():
            m = pattern.search(line)
            if m and key not in found:
                try:
                    found[key] = float(m.group(1).replace(",", ""))
                except ValueError:
                    continue
    return found


def _edges(lines: list[str]) -> list[str]:
    return lines[:_EDGE_LINES] + lines[-_EDGE_LINES:]


def _sheet_lines(df: pd.DataFrame) -> list[str]:
    return [" ".join(str(c) for c in row if pd.notna(c)) for row in df.itertuples(index=False)]


def extract_summary(contents: bytes, file_type: str, pdf_path: str | None = None) -> dict[str, float]:
    """Keys: opening_balance, closing_balance, total_debit, total_credit (only those found).
    A workbook with several account sheets (e.g. OPay wallet + savings) gets the sums, like the parsed rows."""
    try:
        if file_type == "excel":
            from .file_parsers import fix_xlsx_xml
            xl = pd.ExcelFile(io.BytesIO(fix_xlsx_xml(contents)))
            per_sheet = [_find(_edges(_sheet_lines(xl.parse(name, header=None)))) for name in xl.sheet_names]
            per_sheet = [s for s in per_sheet if s]
            return {k: round(sum(s[k] for s in per_sheet if k in s), 2) for k in _PATTERNS if any(k in s for s in per_sheet)}
        if file_type == "csv":
            for enc in ("utf-8", "latin-1"):
                try:
                    return _find(_edges(contents.decode(enc).splitlines()))
                except UnicodeDecodeError:
                    continue
            return {}
        if file_type == "pdf" and pdf_path:
            import pdfplumber
            with pdfplumber.open(pdf_path) as pdf:
                pages = [pdf.pages[0], pdf.pages[-1]] if pdf.pages else []
                return _find([ln for p in pages for ln in (p.extract_text() or "").splitlines()])
    except Exception as exc:   # a summary is a bonus: never let it break an import
        logger.warning("Could not read the statement summary: %s", exc)
    return {}
