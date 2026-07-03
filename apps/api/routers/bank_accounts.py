"""
Bank Account Management API
CRUD operations for managing bank accounts
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from utils.auth import require_permission
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models import BankAccount, BankStatement, Transaction
from schemas import BankAccountCreate, BankAccountOut
from utils import get_or_404

router = APIRouter(prefix="/bank-accounts", tags=["Bank Accounts"], dependencies=[Depends(require_permission("banking"))])


@router.get("", response_model=list[BankAccountOut])
def list_bank_accounts(db: Session = Depends(get_db)):
    """List all bank accounts."""
    accounts = db.query(BankAccount).order_by(BankAccount.bank_name).all()
    return accounts


@router.post("", response_model=BankAccountOut, status_code=201)
def create_bank_account(data: BankAccountCreate, db: Session = Depends(get_db)):
    """Create a new bank account."""
    # Check if bank account with same name already exists
    existing = (
        db.query(BankAccount)
        .filter(BankAccount.bank_name == data.bank_name)
        .first()
    )
    if existing:
        raise HTTPException(
            400,
            f"Bank account '{data.bank_name}' already exists. "
            "Update the existing account instead.",
        )

    account = BankAccount(
        bank_name=data.bank_name,
        account_holder_name=data.account_holder_name,
        account_number=data.account_number,
        opening_balance=data.opening_balance,
        current_balance=data.current_balance,
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


@router.get("/{account_id}", response_model=BankAccountOut)
def get_bank_account(account_id: int, db: Session = Depends(get_db)):
    """Get a specific bank account."""
    return get_or_404(db, BankAccount, account_id, "Bank account")


@router.put("/{account_id}", response_model=BankAccountOut)
def update_bank_account(
    account_id: int, data: BankAccountCreate, db: Session = Depends(get_db)
):
    """Update an existing bank account."""
    account = get_or_404(db, BankAccount, account_id, "Bank account")

    account.bank_name = data.bank_name
    account.account_holder_name = data.account_holder_name
    account.account_number = data.account_number
    account.opening_balance = data.opening_balance
    account.current_balance = data.current_balance
    db.commit()
    db.refresh(account)
    return account


class _BalanceUpdate(BaseModel):
    current_balance: Optional[float]


class _OpeningBalanceUpdate(BaseModel):
    opening_balance: Optional[float]


@router.patch("/{account_id}/balance", response_model=BankAccountOut)
def update_balance(account_id: int, data: _BalanceUpdate, db: Session = Depends(get_db)):
    """Set the actual (real-world) current balance for reconciliation."""
    account = get_or_404(db, BankAccount, account_id, "Bank account")
    account.current_balance = data.current_balance
    db.commit()
    db.refresh(account)
    return account


@router.patch("/{account_id}/opening-balance", response_model=BankAccountOut)
def update_opening_balance(account_id: int, data: _OpeningBalanceUpdate, db: Session = Depends(get_db)):
    """Set the opening balance (closing balance of prior period) for book balance calculation."""
    account = get_or_404(db, BankAccount, account_id, "Bank account")
    account.opening_balance = data.opening_balance
    db.commit()
    db.refresh(account)
    return account


@router.delete("/{account_id}", status_code=204)
def delete_bank_account(account_id: int, db: Session = Depends(get_db)):
    """
    Delete a bank account.
    Only allowed if no transactions or statements are linked.
    """
    account = get_or_404(db, BankAccount, account_id, "Bank account")

    # Check if account has transactions
    tx_count = (
        db.query(Transaction)
        .filter(Transaction.bank_account_id == account_id)
        .count()
    )
    if tx_count > 0:
        raise HTTPException(
            400,
            f"Cannot delete bank account with {tx_count} linked transactions. "
            "Delete or reassign transactions first.",
        )

    # Check if account has statements
    stmt_count = (
        db.query(BankStatement)
        .filter(BankStatement.bank_account_id == account_id)
        .count()
    )
    if stmt_count > 0:
        raise HTTPException(
            400,
            f"Cannot delete bank account with {stmt_count} linked statements. "
            "Delete statements first.",
        )

    db.delete(account)
    db.commit()
