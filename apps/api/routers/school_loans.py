"""
School Loans — loans the school has borrowed (collected) from a lender,
recovered via repayments. Each repayment splits into principal / interest /
misc charges; outstanding balance only goes down by the principal portion.
"""
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from utils.auth import get_current_user
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models import SchoolLoan, SchoolLoanPayment, Transaction

router = APIRouter(prefix="/school-loans", tags=["school-loans"], dependencies=[Depends(get_current_user)])


# ── helpers ────────────────────────────────────────────────────────────────────

def _principal_paid(p: SchoolLoanPayment) -> float:
    return round(p.amount_paid - p.interest_amount - p.misc_amount, 2)


def _total_paid(loan: SchoolLoan) -> float:
    return round(sum(p.amount_paid for p in loan.payments), 2)


def _total_interest_paid(loan: SchoolLoan) -> float:
    return round(sum(p.interest_amount for p in loan.payments), 2)


def _total_misc_paid(loan: SchoolLoan) -> float:
    return round(sum(p.misc_amount for p in loan.payments), 2)


def _outstanding(loan: SchoolLoan) -> float:
    principal_paid = sum(_principal_paid(p) for p in loan.payments)
    return max(0.0, round(loan.loan_amount - principal_paid, 2))


# ── schemas ────────────────────────────────────────────────────────────────────

class SchoolLoanIn(BaseModel):
    lender_name: str
    loan_amount: float
    interest_rate: float = 0.0   # annual %, kept for reference / display only
    collected_date: date
    notes: Optional[str] = None
    is_active: bool = True


class LoanPaymentIn(BaseModel):
    amount_paid: float
    interest_amount: float = 0.0
    misc_amount: float = 0.0
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
    interest_amount: float
    misc_amount: float
    principal_paid: float
    paid_date: date
    notes: Optional[str]
    verified: bool           # True when linked to a transaction
    matched_tx: Optional[MatchedTransaction]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class SchoolLoanOut(BaseModel):
    id: int
    lender_name: str
    loan_amount: float
    interest_rate: float
    collected_date: date
    notes: Optional[str]
    is_active: bool
    outstanding_today: float
    total_paid: float
    total_interest_paid: float
    total_misc_paid: float
    payments: list[LoanPaymentOut]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


def _serialize_payment(p: SchoolLoanPayment) -> LoanPaymentOut:
    tx = p.transaction
    return LoanPaymentOut(
        id=p.id,
        loan_id=p.loan_id,
        transaction_id=p.transaction_id,
        amount_paid=p.amount_paid,
        interest_amount=p.interest_amount,
        misc_amount=p.misc_amount,
        principal_paid=_principal_paid(p),
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


def _to_out(loan: SchoolLoan) -> SchoolLoanOut:
    return SchoolLoanOut(
        id=loan.id,
        lender_name=loan.lender_name,
        loan_amount=loan.loan_amount,
        interest_rate=loan.interest_rate,
        collected_date=loan.collected_date,
        notes=loan.notes,
        is_active=bool(loan.is_active),
        outstanding_today=_outstanding(loan),
        total_paid=_total_paid(loan),
        total_interest_paid=_total_interest_paid(loan),
        total_misc_paid=_total_misc_paid(loan),
        payments=[_serialize_payment(p) for p in loan.payments],
        created_at=loan.created_at,
        updated_at=loan.updated_at,
    )


# ── loan CRUD ──────────────────────────────────────────────────────────────────

@router.get("/", response_model=list[SchoolLoanOut])
def list_school_loans(db: Session = Depends(get_db)):
    loans = db.query(SchoolLoan).order_by(SchoolLoan.collected_date.desc()).all()
    return [_to_out(l) for l in loans]


@router.post("/", response_model=SchoolLoanOut, status_code=201)
def create_school_loan(body: SchoolLoanIn, db: Session = Depends(get_db)):
    loan = SchoolLoan(**body.model_dump())
    db.add(loan)
    db.commit()
    db.refresh(loan)
    return _to_out(loan)


@router.put("/{loan_id}", response_model=SchoolLoanOut)
def update_school_loan(loan_id: int, body: SchoolLoanIn, db: Session = Depends(get_db)):
    loan = db.get(SchoolLoan, loan_id)
    if not loan:
        raise HTTPException(404, "School loan not found")
    for k, v in body.model_dump().items():
        setattr(loan, k, v)
    loan.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(loan)
    return _to_out(loan)


@router.delete("/{loan_id}", status_code=204)
def delete_school_loan(loan_id: int, db: Session = Depends(get_db)):
    loan = db.get(SchoolLoan, loan_id)
    if not loan:
        raise HTTPException(404, "School loan not found")
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
    """Return expense transactions mentioning this lender in the given month
    so the user can verify and link them to a loan payment."""
    from sqlalchemy import or_
    import calendar as cal

    loan = db.get(SchoolLoan, loan_id)
    if not loan:
        raise HTTPException(404, "School loan not found")

    month_start = date(year, month, 1)
    month_end = date(year, month, cal.monthrange(year, month)[1])
    name = loan.lender_name

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
    loan = db.get(SchoolLoan, loan_id)
    if not loan:
        raise HTTPException(404, "School loan not found")
    return [_serialize_payment(p) for p in loan.payments]


@router.post("/{loan_id}/payments", response_model=LoanPaymentOut, status_code=201)
def add_payment(loan_id: int, body: LoanPaymentIn, db: Session = Depends(get_db)):
    loan = db.get(SchoolLoan, loan_id)
    if not loan:
        raise HTTPException(404, "School loan not found")
    payment = SchoolLoanPayment(loan_id=loan_id, **body.model_dump())
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
    payment = db.get(SchoolLoanPayment, payment_id)
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
    payment = db.get(SchoolLoanPayment, payment_id)
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
    loans = db.query(SchoolLoan).filter(SchoolLoan.is_active == True).all()
    total = round(sum(_outstanding(l) for l in loans), 2)
    return {"as_at": as_at, "total_outstanding": total}
