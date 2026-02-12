"""
Bank statement import: CSV, Excel, PDF
Parses rows into BankTransaction records.
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
    StatementImportItem, StatementImportRequest, TransactionOut,
)
import ai_worker

router = APIRouter(prefix="/bank-statements", tags=["bank-statements"])

BASE_DIR = Path(__file__).parent.parent.parent.parent
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)


def _detect_file_type(content_type: str, filename: str) -> str:
    ct = (content_type or "").lower()
    fn = (filename or "").lower()
    if "pdf" in ct or fn.endswith(".pdf"):
        return "pdf"
    if "excel" in ct or "xlsx" in fn or "xls" in fn:
        return "excel"
    return "csv"


def _parse_csv(contents: bytes) -> list[dict]:
    df = pd.read_csv(io.BytesIO(contents))
    return _normalize_df(df)


def _fix_xlsx_xml(contents: bytes) -> bytes:
    """
    Some bank-generated XLSX files contain invalid XML (e.g. vertical="Top" instead
    of "top") that causes openpyxl to raise ValueError.  Patch the offending bytes
    inside the zip archive in-memory so pandas can read the file normally.
    """
    try:
        buf_in = io.BytesIO(contents)
        buf_out = io.BytesIO()
        with zipfile.ZipFile(buf_in, "r") as zin, zipfile.ZipFile(buf_out, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                data = zin.read(item.filename)
                if item.filename == "xl/styles.xml":
                    # Fix case-sensitive enum values that openpyxl rejects
                    text = data.decode("utf-8", errors="replace")
                    for bad, good in [
                        ('vertical="Top"',    'vertical="top"'),
                        ('vertical="Center"', 'vertical="center"'),
                        ('vertical="Bottom"', 'vertical="bottom"'),
                        ('horizontal="Left"',   'horizontal="left"'),
                        ('horizontal="Center"', 'horizontal="center"'),
                        ('horizontal="Right"',  'horizontal="right"'),
                    ]:
                        text = text.replace(bad, good)
                    data = text.encode("utf-8")
                zout.writestr(item, data)
        return buf_out.getvalue()
    except Exception:
        return contents  # return original if patching fails


def _parse_excel(contents: bytes) -> list[dict]:
    # Patch any invalid XML enum values that openpyxl rejects
    contents = _fix_xlsx_xml(contents)

    # First pass with no header to locate the actual header row
    df_raw = pd.read_excel(io.BytesIO(contents), header=None)

    header_row: Optional[int] = None
    for idx, row in df_raw.iterrows():
        cells = [
            str(c).lower().strip()
            for c in row
            if c is not None and str(c).strip() not in ("", "nan", "none")
        ]
        has_date   = any("date" in c for c in cells)
        has_amount = any(
            c in ("debit", "credit", "amount", "narration", "description", "dr", "cr", "withdrawal", "deposit")
            for c in cells
        )
        if has_date and has_amount:
            header_row = int(idx)  # type: ignore[arg-type]
            break

    if header_row is None:
        df = pd.read_excel(io.BytesIO(contents))
    else:
        df = pd.read_excel(io.BytesIO(contents), header=header_row)

    # pandas may produce NaN/None column names for merged-cell spans; rename them
    new_cols: list[str] = []
    for i, c in enumerate(df.columns):
        s = str(c).strip()
        if s.lower() in ("nan", "none", "") or s.startswith("Unnamed"):
            new_cols.append(f"_col_{i}")
        else:
            new_cols.append(s)
    df.columns = new_cols  # type: ignore[assignment]

    return _normalize_df(df)


def _normalize_df(df: pd.DataFrame) -> list[dict]:
    """
    Best-effort normalization of bank statement columns.
    Looks for common column name patterns.
    """
    df.columns = [str(c).lower().strip() for c in df.columns]

    col_map = {
        "date": ["date", "transaction date", "trans date", "posting date", "value date"],
        "description": ["description", "narration", "memo", "details", "narrative", "particulars", "transaction"],
        "amount": ["amount", "debit/credit", "value"],
        "debit": ["debit", "withdrawal", "dr"],
        "credit": ["credit", "deposit", "cr"],
        "reference": ["reference", "ref", "check number", "cheque number"],
    }

    found: dict[str, str] = {}
    for target, aliases in col_map.items():
        for alias in aliases:
            if alias in df.columns:
                found[target] = alias
                break

    rows = []
    for _, row in df.iterrows():
        try:
            raw_date = row.get(found.get("date", ""), None)
            if raw_date is None:
                continue
            tx_date = pd.to_datetime(raw_date, errors="coerce")
            if pd.isna(tx_date):
                continue

            description = str(row.get(found.get("description", ""), "")).strip()

            amount = 0.0
            tx_type = "debit"
            if "amount" in found:
                val = pd.to_numeric(row.get(found["amount"], 0), errors="coerce") or 0.0
                amount = abs(float(val))
                tx_type = "credit" if float(val) > 0 else "debit"
            elif "debit" in found or "credit" in found:
                debit = pd.to_numeric(row.get(found.get("debit", ""), 0), errors="coerce") or 0.0
                credit = pd.to_numeric(row.get(found.get("credit", ""), 0), errors="coerce") or 0.0
                if float(credit) > 0:
                    amount = float(credit)
                    tx_type = "credit"
                else:
                    amount = float(debit)
                    tx_type = "debit"

            reference = str(row.get(found.get("reference", ""), "")).strip() or None

            rows.append({
                "date": tx_date.date(),
                "description": description,
                "amount": amount,
                "transaction_type": tx_type,
                "reference": reference,
            })
        except Exception:
            continue
    return rows


def _parse_amount(val: object) -> float:
    """Parse a cell value like '10,000.00' or '--' into a float."""
    s = str(val or "").strip()
    if not s or s in ("--", "-", "—", "N/A", ""):
        return 0.0
    s = re.sub(r"[₦$€£,\s]", "", s)
    try:
        return abs(float(s))
    except ValueError:
        return 0.0


# Regex for OPay-style (and similar Nigerian bank) PDF text lines.
# Each transaction line looks like:
#   DD Mon YYYY HH:MM:SS  DD Mon YYYY  [description]  DEBIT  CREDIT  BALANCE  CHANNEL  REF
_MONTH = r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)'
_DATE_RE  = rf'\d{{1,2}}\s+{_MONTH}\s+\d{{4}}'
_AMOUNT_RE = r'(?:[\d,]+\.\d{2}|--)'
_CHANNEL_RE = r'(?:Mobile|POS|USSD|ATM|Web|Branch|Internet)'

_TX_LINE_RE = re.compile(
    rf'({_DATE_RE})\s+'                         # trans-time date (used as fallback date)
    rf'\d{{2}}:\d{{2}}:\d{{2}}\s+'             # trans-time HH:MM:SS
    rf'({_DATE_RE})\s+'                         # value date ← use this
    rf'(.*?)\s*'                                # description (may be empty for wrapped rows)
    rf'({_AMOUNT_RE})\s+'                       # debit(₦)
    rf'({_AMOUNT_RE})\s+'                       # credit(₦)
    rf'{_AMOUNT_RE}\s+'                         # balance after (discard)
    rf'{_CHANNEL_RE}\s+'                        # channel (discard)
    rf'(\S+)',                                   # transaction reference
    re.IGNORECASE,
)


def _parse_pdf_text_regex(file_path: str) -> list[dict]:
    """
    Parse a bank PDF by extracting raw text and applying a transaction-line regex.
    Works for OPay, most Nigerian banks that follow the
    'Trans Time | Value Date | Description | Debit | Credit | Balance | Channel | Ref' layout.
    Handles multi-line descriptions gracefully (uses partial description from the anchor line).
    """
    import pdfplumber

    all_lines: list[str] = []
    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                all_lines.extend(text.splitlines())

    rows: list[dict] = []
    for line in all_lines:
        m = _TX_LINE_RE.search(line)
        if not m:
            continue
        value_date_str = m.group(2).strip()
        description    = (m.group(3) or "").strip()
        debit_str      = m.group(4)
        credit_str     = m.group(5)
        reference      = m.group(6)

        try:
            tx_date = pd.to_datetime(value_date_str, dayfirst=True, errors="coerce")
            if pd.isna(tx_date):
                continue

            debit  = _parse_amount(debit_str)
            credit = _parse_amount(credit_str)

            if credit > 0:
                amount, tx_type = credit, "credit"
            elif debit > 0:
                amount, tx_type = debit, "debit"
            else:
                continue

            if not description:
                description = f"{'Credit' if tx_type == 'credit' else 'Debit'} transaction"

            rows.append({
                "date": tx_date.date(),
                "description": description,
                "amount": amount,
                "transaction_type": tx_type,
                "reference": reference or None,
            })
        except Exception:
            continue

    return rows


def _parse_pdf_tables(file_path: str) -> list[dict]:
    """
    Secondary PDF parser: pdfplumber table cells.
    Works when pdfplumber successfully splits the PDF into clean table cells.
    Handles the cases where each cell is correctly extracted (not merged).
    """
    import pdfplumber

    DATE_KEYS        = ["value date", "date", "trans. time", "transaction date", "trans date"]
    DESCRIPTION_KEYS = ["description", "memo", "narration", "details", "particulars", "transaction"]
    DEBIT_KEYS       = ["debit", "withdrawal", "dr", "debit(₦)", "debit(ngn)"]
    CREDIT_KEYS      = ["credit", "deposit", "cr", "credit(₦)", "credit(ngn)"]
    AMOUNT_KEYS      = ["amount", "value"]
    REFERENCE_KEYS   = ["transaction reference", "reference", "ref", "cheque", "check"]

    rows: list[dict] = []

    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()
            for table in tables:
                if not table or len(table) < 2:
                    continue

                header_idx = None
                for i, row in enumerate(table):
                    if not row:
                        continue
                    cells = [str(c or "").lower().strip() for c in row]
                    has_date = any(any(k in c for k in DATE_KEYS) for c in cells)
                    has_amount = any(any(k in c for k in DEBIT_KEYS + CREDIT_KEYS + AMOUNT_KEYS) for c in cells)
                    if has_date and has_amount:
                        header_idx = i
                        break

                if header_idx is None:
                    continue

                header = [str(c or "").lower().strip() for c in table[header_idx]]
                col: dict[str, int] = {}
                for idx, h in enumerate(header):
                    if "date" not in col and ("value date" in h or ("date" in h and "trans" not in h)):
                        col["date"] = idx
                    if "description" not in col and any(k in h for k in DESCRIPTION_KEYS):
                        col["description"] = idx
                    if "debit" not in col and any(k in h for k in DEBIT_KEYS):
                        col["debit"] = idx
                    if "credit" not in col and any(k in h for k in CREDIT_KEYS):
                        col["credit"] = idx
                    if "amount" not in col and "debit" not in col and any(k in h for k in AMOUNT_KEYS):
                        col["amount"] = idx
                    if "reference" not in col and any(k in h for k in REFERENCE_KEYS):
                        col["reference"] = idx

                if "date" not in col:
                    continue

                for row in table[header_idx + 1:]:
                    if not row:
                        continue
                    try:
                        raw_date = row[col["date"]] if col.get("date") is not None else None
                        # Skip merged/bad rows (all remaining cells are None)
                        non_none = sum(1 for c in row if c is not None)
                        if non_none < 3:
                            continue
                        if not raw_date or str(raw_date).strip() in ("", "--"):
                            continue

                        tx_date = pd.to_datetime(str(raw_date).strip(), errors="coerce", dayfirst=True)
                        if pd.isna(tx_date):
                            continue

                        description = ""
                        if col.get("description") is not None:
                            description = str(row[col["description"]] or "").strip()

                        amount, tx_type = 0.0, "debit"
                        if "debit" in col and "credit" in col:
                            debit  = _parse_amount(row[col["debit"]])
                            credit = _parse_amount(row[col["credit"]])
                            if credit > 0:
                                amount, tx_type = credit, "credit"
                            else:
                                amount, tx_type = debit, "debit"
                        elif "amount" in col:
                            raw = str(row[col["amount"]] or "").strip()
                            val = _parse_amount(raw)
                            amount, tx_type = val, "debit" if raw.startswith("-") else "credit"

                        if amount == 0.0:
                            continue

                        reference = str(row[col["reference"]] or "").strip() or None if col.get("reference") is not None else None

                        rows.append({
                            "date": tx_date.date(),
                            "description": description,
                            "amount": amount,
                            "transaction_type": tx_type,
                            "reference": reference,
                        })
                    except Exception:
                        continue

    return rows


def _parse_pdf_statement(file_path: str) -> list[dict]:
    """
    Parse a PDF bank statement.
    Strategy (in order of preference):
      1. Regex on raw text  — handles OPay/Nigerian bank 8-column format reliably
      2. pdfplumber tables  — works when PDF has cleanly extracted table cells
      3. Text + AI          — last resort
    """
    # Strategy 1: regex line parser (fastest, most reliable for OPay format)
    try:
        rows = _parse_pdf_text_regex(file_path)
        if rows:
            logger.info(f"PDF regex parser: {len(rows)} rows found")
            return rows
    except Exception as e:
        logger.warning(f"PDF regex parser failed: {e}")

    # Strategy 2: pdfplumber table cells
    try:
        rows = _parse_pdf_tables(file_path)
        if rows:
            logger.info(f"PDF table extraction: {len(rows)} rows found")
            return rows
    except Exception as e:
        logger.warning(f"PDF table extraction failed: {e}")

    # Strategy 3: text + AI (last resort)
    logger.info("Falling back to AI-based PDF parsing")
    text = ai_worker._extract_pdf_text(file_path)
    if not text:
        return []

    prompt = (
        "Extract all bank transactions from this statement text.\n"
        "Return ONLY a JSON array with keys: date (YYYY-MM-DD), description, amount (number), "
        "transaction_type (debit or credit).\n\n"
        f"Statement text:\n{text[:4000]}\n\nReturn JSON array only, no explanation:"
    )
    try:
        import httpx
        with httpx.Client(timeout=120.0) as client:
            resp = client.post(
                f"{ai_worker.OLLAMA_URL}/api/generate",
                json={"model": ai_worker.OLLAMA_TEXT_MODEL, "prompt": prompt, "stream": False, "options": {"temperature": 0.1}},
            )
            resp.raise_for_status()
            raw = resp.json().get("response", "")
        raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL)
        arr_match = re.search(r"\[[\s\S]*\]", raw)
        if arr_match:
            data = json.loads(arr_match.group())
            rows = []
            for item in data:
                try:
                    rows.append({
                        "date": date.fromisoformat(item["date"]),
                        "description": str(item.get("description", "")),
                        "amount": abs(float(item.get("amount", 0))),
                        "transaction_type": item.get("transaction_type", "debit"),
                        "reference": None,
                    })
                except Exception:
                    continue
            return rows
    except Exception:
        pass
    return []


@router.post("", response_model=BankStatementOut, status_code=201)
async def upload_bank_statement(
    file: UploadFile = File(...),
    bank_name: str = Form(...),
    db: Session = Depends(get_db),
):
    contents = await file.read()
    file_type = _detect_file_type(file.content_type or "", file.filename or "")

    ext = Path(file.filename or "file").suffix
    stored_name = f"{uuid.uuid4().hex}{ext}"
    stored_path = UPLOAD_DIR / stored_name
    stored_path.write_bytes(contents)

    if file_type == "csv":
        rows = _parse_csv(contents)
    elif file_type == "excel":
        rows = _parse_excel(contents)
    else:
        rows = _parse_pdf_statement(str(stored_path))

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


@router.post("/{stmt_id}/import-transactions", response_model=list[TransactionOut], status_code=201)
def import_statement_transactions(
    stmt_id: int,
    req: StatementImportRequest,
    db: Session = Depends(get_db),
):
    """
    Convert selected BankTransactions into real Transactions.
    The bank name from the statement is stored on each transaction.
    """
    stmt = db.get(BankStatement, stmt_id)
    if not stmt:
        raise HTTPException(404, "Statement not found")

    saved = []
    for item in req.items:
        bank_tx = db.get(BankTransaction, item.bank_transaction_id)
        if not bank_tx or bank_tx.statement_id != stmt_id:
            continue

        tx = Transaction(
            type=item.type,
            amount=item.amount,
            currency=item.currency,
            category=item.category,
            description=item.description,
            date=item.date,
            vendor=item.vendor,
            bank=stmt.bank_name,
        )
        db.add(tx)
        db.flush()

        db.add(AuditLog(
            entity_type="transaction",
            entity_id=tx.id,
            action="create",
            new_values=json.dumps({
                "type": item.type, "amount": item.amount,
                "category": item.category, "description": item.description,
                "date": str(item.date), "bank": stmt.bank_name,
                "source": "statement_import",
            }),
        ))
        saved.append(tx)

    db.commit()
    for tx in saved:
        db.refresh(tx)
    return saved
