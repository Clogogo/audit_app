"""
School Loans — loans the school has borrowed (collected) from a lender,
recovered via repayments. Each repayment splits into principal / interest /
misc charges; the principal-only outstanding balance is the Loans Payable
liability figure used elsewhere (Financial Statements). A loan is only
considered fully settled — and auto-closed (is_active flips to False) —
once BOTH the principal and the loan's agreed total_interest_due are paid,
not principal alone.
"""
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from utils.auth import require_permission
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_db
from models import SchoolLoan, SchoolLoanPayment, Transaction

router = APIRouter(prefix="/school-loans", tags=["school-loans"], dependencies=[Depends(require_permission("tax"))])


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


def _outstanding_interest(loan: SchoolLoan) -> float:
    due = loan.total_interest_due or 0.0  # defensive: legacy rows predating this column
    return max(0.0, round(due - _total_interest_paid(loan), 2))


def _is_fully_paid(loan: SchoolLoan) -> bool:
    """Principal AND the agreed total interest must both be cleared —
    paying off principal alone is not enough to consider the loan settled."""
    return _outstanding(loan) <= 0 and _outstanding_interest(loan) <= 0


def _sync_active_status(loan: SchoolLoan) -> None:
    """Keep is_active in lockstep with actual payment completeness after any
    payment is added, edited, or removed — so editing/deleting a payment that
    used to close the loan correctly reopens it, not just the forward
    (payment added → maybe closes) direction the old code handled."""
    loan.is_active = not _is_fully_paid(loan)


# ── schemas ────────────────────────────────────────────────────────────────────

class SchoolLoanIn(BaseModel):
    lender_name: str = Field(max_length=200)  # matches SchoolLoan.lender_name column width
    loan_amount: float
    interest_rate: float = 0.0   # annual %, kept for reference / display only
    total_interest_due: float = 0.0  # agreed total interest owed on this loan
    collected_date: date
    transaction_id: Optional[int] = None
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
    total_interest_due: float
    collected_date: date
    transaction_id: Optional[int]
    verified: bool           # True when linked to a transaction
    matched_tx: Optional[MatchedTransaction]
    notes: Optional[str]
    is_active: bool
    outstanding_today: float          # principal only — the Loans Payable liability figure
    outstanding_interest: float       # agreed interest not yet paid
    fully_paid: bool                  # True only when BOTH principal and interest are cleared
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
    tx = loan.transaction
    return SchoolLoanOut(
        id=loan.id,
        lender_name=loan.lender_name,
        loan_amount=loan.loan_amount,
        interest_rate=loan.interest_rate,
        total_interest_due=loan.total_interest_due or 0.0,  # defensive: legacy rows predating this column
        collected_date=loan.collected_date,
        transaction_id=loan.transaction_id,
        verified=loan.transaction_id is not None,
        matched_tx=MatchedTransaction(
            id=tx.id, date=tx.date, amount=tx.amount,
            description=tx.description, vendor=tx.vendor, category=tx.category,
        ) if tx else None,
        notes=loan.notes,
        is_active=bool(loan.is_active),
        outstanding_today=_outstanding(loan),
        outstanding_interest=_outstanding_interest(loan),
        fully_paid=_is_fully_paid(loan),
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


@router.get("/suggestions", response_model=list[MatchedTransaction])
def suggest_untracked_loan_transactions(db: Session = Depends(get_db)):
    """Income transactions categorized "Loans" that aren't yet linked to any
    school loan record — a loan credit can land in the ledger via bank import
    or manual entry without anyone remembering to also track it here, so
    surface it instead of letting it silently miss the Loans Payable figure."""
    linked_ids = {
        row[0] for row in
        db.query(SchoolLoan.transaction_id).filter(SchoolLoan.transaction_id.isnot(None)).all()
    }
    txs = (
        db.query(Transaction)
        .filter(Transaction.type == "income", Transaction.category == "Loans")
        .order_by(Transaction.date.desc())
        .all()
    )
    return [
        MatchedTransaction(
            id=t.id, date=t.date, amount=t.amount,
            description=t.description, vendor=t.vendor, category=t.category,
        )
        for t in txs if t.id not in linked_ids
    ]


def _assert_transaction_not_already_linked(
    db: Session, transaction_id: Optional[int], exclude_loan_id: Optional[int] = None,
) -> None:
    """A transaction can only be the "collection" record for one loan — two
    loans pointing at the same transaction would double-count it in the
    Loans Payable total (which sums outstanding_today across all active
    loans)."""
    if transaction_id is None:
        return
    query = db.query(SchoolLoan).filter(SchoolLoan.transaction_id == transaction_id)
    if exclude_loan_id is not None:
        query = query.filter(SchoolLoan.id != exclude_loan_id)
    other = query.first()
    if other:
        raise HTTPException(
            400,
            f"Transaction {transaction_id} is already linked to loan "
            f"\"{other.lender_name}\" (id {other.id})",
        )


@router.post("/", response_model=SchoolLoanOut, status_code=201)
def create_school_loan(body: SchoolLoanIn, db: Session = Depends(get_db)):
    _assert_transaction_not_already_linked(db, body.transaction_id)
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
    _assert_transaction_not_already_linked(db, body.transaction_id, exclude_loan_id=loan_id)
    for k, v in body.model_dump().items():
        setattr(loan, k, v)
    loan.updated_at = datetime.utcnow()
    db.flush()
    db.refresh(loan)
    # Editing loan terms (e.g. raising total_interest_due after principal was
    # already paid off) can make a previously fully-paid loan incomplete
    # again. A loan can never be inactive while money is still owed — that
    # would silently drop real debt from the Outstanding (Payable) total,
    # which only sums is_active loans — so force it back open in that case.
    # The reverse isn't forced: a genuinely fully-paid loan may still be
    # explicitly marked active or inactive by the user, either is harmless.
    if not _is_fully_paid(loan):
        loan.is_active = True
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
    tx_type: str = "expense",
    db: Session = Depends(get_db),
):
    """Return transactions of the given type mentioning this lender in the
    given month, so the user can verify and link them — expense for a loan
    payment (cash going out), income for the loan's own collection (cash
    coming in from the lender)."""
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
            Transaction.type == tx_type,
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
    _sync_active_status(loan)
    db.commit()
    db.refresh(payment)
    return _serialize_payment(payment)


@router.put("/{loan_id}/payments/{payment_id}", response_model=LoanPaymentOut)
def update_payment(loan_id: int, payment_id: int, body: LoanPaymentIn, db: Session = Depends(get_db)):
    payment = db.get(SchoolLoanPayment, payment_id)
    if not payment or payment.loan_id != loan_id:
        raise HTTPException(404, "Payment not found")
    loan = db.get(SchoolLoan, loan_id)
    if not loan:
        raise HTTPException(404, "School loan not found")
    for k, v in body.model_dump().items():
        setattr(payment, k, v)
    payment.updated_at = datetime.utcnow()
    db.flush()
    db.refresh(loan)
    _sync_active_status(loan)
    db.commit()
    db.refresh(payment)
    return _serialize_payment(payment)


@router.delete("/{loan_id}/payments/{payment_id}", status_code=204)
def delete_payment(loan_id: int, payment_id: int, db: Session = Depends(get_db)):
    payment = db.get(SchoolLoanPayment, payment_id)
    if not payment or payment.loan_id != loan_id:
        raise HTTPException(404, "Payment not found")
    loan = db.get(SchoolLoan, loan_id)
    if not loan:
        raise HTTPException(404, "School loan not found")
    db.delete(payment)
    db.flush()
    db.refresh(loan)
    _sync_active_status(loan)
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
