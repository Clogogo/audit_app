"""Payroll reconciliation endpoint — upload a payroll schedule (Excel/CSV) and
compare it with what was actually paid out of the bank account. Read-only:
nothing is written to the database."""
import calendar
import logging
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models import BankAccount, Transaction
from utils.auth import require_permission
from utils.payroll_recon import ScheduleError, parse_schedule_full, reconcile

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/payroll", tags=["payroll"], dependencies=[Depends(require_permission("staff"))])

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
SALARY_CATEGORY = "Salary and Wages"


class ReconcileLine(BaseModel):
    row_number: int
    name: str
    account_number: Optional[str]
    expected_amount: float
    paid_amount: float
    difference: float
    status: str  # matched | underpaid | overpaid | not_paid
    transaction_ids: list[int]
    paid_to: Optional[str]
    paid_date: Optional[date]
    note: Optional[str] = None


class SkippedRowOut(BaseModel):
    row_number: int
    reason: str
    ignored: bool = False
    label: str = ""


class UnmatchedTransaction(BaseModel):
    id: int
    date: date
    amount: float
    description: str
    vendor: Optional[str]


class ReconcileSummary(BaseModel):
    rows: int
    matched: int
    underpaid: int
    overpaid: int
    not_paid: int
    expected_total: float
    paid_total: float
    unmatched_payments: int
    unmatched_total: float


class ReconcileOut(BaseModel):
    year: int
    month: int
    lines: list[ReconcileLine]
    skipped_rows: list[SkippedRowOut]
    notes: list[str]
    unmatched_transactions: list[UnmatchedTransaction]
    summary: ReconcileSummary


def _read_limited(file: UploadFile) -> bytes:
    content = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"File too large (limit {MAX_UPLOAD_BYTES // (1024 * 1024)} MB).")
    return content


@router.post("/reconcile", response_model=ReconcileOut)
def reconcile_payroll(
    file: UploadFile = File(...),
    year: int = Form(..., ge=2000, le=2100),
    month: int = Form(..., ge=1, le=12),
    bank_account_id: Optional[int] = Form(None),
    db: Session = Depends(get_db),
):
    """Compare an uploaded payroll schedule with the month's Salary and Wages
    expense transactions (optionally limited to one bank account)."""
    content = _read_limited(file)
    try:
        parsed = parse_schedule_full(content, file.filename or "")
    except ScheduleError as exc:
        raise HTTPException(400, str(exc)) from exc

    if bank_account_id is not None and db.get(BankAccount, bank_account_id) is None:
        raise HTTPException(404, "Bank account not found.")

    month_start = date(year, month, 1)
    month_end = date(year, month, calendar.monthrange(year, month)[1])
    query = db.query(Transaction).filter(
        Transaction.type == "expense",
        Transaction.category == SALARY_CATEGORY,
        Transaction.date >= month_start,
        Transaction.date <= month_end,
    )
    if bank_account_id is not None:
        query = query.filter(Transaction.bank_account_id == bank_account_id)

    result = reconcile(parsed.rows, query.all())
    logger.info("Payroll reconcile %04d-%02d: %s", year, month, result["summary"])
    return {"year": year, "month": month, "skipped_rows": [vars(r) for r in parsed.skipped], "notes": parsed.notes, **result}
