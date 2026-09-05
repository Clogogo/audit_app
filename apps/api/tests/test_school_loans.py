"""Tests for School Loan payment handling — specifically that a loan only
auto-closes (is_active -> False) once BOTH principal and the agreed
total_interest_due are paid, not principal alone."""
from datetime import date

from sqlalchemy.orm import Session as OrmSession

import models as models_module
from models import Transaction


def _create_loan(client, total_interest_due: float = 0.0, loan_amount: float = 100000.0):
    resp = client.post("/school-loans/", json={
        "lender_name": "Test Cooperative",
        "loan_amount": loan_amount,
        "interest_rate": 10.0,
        "total_interest_due": total_interest_due,
        "collected_date": "2026-01-01",
    })
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_loan_with_no_interest_due_closes_on_principal_alone(client, db_session):
    # total_interest_due defaults to 0 -> unchanged legacy behavior.
    loan = _create_loan(client, total_interest_due=0.0)

    resp = client.post(f"/school-loans/{loan['id']}/payments", json={
        "amount_paid": 100000.0, "interest_amount": 0.0, "misc_amount": 0.0,
        "paid_date": "2026-02-01",
    })
    assert resp.status_code == 201, resp.text

    loan_after = client.get("/school-loans/").json()[0]
    assert loan_after["outstanding_today"] == 0.0
    assert loan_after["fully_paid"] is True
    assert loan_after["is_active"] is False


def test_loan_does_not_close_when_principal_paid_but_interest_still_owed(client, db_session):
    # ₦100,000 principal + ₦10,000 agreed interest. Paying only the principal
    # must NOT close the loan — this is the core bug being fixed.
    loan = _create_loan(client, total_interest_due=10000.0)

    resp = client.post(f"/school-loans/{loan['id']}/payments", json={
        "amount_paid": 100000.0, "interest_amount": 0.0, "misc_amount": 0.0,
        "paid_date": "2026-02-01",
    })
    assert resp.status_code == 201, resp.text

    loan_after = client.get("/school-loans/").json()[0]
    assert loan_after["outstanding_today"] == 0.0       # principal cleared
    assert loan_after["outstanding_interest"] == 10000.0  # interest still owed
    assert loan_after["fully_paid"] is False
    assert loan_after["is_active"] is True              # must still be open


def test_loan_closes_only_after_both_principal_and_interest_are_paid(client, db_session):
    loan = _create_loan(client, total_interest_due=10000.0)

    # First payment: principal only.
    resp = client.post(f"/school-loans/{loan['id']}/payments", json={
        "amount_paid": 100000.0, "interest_amount": 0.0, "misc_amount": 0.0,
        "paid_date": "2026-02-01",
    })
    assert resp.status_code == 201
    assert client.get("/school-loans/").json()[0]["is_active"] is True

    # Second payment: the remaining interest.
    resp = client.post(f"/school-loans/{loan['id']}/payments", json={
        "amount_paid": 10000.0, "interest_amount": 10000.0, "misc_amount": 0.0,
        "paid_date": "2026-03-01",
    })
    assert resp.status_code == 201

    loan_after = client.get("/school-loans/").json()[0]
    assert loan_after["outstanding_interest"] == 0.0
    assert loan_after["fully_paid"] is True
    assert loan_after["is_active"] is False


def test_editing_a_payment_reopens_a_loan_that_no_longer_qualifies_as_fully_paid(client, db_session):
    # Regression guard: previously only add_payment ever touched is_active,
    # so editing a payment down (e.g. correcting a data-entry mistake) left a
    # fully-repaid loan incorrectly marked closed.
    loan = _create_loan(client, total_interest_due=0.0)

    resp = client.post(f"/school-loans/{loan['id']}/payments", json={
        "amount_paid": 100000.0, "interest_amount": 0.0, "misc_amount": 0.0,
        "paid_date": "2026-02-01",
    })
    payment_id = resp.json()["id"]
    assert client.get("/school-loans/").json()[0]["is_active"] is False

    # Correcting the payment down to a partial amount must reopen the loan.
    resp = client.put(f"/school-loans/{loan['id']}/payments/{payment_id}", json={
        "amount_paid": 60000.0, "interest_amount": 0.0, "misc_amount": 0.0,
        "paid_date": "2026-02-01",
    })
    assert resp.status_code == 200, resp.text

    loan_after = client.get("/school-loans/").json()[0]
    assert loan_after["outstanding_today"] == 40000.0
    assert loan_after["is_active"] is True


def test_deleting_the_closing_payment_reopens_the_loan(client, db_session):
    loan = _create_loan(client, total_interest_due=0.0)

    resp = client.post(f"/school-loans/{loan['id']}/payments", json={
        "amount_paid": 100000.0, "interest_amount": 0.0, "misc_amount": 0.0,
        "paid_date": "2026-02-01",
    })
    payment_id = resp.json()["id"]
    assert client.get("/school-loans/").json()[0]["is_active"] is False

    resp = client.delete(f"/school-loans/{loan['id']}/payments/{payment_id}")
    assert resp.status_code == 204

    loan_after = client.get("/school-loans/").json()[0]
    assert loan_after["outstanding_today"] == 100000.0
    assert loan_after["is_active"] is True


def _update_loan(client, loan, **overrides):
    body = {
        "lender_name": loan["lender_name"],
        "loan_amount": loan["loan_amount"],
        "interest_rate": loan["interest_rate"],
        "total_interest_due": loan["total_interest_due"],
        "collected_date": loan["collected_date"],
        "notes": loan["notes"],
        "is_active": loan["is_active"],
    }
    body.update(overrides)
    return client.put(f"/school-loans/{loan['id']}", json=body)


def test_raising_total_interest_due_on_a_closed_loan_reopens_it(client, db_session):
    # Regression guard: editing loan terms (not a payment) can also make a
    # previously fully-paid loan incomplete again.
    loan = _create_loan(client, total_interest_due=0.0)
    client.post(f"/school-loans/{loan['id']}/payments", json={
        "amount_paid": 100000.0, "interest_amount": 0.0, "misc_amount": 0.0,
        "paid_date": "2026-02-01",
    })
    loan = client.get("/school-loans/").json()[0]
    assert loan["is_active"] is False

    resp = _update_loan(client, loan, total_interest_due=5000.0, is_active=False)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Money is still owed (the new interest) — can't stay closed even though
    # the request explicitly asked for is_active=False.
    assert body["outstanding_interest"] == 5000.0
    assert body["is_active"] is True


def test_explicit_is_active_is_respected_when_loan_is_genuinely_fully_paid(client, db_session):
    loan = _create_loan(client, total_interest_due=0.0)
    client.post(f"/school-loans/{loan['id']}/payments", json={
        "amount_paid": 100000.0, "interest_amount": 0.0, "misc_amount": 0.0,
        "paid_date": "2026-02-01",
    })
    loan = client.get("/school-loans/").json()[0]
    assert loan["is_active"] is False

    # Fully paid already — the user's explicit choice to reopen it for
    # tracking purposes must be respected, not silently overwritten.
    resp = _update_loan(client, loan, is_active=True)
    assert resp.status_code == 200, resp.text
    assert resp.json()["is_active"] is True


def _simulate_missing_loan(monkeypatch, loan_id: int) -> None:
    # A truly-dangling payment row (parent loan deleted) can't be constructed
    # directly against Postgres — the FK constraint is enforced there (only
    # SQLite lets it happen). Simulate the missing-loan lookup instead, so
    # the 404-not-500 guard is tested the same way on both engines.
    original_get = OrmSession.get

    def fake_get(self, entity, ident, *args, **kwargs):
        if entity is models_module.SchoolLoan and ident == loan_id:
            return None
        return original_get(self, entity, ident, *args, **kwargs)

    monkeypatch.setattr(OrmSession, "get", fake_get)


def test_updating_a_payment_with_a_missing_parent_loan_returns_404_not_500(client, db_session, monkeypatch):
    loan = _create_loan(client, total_interest_due=0.0)
    resp = client.post(f"/school-loans/{loan['id']}/payments", json={
        "amount_paid": 1000.0, "interest_amount": 0.0, "misc_amount": 0.0,
        "paid_date": "2026-01-01",
    })
    payment_id = resp.json()["id"]

    _simulate_missing_loan(monkeypatch, loan["id"])
    resp = client.put(f"/school-loans/{loan['id']}/payments/{payment_id}", json={
        "amount_paid": 2000.0, "interest_amount": 0.0, "misc_amount": 0.0,
        "paid_date": "2026-01-01",
    })
    assert resp.status_code == 404


def test_deleting_a_payment_with_a_missing_parent_loan_returns_404_not_500(client, db_session, monkeypatch):
    loan = _create_loan(client, total_interest_due=0.0)
    resp = client.post(f"/school-loans/{loan['id']}/payments", json={
        "amount_paid": 1000.0, "interest_amount": 0.0, "misc_amount": 0.0,
        "paid_date": "2026-01-01",
    })
    payment_id = resp.json()["id"]

    _simulate_missing_loan(monkeypatch, loan["id"])
    resp = client.delete(f"/school-loans/{loan['id']}/payments/{payment_id}")
    assert resp.status_code == 404


def test_new_loan_is_unverified_with_no_linked_transaction(client, db_session):
    loan = _create_loan(client)
    assert loan["transaction_id"] is None
    assert loan["verified"] is False
    assert loan["matched_tx"] is None


def test_linking_a_transaction_to_a_loan_marks_it_verified(client, db_session):
    loan = _create_loan(client)
    tx = Transaction(
        type="income", amount=100000.0, currency="NGN", category="Loans",
        description="Loan from Test Cooperative", date=date(2026, 1, 1),
    )
    db_session.add(tx)
    db_session.commit()

    resp = client.put(f"/school-loans/{loan['id']}", json={
        "lender_name": loan["lender_name"], "loan_amount": loan["loan_amount"],
        "interest_rate": loan["interest_rate"], "total_interest_due": loan["total_interest_due"],
        "collected_date": loan["collected_date"], "transaction_id": tx.id,
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["transaction_id"] == tx.id
    assert body["verified"] is True
    assert body["matched_tx"]["id"] == tx.id
    assert body["matched_tx"]["amount"] == 100000.0


def test_overpaid_interest_credits_toward_principal_remaining(client, db_session):
    # Regression guard for the "Total Remaining" figure not moving after
    # editing total_interest_due: two payments recorded 30,000 interest each
    # (60,000 total) against a loan whose agreed interest is later corrected
    # down to 50,000. The 10,000 excess must count toward principal, not
    # vanish into the outstanding_interest floor — total paid (200,038.60)
    # already covers total owed (150,000 + 50,000), so nothing should be left.
    loan = _create_loan(client, total_interest_due=60000.0, loan_amount=150000.0)
    client.post(f"/school-loans/{loan['id']}/payments", json={
        "amount_paid": 100020.0, "interest_amount": 30000.0, "misc_amount": 0.0,
        "paid_date": "2026-02-18",
    })
    client.post(f"/school-loans/{loan['id']}/payments", json={
        "amount_paid": 100018.6, "interest_amount": 30000.0, "misc_amount": 0.0,
        "paid_date": "2026-06-13",
    })
    loan = client.get("/school-loans/").json()[0]
    # At the original 60,000 agreed interest, nothing is overpaid yet — a
    # small principal balance genuinely remains.
    assert loan["outstanding_today"] == 9961.4
    assert loan["fully_paid"] is False

    # Now correct the agreed interest down to 50,000 — interest paid (60,000)
    # now exceeds it by 10,000, which must credit toward the remaining
    # principal instead of vanishing.
    resp = _update_loan(client, loan, total_interest_due=50000.0)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["outstanding_interest"] == 0.0
    assert body["outstanding_today"] == 0.0
    assert body["fully_paid"] is True
    # is_active is untouched here by design: the loan-terms endpoint only
    # force-reopens a loan that no longer qualifies as paid, it never
    # force-closes one — the user's explicit active/inactive choice stands.


def test_match_transactions_income_type_excludes_expense_transactions(client, db_session):
    loan = _create_loan(client)
    income_tx = Transaction(
        type="income", amount=100000.0, currency="NGN", category="Loans",
        description="Test Cooperative loan disbursement", date=date(2026, 1, 1),
    )
    expense_tx = Transaction(
        type="expense", amount=5000.0, currency="NGN", category="Loans",
        description="Test Cooperative repayment", date=date(2026, 1, 1),
    )
    db_session.add_all([income_tx, expense_tx])
    db_session.commit()

    resp = client.get(f"/school-loans/{loan['id']}/match-transactions", params={
        "year": 2026, "month": 1, "tx_type": "income",
    })
    assert resp.status_code == 200, resp.text
    ids = {t["id"] for t in resp.json()}
    assert ids == {income_tx.id}
