"""
Bank account management: store bank name + account number for reuse.
Enhanced with transaction mapping, balance tracking, and account linking.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import Optional, List
from datetime import datetime, date

from database import get_db
from models import BankAccount, BankTransaction
import bank_account_service

router = APIRouter(prefix="/bank-accounts", tags=["bank-accounts"])


class BankAccountCreate(BaseModel):
    bank_name: str
    account_number: str
    account_holder: Optional[str] = None
    currency: str = "NGN"
    account_type: Optional[str] = None


class BankAccountOut(BaseModel):
    id: int
    bank_name: str
    account_number: str
    account_holder: Optional[str]
    currency: str
    account_type: Optional[str]
    opening_balance: Optional[float]
    closing_balance: Optional[float]
    last_statement_date: Optional[date]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class BankAccountDetail(BankAccountOut):
    balance_summary: dict


class BalanceUpdate(BaseModel):
    opening_balance: Optional[float] = None
    closing_balance: Optional[float] = None


class MergeRequest(BaseModel):
    primary_account_id: int
    duplicate_account_ids: List[int]


class DuplicateGroup(BaseModel):
    account_number: str
    bank_name: str
    count: int
    accounts: List[dict]


# ── Endpoints ─────────────────────────────────────────────────────────────

@router.get("", response_model=list[BankAccountOut])
def list_bank_accounts(db: Session = Depends(get_db)):
    """List all bank accounts ordered by most recent statement."""
    return db.query(BankAccount).order_by(
        desc(BankAccount.last_statement_date),
        BankAccount.bank_name
    ).all()


@router.post("", response_model=BankAccountOut, status_code=201)
def create_bank_account(body: BankAccountCreate, db: Session = Depends(get_db)):
    """Create a new bank account."""
    try:
        account = bank_account_service.get_or_create_bank_account(
            db=db,
            bank_name=body.bank_name,
            account_number=body.account_number,
            account_holder=body.account_holder,
            currency=body.currency,
            account_type=body.account_type,
        )
        return BankAccountOut.model_validate(account)
    except Exception as e:
        raise HTTPException(400, f"Failed to create account: {str(e)}")


@router.get("/{account_id}", response_model=BankAccountDetail)
def get_bank_account(account_id: int, db: Session = Depends(get_db)):
    """Get detailed information about a specific bank account."""
    account = db.query(BankAccount).filter(BankAccount.id == account_id).first()
    if not account:
        raise HTTPException(404, "Bank account not found")
    
    account_data = BankAccountOut.model_validate(account).model_dump()
    account_data["balance_summary"] = bank_account_service.get_account_balance_summary(db, account_id)
    return account_data


@router.get("/{account_id}/transactions", response_model=list[dict])
def get_account_transactions(
    account_id: int,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    db: Session = Depends(get_db),
):
    """Get all transactions for a specific bank account."""
    account = db.query(BankAccount).filter(BankAccount.id == account_id).first()
    if not account:
        raise HTTPException(404, "Bank account not found")
    
    transactions = bank_account_service.get_account_transactions(db, account_id, start_date, end_date)
    return [
        {
            "id": tx.id,
            "date": tx.date.isoformat(),
            "description": tx.description,
            "amount": tx.amount,
            "type": tx.transaction_type,
            "category": tx.suggested_category,
            "reference": tx.reference,
            "vendor": tx.vendor,
        }
        for tx in transactions
    ]


@router.get("/{account_id}/summary", response_model=dict)
def get_account_summary(account_id: int, db: Session = Depends(get_db)):
    """Get balance summary for a bank account."""
    account = db.query(BankAccount).filter(BankAccount.id == account_id).first()
    if not account:
        raise HTTPException(404, "Bank account not found")
    
    return bank_account_service.get_account_balance_summary(db, account_id)


@router.patch("/{account_id}/balances", response_model=BankAccountOut)
def update_account_balances(
    account_id: int,
    update: BalanceUpdate,
    db: Session = Depends(get_db),
):
    """Update opening and closing balances for an account."""
    try:
        updated_account = bank_account_service.update_account_balances(
            db,
            account_id,
            update.opening_balance,
            update.closing_balance,
        )
        return BankAccountOut.model_validate(updated_account)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.get("/search/number/{account_number}", response_model=Optional[BankAccountOut])
def search_account_by_number(
    account_number: str,
    bank_name: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Search for a bank account by account number."""
    account = bank_account_service.get_account_by_number(db, account_number, bank_name)
    if not account:
        raise HTTPException(404, "Bank account not found")
    return BankAccountOut.model_validate(account)


@router.get("/duplicates/find", response_model=list[DuplicateGroup])
def find_duplicates(db: Session = Depends(get_db)):
    """Find potential duplicate bank accounts."""
    duplicates = bank_account_service.find_duplicate_accounts(db)
    return duplicates


@router.post("/duplicates/merge", response_model=BankAccountOut)
def merge_duplicates(request: MergeRequest, db: Session = Depends(get_db)):
    """Merge duplicate accounts into a primary account."""
    try:
        merged_account = bank_account_service.merge_duplicate_accounts(
            db,
            request.primary_account_id,
            request.duplicate_account_ids,
        )
        return BankAccountOut.model_validate(merged_account)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/stats/overview", response_model=dict)
def get_accounts_overview(db: Session = Depends(get_db)):
    """Get overview statistics for all bank accounts."""
    accounts = db.query(BankAccount).all()
    total_accounts = len(accounts)
    total_transactions = db.query(BankTransaction).count()
    
    total_income = 0
    total_expense = 0
    for account in accounts:
        summary = bank_account_service.get_account_balance_summary(db, account.id)
        total_income += summary["total_income"]
        total_expense += summary["total_expense"]
    
    return {
        "total_accounts": total_accounts,
        "total_transactions": total_transactions,
        "total_income": round(total_income, 2),
        "total_expense": round(total_expense, 2),
        "net_balance": round(total_income - total_expense, 2),
    }


@router.get("/mapping/all", response_model=dict)
def get_all_transaction_mappings(db: Session = Depends(get_db)):
    """Get mapping of all transactions grouped by bank account."""
    return bank_account_service.map_transactions_by_account(db)
    db.refresh(account)
    return account


@router.delete("/{account_id}", status_code=204)
def delete_bank_account(account_id: int, db: Session = Depends(get_db)):
    account = db.get(BankAccount, account_id)
    if not account:
        raise HTTPException(404, "Bank account not found")
    db.delete(account)
    db.commit()
