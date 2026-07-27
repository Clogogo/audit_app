"""
Teacher/Staff Bonuses — performance, punctuality, referral, loyalty, and
annual bonuses that feed automatically into a specific payroll month (see
routers/payroll.py's compute_payroll). The qualifying judgment (class
average, punctuality rating, "the referred teacher stayed") happens
outside this app; recording a bonus here already is the approval, same as
StaffLoan/AdvancePayment — no separate pending/approved workflow.
"""
import re
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models import BonusType, Staff, TeacherBonus, Term
from utils.auth import require_permission
from utils.errors import get_or_404

router = APIRouter(prefix="/teacher-bonuses", tags=["teacher-bonuses"], dependencies=[Depends(require_permission("staff"))])

_CALCULATION_METHODS = {"percentage", "flat_amount"}


def _slugify(label: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", label.strip().lower()).strip("_")
    return slug or "type"


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


class BonusTypeIn(BaseModel):
    label: str
    description: Optional[str] = None
    calculation_method: str = "percentage"
    basis_is_salary: bool = True
    default_percentage: float = 0.0
    is_active: bool = True


class BonusTypeOut(BaseModel):
    id: int
    key: str
    label: str
    description: Optional[str]
    calculation_method: str
    basis_is_salary: bool
    default_percentage: float
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


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
    if not db.query(BonusType).filter(BonusType.key == body.bonus_type).first():
        raise HTTPException(400, "Unknown bonus type")
    if body.percentage < 0:
        raise HTTPException(400, "percentage cannot be negative")
    if body.basis_amount < 0:
        raise HTTPException(400, "basis_amount cannot be negative")
    if not (1 <= body.period_month <= 12):
        raise HTTPException(400, "period_month must be between 1 and 12")


def _validate_bonus_type(body: BonusTypeIn) -> None:
    if not body.label.strip():
        raise HTTPException(400, "label is required")
    if body.calculation_method not in _CALCULATION_METHODS:
        raise HTTPException(400, f"calculation_method must be one of {sorted(_CALCULATION_METHODS)}")
    if body.default_percentage < 0:
        raise HTTPException(400, "default_percentage cannot be negative")


# ── bonus type endpoints (admin-managed, replaces the old hardcoded list) ────

@router.get("/types", response_model=list[BonusTypeOut])
def list_bonus_types(active_only: bool = False, db: Session = Depends(get_db)):
    q = db.query(BonusType).order_by(BonusType.label)
    if active_only:
        q = q.filter(BonusType.is_active == True)
    return q.all()


@router.post("/types", response_model=BonusTypeOut, status_code=201)
def create_bonus_type(body: BonusTypeIn, db: Session = Depends(get_db)):
    _validate_bonus_type(body)
    key = _slugify(body.label)
    if db.query(BonusType).filter(BonusType.key == key).first():
        raise HTTPException(400, f"A bonus type named '{body.label}' already exists")
    bonus_type = BonusType(
        key=key, label=body.label, description=body.description,
        calculation_method=body.calculation_method,
        basis_is_salary=body.basis_is_salary,
        default_percentage=0.0 if body.calculation_method == "flat_amount" else body.default_percentage,
        is_active=body.is_active,
    )
    db.add(bonus_type)
    db.commit()
    db.refresh(bonus_type)
    return bonus_type


@router.put("/types/{type_id}", response_model=BonusTypeOut)
def update_bonus_type(type_id: int, body: BonusTypeIn, db: Session = Depends(get_db)):
    bonus_type = get_or_404(db, BonusType, type_id, "Bonus type")
    _validate_bonus_type(body)
    bonus_type.label = body.label
    bonus_type.description = body.description
    bonus_type.calculation_method = body.calculation_method
    bonus_type.basis_is_salary = body.basis_is_salary
    bonus_type.default_percentage = 0.0 if body.calculation_method == "flat_amount" else body.default_percentage
    bonus_type.is_active = body.is_active
    bonus_type.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(bonus_type)
    return bonus_type


@router.delete("/types/{type_id}", status_code=204)
def retire_bonus_type(type_id: int, db: Session = Depends(get_db)):
    """Soft-retire only — is_active=False, never a hard delete, so any
    historical TeacherBonus referencing this type's key keeps resolving
    its label via GET /types?active_only=false."""
    bonus_type = get_or_404(db, BonusType, type_id, "Bonus type")
    bonus_type.is_active = False
    bonus_type.updated_at = datetime.utcnow()
    db.commit()


# ── endpoints ────────────────────────────────────────────────────────────────


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
