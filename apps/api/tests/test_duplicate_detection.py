"""Tests for detect_duplicates_for_transaction — specifically the fix for
re-imports creating un-flagged duplicates against already-reviewed transactions.
"""
from datetime import date

from models import BankStatement, BankTransaction, Transaction
from routers.duplicates import detect_duplicates_for_transaction


def _tx(db_session, **kwargs) -> Transaction:
    defaults = dict(
        type="expense", amount=10000.0, currency="NGN",
        category="Salary and Wages",
        description="Transfer to Ngozi Williams",
        date=date(2026, 1, 15), bank="Opay",
    )
    tx = Transaction(**{**defaults, **kwargs})
    db_session.add(tx)
    db_session.commit()
    return tx


def test_detects_duplicate_of_an_unreviewed_transaction(db_session):
    original = _tx(db_session, duplicate_reviewed=False)
    reimport = _tx(db_session, duplicate_reviewed=False)

    matches = detect_duplicates_for_transaction(db_session, reimport)
    assert len(matches) == 1
    assert matches[0][0].id == original.id


def test_detects_duplicate_of_a_reviewed_and_kept_transaction(db_session):
    # Core regression: after a transaction is reviewed ("keep" / "not a
    # duplicate"), re-importing the same data must still be caught.
    # Previously, duplicate_reviewed == False filtered out reviewed
    # transactions, so re-imports slipped through as undetected duplicates.
    reviewed_original = _tx(db_session, duplicate_reviewed=True, is_potential_duplicate=False)
    reimport = _tx(db_session, duplicate_reviewed=False)

    matches = detect_duplicates_for_transaction(db_session, reimport)
    assert len(matches) == 1
    assert matches[0][0].id == reviewed_original.id


def test_different_description_is_not_flagged(db_session):
    _tx(db_session, description="Transfer to Ngozi Williams", duplicate_reviewed=True)
    different = _tx(db_session, description="Transfer to Chidi Okonkwo")

    matches = detect_duplicates_for_transaction(db_session, different)
    assert matches == []


def _link_reference(db_session, tx: Transaction, reference: str) -> None:
    stmt = BankStatement(bank_name=tx.bank, file_type="excel", status="pending")
    db_session.add(stmt)
    db_session.flush()
    db_session.add(BankTransaction(
        statement_id=stmt.id, date=tx.date, description=tx.description,
        amount=tx.amount, transaction_type="credit", reference=reference,
        matched_transaction_id=tx.id, match_status="matched",
    ))
    db_session.commit()


def test_same_sender_twice_in_one_day_is_not_flagged_when_references_differ(db_session):
    # Real-world case: a sender (e.g. a proprietor) transfers the same amount
    # twice in one day. Field-matching alone can't tell these apart — only
    # the bank statement reference proves they're two distinct events.
    first = _tx(db_session, description="Transfer from PATRICIA NKECHI OGOGO", amount=5000.0)
    second = _tx(db_session, description="Transfer from PATRICIA NKECHI OGOGO", amount=5000.0)
    _link_reference(db_session, first, "MIT|HBP|ref-aaaa")
    _link_reference(db_session, second, "MIT|TMP|ref-bbbb")

    matches = detect_duplicates_for_transaction(db_session, second)
    assert matches == []


def test_recurring_fee_is_never_flagged(db_session):
    _tx(db_session, description="Stamp Duty", amount=50.0, duplicate_reviewed=True)
    fee2 = _tx(db_session, description="Stamp Duty", amount=50.0, duplicate_reviewed=False)

    matches = detect_duplicates_for_transaction(db_session, fee2)
    assert matches == []


def test_scan_endpoint_flags_reimport_against_reviewed_transaction(client, db_session):
    # End-to-end: POST /duplicates/scan must catch re-imports of reviewed data.
    reviewed_original = _tx(db_session, duplicate_reviewed=True, is_potential_duplicate=False)
    reimport = _tx(db_session, duplicate_reviewed=False)

    resp = client.post("/duplicates/scan")
    assert resp.status_code == 200
    assert resp.json()["flagged"] == 1

    db_session.refresh(reimport)
    assert reimport.is_potential_duplicate is True
    assert reimport.duplicate_of_id == reviewed_original.id
