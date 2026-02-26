"""
Duplicate Detection Engine
Reuses the fuzzy matching algorithm from reconciliation to detect duplicate transactions.
"""
import json
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func

from database import get_db
from models import Transaction, AuditLog
from schemas import TransactionOut

router = APIRouter(prefix="/duplicates", tags=["duplicates"])


def _fuzzy_score(a: str, b: str) -> float:
    """Simple token-based similarity score (0-1). Reused from reconciliation."""
    try:
        from rapidfuzz import fuzz
        return fuzz.token_sort_ratio(a.lower(), b.lower()) / 100.0
    except ImportError:
        # Fallback: word overlap
        wa = set(a.lower().split())
        wb = set(b.lower().split())
        if not wa or not wb:
            return 0.0
        return len(wa & wb) / max(len(wa), len(wb))


def _extract_ref_id(reference: str | None) -> str | None:
    """Extract last 6 characters from transaction reference for comparison."""
    if not reference or len(reference) < 6:
        return None
    return reference[-6:].upper()


def detect_duplicates_for_transaction(db: Session, tx: Transaction) -> list[tuple[Transaction, float]]:
    """
    Find potential duplicates for a given transaction using reference-based and fuzzy matching.
    Returns list of (transaction, confidence_score) tuples.

    Matching strategy:
    1. If BOTH transactions have references:
       - Same ref (last 6 chars) → Duplicate (100% confidence)
       - Different refs → NOT duplicate (skip fuzzy matching)
       - Exception: Stamp Duty charges are recurring, not duplicates

    2. If EITHER transaction lacks a reference:
       - Use fuzzy matching:
         * Amount within ₦0.01
         * Date within 3 days
         * Description similarity >= 0.4
         * Vendor name must match (if both present)
    """
    candidates = (
        db.query(Transaction)
        .filter(
            Transaction.id != tx.id,
            Transaction.duplicate_reviewed == 0,
            Transaction.date >= tx.date - timedelta(days=3),
            Transaction.date <= tx.date + timedelta(days=3),
        )
        .all()
    )

    matches = []
    # Transaction model doesn't have a reference field, use description instead
    tx_ref_id = _extract_ref_id(getattr(tx, 'reference', None) or tx.description)

    for candidate in candidates:
        candidate_ref_id = _extract_ref_id(getattr(candidate, 'reference', None) or candidate.description)

        # ─── Case 1: Both have references ────────────────────────────────────
        if tx_ref_id and candidate_ref_id:
            if tx_ref_id == candidate_ref_id:
                # Exact reference match → Definite duplicate
                matches.append((candidate, 1.0))
                continue
            else:
                # Different references → NOT a duplicate
                # Exception: Recurring charges like Stamp Duty are NOT duplicates
                is_stamp_duty = (
                    "stamp duty" in tx.description.lower() or
                    "stamp duty" in candidate.description.lower()
                )
                if is_stamp_duty:
                    continue  # Skip - not a duplicate
                else:
                    continue  # Different refs = different transactions

        # ─── Case 2: At least one lacks reference → Use fuzzy matching ──────

        # Amount must match within 1 cent
        if abs(candidate.amount - tx.amount) > 0.01:
            continue

        # Date difference
        delta = abs((candidate.date - tx.date).days)
        if delta > 3:
            continue

        # Vendor matching (strict requirement if both present)
        tx_vendor = (tx.vendor or "").strip().lower()
        candidate_vendor = (candidate.vendor or "").strip().lower()

        if tx_vendor and candidate_vendor:
            vendor_score = _fuzzy_score(tx_vendor, candidate_vendor)
            if vendor_score < 0.7:  # Strict threshold for vendor match
                continue

        # Description fuzzy match
        desc_score = _fuzzy_score(tx.description, candidate.description)

        # Boost for same-day transactions
        date_bonus = (3 - delta) / 3 * 0.2
        total_score = desc_score + date_bonus

        # Threshold: 0.4 for description similarity
        if total_score >= 0.4:
            matches.append((candidate, round(total_score, 3)))

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
        .filter(Transaction.duplicate_reviewed == 0)
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
            Transaction.is_potential_duplicate == 1,
            Transaction.duplicate_reviewed == 0,
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
        Transaction.is_potential_duplicate == 1
    ).scalar()

    pending = db.query(func.count(Transaction.id)).filter(
        Transaction.is_potential_duplicate == 1,
        Transaction.duplicate_reviewed == 0,
    ).scalar()

    reviewed = db.query(func.count(Transaction.id)).filter(
        Transaction.duplicate_reviewed == 1
    ).scalar()

    return {
        "total_duplicates": total_duplicates,
        "pending": pending,
        "reviewed": reviewed,
    }
