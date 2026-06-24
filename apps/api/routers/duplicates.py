"""
Duplicate Detection Engine
A transaction is a duplicate only when it matches another on ALL of:
Date, Amount, Type, Category, Description, Bank — exact match, no fuzzy logic.
"""
import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func

from database import get_db
from models import Transaction, AuditLog
from schemas import TransactionOut

router = APIRouter(prefix="/duplicates", tags=["duplicates"])

# Amount tolerance to absorb floating-point rounding only (not a fuzzy window).
_AMOUNT_EPSILON = 0.01

# Recurring per-transaction fees / system entries that carry no unique reference
# in their description. Two of these on the same day at the same amount are
# legitimately two separate charges (e.g. ₦50 stamp duty on each of several
# transfers that day), not a re-imported duplicate — never flag them.
_RECURRING_FEE_KEYWORDS = (
    "stamp duty",
    "stamp duties",
    "vat on transfer fee",
    "owealth withdrawal",
    "auto-save to owealth",
    "electronic money transfer levy",
)


def _norm(value: str | None) -> str:
    """Normalize a text field for exact comparison: trim + lowercase."""
    return (value or "").strip().lower()


def _is_recurring_fee(description: str | None) -> bool:
    text = _norm(description)
    return any(keyword in text for keyword in _RECURRING_FEE_KEYWORDS)


def detect_duplicates_for_transaction(db: Session, tx: Transaction) -> list[tuple[Transaction, float]]:
    """
    Find exact duplicates of `tx`.

    Two transactions are duplicates only when EVERY one of these fields is
    identical:
        - Date         (same calendar day)
        - Amount       (within ₦0.01, float-rounding tolerance only)
        - Type         (income / expense / transfer)
        - Category
        - Description
        - Bank

    Text fields are compared case-insensitively after trimming whitespace.
    Matching is fully deterministic — no references, fuzzy scoring, vendor
    heuristics, or date windows.

    Returns a list of (transaction, 1.0) tuples. Confidence is always 1.0
    because every reported match is exact. The signature and return shape are
    unchanged so all existing callers keep working.
    """
    if _is_recurring_fee(tx.description):
        return []

    # Narrow candidates in SQL on the cheap exact keys (date + type + bank),
    # then confirm amount and the remaining text fields in Python so string
    # comparison is case-insensitive and whitespace-insensitive.
    candidates = (
        db.query(Transaction)
        .filter(
            Transaction.id != tx.id,
            Transaction.duplicate_reviewed == False,
            Transaction.date == tx.date,
        )
        .all()
    )

    matches: list[tuple[Transaction, float]] = []
    for candidate in candidates:
        if abs(candidate.amount - tx.amount) > _AMOUNT_EPSILON:
            continue
        if _norm(candidate.type) != _norm(tx.type):
            continue
        if _norm(candidate.category) != _norm(tx.category):
            continue
        if _norm(candidate.description) != _norm(tx.description):
            continue
        if _norm(candidate.bank) != _norm(tx.bank):
            continue

        # All six fields matched exactly → definite duplicate.
        matches.append((candidate, 1.0))

    return matches


def mark_as_duplicates(db: Session, tx1: Transaction, tx2: Transaction, confidence: float):
    """Mark two transactions as potential duplicates."""
    tx1.is_potential_duplicate = True
    tx1.duplicate_of_id = tx2.id
    tx1.duplicate_confidence = confidence

    tx2.is_potential_duplicate = True

    db.add(AuditLog(
        entity_type="transaction",
        entity_id=tx1.id,
        action="flag_duplicate",
        new_values=json.dumps({
            "duplicate_of_id": tx2.id,
            "confidence": confidence,
        }),
    ))


@router.post("/scan")
def scan_all_duplicates(db: Session = Depends(get_db)):
    """
    Scan all unreviewed transactions for duplicates.
    Useful for initial setup or periodic re-scanning.
    """
    transactions = (
        db.query(Transaction)
        .filter(Transaction.duplicate_reviewed == False)
        .order_by(Transaction.date.desc())
        .all()
    )

    flagged = 0

    for tx in transactions:
        matches = detect_duplicates_for_transaction(db, tx)
        if matches:
            # Link to the best match
            best_match, confidence = matches[0]
            mark_as_duplicates(db, tx, best_match, confidence)
            flagged += 1

    db.commit()
    return {"scanned": len(transactions), "flagged": flagged}


@router.get("/pending", response_model=list[TransactionOut])
def list_pending_duplicates(db: Session = Depends(get_db)):
    """Get all transactions flagged as potential duplicates that need review."""
    duplicates = (
        db.query(Transaction)
        .filter(
            Transaction.is_potential_duplicate == True,
            Transaction.duplicate_reviewed == False,
        )
        .order_by(Transaction.date.desc())
        .all()
    )
    return duplicates


@router.post("/{tx_id}/keep")
def keep_transaction(tx_id: int, db: Session = Depends(get_db)):
    """
    Mark this transaction as NOT a duplicate (keep it, discard the other).
    Also deletes the linked duplicate transaction.
    """
    tx = db.get(Transaction, tx_id)
    if not tx:
        raise HTTPException(404, "Transaction not found")

    duplicate_id = tx.duplicate_of_id

    # Mark as reviewed
    tx.is_potential_duplicate = False
    tx.duplicate_of_id = None
    tx.duplicate_reviewed = True
    tx.duplicate_confidence = None

    # Delete the duplicate if it exists
    if duplicate_id:
        duplicate = db.get(Transaction, duplicate_id)
        if duplicate:
            db.add(AuditLog(
                entity_type="transaction",
                entity_id=tx_id,
                action="resolve_duplicate",
                old_values=json.dumps({"deleted_duplicate_id": duplicate_id}),
            ))
            db.delete(duplicate)

    db.commit()
    return {"ok": True}


@router.post("/{tx_id}/mark-not-duplicate")
def mark_not_duplicate(tx_id: int, db: Session = Depends(get_db)):
    """Mark this transaction as NOT a duplicate (keep both transactions)."""
    tx = db.get(Transaction, tx_id)
    if not tx:
        raise HTTPException(404, "Transaction not found")

    duplicate_id = tx.duplicate_of_id

    # Mark as reviewed
    tx.is_potential_duplicate = False
    tx.duplicate_of_id = None
    tx.duplicate_reviewed = True
    tx.duplicate_confidence = None

    # Also mark the linked transaction as not a duplicate
    if duplicate_id:
        duplicate = db.get(Transaction, duplicate_id)
        if duplicate:
            duplicate.is_potential_duplicate = False
            duplicate.duplicate_of_id = None
            duplicate.duplicate_reviewed = True

    db.add(AuditLog(
        entity_type="transaction",
        entity_id=tx_id,
        action="mark_not_duplicate",
        new_values=json.dumps({"marked_not_duplicate": True}),
    ))

    db.commit()
    return {"ok": True}


@router.get("/stats")
def get_duplicate_stats(db: Session = Depends(get_db)):
    """Get statistics about duplicate detection."""
    total_duplicates = db.query(func.count(Transaction.id)).filter(
        Transaction.is_potential_duplicate == True
    ).scalar()

    pending = db.query(func.count(Transaction.id)).filter(
        Transaction.is_potential_duplicate == True,
        Transaction.duplicate_reviewed == False,
    ).scalar()

    reviewed = db.query(func.count(Transaction.id)).filter(
        Transaction.duplicate_reviewed == True
    ).scalar()

    return {
        "total_duplicates": total_duplicates,
        "pending": pending,
        "reviewed": reviewed,
    }
