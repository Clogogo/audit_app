"""Tests for detect_duplicates_for_transaction — specifically the fix for
re-imports creating un-flagged duplicates against already-reviewed transactions.
"""
from datetime import date

from models import Transaction
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
