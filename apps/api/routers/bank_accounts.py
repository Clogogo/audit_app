"""
Bank account management: store bank name + account number for reuse.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime

from database import get_db
from models import BankAccount

router = APIRouter(prefix="/bank-accounts", tags=["bank-accounts"])


class BankAccountCreate(BaseModel):
    bank_name: str
    account_number: Optional[str] = None


class BankAccountOut(BaseModel):
    id: int
    bank_name: str
    account_number: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


@router.get("", response_model=list[BankAccountOut])
def list_bank_accounts(db: Session = Depends(get_db)):
    return db.query(BankAccount).order_by(BankAccount.bank_name).all()


@router.post("", response_model=BankAccountOut, status_code=201)
def create_bank_account(body: BankAccountCreate, db: Session = Depends(get_db)):
    # Prevent exact duplicates (same name + number)
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
    return account


@router.delete("/{account_id}", status_code=204)
def delete_bank_account(account_id: int, db: Session = Depends(get_db)):
    account = db.get(BankAccount, account_id)
    if not account:
        raise HTTPException(404, "Bank account not found")
    db.delete(account)
    db.commit()
