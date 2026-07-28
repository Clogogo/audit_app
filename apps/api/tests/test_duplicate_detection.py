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


def test_recurring_fee_with_no_reference_is_never_flagged(db_session):
    # No bank reference on either side — description/amount alone can never
    # prove this is a re-import rather than two genuinely separate ₦50 fees
    # charged the same day, so it must never be flagged.
    _tx(db_session, description="Stamp Duty", amount=50.0, duplicate_reviewed=True)
    fee2 = _tx(db_session, description="Stamp Duty", amount=50.0, duplicate_reviewed=False)

    matches = detect_duplicates_for_transaction(db_session, fee2)
    assert matches == []


def test_recurring_fee_with_different_references_is_not_flagged(db_session):
    # Two genuinely separate real fees, each with its own bank reference —
    # looking identical is a coincidence, not proof of a re-import.
    first = _tx(db_session, description="Stamp Duty", amount=50.0)
    second = _tx(db_session, description="Stamp Duty", amount=50.0)
    _link_reference(db_session, first, "260130550101697469440335")
    _link_reference(db_session, second, "260130550101697651725248")

    matches = detect_duplicates_for_transaction(db_session, second)
    assert matches == []


def test_recurring_fee_sharing_a_reference_within_one_statement_is_not_flagged(db_session):
    # Production regression: Opay reuses the same bank reference across
    # distinct real same-day fee events within a single statement (not a
    # re-import) — confirmed against production data where two separate real
    # OWealth Withdrawal fees shared one reference. Reference overlap alone
    # is not proof of duplication; only a twin bank row under a DIFFERENT
    # statement upload is. Both fees here share one statement, so neither
    # should be flagged even though their bank references match.
    first = _tx(db_session, description="OWealth Withdrawal(Transaction Payment)", amount=50.0, type="expense")
    second = _tx(db_session, description="OWealth Withdrawal(Transaction Payment)", amount=50.0, type="expense")
    stmt = BankStatement(bank_name="Opay", file_type="excel", status="pending")
    db_session.add(stmt)
    db_session.flush()
    shared_ref = "260130010201697602627534"
    db_session.add(BankTransaction(
        statement_id=stmt.id, date=first.date, description=first.description,
        amount=first.amount, transaction_type="debit", reference=shared_ref,
        matched_transaction_id=first.id, match_status="matched",
    ))
    db_session.add(BankTransaction(
        statement_id=stmt.id, date=second.date, description=second.description,
        amount=second.amount, transaction_type="debit", reference=shared_ref,
        matched_transaction_id=second.id, match_status="matched",
    ))
    db_session.commit()

    matches = detect_duplicates_for_transaction(db_session, second)
    assert matches == []


def test_recurring_fee_with_shared_reference_is_flagged(db_session):
    # Regression for the production bug: a re-imported statement links a new
    # bank_transactions row (same reference as the original) to a brand-new
    # Transaction rather than the existing one — this is exactly the pattern
    # that let 303 real duplicates slip through undetected on OPay.
    original = _tx(db_session, description="Auto-save to OWealth Balance", amount=44825.0, type="transfer")
    reimport = _tx(db_session, description="Auto-save to OWealth Balance", amount=44825.0, type="transfer")
    _link_reference(db_session, original, "260103140300938512383777")
    _link_reference(db_session, reimport, "260103140300938512383777")

    matches = detect_duplicates_for_transaction(db_session, reimport)
    assert len(matches) == 1
    assert matches[0][0].id == original.id


def test_recurring_fee_reimport_with_different_ledger_dates_is_not_flagged(db_session):
    # The bank rows can share a reference while the ledger transactions
    # themselves have since diverged (e.g. one was edited after matching) —
    # date must be re-checked at the ledger level, not just the bank-row
    # level, or a genuinely different transaction could be "Keep"-deleted.
    original = _tx(db_session, description="Auto-save to OWealth Balance", amount=44825.0, type="transfer", date=date(2026, 1, 15))
    edited = _tx(db_session, description="Auto-save to OWealth Balance", amount=44825.0, type="transfer", date=date(2026, 3, 1))
    shared_ref = "260103140300938512383777"
    _link_reference(db_session, original, shared_ref)
    # The bank row itself still reflects the original import date even
    # though the ledger transaction's own date was edited afterward.
    stmt = BankStatement(bank_name="Opay", file_type="excel", status="pending")
    db_session.add(stmt)
    db_session.flush()
    db_session.add(BankTransaction(
        statement_id=stmt.id, date=original.date, description=edited.description,
        amount=edited.amount, transaction_type="credit", reference=shared_ref,
        matched_transaction_id=edited.id, match_status="matched",
    ))
    db_session.commit()

    matches = detect_duplicates_for_transaction(db_session, edited)
    assert matches == []


def test_recurring_fee_where_tx_is_matched_to_two_references_is_not_flagged(db_session):
    # Hub case found in production: a single ledger transaction wrongly
    # matched (by the reconciliation engine, not this code) to two
    # DIFFERENT bank rows with two different references. Each reference
    # independently looks like a clean reimport pair with a different
    # other transaction — neither should be trusted.
    hub = _tx(db_session, description="OWealth Withdrawal(Transaction Payment)", amount=50.0, type="expense")
    partner_a = _tx(db_session, description="OWealth Withdrawal(Transaction Payment)", amount=50.0, type="expense")
    partner_b = _tx(db_session, description="OWealth Withdrawal(Transaction Payment)", amount=50.0, type="expense")
    _link_reference(db_session, hub, "ref-one")
    _link_reference(db_session, partner_a, "ref-one")
    _link_reference(db_session, hub, "ref-two")
    _link_reference(db_session, partner_b, "ref-two")

    assert detect_duplicates_for_transaction(db_session, hub) == []
    # The candidate side must also reject the hub as an untrustworthy partner.
    assert detect_duplicates_for_transaction(db_session, partner_a) == []
    assert detect_duplicates_for_transaction(db_session, partner_b) == []


def test_non_recurring_candidate_matched_to_two_references_is_not_flagged(db_session):
    # Same over-matching risk on the non-recurring path: if the candidate
    # side is matched to two different references, its reference set can't
    # be trusted to confirm anything, even though tx itself is clean.
    tx = _tx(db_session, description="Transfer from PATRICIA NKECHI OGOGO", amount=5000.0)
    over_matched = _tx(db_session, description="Transfer from PATRICIA NKECHI OGOGO", amount=5000.0)
    other = _tx(db_session, description="Transfer from PATRICIA NKECHI OGOGO", amount=5000.0)
    _link_reference(db_session, tx, "ref-shared")
    _link_reference(db_session, over_matched, "ref-shared")
    _link_reference(db_session, over_matched, "ref-extra")
    _link_reference(db_session, other, "ref-extra")

    matches = detect_duplicates_for_transaction(db_session, tx)
    assert matches == []


def test_non_recurring_tx_matched_to_two_references_is_not_flagged(db_session):
    # Symmetric case: tx itself (not the candidate) is over-matched to two
    # different references — its own reference set can't be trusted either.
    hub = _tx(db_session, description="Transfer from PATRICIA NKECHI OGOGO", amount=5000.0)
    partner_a = _tx(db_session, description="Transfer from PATRICIA NKECHI OGOGO", amount=5000.0)
    partner_b = _tx(db_session, description="Transfer from PATRICIA NKECHI OGOGO", amount=5000.0)
    _link_reference(db_session, hub, "ref-one")
    _link_reference(db_session, partner_a, "ref-one")
    _link_reference(db_session, hub, "ref-two")
    _link_reference(db_session, partner_b, "ref-two")

    assert detect_duplicates_for_transaction(db_session, hub) == []


def test_non_recurring_shared_reference_within_one_statement_is_not_flagged(db_session):
    # Same production characteristic as the recurring-fee case, applied to
    # a normal transfer: a reference reused within one statement for two
    # genuinely separate real transfers must not be treated as proof.
    first = _tx(db_session, description="Transfer from PATRICIA NKECHI OGOGO", amount=5000.0)
    second = _tx(db_session, description="Transfer from PATRICIA NKECHI OGOGO", amount=5000.0)
    stmt = BankStatement(bank_name="Opay", file_type="excel", status="pending")
    db_session.add(stmt)
    db_session.flush()
    shared_ref = "ref-reused-in-one-statement"
    db_session.add(BankTransaction(
        statement_id=stmt.id, date=first.date, description=first.description,
        amount=first.amount, transaction_type="credit", reference=shared_ref,
        matched_transaction_id=first.id, match_status="matched",
    ))
    db_session.add(BankTransaction(
        statement_id=stmt.id, date=second.date, description=second.description,
        amount=second.amount, transaction_type="credit", reference=shared_ref,
        matched_transaction_id=second.id, match_status="matched",
    ))
    db_session.commit()

    matches = detect_duplicates_for_transaction(db_session, second)
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
