"""
File Parsers for Bank Statements
Handles CSV, Excel (XLSX), and PDF format parsing.
"""
import io
import logging
import re
import zipfile
from typing import Optional, List

import pandas as pd

from . import statement_config as config
from . import category_suggester

logger = logging.getLogger(__name__)


# ── File Type Detection ───────────────────────────────────────────────────────

def detect_file_type(content_type: str, filename: str) -> str:
    """Detect file type from content type or filename."""
    ct = (content_type or "").lower()
    fn = (filename or "").lower()
    if "pdf" in ct or fn.endswith(".pdf"):
        return "pdf"
    if "excel" in ct or "xlsx" in fn or "xls" in fn:
        return "excel"
    return "csv"


# ── XLSX XML Patcher ──────────────────────────────────────────────────────────

def fix_xlsx_xml(contents: bytes) -> bytes:
    """
    Patch invalid XML enum values that openpyxl rejects
    (e.g. vertical="Top" must be vertical="top").
    """
    try:
        buf_in = io.BytesIO(contents)
        buf_out = io.BytesIO()
        with zipfile.ZipFile(buf_in, "r") as zin, \
                zipfile.ZipFile(buf_out, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                data = zin.read(item.filename)
                if item.filename == "xl/styles.xml":
                    text = data.decode("utf-8", errors="replace")
                    for bad, good in [
                        ('vertical="Top"', 'vertical="top"'),
                        ('vertical="Center"', 'vertical="center"'),
                        ('vertical="Bottom"', 'vertical="bottom"'),
                        ('horizontal="Left"', 'horizontal="left"'),
                        ('horizontal="Center"', 'horizontal="center"'),
                        ('horizontal="Right"', 'horizontal="right"'),
                    ]:
                        text = text.replace(bad, good)
                    data = text.encode("utf-8")
                zout.writestr(item, data)
        return buf_out.getvalue()
    except Exception:
        return contents


# ── CSV Parser ────────────────────────────────────────────────────────────────

def parse_csv(contents: bytes, bank_name: str = None) -> List[dict]:
    """Try multiple encodings and separators to parse CSV."""
    from . import statement_parser  # Avoid circular import

    for enc in ("utf-8", "latin-1", "cp1252"):
        for sep in (",", ";", "\t", "|"):
            try:
                # Attempt 1: treat first row as header
                df_raw = pd.read_csv(
                    io.BytesIO(contents), encoding=enc,
                    sep=sep, engine="python", header=0,
                )
                if len(df_raw.columns) >= 2:
                    df = statement_parser.replace_blank_column_names(df_raw)
                    rows = statement_parser.normalize_dataframe(df, bank_name=bank_name)
                    if rows:
                        logger.info(f"CSV parsed ({enc}, sep={sep!r}): {len(rows)} rows")
                        return rows

                    # Attempt 2: scan for header row if first attempt failed
                    df_no_header = pd.read_csv(
                        io.BytesIO(contents), encoding=enc,
                        sep=sep, engine="python", header=None,
                    )
                    header_idx = statement_parser.find_header_row_index(df_no_header)
                    if header_idx is not None:
                        df_with_header = df_no_header.iloc[header_idx + 1:].copy()
                        df_with_header.columns = [str(v) for v in df_no_header.iloc[header_idx]]
                        df = statement_parser.replace_blank_column_names(df_with_header)
                        rows = statement_parser.normalize_dataframe(df, bank_name=bank_name)
                        if rows:
                            logger.info(f"CSV parsed ({enc}, sep={sep!r}, header at row {header_idx}): {len(rows)} rows")
                            return rows
            except Exception as e:
                logger.debug(f"CSV parse failed ({enc}, sep={sep!r}): {e}")
                continue
    return []


# ── Excel Parser ──────────────────────────────────────────────────────────────

def parse_excel(contents: bytes, bank_name: str = None) -> List[dict]:
    """
    Parse an Excel file, accumulating transactions from EVERY sheet.

    Multi-account workbooks (e.g. OPay exports a 'Wallet Account' sheet and a
    separate 'Savings Account' sheet) must all be imported — parsing only the
    first sheet silently drops entire accounts.
    """
    from . import statement_parser  # Avoid circular import

    contents = fix_xlsx_xml(contents)
    try:
        xl = pd.ExcelFile(io.BytesIO(contents))
    except Exception as e:
        logger.warning(f"ExcelFile open failed: {e}")
        return []

    all_rows: List[dict] = []
    for sheet in xl.sheet_names:
        try:
            # Try with first row as header (most common case)
            df_raw = xl.parse(sheet, header=0)
            df = statement_parser.replace_blank_column_names(df_raw)
            rows = statement_parser.normalize_dataframe(df, bank_name=bank_name)

            # Fallback: scan for the header row if the first attempt found nothing
            if not rows:
                df_raw_no_header = xl.parse(sheet, header=None)
                header_idx = statement_parser.find_header_row_index(df_raw_no_header)
                if header_idx is not None:
                    df_with_header = df_raw_no_header.iloc[header_idx + 1:].copy()
                    df_with_header.columns = [str(v) for v in df_raw_no_header.iloc[header_idx]]
                    df = statement_parser.replace_blank_column_names(df_with_header)
                    rows = statement_parser.normalize_dataframe(df, bank_name=bank_name)

            if rows:
                logger.info(f"Excel sheet {sheet!r}: {len(rows)} rows")
                all_rows.extend(rows)
        except Exception as e:
            logger.warning(f"Excel sheet {sheet!r} failed: {e}")
            continue

    logger.info(f"Excel parsed: {len(all_rows)} rows across {len(xl.sheet_names)} sheet(s)")
    return all_rows


# ── PDF Parser (import from pdf_extraction if available) ──────────────────────

def parse_pdf(file_path: str, bank_name: str = None) -> List[dict]:
    """
    Parse PDF using pdfplumber.
    Falls back to generic text extraction if table parsing fails.
    """
    try:
        import pdf_extraction
        # Use the comprehensive PDF parser if available
        return pdf_extraction.extract_transactions_from_pdf(file_path, bank_name=bank_name)
    except (ImportError, AttributeError):
        # Fallback: basic PDF parsing
        logger.warning("pdf_extraction module not available, using basic PDF parser")
        return _parse_pdf_basic(file_path)


def _parse_pdf_basic(file_path: str) -> List[dict]:
    """Basic PDF text extraction fallback."""
    try:
        import pdfplumber
        from . import statement_parser
        
        all_rows = []
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                # Try table extraction first
                for table in (page.extract_tables() or []):
                    if not table or len(table) < 2:
                        continue
                    try:
                        df = pd.DataFrame(table[1:], columns=table[0])
                        rows = statement_parser.normalize_dataframe(df)
                        if rows:
                            all_rows.extend(rows)
                    except Exception:
                        continue
        
        return all_rows
    except ImportError:
        logger.error("pdfplumber not installed")
        return []
