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


def _reimport_partner_id(db: Session, tx: Transaction) -> int | None:
    """Find the one OTHER ledger transaction that is unambiguously a literal
    re-import of the same bank line as `tx`.

    A bank reference is not guaranteed unique per real transaction — Opay
    reuses the same reference across distinct same-day fee events, and
    sometimes even across multiple rows within a single statement (confirmed
    against production data). So a reference is only trusted as proof of a
    duplicate when every one of these holds (each enforced by a specific
    check below, in order):
      1. tx itself is matched to exactly one distinct reference — if it's
         matched to two+ DIFFERENT references, the reconciliation collapsed
         two real bank lines onto this one ledger row and nothing about tx's
         reference history can be trusted.
      2. That reference appears EXACTLY twice in the whole bank_transactions
         table (rules out 3+ occurrences and "reused within one statement",
         where tx would be one of two+ rows sharing the SAME reference).
      3. The other occurrence is under a DIFFERENT statement upload, matched
         to a DIFFERENT ledger transaction, same date/amount.
      4. That other (candidate) transaction is, symmetrically, also matched
         to exactly one distinct reference.
    Any pattern failing one of these is left unflagged rather than guessed
    at, since it can't be told apart from two genuinely separate real
    charges that happen to share a reference.
    """
    my_bank_txs = (
        db.query(BankTransaction)
        .filter(BankTransaction.matched_transaction_id == tx.id, BankTransaction.reference.isnot(None))
        .all()
    )
    # tx itself must be matched to exactly one distinct reference — matched
    # to more than one means the reconciliation collapsed two real bank
    # lines onto this one ledger row, so nothing about tx's reference
    # history can be trusted (production case: a transaction matched to two
    # references, each independently looking like a clean reimport pair
    # with a DIFFERENT other transaction).
    if len({bt.reference for bt in my_bank_txs}) != 1:
        return None

    bt = my_bank_txs[0]
    all_with_ref = db.query(BankTransaction).filter(BankTransaction.reference == bt.reference).all()
    if len(all_with_ref) != 2:
        return None
    other = next((b for b in all_with_ref if b.id != bt.id), None)
    if not other or other.statement_id == bt.statement_id:
        return None
    if not other.matched_transaction_id or other.matched_transaction_id == tx.id:
        return None
    if other.date != bt.date or abs(other.amount - bt.amount) > _AMOUNT_EPSILON:
        return None

    # Same guard on the candidate side.
    other_refs = {
        b.reference for b in db.query(BankTransaction).filter(
            BankTransaction.matched_transaction_id == other.matched_transaction_id,
            BankTransaction.reference.isnot(None),
        ).all()
    }
    if len(other_refs) != 1:
        return None
    return other.matched_transaction_id


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

    # Recurring fees use a different, stricter signal (see _reimport_partner_id)
    # — reference overlap alone is not reliable for this category, so resolve
    # the one true reimport partner (if any) up front instead of scanning
    # same-day candidates by field+reference.
    if is_recurring:
        partner_id = _reimport_partner_id(db, tx)
        if partner_id is None:
            return []
        partner = db.get(Transaction, partner_id)
        if (
            partner
            and partner.date == tx.date
            and abs(partner.amount - tx.amount) <= _AMOUNT_EPSILON
            and _norm(partner.type) == _norm(tx.type)
            and _norm(partner.category) == _norm(tx.category)
            and _norm(partner.description) == _norm(tx.description)
            and _norm(partner.bank) == _norm(tx.bank)
        ):
            return [(partner, 1.0)]
        return []

    tx_refs = _references_for(db, tx)
    # More than one distinct reference matched to tx means the reconciliation
    # collapsed two real bank lines onto this one ledger row (confirmed in
    # production) — its reference set can't be trusted for disambiguation.
    tx_ambiguous = len(tx_refs) > 1
    # Loop-invariant: tx's own bank-row statements for its one reference (if
    # unambiguous), computed once rather than per-candidate.
    tx_stmts = (
        {
            b.statement_id for b in db.query(BankTransaction).filter(
                BankTransaction.matched_transaction_id == tx.id, BankTransaction.reference == next(iter(tx_refs)),
            ).all()
        }
        if tx_refs and not tx_ambiguous
        else set()
    )

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
        if tx_ambiguous or len(candidate_refs) > 1:
            continue

        # Both sides carry a bank statement reference and they disagree →
        # two distinct real transfers that happen to look identical (e.g. the
        # same sender paying twice in one day), never a duplicate.
        if tx_refs and tx_refs.isdisjoint(candidate_refs):
            continue

        # Both sides share the same single reference — only treat that as
        # confirming a duplicate if the underlying bank rows come from
        # different statement uploads. A reference reused within one
        # statement (confirmed against production data) is consistent with
        # two genuinely separate real events, not proof of one.
        if tx_refs and candidate_refs:
            shared_ref = next(iter(tx_refs))
            candidate_stmts = {
                b.statement_id for b in db.query(BankTransaction).filter(
                    BankTransaction.matched_transaction_id == candidate.id, BankTransaction.reference == shared_ref,
                ).all()
            }
            if not tx_stmts.isdisjoint(candidate_stmts):
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
