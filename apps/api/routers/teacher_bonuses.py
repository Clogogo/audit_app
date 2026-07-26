"""
Teacher/Staff Bonuses — performance, punctuality, referral, loyalty, and
annual bonuses that feed automatically into a specific payroll month (see
routers/payroll.py's compute_payroll). The qualifying judgment (class
average, punctuality rating, "the referred teacher stayed") happens
outside this app; recording a bonus here already is the approval, same as
StaffLoan/AdvancePayment — no separate pending/approved workflow.
"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models import Staff, TeacherBonus, Term
from utils.auth import require_permission
from utils.errors import get_or_404

router = APIRouter(prefix="/teacher-bonuses", tags=["teacher-bonuses"], dependencies=[Depends(require_permission("staff"))])

# Suggested types — advisory only (bonus_type is free text under the hood,
# same as Transaction.category), so adding a 7th bonus type later is just
# one more entry here, no schema change.
BONUS_TYPES = [
    {"key": "performance", "label": "Performance Bonus", "default_percentage": 10.0,
     "description": "Class average 80%+ — reviewed termly"},
    {"key": "punctuality", "label": "Punctuality & Classroom Management Bonus", "default_percentage": 5.0,
     "description": "Rated EXCELLENT for punctuality and classroom conduct"},
    {"key": "student_referral", "label": "Student Referral Bonus", "default_percentage": 10.0,
     "description": "% of the referred student's fee — paid after their first full term"},
    {"key": "teacher_referral", "label": "Teacher Referral Bonus", "default_percentage": 20.0,
     "description": "One-time — the referred teacher was hired and stayed"},
    {"key": "loyalty", "label": "Loyalty Bonus", "default_percentage": 10.0,
     "description": "End of session — full attendance and consistent performance, any staff member"},
    {"key": "annual_high_performance", "label": "Annual High Performance Bonus", "default_percentage": 0.0,
     "description": "Dynamic 0-100%, set by management at end of session"},
]


# ── schemas ──────────────────────────────────────────────────────────────────

class TeacherBonusIn(BaseModel):
    staff_id: int
    bonus_type: str
    percentage: float
    basis_amount: float
    period_year: int
    period_month: int
    term_id: Optional[int] = None
    notes: Optional[str] = None


class TeacherBonusOut(BaseModel):
    id: int
    staff_id: int
    staff_name: str
    bonus_type: str
    percentage: float
    basis_amount: float
    amount: float
    period_year: int
    period_month: int
    term_id: Optional[int]
    term_name: Optional[str]
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime


# ── serialization ────────────────────────────────────────────────────────────

def _to_out(b: TeacherBonus) -> TeacherBonusOut:
    return TeacherBonusOut(
        id=b.id, staff_id=b.staff_id, staff_name=b.staff.full_name,
        bonus_type=b.bonus_type, percentage=b.percentage, basis_amount=b.basis_amount,
        amount=b.amount, period_year=b.period_year, period_month=b.period_month,
        term_id=b.term_id, term_name=b.term.name if b.term else None,
        notes=b.notes, created_at=b.created_at, updated_at=b.updated_at,
    )


def _validate(body: TeacherBonusIn, db: Session) -> None:
    get_or_404(db, Staff, body.staff_id, "Staff member")
    if body.term_id is not None:
        get_or_404(db, Term, body.term_id, "Term")
    if body.percentage < 0:
        raise HTTPException(400, "percentage cannot be negative")
    if body.basis_amount < 0:
        raise HTTPException(400, "basis_amount cannot be negative")
    if not (1 <= body.period_month <= 12):
        raise HTTPException(400, "period_month must be between 1 and 12")


# ── endpoints ────────────────────────────────────────────────────────────────

@router.get("/types")
def list_bonus_types():
    return BONUS_TYPES


@router.get("/", response_model=list[TeacherBonusOut])
def list_teacher_bonuses(
    staff_id: Optional[int] = None,
    bonus_type: Optional[str] = None,
    period_year: Optional[int] = None,
    period_month: Optional[int] = None,
    db: Session = Depends(get_db),
):
    q = db.query(TeacherBonus).order_by(
        TeacherBonus.period_year.desc(), TeacherBonus.period_month.desc(), TeacherBonus.created_at.desc()
    )
    if staff_id:
        q = q.filter(TeacherBonus.staff_id == staff_id)
    if bonus_type:
        q = q.filter(TeacherBonus.bonus_type == bonus_type)
    if period_year:
        q = q.filter(TeacherBonus.period_year == period_year)
    if period_month:
        q = q.filter(TeacherBonus.period_month == period_month)
    return [_to_out(b) for b in q.all()]


@router.post("/", response_model=TeacherBonusOut, status_code=201)
def create_teacher_bonus(body: TeacherBonusIn, db: Session = Depends(get_db)):
    _validate(body, db)
    bonus = TeacherBonus(
        **body.model_dump(),
        amount=round(body.percentage / 100 * body.basis_amount, 2),
    )
    db.add(bonus)
    db.commit()
    db.refresh(bonus)
    return _to_out(bonus)


@router.put("/{bonus_id}", response_model=TeacherBonusOut)
def update_teacher_bonus(bonus_id: int, body: TeacherBonusIn, db: Session = Depends(get_db)):
    bonus = get_or_404(db, TeacherBonus, bonus_id, "Teacher bonus")
    _validate(body, db)
    for k, v in body.model_dump().items():
        setattr(bonus, k, v)
    bonus.amount = round(body.percentage / 100 * body.basis_amount, 2)
    bonus.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(bonus)
    return _to_out(bonus)


@router.delete("/{bonus_id}", status_code=204)
def delete_teacher_bonus(bonus_id: int, db: Session = Depends(get_db)):
    bonus = get_or_404(db, TeacherBonus, bonus_id, "Teacher bonus")
    db.delete(bonus)
    db.commit()
