"""Payroll reconciliation — upload a payroll schedule (Excel/CSV) and compare it with what was
actually paid out of the bank account. The schedule is kept for the month (so it can be reopened);
the comparison itself is recomputed each time, so it always reflects the current bank and directory."""
import calendar
import json
import logging
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_db
from models import PayrollEntry, PayrollReconciliation, Staff, Transaction
from utils.auth import require_permission
from utils.payroll_recon import ScheduleError, ScheduleRow, check_account, link_and_fill, parse_schedule_full, reconcile, within_tolerance

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/payroll", tags=["payroll"], dependencies=[Depends(require_permission("staff"))])

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
SALARY_CATEGORY = "Salary and Wages"


class SuggestedPayment(BaseModel):
    id: int
    date: date
    amount: float
    vendor: Optional[str] = None
    account: Optional[str] = None
    bank: Optional[str] = None


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
    paid_account: Optional[str] = None       # account/bank the bank actually paid (the truth)
    paid_bank: Optional[str] = None
    suggested_payments: list[SuggestedPayment] = []
    account_source: Optional[str] = None     # 'sheet' | 'directory': where the row's account number came from
    directory_account: Optional[str] = None
    account_check: Optional[str] = None      # 'ok' | 'missing' | 'differs' (directory vs the paid account)
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
    account: Optional[str] = None
    bank: Optional[str] = None


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
    saved_at: Optional[datetime] = None


def _read_limited(file: UploadFile) -> bytes:
    content = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"File too large (limit {MAX_UPLOAD_BYTES // (1024 * 1024)} MB).")
    return content


def _reconcile_with_directory(rows: list, payments: list, year: int, month: int, db: Session) -> dict:
    """Reconcile the schedule, filling a blank account number from the staff
    directory first, then attach to each row the staff member it belongs to,
    whether the directory's computed net agrees, and whether the directory's
    account matches the account the bank actually paid."""
    from routers.payroll import compute_payroll

    payroll = compute_payroll(year, month, db)
    staff = db.query(Staff).filter(Staff.id.in_([p.staff_id for p in payroll])).all() if payroll else []
    filled, links, sources = link_and_fill(rows, staff)
    result = reconcile(filled, payments)

    net_by_staff = {p.staff_id: p.net_salary for p in payroll}
    staff_by_id = {s.id: s for s in staff}
    staff_by_row = {row.row_number: sid for sid, row in links.items()}

    def enrich(line: dict) -> dict:
        line = {**line, "account_source": sources.get(line["row_number"])}
        sid = staff_by_row.get(line["row_number"])
        if sid is None:
            return line
        computed = round(net_by_staff[sid], 2)
        gap = round(computed - line["expected_amount"], 2)
        directory = staff_by_id[sid].account_number or None
        return {**line, "staff_id": sid, "staff_name": staff_by_id[sid].full_name, "computed_net": computed,
                "net_difference": gap, "in_sync": within_tolerance(round(gap * 100)),
                "directory_account": directory, "account_check": check_account(directory, line["paid_account"])}

    return {
        **result,
        "lines": [enrich(ln) for ln in result["lines"]],
        "unlinked_staff": [
            {"staff_id": p.staff_id, "full_name": p.full_name, "computed_net": round(p.net_salary, 2)}
            for p in payroll if p.staff_id not in links
        ],
    }


def _bank_payments(year: int, month: int, db: Session) -> list:
    month_start = date(year, month, 1)
    month_end = date(year, month, calendar.monthrange(year, month)[1])
    return db.query(Transaction).filter(
        Transaction.type == "expense", Transaction.category == SALARY_CATEGORY,
        Transaction.date >= month_start, Transaction.date <= month_end,
    ).all()


def _output(year: int, month: int, rows: list, skipped: list, notes: list, saved_at: Optional[datetime], db: Session) -> dict:
    result = _reconcile_with_directory(rows, _bank_payments(year, month, db), year, month, db)
    logger.info("Payroll reconcile %04d-%02d: %s", year, month, result["summary"])
    return {"year": year, "month": month, "skipped_rows": skipped, "notes": notes, "saved_at": saved_at, **result}


@router.post("/reconcile", response_model=ReconcileOut)
def reconcile_payroll(
    file: UploadFile = File(...),
    year: int = Form(..., ge=2000, le=2100),
    month: int = Form(..., ge=1, le=12),
    db: Session = Depends(get_db),
):
    """Compare a payroll schedule (uploaded or pasted) with the month's Salary and Wages bank payments,
    cross-check each row against the staff directory's computed net pay, and keep the schedule for the month."""
    try:
        parsed = parse_schedule_full(_read_limited(file), file.filename or "")
    except ScheduleError as exc:
        raise HTTPException(400, str(exc)) from exc
    skipped = [vars(r) for r in parsed.skipped]
    payload = json.dumps({"rows": [vars(r) for r in parsed.rows], "skipped": skipped, "notes": parsed.notes})
    saved = db.query(PayrollReconciliation).filter_by(period_year=year, period_month=month).first()
    if saved:
        saved.schedule_json = payload
    else:
        saved = PayrollReconciliation(period_year=year, period_month=month, schedule_json=payload)
        db.add(saved)
    db.commit()
    db.refresh(saved)
    return _output(year, month, parsed.rows, skipped, parsed.notes, saved.saved_at, db)


@router.get("/reconcile/saved", response_model=Optional[ReconcileOut])
def saved_reconciliation(year: int, month: int, db: Session = Depends(get_db)):
    """The month's saved schedule, compared with the bank and the staff directory as they are now (null if none)."""
    saved = db.query(PayrollReconciliation).filter_by(period_year=year, period_month=month).first()
    if saved is None:
        return None
    data = json.loads(saved.schedule_json)
    return _output(year, month, [ScheduleRow(**r) for r in data["rows"]], data["skipped"], data["notes"], saved.saved_at, db)


class DeductionIn(BaseModel):
    year: int = Field(ge=2000, le=2100)
    month: int = Field(ge=1, le=12)
    staff_id: int
    amount: float = Field(gt=0, le=100_000_000)


@router.post("/other-deduction")
def add_other_deduction(body: DeductionIn, db: Session = Depends(get_db)):
    """Add an amount to a staff member's 'other deductions' for a month that is not processed yet
    (used when the schedule pays less than the staff directory expects)."""
    from routers.payroll import compute_payroll

    line = next((p for p in compute_payroll(body.year, body.month, db) if p.staff_id == body.staff_id), None)
    if line is None:
        raise HTTPException(404, "That staff member is not on the payroll for this month.")
    if line.is_paid:
        raise HTTPException(409, "This month is already processed for that staff member.")
    other = round(line.other_deductions + body.amount, 2)
    net = max(0.0, round(line.gross_salary + line.bonus - line.loan_deduction - line.advance_deduction - other, 2))
    entry = db.query(PayrollEntry).filter_by(staff_id=body.staff_id, period_year=body.year, period_month=body.month).first()
    if entry is None:
        entry = PayrollEntry(staff_id=body.staff_id, period_year=body.year, period_month=body.month, is_paid=False)
        db.add(entry)
    entry.gross_salary, entry.bonus = line.gross_salary, line.bonus
    entry.loan_deduction, entry.advance_deduction = line.loan_deduction, line.advance_deduction
    entry.other_deductions, entry.net_salary = other, net
    db.commit()
    return {"staff_id": body.staff_id, "other_deductions": other, "net_salary": net}
