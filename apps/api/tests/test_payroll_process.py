"""Tests for POST /payroll/process, focused on the category+amount fallback
match used when the bank account is registered under a different
first/middle name than the staff record (e.g. a spouse's name)."""
from datetime import date

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


def test_fallback_rejects_amount_below_net_pay(client, db_session):
    staff = _create_staff(db_session, "Mrs Jonathan Ogogo", monthly_gross=50000.0)
    _create_salary_transaction(db_session, "PATRICIA NKECHI OGOGO", amount=20000.0, day="2026-01-30")

    resp = client.post("/payroll/process", json={
        "year": 2026, "month": 1,
        "lines": [{"staff_id": staff.id, "gross_salary": 50000.0}],
    })
    assert resp.status_code == 422
    assert "Mrs Jonathan Ogogo" in resp.json()["detail"]["missing"]


def test_fallback_rejects_wrong_category_even_with_matching_amount(client, db_session):
    staff = _create_staff(db_session, "Emmanuella Christian", monthly_gross=15020.0)
    _create_salary_transaction(
        db_session, "HELEN CHINENYE CHRISTIAN", amount=15020.0, day="2026-01-30", category="Other"
    )

    resp = client.post("/payroll/process", json={
        "year": 2026, "month": 1,
        "lines": [{"staff_id": staff.id, "gross_salary": 15020.0}],
    })
    assert resp.status_code == 422
    assert "Emmanuella Christian" in resp.json()["detail"]["missing"]


def test_fallback_rejects_zero_name_overlap(client, db_session):
    staff = _create_staff(db_session, "Emmanuella Christian", monthly_gross=15020.0)
    _create_salary_transaction(db_session, "SOMEONE ELSE ENTIRELY", amount=15020.0, day="2026-01-30")

    resp = client.post("/payroll/process", json={
        "year": 2026, "month": 1,
        "lines": [{"staff_id": staff.id, "gross_salary": 15020.0}],
    })
    assert resp.status_code == 422
    assert "Emmanuella Christian" in resp.json()["detail"]["missing"]
