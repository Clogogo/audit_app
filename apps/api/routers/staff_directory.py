"""Staff directory — employee profiles used by payroll and loan tracking."""
import logging
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from utils.auth import require_permission
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from llm_providers import get_llm_client
from models import AdvancePayment, PayrollEntry, Staff, StaffLoan, Term
from routers.staff_loans import _outstanding as _loan_outstanding
from schemas import TransactionAISummary

router = APIRouter(prefix="/staff-directory", tags=["staff-directory"], dependencies=[Depends(require_permission("staff"))])

logger = logging.getLogger(__name__)


class StaffIn(BaseModel):
    full_name: str
    role: Optional[str] = None
    bank_name: Optional[str] = None
    account_number: Optional[str] = None
    monthly_gross: float = 0.0
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    is_active: bool = True
    notes: Optional[str] = None


class StaffOut(BaseModel):
    id: int
    full_name: str
    role: Optional[str]
    bank_name: Optional[str]
    account_number: Optional[str]
    monthly_gross: float
    start_date: Optional[date]
    end_date: Optional[date]
    is_active: bool
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


@router.get("/", response_model=list[StaffOut])
def list_staff(active_only: bool = False, db: Session = Depends(get_db)):
    q = db.query(Staff).order_by(Staff.full_name)
    if active_only:
        q = q.filter(Staff.is_active == True)
    return q.all()


@router.post("/", response_model=StaffOut, status_code=201)
def create_staff(body: StaffIn, db: Session = Depends(get_db)):
    member = Staff(**body.model_dump())
    db.add(member)
    db.commit()
    db.refresh(member)
    return member


@router.put("/{staff_id}", response_model=StaffOut)
def update_staff(staff_id: int, body: StaffIn, db: Session = Depends(get_db)):
    member = db.get(Staff, staff_id)
    if not member:
        raise HTTPException(404, "Staff member not found")
    for k, v in body.model_dump().items():
        setattr(member, k, v)
    member.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(member)
    return member


@router.delete("/{staff_id}", status_code=204)
def delete_staff(staff_id: int, db: Session = Depends(get_db)):
    member = db.get(Staff, staff_id)
    if not member:
        raise HTTPException(404, "Staff member not found")
    db.delete(member)
    db.commit()


# ── AI narrative summary ────────────────────────────────────────────────────
# Same content-keyed caching approach as transactions.py's /ai-summary —
# identical aggregate figures reuse the cached narrative; a real change in
# staffing, loans, IOUs, or payroll status invalidates it automatically.
# today's date is folded into the key too, since "days remaining in term"
# moves forward daily even when nothing else changes.
_STAFF_AI_SUMMARY_CACHE: dict[tuple, str] = {}
_STAFF_AI_SUMMARY_CACHE_MAX = 16


def _build_staff_ai_summary_prompt(
    active_count: int, inactive_count: int, total_monthly_gross: float,
    active_loan_count: int, total_loan_outstanding: float,
    open_advance_count: int, total_advance_outstanding: float,
    paid_this_month: int, term_text: str,
) -> str:
    return (
        "You are advising the leadership of a small school organization in "
        "Nigeria on staff and payroll management. All amounts are in "
        "Nigerian Naira — always use the ₦ symbol, never £, $, or any other "
        "currency.\n\n"
        "Answer exactly these questions, in this order, as four short "
        "paragraphs (2-3 sentences each), plain prose with no bullet points "
        "or numbered lists. Start each paragraph with its bold label exactly "
        "as written below, followed by a colon, then a blank line between "
        "paragraphs:\n\n"
        "**Staffing Overview:** How many staff are active vs inactive, and "
        "what is the total monthly payroll obligation?\n"
        "**Loans & IOUs:** What is the exposure from outstanding staff loans "
        "and unrecovered salary advances (IOUs) — is it a concern?\n"
        "**Payroll Status:** Is this month's payroll on track, based on how "
        "many active staff have been paid so far?\n"
        "**Recommendations:** What should leadership prioritize next around "
        "staffing, loans, or payroll?\n\n"
        f"Active staff: {active_count}\n"
        f"Inactive staff: {inactive_count}\n"
        f"Total monthly gross payroll (active staff): ₦{total_monthly_gross:,.2f}\n"
        f"Active staff loans: {active_loan_count}, total outstanding: ₦{total_loan_outstanding:,.2f}\n"
        f"Unrecovered salary advances (IOUs): {open_advance_count}, total outstanding: ₦{total_advance_outstanding:,.2f}\n"
        f"Payroll this month: {paid_this_month} of {active_count} active staff paid\n"
        f"{term_text}"
    )


@router.get("/ai-summary", response_model=TransactionAISummary)
def get_staff_ai_summary(db: Session = Depends(get_db)):
    """AI-generated narrative over the staff directory, staff loans, salary
    advances (IOUs), this month's payroll status, and the current term.
    Never raises on AI failure — returns available=False instead, so the
    frontend can simply omit the summary card rather than show an error."""
    today = date.today()

    all_staff = db.query(Staff).all()
    active_staff = [s for s in all_staff if s.is_active]
    inactive_count = len(all_staff) - len(active_staff)
    total_monthly_gross = round(sum(s.monthly_gross for s in active_staff), 2)

    active_loans = db.query(StaffLoan).filter(StaffLoan.is_active == True).all()
    total_loan_outstanding = round(sum(_loan_outstanding(loan) for loan in active_loans), 2)

    open_advances = db.query(AdvancePayment).filter(AdvancePayment.is_recovered == False).all()
    total_advance_outstanding = round(sum(a.remaining_amount for a in open_advances), 2)

    active_staff_ids = {s.id for s in active_staff}
    paid_this_month = 0
    if active_staff_ids:
        paid_this_month = (
            db.query(PayrollEntry)
            .filter(
                PayrollEntry.staff_id.in_(active_staff_ids),
                PayrollEntry.period_year == today.year,
                PayrollEntry.period_month == today.month,
                PayrollEntry.is_paid == True,
            )
            .count()
        )

    current_term = (
        db.query(Term)
        .filter(Term.start_date <= today, Term.end_date >= today)
        .order_by(Term.start_date.desc())
        .first()
    )
    if current_term:
        days_remaining = (current_term.end_date - today).days
        term_text = f"Current term: {current_term.name}, {days_remaining} day(s) remaining"
    else:
        term_text = "Current term: none configured"

    cache_key = (
        len(active_staff), inactive_count, total_monthly_gross,
        len(active_loans), total_loan_outstanding,
        len(open_advances), total_advance_outstanding,
        paid_this_month, term_text, today.isoformat(),
    )
    cached = _STAFF_AI_SUMMARY_CACHE.get(cache_key)
    if cached is not None:
        return TransactionAISummary(narrative=cached, available=True)

    try:
        client = get_llm_client()
        prompt_messages = [{"role": "user", "content": _build_staff_ai_summary_prompt(
            len(active_staff), inactive_count, total_monthly_gross,
            len(active_loans), total_loan_outstanding,
            len(open_advances), total_advance_outstanding,
            paid_this_month, term_text,
        )}]
        try:
            narrative = client.create_message(
                messages=prompt_messages,
                max_tokens=1500,
                # See transactions.py's identical retry — a reasoning model
                # may consume the whole token budget on chain-of-thought
                # before writing the four-section answer without this.
                extra_body={"reasoning": {"effort": "low"}},
            )
        except TypeError:
            narrative = client.create_message(messages=prompt_messages, max_tokens=1500)
    except Exception as e:
        logger.warning(
            "Staff AI summary generation failed, returning available=False: %s",
            e,
            exc_info=True,
        )
        return TransactionAISummary(narrative=None, available=False)

    if len(_STAFF_AI_SUMMARY_CACHE) >= _STAFF_AI_SUMMARY_CACHE_MAX:
        try:
            _STAFF_AI_SUMMARY_CACHE.pop(next(iter(_STAFF_AI_SUMMARY_CACHE)))
        except (StopIteration, KeyError):
            pass
    _STAFF_AI_SUMMARY_CACHE[cache_key] = narrative

    return TransactionAISummary(narrative=narrative, available=True)
