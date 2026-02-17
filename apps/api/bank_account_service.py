"""
Bank Account Management Service

Handles:
- Creating/retrieving bank accounts from extracted statement data
- Mapping transactions to their corresponding bank accounts
- Updating account metadata from statements
"""

from datetime import date
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_, desc

from models import BankAccount, BankStatement, BankTransaction
import logging

logger = logging.getLogger(__name__)


def get_or_create_bank_account(
    db: Session,
    bank_name: str,
    account_number: str,
    account_holder: Optional[str] = None,
    currency: str = "NGN",
    account_type: Optional[str] = None,
) -> BankAccount:
    """
    Get existing bank account or create a new one.
    
    Args:
        db: Database session
        bank_name: Name of the bank (e.g., "Access Bank", "GTBank")
        account_number: Full account number (unique identifier)
        account_holder: Optional account holder name
        currency: Currency code (default: NGN for Nigerian Naira)
        account_type: Account type (e.g., "Savings", "Checking")
    
    Returns:
        BankAccount instance (created or existing)
    """
    # Try to find existing account
    existing = db.query(BankAccount).filter(
        and_(
            BankAccount.bank_name == bank_name,
            BankAccount.account_number == account_number,
        )
    ).first()
    
    if existing:
        logger.info(f"Found existing bank account: {bank_name} {account_number[-4:]}")
        return existing
    
    # Create new account
    new_account = BankAccount(
        bank_name=bank_name,
        account_number=account_number,
        account_holder=account_holder,
        currency=currency,
        account_type=account_type,
    )
    db.add(new_account)
    db.commit()
    db.refresh(new_account)
    logger.info(f"Created new bank account: {bank_name} {account_number[-4:]}")
    return new_account


def link_statement_to_account(
    db: Session,
    statement: BankStatement,
    bank_account: BankAccount,
) -> BankStatement:
    """
    Link a bank statement to a bank account.
    
    Args:
        db: Database session
        statement: BankStatement to link
        bank_account: BankAccount to link to
    
    Returns:
        Updated BankStatement
    """
    statement.bank_account_id = bank_account.id
    
    # Update account's last_statement_date if this is more recent
    if statement.statement_period_end:
        if not bank_account.last_statement_date or statement.statement_period_end > bank_account.last_statement_date:
            bank_account.last_statement_date = statement.statement_period_end
    
    db.commit()
    db.refresh(statement)
    logger.info(f"Linked statement {statement.id} to account {bank_account.id}")
    return statement


def link_transactions_to_account(
    db: Session,
    transactions: list[BankTransaction],
    bank_account: BankAccount,
) -> None:
    """
    Bulk link multiple transactions to a bank account.
    
    Args:
        db: Database session
        transactions: List of BankTransaction objects
        bank_account: BankAccount to link to
    """
    for tx in transactions:
        tx.bank_account_id = bank_account.id
    
    db.commit()
    logger.info(f"Linked {len(transactions)} transactions to account {bank_account.id}")


def get_account_transactions(
    db: Session,
    bank_account_id: int,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> list[BankTransaction]:
    """
    Retrieve all transactions for a bank account within date range.
    
    Args:
        db: Database session
        bank_account_id: ID of the bank account
        start_date: Optional filter start date
        end_date: Optional filter end date
    
    Returns:
        List of BankTransaction objects
    """
    query = db.query(BankTransaction).filter(
        BankTransaction.bank_account_id == bank_account_id
    )
    
    if start_date:
        query = query.filter(BankTransaction.date >= start_date)
    if end_date:
        query = query.filter(BankTransaction.date <= end_date)
    
    return query.order_by(BankTransaction.date).all()


def get_account_balance_summary(
    db: Session,
    bank_account_id: int,
) -> dict:
    """
    Get balance summary for a bank account (total income, expenses, net).
    
    Args:
        db: Database session
        bank_account_id: ID of the bank account
    
    Returns:
        Dictionary with balance metrics
    """
    transactions = db.query(BankTransaction).filter(
        BankTransaction.bank_account_id == bank_account_id
    ).all()
    
    total_income = sum(tx.amount for tx in transactions if tx.transaction_type == "credit")
    total_expense = sum(tx.amount for tx in transactions if tx.transaction_type == "debit")
    net = total_income - total_expense
    
    return {
        "total_income": round(total_income, 2),
        "total_expense": round(total_expense, 2),
        "net": round(net, 2),
        "transaction_count": len(transactions),
    }


def map_transactions_by_account(
    db: Session,
) -> dict:
    """
    Get mapping of all transactions grouped by bank account.
    
    Returns:
        Dictionary with account_id -> transactions mapping
    """
    accounts = db.query(BankAccount).all()
    mapping = {}
    
    for account in accounts:
        transactions = db.query(BankTransaction).filter(
            BankTransaction.bank_account_id == account.id
        ).all()
        mapping[account.id] = {
            "account": {
                "id": account.id,
                "bank_name": account.bank_name,
                "account_number": account.account_number,
                "account_holder": account.account_holder,
                "currency": account.currency,
            },
            "transactions": [
                {
                    "id": tx.id,
                    "date": tx.date.isoformat(),
                    "description": tx.description,
                    "amount": tx.amount,
                    "type": tx.transaction_type,
                    "category": tx.suggested_category,
                }
                for tx in transactions
            ],
            "summary": get_account_balance_summary(db, account.id),
        }
    
    return mapping


def update_account_balances(
    db: Session,
    bank_account_id: int,
    opening_balance: Optional[float] = None,
    closing_balance: Optional[float] = None,
) -> BankAccount:
    """
    Update opening and closing balances for a bank account.
    
    Args:
        db: Database session
        bank_account_id: ID of the bank account
        opening_balance: Optional opening balance
        closing_balance: Optional closing balance
    
    Returns:
        Updated BankAccount
    """
    account = db.query(BankAccount).filter(BankAccount.id == bank_account_id).first()
    
    if not account:
        raise ValueError(f"Bank account {bank_account_id} not found")
    
    if opening_balance is not None:
        account.opening_balance = opening_balance
    if closing_balance is not None:
        account.closing_balance = closing_balance
    
    db.commit()
    db.refresh(account)
    logger.info(f"Updated balances for account {bank_account_id}")
    return account


def get_account_by_number(
    db: Session,
    account_number: str,
    bank_name: Optional[str] = None,
) -> Optional[BankAccount]:
    """
    Retrieve a bank account by account number and optionally bank name.
    
    Args:
        db: Database session
        account_number: Account number to search for
        bank_name: Optional bank name for more specific search
    
    Returns:
        BankAccount if found, None otherwise
    """
    query = db.query(BankAccount).filter(BankAccount.account_number == account_number)
    
    if bank_name:
        query = query.filter(BankAccount.bank_name == bank_name)
    
    return query.first()


def find_duplicate_accounts(
    db: Session,
) -> list[dict]:
    """
    Find potential duplicate bank accounts (same account number, different entries).
    
    Returns:
        List of duplicate account groups
    """
    from sqlalchemy import func
    
    duplicates = (
        db.query(
            BankAccount.account_number,
            BankAccount.bank_name,
            func.count(BankAccount.id).label('count')
        )
        .group_by(BankAccount.account_number, BankAccount.bank_name)
        .having(func.count(BankAccount.id) > 1)
        .all()
    )
    
    result = []
    for dup in duplicates:
        accounts = db.query(BankAccount).filter(
            and_(
                BankAccount.account_number == dup.account_number,
                BankAccount.bank_name == dup.bank_name,
            )
        ).all()
        result.append({
            "account_number": dup.account_number,
            "bank_name": dup.bank_name,
            "count": dup.count,
            "accounts": [
                {
                    "id": acc.id,
                    "account_holder": acc.account_holder,
                    "created_at": acc.created_at.isoformat(),
                }
                for acc in accounts
            ],
        })
    
    return result


def merge_duplicate_accounts(
    db: Session,
    primary_account_id: int,
    duplicate_account_ids: list[int],
) -> BankAccount:
    """
    Merge duplicate accounts by consolidating all transactions to primary account.
    
    Args:
        db: Database session
        primary_account_id: ID of the account to keep
        duplicate_account_ids: List of account IDs to merge into primary
    
    Returns:
        Primary BankAccount with merged transactions
    """
    primary = db.query(BankAccount).filter(BankAccount.id == primary_account_id).first()
    if not primary:
        raise ValueError(f"Primary account {primary_account_id} not found")
    
    # Move all transactions from duplicates to primary
    for dup_id in duplicate_account_ids:
        db.query(BankTransaction).filter(
            BankTransaction.bank_account_id == dup_id
        ).update({BankTransaction.bank_account_id: primary_account_id})
        
        # Delete the duplicate account
        db.query(BankAccount).filter(BankAccount.id == dup_id).delete()
    
    db.commit()
    db.refresh(primary)
    logger.info(f"Merged {len(duplicate_account_ids)} accounts into account {primary_account_id}")
    return primary
