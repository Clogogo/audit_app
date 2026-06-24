"""
Payroll calculator — monthly payroll computation and processing.
Gross → loan deductions → other deductions → net salary.
Processing creates salary expense transactions and saves PayrollEntry records.
"""
import calendar
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models import PayrollEntry, Staff, StaffLoan, Transaction

router = APIRouter(prefix="/payroll", tags=["payroll"])


def _active_loans_for_staff(staff_id: int, employee_name: str, db: Session) -> list[StaffLoan]:
    """Return active loans matching this staff member."""
    from sqlalchemy import or_
    return (
        db.query(StaffLoan)
        .filter(
            StaffLoan.is_active == True,
            or_(
                StaffLoan.staff_id == staff_id,
                StaffLoan.employee_name.ilike(f"%{employee_name}%"),
            ),
        )
        .all()
    )


def _loan_deduction_for_month(staff: Staff, year: int, month: int, db: Session) -> float:
    """Total loan deduction for a staff member in a given month."""
    last_day = calendar.monthrange(year, month)[1]
    period_end = date(year, month, last_day)

    loans = _active_loans_for_staff(staff.id, staff.full_name, db)
    total = 0.0
    for loan in loans:
        if loan.deduction_start > period_end:
            continue
        rate = loan.deduction_rate if loan.deduction_rate is not None else 0.5
        total += staff.monthly_gross * rate

    return round(min(total, staff.monthly_gross), 2)


# ── Pydantic models ────────────────────────────────────────────────────────────

class PayrollLineIn(BaseModel):
    staff_id: int
    gross_salary: float
    bonus: float = 0.0
    other_deductions: float = 0.0
    notes: Optional[str] = None


class PayrollLineOut(BaseModel):
    staff_id: int
    full_name: str
    role: Optional[str]
    gross_salary: float
    bonus: float
    loan_deduction: float
    other_deductions: float
    net_salary: float
    is_paid: bool
    paid_date: Optional[date]
    entry_id: Optional[int]  # None if not yet processed


class ProcessRequest(BaseModel):
    year: int
    month: int
    lines: list[PayrollLineIn]


class PayrollEntryOut(BaseModel):
    id: int
    staff_id: int
    full_name: str
    period_year: int
    period_month: int
    gross_salary: float
    bonus: float
    loan_deduction: float
    other_deductions: float
    net_salary: float
    is_paid: bool
    paid_date: Optional[date]
    transaction_id: Optional[int]
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/compute", response_model=list[PayrollLineOut])
def compute_payroll(year: int, month: int, db: Session = Depends(get_db)):
    """Compute payroll for all active staff for the given month.
    Only includes staff who had started by the last day of the month and
    had not yet ended before the first day of the month.
    Returns existing processed entries if available, or fresh calculation otherwise.
    """
    from sqlalchemy import or_
    month_first = date(year, month, 1)
    month_last  = date(year, month, calendar.monthrange(year, month)[1])

    staff_list = (
        db.query(Staff)
        .filter(
            Staff.is_active == True,
            # started on or before the last day of this month (or no start date set)
            or_(Staff.start_date == None, Staff.start_date <= month_last),  # noqa: E711
            # not yet ended before the first day of this month (or no end date set)
            or_(Staff.end_date == None, Staff.end_date >= month_first),     # noqa: E711
        )
        .order_by(Staff.full_name)
        .all()
    )

    result: list[PayrollLineOut] = []
    for s in staff_list:
        existing: Optional[PayrollEntry] = (
            db.query(PayrollEntry)
            .filter(
                PayrollEntry.staff_id == s.id,
                PayrollEntry.period_year == year,
                PayrollEntry.period_month == month,
            )
            .first()
        )

        if existing:
            result.append(PayrollLineOut(
                staff_id=s.id,
                full_name=s.full_name,
                role=s.role,
                gross_salary=existing.gross_salary,
                bonus=existing.bonus,
                loan_deduction=existing.loan_deduction,
                other_deductions=existing.other_deductions,
                net_salary=existing.net_salary,
                is_paid=bool(existing.is_paid),
                paid_date=existing.paid_date,
                entry_id=existing.id,
            ))
        else:
            loan_ded = _loan_deduction_for_month(s, year, month, db)
            net = round(s.monthly_gross - loan_ded, 2)
            result.append(PayrollLineOut(
                staff_id=s.id,
                full_name=s.full_name,
                role=s.role,
                gross_salary=s.monthly_gross,
                bonus=0.0,
                loan_deduction=loan_ded,
                other_deductions=0.0,
                net_salary=net,
                is_paid=False,
                paid_date=None,
                entry_id=None,
            ))

    return result


@router.post("/process", response_model=list[PayrollEntryOut])
def process_payroll(req: ProcessRequest, db: Session = Depends(get_db)):
    """Process payroll for a month.
    Each staff member must have a salary expense transaction already recorded in
    the transactions table for this month before payroll can be marked as paid.
    """
    from sqlalchemy import or_

    month_start = date(req.year, req.month, 1)
    month_end   = date(req.year, req.month, calendar.monthrange(req.year, req.month)[1])

    # ── Phase 1: resolve transactions for ALL staff before saving anything ────
    missing: list[str] = []
    tx_map: dict[int, int] = {}  # staff_id → transaction.id

    for line in req.lines:
        staff = db.get(Staff, line.staff_id)
        if not staff:
            raise HTTPException(404, f"Staff {line.staff_id} not found")

        # If the entry already has a linked transaction (e.g. previously processed
        # then reset), keep that link without re-searching.
        existing_entry: Optional[PayrollEntry] = (
            db.query(PayrollEntry)
            .filter(
                PayrollEntry.staff_id == line.staff_id,
                PayrollEntry.period_year == req.year,
                PayrollEntry.period_month == req.month,
            )
            .first()
        )
        if existing_entry and existing_entry.transaction_id:
            tx_map[line.staff_id] = existing_entry.transaction_id
            continue

        # Search for a matching salary expense transaction in this month
        tx = (
            db.query(Transaction)
            .filter(
                Transaction.type == "expense",
                Transaction.date >= month_start,
                Transaction.date <= month_end,
                or_(
                    Transaction.vendor.ilike(f"%{staff.full_name}%"),
                    Transaction.description.ilike(f"%{staff.full_name}%"),
                ),
            )
            .first()
        )

        if tx:
            tx_map[line.staff_id] = tx.id
        else:
            missing.append(staff.full_name)

    if missing:
        raise HTTPException(
            status_code=422,
            detail={
                "message": (
                    f"Cannot process payroll: salary transactions not found "
                    f"for {len(missing)} staff member(s)"
                ),
                "missing": missing,
                "hint": (
                    f"Go to Transactions and record an expense transaction for "
                    f"each missing staff member dated in "
                    f"{req.year}-{req.month:02d}, then try again."
                ),
            },
        )

    # ── Phase 2: all transactions verified — upsert payroll entries ───────────
    saved: list[PayrollEntry] = []

    for line in req.lines:
        staff = db.get(Staff, line.staff_id)
        loan_ded = _loan_deduction_for_month(staff, req.year, req.month, db)
        net = round(line.gross_salary + line.bonus - loan_ded - line.other_deductions, 2)
        pay_date = date(req.year, req.month, calendar.monthrange(req.year, req.month)[1])

        entry: Optional[PayrollEntry] = (
            db.query(PayrollEntry)
            .filter(
                PayrollEntry.staff_id == line.staff_id,
                PayrollEntry.period_year == req.year,
                PayrollEntry.period_month == req.month,
            )
            .first()
        )
        if not entry:
            entry = PayrollEntry(
                staff_id=line.staff_id,
                period_year=req.year,
                period_month=req.month,
            )
            db.add(entry)

        entry.gross_salary   = line.gross_salary
        entry.bonus          = line.bonus
        entry.loan_deduction = loan_ded
        entry.other_deductions = line.other_deductions
        entry.net_salary     = net
        entry.notes          = line.notes
        entry.transaction_id = tx_map[line.staff_id]
        entry.is_paid        = True
        entry.paid_date      = pay_date
        entry.updated_at     = datetime.utcnow()

        db.commit()
        db.refresh(entry)
        saved.append(entry)

    from routers.financial_statements import _cache_bust
    _cache_bust()

    result = []
    for e in saved:
        s = db.get(Staff, e.staff_id)
        result.append(PayrollEntryOut(
            id=e.id,
            staff_id=e.staff_id,
            full_name=s.full_name if s else "",
            period_year=e.period_year,
            period_month=e.period_month,
            gross_salary=e.gross_salary,
            bonus=e.bonus,
            loan_deduction=e.loan_deduction,
            other_deductions=e.other_deductions,
            net_salary=e.net_salary,
            is_paid=bool(e.is_paid),
            paid_date=e.paid_date,
            transaction_id=e.transaction_id,
            notes=e.notes,
            created_at=e.created_at,
            updated_at=e.updated_at,
        ))
    return result


def _is_auto_created_tx(tx: Transaction) -> bool:
    """True if the transaction was auto-generated by the old process_payroll logic."""
    return (
        tx.category == "Salary and Wages"
        and tx.description.startswith("Salary — ")
        and tx.bank_account_id is None
    )


@router.post("/reset")
def reset_payroll(year: int, month: int, db: Session = Depends(get_db)):
    """Mark all payroll entries for a month as unpaid.
    Any auto-created salary transactions (not from a bank statement import) are
    deleted so the user must re-verify against imported transactions before
    re-processing.
    """
    entries = (
        db.query(PayrollEntry)
        .filter(PayrollEntry.period_year == year, PayrollEntry.period_month == month)
        .all()
    )
    deleted_tx = 0
    for e in entries:
        if e.transaction_id:
            tx = db.get(Transaction, e.transaction_id)
            if tx and _is_auto_created_tx(tx):
                e.transaction_id = None
                db.delete(tx)
                deleted_tx += 1
            else:
                # Bank-imported transaction — keep it but unlink from the entry
                e.transaction_id = None
        e.is_paid = False
        e.paid_date = None
        e.updated_at = datetime.utcnow()
    db.commit()

    from routers.financial_statements import _cache_bust
    _cache_bust()

    return {"reset": len(entries), "deleted_transactions": deleted_tx, "year": year, "month": month}


@router.delete("/purge-auto-transactions")
def purge_auto_transactions(db: Session = Depends(get_db)):
    """One-time cleanup: delete all salary transactions that were auto-created by
    the old process_payroll logic (not imported from a bank statement), and clear
    the transaction_id link on the associated payroll entries.
    """
    entries_with_tx = (
        db.query(PayrollEntry)
        .filter(PayrollEntry.transaction_id.isnot(None))
        .all()
    )
    deleted = 0
    unlinked = 0
    for e in entries_with_tx:
        tx = db.get(Transaction, e.transaction_id)
        if tx and _is_auto_created_tx(tx):
            e.transaction_id = None
            db.delete(tx)
            deleted += 1
        else:
            e.transaction_id = None
            unlinked += 1
    db.commit()

    from routers.financial_statements import _cache_bust
    _cache_bust()

    return {"deleted_transactions": deleted, "unlinked_entries": unlinked}


@router.get("/entries", response_model=list[PayrollEntryOut])
def get_payroll_entries(year: int, month: int, db: Session = Depends(get_db)):
    """Return all processed payroll entries for a month."""
    entries = (
        db.query(PayrollEntry)
        .filter(PayrollEntry.period_year == year, PayrollEntry.period_month == month)
        .all()
    )
    result = []
    for e in entries:
        s = db.get(Staff, e.staff_id)
        result.append(PayrollEntryOut(
            id=e.id,
            staff_id=e.staff_id,
            full_name=s.full_name if s else "",
            period_year=e.period_year,
            period_month=e.period_month,
            gross_salary=e.gross_salary,
            bonus=e.bonus,
            loan_deduction=e.loan_deduction,
            other_deductions=e.other_deductions,
            net_salary=e.net_salary,
            is_paid=bool(e.is_paid),
            paid_date=e.paid_date,
            transaction_id=e.transaction_id,
            notes=e.notes,
            created_at=e.created_at,
            updated_at=e.updated_at,
        ))
    return result
