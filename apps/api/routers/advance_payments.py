"""
Advance Payment (IOU) — a one-off salary advance given to a staff member,
recovered in full from the next payroll run processed after it's recorded
(see payroll.py's _advance_deduction_for_month), not repaid in installments
like a StaffLoan.
"""
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models import AdvancePayment, Staff, Transaction
from utils.auth import get_current_user

router = APIRouter(prefix="/advance-payments", tags=["advance-payments"], dependencies=[Depends(get_current_user)])


# ── schemas ────────────────────────────────────────────────────────────────────

class AdvancePaymentIn(BaseModel):
    staff_id: int
    amount: float
    date_issued: date
    transaction_id: Optional[int] = None
    notes: Optional[str] = None


class MatchedTransaction(BaseModel):
    id: int
    date: date
    amount: float
    description: str
    vendor: Optional[str]
    category: str


class AdvancePaymentOut(BaseModel):
    id: int
    staff_id: int
    staff_name: str
    amount: float
    date_issued: date
    transaction_id: Optional[int]
    is_recovered: bool
    recovered_period_year: Optional[int]
    recovered_period_month: Optional[int]
    notes: Optional[str]
    verified: bool  # True when linked to a transaction
    matched_tx: Optional[MatchedTransaction]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


def _serialize(advance: AdvancePayment) -> AdvancePaymentOut:
    tx = advance.transaction
    return AdvancePaymentOut(
        id=advance.id,
        staff_id=advance.staff_id,
        staff_name=advance.staff_member.full_name if advance.staff_member else "Unknown",
        amount=advance.amount,
        date_issued=advance.date_issued,
        transaction_id=advance.transaction_id,
        is_recovered=bool(advance.is_recovered),
        recovered_period_year=advance.recovered_period_year,
        recovered_period_month=advance.recovered_period_month,
        notes=advance.notes,
        verified=advance.transaction_id is not None,
        matched_tx=MatchedTransaction(
            id=tx.id, date=tx.date, amount=tx.amount,
            description=tx.description, vendor=tx.vendor, category=tx.category,
        ) if tx else None,
        created_at=advance.created_at,
        updated_at=advance.updated_at,
    )


# ── CRUD ───────────────────────────────────────────────────────────────────────

@router.get("/", response_model=list[AdvancePaymentOut])
def list_advance_payments(db: Session = Depends(get_db)):
    advances = db.query(AdvancePayment).order_by(AdvancePayment.date_issued.desc()).all()
    return [_serialize(a) for a in advances]


@router.post("/", response_model=AdvancePaymentOut, status_code=201)
def create_advance_payment(body: AdvancePaymentIn, db: Session = Depends(get_db)):
    staff = db.get(Staff, body.staff_id)
    if not staff:
        raise HTTPException(404, "Staff member not found")
    advance = AdvancePayment(**body.model_dump())
    db.add(advance)
    db.commit()
    db.refresh(advance)
    return _serialize(advance)


@router.put("/{advance_id}", response_model=AdvancePaymentOut)
def update_advance_payment(advance_id: int, body: AdvancePaymentIn, db: Session = Depends(get_db)):
    advance = db.get(AdvancePayment, advance_id)
    if not advance:
        raise HTTPException(404, "Advance payment not found")
    if advance.is_recovered:
        raise HTTPException(400, "Cannot edit an advance that has already been recovered from payroll")
    staff = db.get(Staff, body.staff_id)
    if not staff:
        raise HTTPException(404, "Staff member not found")
    for k, v in body.model_dump().items():
        setattr(advance, k, v)
    advance.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(advance)
    return _serialize(advance)


@router.delete("/{advance_id}", status_code=204)
def delete_advance_payment(advance_id: int, db: Session = Depends(get_db)):
    advance = db.get(AdvancePayment, advance_id)
    if not advance:
        raise HTTPException(404, "Advance payment not found")
    if advance.is_recovered:
        raise HTTPException(400, "Cannot delete an advance that has already been recovered from payroll")
    db.delete(advance)
    db.commit()
