"""Tests for the opening-balance-date anchor fix in /bank-statements/bank-accounts.

Book balance (net_amount) must roll forward from the date opening_balance was
actually recorded, not from whatever start_date a report happens to be filtered
by — otherwise changing the date filter silently drops income/expense that
occurred between the true anchor and start_date, drifting away from the real
bank statement.
"""
from datetime import date

from models import BankAccount, Transaction


def _create_account(db_session, opening_balance_date: str | None = None, **kwargs) -> BankAccount:
    account = BankAccount(
        bank_name="Test Bank",
        opening_balance_date=date.fromisoformat(opening_balance_date) if opening_balance_date else None,
        **kwargs,
    )
    db_session.add(account)
    db_session.commit()
    db_session.refresh(account)
    return account


def _create_transaction(db_session, bank_account_id: int, type_: str, amount: float, date_: str, category: str = "General") -> Transaction:
    tx = Transaction(
        type=type_, amount=amount, category=category, description="test",
        date=date.fromisoformat(date_), bank_account_id=bank_account_id,
    )
    db_session.add(tx)
    db_session.commit()
    return tx


def test_net_amount_without_anchor_matches_old_behavior(client, db_session):
    """No opening_balance_date set: falls back to start_date, i.e. unchanged."""
    account = _create_account(db_session, opening_balance=1000.0)
    _create_transaction(db_session, account.id, "income", 500.0, "2026-02-01")
    _create_transaction(db_session, account.id, "expense", 200.0, "2026-02-10")

    resp = client.get(
        "/bank-statements/bank-accounts",
        params={"start_date": "2026-02-01", "end_date": "2026-02-28"},
    )
    assert resp.status_code == 200, resp.text
    report = next(r for r in resp.json() if r["bank_account_id"] == account.id)
    assert report["opening_balance_date"] is None
    assert report["net_amount"] == 1000.0 + 500.0 - 200.0


def test_net_amount_rolls_forward_from_anchor_not_start_date(client, db_session):
    """
    opening_balance was recorded Jan 1; a Feb 1 transaction happened between
    the anchor and the report's selected start_date (Feb 1..Feb 28). Without
    the fix, that January activity would be silently dropped from net_amount
    when the user filters to February only — this is exactly the gap the user
    reported (report balance not matching the real statement).
    """
    account = _create_account(
        db_session, opening_balance=1000.0, opening_balance_date="2026-01-01",
    )
    # Activity between the anchor (Jan 1) and the report's start_date (Feb 1) —
    # must still count toward net_amount even though it's outside the period filter.
    _create_transaction(db_session, account.id, "income", 300.0, "2026-01-15")
    # Activity inside the selected period.
    _create_transaction(db_session, account.id, "expense", 200.0, "2026-02-10")

    resp = client.get(
        "/bank-statements/bank-accounts",
        params={"start_date": "2026-02-01", "end_date": "2026-02-28"},
    )
    assert resp.status_code == 200, resp.text
    report = next(r for r in resp.json() if r["bank_account_id"] == account.id)

    # Period totals reflect only the Feb window (unchanged semantics).
    assert report["total_income"] == 0.0
    assert report["total_expense"] == 200.0

    # But net_amount rolls forward from the true anchor: 1000 + 300 (Jan) - 200 (Feb).
    assert report["net_amount"] == 1000.0 + 300.0 - 200.0
    assert report["opening_balance_date"] == "2026-01-01"


def test_detail_endpoint_net_amount_also_rolls_forward(client, db_session):
    account = _create_account(
        db_session, opening_balance=500.0, opening_balance_date="2026-01-01",
    )
    _create_transaction(db_session, account.id, "income", 100.0, "2026-01-20")
    _create_transaction(db_session, account.id, "expense", 50.0, "2026-02-05")

    resp = client.get(
        f"/bank-statements/bank-accounts/{account.id}",
        params={"start_date": "2026-02-01", "end_date": "2026-02-28"},
    )
    assert resp.status_code == 200, resp.text
    report = resp.json()
    assert report["total_income"] == 0.0
    assert report["total_expense"] == 50.0
    assert report["net_amount"] == 500.0 + 100.0 - 50.0


def test_patch_opening_balance_sets_anchor_date(client, db_session):
    account = _create_account(db_session)

    resp = client.patch(
        f"/bank-accounts/{account.id}/opening-balance",
        json={"opening_balance": 750.0, "opening_balance_date": "2026-03-01"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["opening_balance"] == 750.0
    assert body["opening_balance_date"] == "2026-03-01"
