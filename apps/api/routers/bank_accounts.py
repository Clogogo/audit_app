"""
Bank account management: store bank name + account number for reuse.
Transactions can be linked to a bank account via bank_account_id FK.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime, date

from database import get_db
from models import BankAccount, Transaction

router = APIRouter(prefix="/bank-accounts", tags=["bank-accounts"])


class BankAccountCreate(BaseModel):
    bank_name: str
    account_number: Optional[str] = None


class BankAccountOut(BaseModel):
    id: int
    bank_name: str
    account_number: Optional[str]
    created_at: datetime
    transaction_count: int = 0

    model_config = {"from_attributes": True}


class LinkedTransactionOut(BaseModel):
    id: int
    type: str
    amount: float
    currency: str
    category: str
    description: str
    date: date
    vendor: Optional[str]

    model_config = {"from_attributes": True}


@router.get("", response_model=list[BankAccountOut])
def list_bank_accounts(db: Session = Depends(get_db)):
    accounts = db.query(BankAccount).order_by(BankAccount.bank_name).all()
    result = []
    for acc in accounts:
        out = BankAccountOut.model_validate(acc)
        out.transaction_count = len(acc.transactions)
        result.append(out)
    return result


@router.get("/{account_id}/transactions", response_model=list[LinkedTransactionOut])
def get_account_transactions(account_id: int, db: Session = Depends(get_db)):
    account = db.get(BankAccount, account_id)
    if not account:
        raise HTTPException(404, "Bank account not found")
    return (
        db.query(Transaction)
        .filter(Transaction.bank_account_id == account_id)
        .order_by(Transaction.date.desc())
        .all()
    )


@router.post("", response_model=BankAccountOut, status_code=201)
def create_bank_account(body: BankAccountCreate, db: Session = Depends(get_db)):
    existing = (
        db.query(BankAccount)
        .filter(
            BankAccount.bank_name == body.bank_name,
            BankAccount.account_number == body.account_number,
        )
        .first()
    )
    if existing:
        raise HTTPException(400, "A bank account with this name and number already exists")
    account = BankAccount(bank_name=body.bank_name, account_number=body.account_number)
    db.add(account)
    db.commit()
    db.refresh(account)
    out = BankAccountOut.model_validate(account)
    out.transaction_count = 0
    return out


@router.patch("/{account_id}/transactions/{tx_id}", status_code=200)
def link_transaction(account_id: int, tx_id: int, db: Session = Depends(get_db)):
    """Manually link a transaction to a bank account."""
    account = db.get(BankAccount, account_id)
    if not account:
        raise HTTPException(404, "Bank account not found")
    tx = db.get(Transaction, tx_id)
    if not tx:
        raise HTTPException(404, "Transaction not found")
    tx.bank_account_id = account_id
    db.commit()
    return {"ok": True}


@router.delete("/{account_id}/transactions/{tx_id}", status_code=200)
def unlink_transaction(account_id: int, tx_id: int, db: Session = Depends(get_db)):
    """Remove the bank account link from a transaction."""
    tx = db.get(Transaction, tx_id)
    if not tx or tx.bank_account_id != account_id:
        raise HTTPException(404, "Transaction not found in this account")
    tx.bank_account_id = None
    db.commit()
    return {"ok": True}


@router.delete("/{account_id}", status_code=204)
def delete_bank_account(account_id: int, db: Session = Depends(get_db)):
    account = db.get(BankAccount, account_id)
    if not account:
        raise HTTPException(404, "Bank account not found")
    db.delete(account)
    db.commit()
