"""
Payroll calculator — monthly payroll computation and processing.
Gross → loan deductions → other deductions → net salary.
Processing creates salary expense transactions and saves PayrollEntry records.
"""
import calendar
import re
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from utils.auth import get_current_user
from pydantic import BaseModel
from rapidfuzz import fuzz
from sqlalchemy.orm import Session

from database import get_db
from models import AdvancePayment, PayrollEntry, Staff, StaffLoan, StaffLoanPayment, Transaction

router = APIRouter(prefix="/payroll", tags=["payroll"], dependencies=[Depends(get_current_user)])


_NAME_TITLES = {"mr", "mrs", "miss", "ms", "mstr", "dr", "mister", "engr", "chief", "elder", "pastor"}


_MIN_FUZZY_TOKEN_LEN = 4  # tokens shorter than this only match exactly (see _tokens_match)


def _normalize_name_tokens(name: str) -> list[str]:
    """Lowercase, strip punctuation and honorifics, split into tokens."""
    cleaned = re.sub(r"[^a-z0-9\s]", " ", name.lower())
    return [t for t in cleaned.split() if t not in _NAME_TITLES and len(t) >= 2]


def _tokens_match(st: str, tt: str) -> bool:
    """True if two name tokens refer to the same word — exact match always
    counts; fuzzy similarity only kicks in for tokens of at least
    _MIN_FUZZY_TOKEN_LEN characters. Short tokens (e.g. "anu", "ola") are too
    likely to coincidentally appear as substrings of unrelated words (e.g.
    "anu" inside "january") for partial_ratio to be safe at that length."""
    if st == tt:
        return True
    if len(st) < _MIN_FUZZY_TOKEN_LEN or len(tt) < _MIN_FUZZY_TOKEN_LEN:
        return False
    return fuzz.ratio(st, tt) >= 80 or fuzz.partial_ratio(st, tt) >= 90


def _name_matches_text(staff_name: str, text: str) -> bool:
    """True if most significant name tokens are present in text, in any order,
    tolerating reordered names, missing/extra titles, dropped middle names,
    and minor spelling differences typical of bank narrations."""
    staff_tokens = _normalize_name_tokens(staff_name)
    text_tokens = _normalize_name_tokens(text)
    if not staff_tokens or not text_tokens:
        return False

    matched = sum(
        1
        for st in staff_tokens
        if any(_tokens_match(st, tt) for tt in text_tokens)
    )
    min_required = 2 if len(staff_tokens) >= 2 else 1
    return matched >= min_required and (matched / len(staff_tokens)) >= 0.6


def _has_any_name_token_overlap(staff_name: str, text: str) -> bool:
    """True if at least one significant name token (e.g. a surname) appears in
    text. Looser than _name_matches_text — used only as a sanity check
    alongside category+amount validation, for cases where the bank account is
    registered under a different first/middle name than the staff record
    (e.g. a spouse's name, or a maiden name)."""
    staff_tokens = _normalize_name_tokens(staff_name)
    text_tokens = _normalize_name_tokens(text)
    if not staff_tokens or not text_tokens:
        return False
    return any(
        _tokens_match(st, tt)
        for st in staff_tokens
        for tt in text_tokens
    )


def _loans_for_staff(staff_id: int, employee_name: str, db: Session) -> list[StaffLoan]:
    """Return all loans matching this staff member, active or not — a
    payment recorded for a loan that has since been paid off (is_active
    flipped to False on the final payment) must still count toward the
    month it was actually made in."""
    from sqlalchemy import or_
    return (
        db.query(StaffLoan)
        .filter(
            or_(
                StaffLoan.staff_id == staff_id,
                StaffLoan.employee_name.ilike(f"%{employee_name}%"),
            ),
        )
        .all()
    )


def _loan_deduction_for_month(staff: Staff, year: int, month: int, db: Session) -> float:
    """Total loan deduction for a staff member in a given month — the sum of
    StaffLoanPayment.amount_paid actually recorded (via the Staff Loans page)
    against that staff's loan(s) with paid_date in the period. Reflects what
    was really repaid, not a gross*deduction_rate estimate that could drift
    from reality once a loan is partway paid off."""
    month_start = date(year, month, 1)
    month_end = date(year, month, calendar.monthrange(year, month)[1])

    loan_ids = [loan.id for loan in _loans_for_staff(staff.id, staff.full_name, db)]
    if not loan_ids:
        return 0.0

    from sqlalchemy import func
    total = db.query(func.sum(StaffLoanPayment.amount_paid)).filter(
        StaffLoanPayment.loan_id.in_(loan_ids),
        StaffLoanPayment.paid_date >= month_start,
        StaffLoanPayment.paid_date <= month_end,
    ).scalar() or 0.0

    # Sanity cap, not a reintroduction of the old gross*rate estimate: a
    # mis-recorded payment exceeding the staff's gross would otherwise drive
    # net_salary negative and make the salary-transaction fallback match
    # (amount >= net) accept any transaction at all.
    return round(min(total, staff.monthly_gross), 2)


def _advance_deduction_for_month(staff: Staff, year: int, month: int, db: Session) -> float:
    """Total advance/IOU deduction for a staff member in a given month — the
    sum of AdvancePayment.amount for advances not yet recovered, issued on
    or before this period's end. An advance becomes eligible for recovery
    in whichever payroll period is next *processed* after it's recorded —
    this picks it up regardless of exact calendar timing, then
    process_payroll marks it is_recovered so it's never deducted twice."""
    period_end = date(year, month, calendar.monthrange(year, month)[1])

    from sqlalchemy import func
    total = db.query(func.sum(AdvancePayment.amount)).filter(
        AdvancePayment.staff_id == staff.id,
        AdvancePayment.is_recovered == False,  # noqa: E712
        AdvancePayment.date_issued <= period_end,
    ).scalar() or 0.0

    return round(min(total, staff.monthly_gross), 2)


def _capped_deductions(
    staff: Staff, year: int, month: int, gross: float, bonus: float, other_deductions: float, db: Session,
) -> tuple[float, float]:
    """_loan_deduction_for_month and _advance_deduction_for_month each cap
    against the Staff record's current monthly_gross individually, but a
    specific payroll line (a draft override, or a submitted process_payroll
    line) may use its own reduced gross/bonus — and capping each deduction
    independently against that line's earnings could still let their SUM
    exceed what's available. Cap them together instead: loan first, then
    advance fills whatever room is left. Doesn't guarantee net_salary >= 0
    on its own — other_deductions alone could still exceed gross + bonus,
    independent of either of these."""
    available = max(0.0, gross + bonus - other_deductions)
    loan_ded = min(_loan_deduction_for_month(staff, year, month, db), available)
    advance_ded = min(_advance_deduction_for_month(staff, year, month, db), available - loan_ded)
    return round(loan_ded, 2), round(advance_ded, 2)


def _recover_advances_for_month(staff: Staff, year: int, month: int, applied_amount: float, db: Session) -> None:
    """Mark this staff's not-yet-recovered advances as recovered for this
    period — but only if `applied_amount` (the actual deduction applied,
    after _capped_deductions' line-specific capping) covers their full
    outstanding sum. A partially-capped advance is left unrecovered so it
    rolls over and gets picked up again next period, rather than being
    marked recovered for less than it's actually worth."""
    period_end = date(year, month, calendar.monthrange(year, month)[1])
    advances = (
        db.query(AdvancePayment)
        .filter(
            AdvancePayment.staff_id == staff.id,
            AdvancePayment.is_recovered == False,  # noqa: E712
            AdvancePayment.date_issued <= period_end,
        )
        .all()
    )
    if not advances:
        return

    full_sum = round(sum(a.amount for a in advances), 2)
    if applied_amount + 0.01 < full_sum:
        return

    for advance in advances:
        advance.is_recovered = True
        advance.recovered_period_year = year
        advance.recovered_period_month = month


# ── Pydantic models ────────────────────────────────────────────────────────────

class PayrollLineIn(BaseModel):
    staff_id: int
    gross_salary: float
    bonus: float = 0.0
    other_deductions: float = 0.0
    notes: Optional[str] = None
    transaction_id: Optional[int] = None  # manual override of automatic matching


class PayrollLineOut(BaseModel):
    staff_id: int
    full_name: str
    role: Optional[str]
    gross_salary: float
    bonus: float
    loan_deduction: float
    advance_deduction: float
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
    advance_deduction: float
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

        if existing and existing.is_paid:
            # A truly processed entry is a frozen historical record — show
            # exactly what was paid, not a live recalculation.
            result.append(PayrollLineOut(
                staff_id=s.id,
                full_name=s.full_name,
                role=s.role,
                gross_salary=existing.gross_salary,
                bonus=existing.bonus,
                loan_deduction=existing.loan_deduction,
                advance_deduction=existing.advance_deduction,
                other_deductions=existing.other_deductions,
                net_salary=existing.net_salary,
                is_paid=bool(existing.is_paid),
                paid_date=existing.paid_date,
                entry_id=existing.id,
            ))
        elif existing:
            # Not yet paid (e.g. skipped, or reset via "Edit Payroll") — the
            # stored loan_deduction/advance_deduction is a stale snapshot
            # from whenever this row was last touched, which can predate
            # loan payments or advances recorded since. Recompute it live;
            # keep the user's own gross/bonus/other overrides rather than
            # discarding their draft edits.
            loan_ded, advance_ded = _capped_deductions(
                s, year, month, existing.gross_salary, existing.bonus, existing.other_deductions, db,
            )
            net = round(existing.gross_salary + existing.bonus - loan_ded - advance_ded - existing.other_deductions, 2)
            result.append(PayrollLineOut(
                staff_id=s.id,
                full_name=s.full_name,
                role=s.role,
                gross_salary=existing.gross_salary,
                bonus=existing.bonus,
                loan_deduction=loan_ded,
                advance_deduction=advance_ded,
                other_deductions=existing.other_deductions,
                net_salary=net,
                is_paid=False,
                paid_date=None,
                entry_id=existing.id,
            ))
        else:
            loan_ded, advance_ded = _capped_deductions(s, year, month, s.monthly_gross, 0.0, 0.0, db)
            net = round(s.monthly_gross - loan_ded - advance_ded, 2)
            result.append(PayrollLineOut(
                staff_id=s.id,
                full_name=s.full_name,
                role=s.role,
                gross_salary=s.monthly_gross,
                bonus=0.0,
                loan_deduction=loan_ded,
                advance_deduction=advance_ded,
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
    month_start = date(req.year, req.month, 1)
    month_end   = date(req.year, req.month, calendar.monthrange(req.year, req.month)[1])

    # Fetch this month's expense transactions once; fuzzy-match staff names
    # against them in Python rather than per-staff SQL ilike (which required an
    # exact substring match and broke on reordered/varied bank narrations).
    month_expenses = (
        db.query(Transaction)
        .filter(
            Transaction.type == "expense",
            Transaction.date >= month_start,
            Transaction.date <= month_end,
        )
        .all()
    )

    # ── Phase 1: resolve transactions for ALL staff before saving anything ────
    missing: list[str] = []
    tx_map: dict[int, int] = {}  # staff_id → transaction.id
    net_by_staff: dict[int, float] = {}  # staff_id → net salary, computed once and reused in Phase 2
    loan_ded_by_staff: dict[int, float] = {}  # staff_id → loan deduction, computed once and reused in Phase 2
    advance_ded_by_staff: dict[int, float] = {}  # staff_id → advance deduction, computed once and reused in Phase 2
    # Seed with manual overrides up front so an automatic search later in this
    # same request can't claim a transaction the user already hand-picked.
    manual_tx_ids = [l.transaction_id for l in req.lines if l.transaction_id]
    if len(manual_tx_ids) != len(set(manual_tx_ids)):
        raise HTTPException(400, "A transaction cannot be manually linked to more than one staff member in the same request")
    used_tx_ids: set[int] = set(manual_tx_ids)

    for line in req.lines:
        staff = db.get(Staff, line.staff_id)
        if not staff:
            raise HTTPException(404, f"Staff {line.staff_id} not found")

        loan_ded, advance_ded = _capped_deductions(
            staff, req.year, req.month, line.gross_salary, line.bonus, line.other_deductions, db,
        )
        loan_ded_by_staff[line.staff_id] = loan_ded
        advance_ded_by_staff[line.staff_id] = advance_ded
        net_by_staff[line.staff_id] = round(line.gross_salary + line.bonus - loan_ded - advance_ded - line.other_deductions, 2)

        # Manual override: the user explicitly picked this transaction (e.g.
        # after automatic matching failed to find it) — use it as-is, no
        # name/category/amount re-validation needed.
        if line.transaction_id:
            tx = db.get(Transaction, line.transaction_id)
            if not tx or tx.type != "expense":
                raise HTTPException(400, f"Transaction {line.transaction_id} is not a valid expense transaction")
            if tx.date < month_start or tx.date > month_end:
                raise HTTPException(400, f"Transaction {line.transaction_id} is outside the payroll period")
            claimed_by_other = (
                db.query(PayrollEntry)
                .filter(
                    PayrollEntry.transaction_id == line.transaction_id,
                    PayrollEntry.staff_id != line.staff_id,
                )
                .first()
            )
            if claimed_by_other:
                raise HTTPException(400, f"Transaction {line.transaction_id} is already linked to another staff member's payroll entry")
            tx_map[line.staff_id] = tx.id
            continue

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
        tx = next(
            (
                t for t in month_expenses
                if t.id not in used_tx_ids
                and (
                    _name_matches_text(staff.full_name, t.vendor or "")
                    or _name_matches_text(staff.full_name, t.description or "")
                )
            ),
            None,
        )

        # Fallback: the bank account may be registered under a different
        # first/middle name than the staff record (e.g. a spouse's name, or a
        # maiden name) — common enough in practice that name-matching alone
        # can't bridge it. Accept a transaction tagged "Salary and Wages"
        # whose amount covers at least the computed net pay (it may be
        # bundled with an IOU/advance repayment on top) and that still shares
        # at least one name token, so we don't attach the wrong payment when
        # multiple unclaimed salary transactions exist in the same month.
        if not tx:
            net = net_by_staff[line.staff_id]
            tx = next(
                (
                    t for t in month_expenses
                    if t.id not in used_tx_ids
                    and t.category == "Salary and Wages"
                    and t.amount >= net - 0.01
                    and (
                        _has_any_name_token_overlap(staff.full_name, t.vendor or "")
                        or _has_any_name_token_overlap(staff.full_name, t.description or "")
                    )
                ),
                None,
            )

        if tx:
            used_tx_ids.add(tx.id)
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
        loan_ded = loan_ded_by_staff[line.staff_id]
        advance_ded = advance_ded_by_staff[line.staff_id]
        net = net_by_staff[line.staff_id]
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
        entry.advance_deduction = advance_ded
        entry.other_deductions = line.other_deductions
        entry.net_salary     = net
        entry.notes          = line.notes
        entry.transaction_id = tx_map[line.staff_id]
        entry.is_paid        = True
        entry.paid_date      = pay_date
        entry.updated_at     = datetime.utcnow()

        _recover_advances_for_month(staff, req.year, req.month, advance_ded, db)

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
            advance_deduction=e.advance_deduction,
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


@router.post("/reset")
def reset_payroll(year: int, month: int, db: Session = Depends(get_db)):
    """Mark all payroll entries for a month as unpaid and unlink their
    transactions, so the user can re-process against a different transaction
    (e.g. after importing a corrected bank statement)."""
    entries = (
        db.query(PayrollEntry)
        .filter(PayrollEntry.period_year == year, PayrollEntry.period_month == month)
        .all()
    )
    for e in entries:
        e.transaction_id = None
        e.is_paid = False
        e.paid_date = None
        e.updated_at = datetime.utcnow()
    db.commit()

    from routers.financial_statements import _cache_bust
    _cache_bust()

    return {"reset": len(entries), "year": year, "month": month}


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
            advance_deduction=e.advance_deduction,
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
