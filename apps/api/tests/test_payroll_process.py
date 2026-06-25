"""Tests for POST /payroll/process, focused on the category+amount fallback
match used when the bank account is registered under a different
first/middle name than the staff record (e.g. a spouse's name)."""
from datetime import date

import pytest

from models import Staff, Transaction


def _create_staff(db_session, full_name: str, monthly_gross: float) -> Staff:
    staff = Staff(full_name=full_name, monthly_gross=monthly_gross, is_active=True)
    db_session.add(staff)
    db_session.commit()
    return staff


def _create_salary_transaction(db_session, vendor: str, amount: float, day: str, category: str = "Salary and Wages"):
    tx = Transaction(
        type="expense",
        amount=amount,
        currency="NGN",
        category=category,
        description=f"Transfer to {vendor} | OPay | 0000000000 | January 2026",
        date=date.fromisoformat(day),
        vendor=vendor,
    )
    db_session.add(tx)
    db_session.commit()
    return tx


def test_fallback_matches_different_first_name_when_category_and_amount_agree(client, db_session):
    staff = _create_staff(db_session, "Emmanuella Christian", monthly_gross=15020.0)
    tx = _create_salary_transaction(db_session, "HELEN CHINENYE CHRISTIAN", amount=15020.0, day="2026-01-30")

    resp = client.post("/payroll/process", json={
        "year": 2026, "month": 1,
        "lines": [{"staff_id": staff.id, "gross_salary": 15020.0}],
    })
    assert resp.status_code == 200, resp.text
    entry = resp.json()[0]
    assert entry["net_salary"] == 15020.0
    assert entry["transaction_id"] == tx.id


def test_fallback_accepts_amount_above_net_pay_for_bundled_iou(client, db_session):
    staff = _create_staff(db_session, "Mrs Jonathan Ogogo", monthly_gross=63000.0)
    tx = _create_salary_transaction(db_session, "PATRICIA NKECHI OGOGO", amount=63000.0, day="2026-01-30")

    resp = client.post("/payroll/process", json={
        "year": 2026, "month": 1,
        "lines": [{"staff_id": staff.id, "gross_salary": 50000.0, "bonus": 0.0}],
    })
    assert resp.status_code == 200, resp.text
    entry = resp.json()[0]
    # net pay (50000) <= transaction amount (63000, salary + bundled IOU) -> matched
    assert entry["net_salary"] == 50000.0
    assert entry["transaction_id"] == tx.id


@pytest.mark.parametrize(
    "staff_name,gross,vendor,amount,category",
    [
        # Amount below net pay — looks like a partial/wrong payment, not a salary.
        ("Mrs Jonathan Ogogo", 50000.0, "PATRICIA NKECHI OGOGO", 20000.0, "Salary and Wages"),
        # Right person, right amount, but wrong category — not a salary transaction at all.
        ("Emmanuella Christian", 15020.0, "HELEN CHINENYE CHRISTIAN", 15020.0, "Other"),
        # Right category and amount, but zero name overlap — too risky to attach blindly.
        ("Emmanuella Christian", 15020.0, "SOMEONE ELSE ENTIRELY", 15020.0, "Salary and Wages"),
    ],
    ids=["amount_below_net_pay", "wrong_category", "zero_name_overlap"],
)
def test_fallback_rejects_when_validation_fails(client, db_session, staff_name, gross, vendor, amount, category):
    staff = _create_staff(db_session, staff_name, monthly_gross=gross)
    _create_salary_transaction(db_session, vendor, amount=amount, day="2026-01-30", category=category)

    resp = client.post("/payroll/process", json={
        "year": 2026, "month": 1,
        "lines": [{"staff_id": staff.id, "gross_salary": gross}],
    })
    assert resp.status_code == 422
    assert staff_name in resp.json()["detail"]["missing"]
