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
from models import Staff, Transaction
from utils.auth import require_permission
from utils.payroll_recon import ScheduleError, link_staff_to_rows, parse_schedule_full, reconcile, within_tolerance

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
    extra_payment_ids: list[int] = []   # other payments that look like this person's: possible duplicate
    extra_paid_amount: float = 0.0
    # Staff-directory cross-check (filled when the row can be linked to a staff member)
    staff_id: Optional[int] = None
    staff_name: Optional[str] = None
    computed_net: Optional[float] = None
    net_difference: Optional[float] = None   # computed - schedule
    in_sync: Optional[bool] = None           # computed net within ₦100 of the schedule


class SkippedRowOut(BaseModel):
    row_number: int
    reason: str
    ignored: bool = False
    label: str = ""


class UnlinkedStaff(BaseModel):
    staff_id: int
    full_name: str
    computed_net: float


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
    unlinked_staff: list[UnlinkedStaff]
    unmatched_transactions: list[UnmatchedTransaction]
    summary: ReconcileSummary


def _read_limited(file: UploadFile) -> bytes:
    content = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"File too large (limit {MAX_UPLOAD_BYTES // (1024 * 1024)} MB).")
    return content


def _with_directory_check(result: dict, rows: list, year: int, month: int, db: Session) -> dict:
    """Attach, to each reconciled row, the staff member it belongs to and
    whether the directory's computed net pay agrees with the schedule."""
    from routers.payroll import compute_payroll

    payroll = compute_payroll(year, month, db)
    staff = db.query(Staff).filter(Staff.id.in_([p.staff_id for p in payroll])).all() if payroll else []
    links = link_staff_to_rows(staff, rows)
    net_by_staff = {p.staff_id: p.net_salary for p in payroll}
    names = {s.id: s.full_name for s in staff}
    staff_by_row = {row.row_number: sid for sid, row in links.items()}

    def enrich(line: dict) -> dict:
        sid = staff_by_row.get(line["row_number"])
        if sid is None:
            return line
        computed = round(net_by_staff[sid], 2)
        gap = round(computed - line["expected_amount"], 2)
        return {**line, "staff_id": sid, "staff_name": names[sid], "computed_net": computed,
                "net_difference": gap, "in_sync": within_tolerance(round(gap * 100))}

    return {
        **result,
        "lines": [enrich(ln) for ln in result["lines"]],
        "unlinked_staff": [
            {"staff_id": p.staff_id, "full_name": p.full_name, "computed_net": round(p.net_salary, 2)}
            for p in payroll if p.staff_id not in links
        ],
    }


@router.post("/reconcile", response_model=ReconcileOut)
def reconcile_payroll(
    file: UploadFile = File(...),
    year: int = Form(..., ge=2000, le=2100),
    month: int = Form(..., ge=1, le=12),
    db: Session = Depends(get_db),
):
    """Compare a payroll schedule (uploaded or pasted) with the month's Salary
    and Wages bank payments, and cross-check each row against the staff
    directory's computed net pay."""
    content = _read_limited(file)
    try:
        parsed = parse_schedule_full(content, file.filename or "")
    except ScheduleError as exc:
        raise HTTPException(400, str(exc)) from exc

    month_start = date(year, month, 1)
    month_end = date(year, month, calendar.monthrange(year, month)[1])
    query = db.query(Transaction).filter(
        Transaction.type == "expense",
        Transaction.category == SALARY_CATEGORY,
        Transaction.date >= month_start,
        Transaction.date <= month_end,
    )
    result = _with_directory_check(reconcile(parsed.rows, query.all()), parsed.rows, year, month, db)
    logger.info("Payroll reconcile %04d-%02d: %s", year, month, result["summary"])
    return {"year": year, "month": month, "skipped_rows": [vars(r) for r in parsed.skipped], "notes": parsed.notes, **result}
