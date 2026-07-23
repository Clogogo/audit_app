"""
Duplicate Detection Engine
A transaction is a duplicate only when it matches another on ALL of:
Date, Amount, Type, Category, Description, Bank — exact match, no fuzzy logic.
"""
import json

from fastapi import APIRouter, Depends, HTTPException
from utils.auth import require_permission
from sqlalchemy.orm import Session
from sqlalchemy import func

from database import get_db
from models import Transaction, AuditLog, BankTransaction
from schemas import TransactionOut

router = APIRouter(prefix="/duplicates", tags=["duplicates"], dependencies=[Depends(require_permission("transactions"))])


# Amount tolerance to absorb floating-point rounding only (not a fuzzy window).
_AMOUNT_EPSILON = 0.01

# Recurring per-transaction fees / system entries whose description alone
# never proves duplication. Two of these on the same day at the same amount
# are usually legitimately two separate charges (e.g. ₦50 stamp duty on each
# of several transfers that day) — but a re-imported statement produces the
# exact same pattern. Description/amount/date can't tell the two cases
# apart; only the bank's own reference code can, so these are flagged as
# duplicates only when a reference is shared (see detect_duplicates_for_transaction).
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


def _references_for(db: Session, tx: Transaction) -> set[str]:
    """Bank statement references linked to this transaction (across re-imports)."""
    rows = (
        db.query(BankTransaction.reference)
        .filter(
            BankTransaction.matched_transaction_id == tx.id,
            BankTransaction.reference.isnot(None),
        )
        .all()
    )
    return {r[0] for r in rows}


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
    Matching is fully deterministic — no fuzzy scoring, vendor heuristics, or
    date windows. Bank statement references are used only to disambiguate
    field-identical candidates, never as the primary match key.

    Returns a list of (transaction, 1.0) tuples. Confidence is always 1.0
    because every reported match is exact. The signature and return shape are
    unchanged so all existing callers keep working.
    """
    is_recurring = _is_recurring_fee(tx.description)
    tx_refs = _references_for(db, tx)

    # A recurring fee with no bank reference at all can never be proven a
    # duplicate (see the reference-required branch below) — skip the query
    # entirely rather than building candidates that can't ever match.
    if is_recurring and not tx_refs:
        return []

    # Narrow candidates in SQL on the cheap exact keys (date + type + bank),
    # then confirm amount and the remaining text fields in Python so string
    # comparison is case-insensitive and whitespace-insensitive.
    # NOTE: do NOT filter by duplicate_reviewed here. A transaction that was
    # previously reviewed and kept is still a real existing record — a
    # re-import of the same data IS a duplicate of it and must be flagged.
    # Filtering by duplicate_reviewed == False caused reviewed transactions
    # to become invisible to the scanner, letting re-imports silently create
    # genuine un-flagged duplicates in the transaction list.
    candidates = (
        db.query(Transaction)
        .filter(
            Transaction.id != tx.id,
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

        candidate_refs = _references_for(db, candidate)

        if is_recurring:
            # A recurring fee looks identical whether it's 10 separate real
            # charges today or the same charge re-imported twice — only a
            # shared reference proves the latter, so require one instead of
            # flagging on appearance alone (the false-positive risk this
            # keyword list exists to avoid).
            if tx_refs.isdisjoint(candidate_refs):
                continue
        else:
            # Both sides carry a bank statement reference and they disagree →
            # two distinct real transfers that happen to look identical (e.g. the
            # same sender paying twice in one day), never a duplicate.
            if tx_refs and tx_refs.isdisjoint(candidate_refs):
                continue

        # All fields matched exactly → definite duplicate.
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
