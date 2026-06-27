"""
Staff Loans — loans given to employees, recovered via monthly payments.
Outstanding balance = loan_amount − sum(StaffLoanPayment.amount_paid).
"""
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from utils.auth import get_current_user
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models import Staff, StaffLoan, StaffLoanPayment, Transaction

router = APIRouter(prefix="/staff-loans", tags=["staff-loans"], dependencies=[Depends(get_current_user)])


# ── helpers ────────────────────────────────────────────────────────────────────

def _total_paid(loan: StaffLoan) -> float:
    return round(sum(p.amount_paid for p in loan.payments), 2)


def _outstanding(loan: StaffLoan) -> float:
    return max(0.0, round(loan.loan_amount - _total_paid(loan), 2))


# ── schemas ────────────────────────────────────────────────────────────────────

class StaffLoanIn(BaseModel):
    staff_id: Optional[int] = None
    employee_name: Optional[str] = None
    loan_amount: float
    deduction_rate: float = 0.5        # kept for reference / display only
    deduction_start: date
    notes: Optional[str] = None
    is_active: bool = True


class LoanPaymentIn(BaseModel):
    amount_paid: float
    paid_date: date
    transaction_id: Optional[int] = None
    notes: Optional[str] = None


class MatchedTransaction(BaseModel):
    id: int
    date: date
    amount: float
    description: str
    vendor: Optional[str]
    category: str


class LoanPaymentOut(BaseModel):
    id: int
    loan_id: int
    transaction_id: Optional[int]
    amount_paid: float
    paid_date: date
    notes: Optional[str]
    verified: bool           # True when linked to a transaction
    matched_tx: Optional[MatchedTransaction]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class StaffLoanOut(BaseModel):
    id: int
    staff_id: Optional[int]
    employee_name: str
    loan_amount: float
    deduction_rate: float
    deduction_start: date
    notes: Optional[str]
    is_active: bool
    outstanding_today: float
    total_paid: float
    monthly_deduction_amount: float
    payments: list[LoanPaymentOut]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


def _serialize_payment(p: StaffLoanPayment) -> LoanPaymentOut:
    tx = p.transaction
    return LoanPaymentOut(
        id=p.id,
        loan_id=p.loan_id,
        transaction_id=p.transaction_id,
        amount_paid=p.amount_paid,
        paid_date=p.paid_date,
        notes=p.notes,
        verified=p.transaction_id is not None,
        matched_tx=MatchedTransaction(
            id=tx.id,
            date=tx.date,
            amount=tx.amount,
            description=tx.description,
            vendor=tx.vendor,
            category=tx.category,
        ) if tx else None,
        created_at=p.created_at,
        updated_at=p.updated_at,
    )


def _to_out(loan: StaffLoan, db: Session) -> StaffLoanOut:
    rate = loan.deduction_rate if loan.deduction_rate is not None else 0.5
    staff: Optional[Staff] = db.get(Staff, loan.staff_id) if loan.staff_id else None
    monthly_deduction_amount = round((staff.monthly_gross if staff else 0.0) * rate, 2)

    return StaffLoanOut(
        id=loan.id,
        staff_id=loan.staff_id,
        employee_name=loan.employee_name,
        loan_amount=loan.loan_amount,
        deduction_rate=rate,
        deduction_start=loan.deduction_start,
        notes=loan.notes,
        is_active=bool(loan.is_active),
        outstanding_today=_outstanding(loan),
        total_paid=_total_paid(loan),
        monthly_deduction_amount=monthly_deduction_amount,
        payments=[_serialize_payment(p) for p in loan.payments],
        created_at=loan.created_at,
        updated_at=loan.updated_at,
    )


def _resolve_name(data: dict, db: Session) -> dict:
    if data.get("staff_id"):
        staff = db.get(Staff, data["staff_id"])
        if staff:
            data["employee_name"] = staff.full_name
    if not data.get("employee_name"):
        data["employee_name"] = "Unknown"
    return data


# ── loan CRUD ──────────────────────────────────────────────────────────────────

@router.get("/", response_model=list[StaffLoanOut])
def list_staff_loans(db: Session = Depends(get_db)):
    loans = db.query(StaffLoan).order_by(StaffLoan.employee_name).all()
    return [_to_out(l, db) for l in loans]


@router.post("/", response_model=StaffLoanOut, status_code=201)
def create_staff_loan(body: StaffLoanIn, db: Session = Depends(get_db)):
    data = _resolve_name(body.model_dump(), db)
    loan = StaffLoan(**data)
    db.add(loan)
    db.commit()
    db.refresh(loan)
    return _to_out(loan, db)


@router.put("/{loan_id}", response_model=StaffLoanOut)
def update_staff_loan(loan_id: int, body: StaffLoanIn, db: Session = Depends(get_db)):
    loan = db.get(StaffLoan, loan_id)
    if not loan:
        raise HTTPException(404, "Staff loan not found")
    data = _resolve_name(body.model_dump(), db)
    for k, v in data.items():
        setattr(loan, k, v)
    loan.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(loan)
    return _to_out(loan, db)


@router.delete("/{loan_id}", status_code=204)
def delete_staff_loan(loan_id: int, db: Session = Depends(get_db)):
    loan = db.get(StaffLoan, loan_id)
    if not loan:
        raise HTTPException(404, "Staff loan not found")
    db.delete(loan)
    db.commit()


# ── transaction lookup for payment verification ────────────────────────────────

@router.get("/{loan_id}/match-transactions", response_model=list[MatchedTransaction])
def match_transactions(
    loan_id: int,
    year: int,
    month: int,
    db: Session = Depends(get_db),
):
    """Return salary transactions for this staff member in the given month
    so the user can verify and link them to a loan payment."""
    from sqlalchemy import or_
    import calendar as cal

    loan = db.get(StaffLoan, loan_id)
    if not loan:
        raise HTTPException(404, "Staff loan not found")

    month_start = date(year, month, 1)
    month_end   = date(year, month, cal.monthrange(year, month)[1])
    name = loan.employee_name

    txs = (
        db.query(Transaction)
        .filter(
            Transaction.type == "expense",
            Transaction.date >= month_start,
            Transaction.date <= month_end,
            or_(
                Transaction.vendor.ilike(f"%{name}%"),
                Transaction.description.ilike(f"%{name}%"),
            ),
        )
        .order_by(Transaction.date.desc())
        .limit(20)
        .all()
    )
    return [
        MatchedTransaction(
            id=t.id, date=t.date, amount=t.amount,
            description=t.description, vendor=t.vendor, category=t.category,
        )
        for t in txs
    ]


# ── payment CRUD ───────────────────────────────────────────────────────────────

@router.get("/{loan_id}/payments", response_model=list[LoanPaymentOut])
def list_payments(loan_id: int, db: Session = Depends(get_db)):
    loan = db.get(StaffLoan, loan_id)
    if not loan:
        raise HTTPException(404, "Staff loan not found")
    return [_serialize_payment(p) for p in loan.payments]


@router.post("/{loan_id}/payments", response_model=LoanPaymentOut, status_code=201)
def add_payment(loan_id: int, body: LoanPaymentIn, db: Session = Depends(get_db)):
    loan = db.get(StaffLoan, loan_id)
    if not loan:
        raise HTTPException(404, "Staff loan not found")
    payment = StaffLoanPayment(loan_id=loan_id, **body.model_dump())
    db.add(payment)
    db.flush()
    db.refresh(loan)
    if _outstanding(loan) <= 0:
        loan.is_active = False
    db.commit()
    db.refresh(payment)
    return _serialize_payment(payment)


@router.put("/{loan_id}/payments/{payment_id}", response_model=LoanPaymentOut)
def update_payment(loan_id: int, payment_id: int, body: LoanPaymentIn, db: Session = Depends(get_db)):
    payment = db.get(StaffLoanPayment, payment_id)
    if not payment or payment.loan_id != loan_id:
        raise HTTPException(404, "Payment not found")
    for k, v in body.model_dump().items():
        setattr(payment, k, v)
    payment.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(payment)
    return _serialize_payment(payment)


@router.delete("/{loan_id}/payments/{payment_id}", status_code=204)
def delete_payment(loan_id: int, payment_id: int, db: Session = Depends(get_db)):
    payment = db.get(StaffLoanPayment, payment_id)
    if not payment or payment.loan_id != loan_id:
        raise HTTPException(404, "Payment not found")
    db.delete(payment)
    db.commit()


# ── summary used by Financial Statements ──────────────────────────────────────

@router.get("/outstanding")
def get_outstanding_total(as_at: str, db: Session = Depends(get_db)):
    try:
        date.fromisoformat(as_at)
    except ValueError:
        raise HTTPException(400, "as_at must be YYYY-MM-DD")
    loans = db.query(StaffLoan).filter(StaffLoan.is_active == True).all()
    total = round(sum(_outstanding(l) for l in loans), 2)
    return {"as_at": as_at, "total_outstanding": total}
