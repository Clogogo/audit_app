"""Tests for POST /payroll/process, focused on the category+amount fallback
match used when the bank account is registered under a different
first/middle name than the staff record (e.g. a spouse's name). Names below
are fictional — not real staff or bank data."""
from datetime import date

import pytest

from models import PayrollEntry, Staff, Transaction


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
    staff = _create_staff(db_session, "Ngozi Williams", monthly_gross=15020.0)
    tx = _create_salary_transaction(db_session, "ABIGAIL CHIDERA WILLIAMS", amount=15020.0, day="2026-01-30")

    resp = client.post("/payroll/process", json={
        "year": 2026, "month": 1,
        "lines": [{"staff_id": staff.id, "gross_salary": 15020.0}],
    })
    assert resp.status_code == 200, resp.text
    entry = resp.json()[0]
    assert entry["net_salary"] == 15020.0
    assert entry["transaction_id"] == tx.id
    # Exact payment — real amount captured, nothing folded into bonus
    assert entry["paid_amount"] == 15020.0
    assert entry["bonus_excess"] == 0.0


def test_fallback_accepts_amount_above_net_pay_and_folds_excess_into_bonus(client, db_session):
    staff = _create_staff(db_session, "Mrs Daniel Eze", monthly_gross=63000.0)
    tx = _create_salary_transaction(db_session, "CHIOMA UGOCHI EZE", amount=63000.0, day="2026-01-30")

    resp = client.post("/payroll/process", json={
        "year": 2026, "month": 1,
        "lines": [{"staff_id": staff.id, "gross_salary": 50000.0, "bonus": 0.0}],
    })
    assert resp.status_code == 200, resp.text
    entry = resp.json()[0]
    # net pay (50000) <= transaction amount (63000) -> matched, and the
    # 13000 the bank actually paid on top is captured as bonus so the
    # payroll entry reflects the real amount paid.
    assert entry["transaction_id"] == tx.id
    assert entry["paid_amount"] == 63000.0
    assert entry["bonus"] == 13000.0
    assert entry["bonus_excess"] == 13000.0
    assert entry["net_salary"] == 63000.0


@pytest.mark.parametrize(
    "staff_name,gross,vendor,amount,category",
    [
        # Amount below net pay — looks like a partial/wrong payment, not a salary.
        ("Mrs Daniel Eze", 50000.0, "CHIOMA UGOCHI EZE", 20000.0, "Salary and Wages"),
        # Right person, right amount, but wrong category — not a salary transaction at all.
        ("Ngozi Williams", 15020.0, "ABIGAIL CHIDERA WILLIAMS", 15020.0, "Other"),
        # Right category and amount, but zero name overlap — too risky to attach blindly.
        ("Ngozi Williams", 15020.0, "SOMEONE ELSE ENTIRELY", 15020.0, "Salary and Wages"),
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


def test_exact_name_match_with_wrong_category_is_not_treated_as_salary(client, db_session):
    # Full name match (the strongest signal) must still not attach an
    # unrelated expense — e.g. a reimbursement or vendor payment that
    # happens to mention the staff member's exact name.
    staff = _create_staff(db_session, "Ngozi Williams", monthly_gross=15020.0)
    _create_salary_transaction(db_session, "Ngozi Williams", amount=15020.0, day="2026-01-30", category="Other")

    resp = client.post("/payroll/process", json={
        "year": 2026, "month": 1,
        "lines": [{"staff_id": staff.id, "gross_salary": 15020.0}],
    })
    assert resp.status_code == 422
    assert "Ngozi Williams" in resp.json()["detail"]["missing"]


def test_manual_transaction_id_rejects_wrong_category(client, db_session):
    staff = _create_staff(db_session, "Ngozi Williams", monthly_gross=15020.0)
    tx = _create_salary_transaction(db_session, "Ngozi Williams", amount=15020.0, day="2026-01-30", category="Other")

    resp = client.post("/payroll/process", json={
        "year": 2026, "month": 1,
        "lines": [{"staff_id": staff.id, "gross_salary": 15020.0, "transaction_id": tx.id}],
    })
    assert resp.status_code == 400
    assert "Salary and Wages" in resp.json()["detail"]


def test_manual_transaction_id_overrides_automatic_matching(client, db_session):
    # Vendor name has zero overlap with staff name and amount is below net
    # pay — automatic matching (name + category/amount fallback) would
    # reject this, but an explicit manual link should be used as-is.
    staff = _create_staff(db_session, "Ngozi Williams", monthly_gross=15020.0)
    tx = _create_salary_transaction(db_session, "SOMEONE UNRELATED", amount=500.0, day="2026-01-30")

    resp = client.post("/payroll/process", json={
        "year": 2026, "month": 1,
        "lines": [{"staff_id": staff.id, "gross_salary": 15020.0, "transaction_id": tx.id}],
    })
    assert resp.status_code == 200, resp.text
    entry = resp.json()[0]
    assert entry["transaction_id"] == tx.id
    # Underpayment is captured but never auto-adjusted — we can't guess
    # which deduction explains the gap, so the figures stay as computed.
    assert entry["paid_amount"] == 500.0
    assert entry["bonus"] == 0.0
    assert entry["bonus_excess"] == 0.0
    assert entry["net_salary"] == 15020.0


def test_manual_link_with_higher_amount_folds_excess_into_bonus(client, db_session):
    staff = _create_staff(db_session, "Ngozi Williams", monthly_gross=15020.0)
    tx = _create_salary_transaction(db_session, "SOMEONE UNRELATED", amount=20000.0, day="2026-01-30")

    resp = client.post("/payroll/process", json={
        "year": 2026, "month": 1,
        "lines": [{"staff_id": staff.id, "gross_salary": 15020.0, "bonus": 1000.0, "transaction_id": tx.id}],
    })
    assert resp.status_code == 200, resp.text
    entry = resp.json()[0]
    # computed net = 15020 + 1000 = 16020; paid 20000 → excess 3980 → bonus
    assert entry["paid_amount"] == 20000.0
    assert entry["bonus_excess"] == 3980.0
    assert entry["bonus"] == 4980.0
    assert entry["net_salary"] == 20000.0


def test_compute_returns_real_paid_amount_for_processed_entries(client, db_session):
    staff = _create_staff(db_session, "Mrs Daniel Eze", monthly_gross=63000.0)
    tx = _create_salary_transaction(db_session, "CHIOMA UGOCHI EZE", amount=63000.0, day="2026-01-30")

    resp = client.post("/payroll/process", json={
        "year": 2026, "month": 1,
        "lines": [{"staff_id": staff.id, "gross_salary": 50000.0, "bonus": 0.0}],
    })
    assert resp.status_code == 200, resp.text

    resp = client.get("/payroll/compute", params={"year": 2026, "month": 1})
    assert resp.status_code == 200
    line = next(l for l in resp.json() if l["staff_id"] == staff.id)
    assert line["is_paid"] is True
    assert line["transaction_id"] == tx.id
    assert line["paid_amount"] == 63000.0
    assert line["net_salary"] == 63000.0  # frozen record includes the excess


def test_manual_transaction_id_rejects_when_claimed_by_another_staff(client, db_session):
    staff_a = _create_staff(db_session, "Ngozi Williams", monthly_gross=15020.0)
    staff_b = _create_staff(db_session, "Mrs Daniel Eze", monthly_gross=63000.0)
    tx = _create_salary_transaction(db_session, "ABIGAIL CHIDERA WILLIAMS", amount=15020.0, day="2026-01-30")

    existing_entry = PayrollEntry(
        staff_id=staff_a.id, period_year=2026, period_month=1,
        gross_salary=15020.0, net_salary=15020.0, transaction_id=tx.id, is_paid=True,
    )
    db_session.add(existing_entry)
    db_session.commit()

    resp = client.post("/payroll/process", json={
        "year": 2026, "month": 1,
        "lines": [{"staff_id": staff_b.id, "gross_salary": 63000.0, "transaction_id": tx.id}],
    })
    assert resp.status_code == 400
    assert "already linked" in resp.json()["detail"]


def test_manual_transaction_id_rejects_nonexistent_or_non_expense(client, db_session):
    staff = _create_staff(db_session, "Ngozi Williams", monthly_gross=15020.0)

    resp = client.post("/payroll/process", json={
        "year": 2026, "month": 1,
        "lines": [{"staff_id": staff.id, "gross_salary": 15020.0, "transaction_id": 999999}],
    })
    assert resp.status_code == 400

    income_tx = Transaction(
        type="income", amount=15020.0, currency="NGN", category="Salary and Wages",
        description="Salary received", date=date.fromisoformat("2026-01-30"), vendor="N/A",
    )
    db_session.add(income_tx)
    db_session.commit()

    resp = client.post("/payroll/process", json={
        "year": 2026, "month": 1,
        "lines": [{"staff_id": staff.id, "gross_salary": 15020.0, "transaction_id": income_tx.id}],
    })
    assert resp.status_code == 400


def test_manual_transaction_id_rejects_duplicate_within_same_request(client, db_session):
    staff_a = _create_staff(db_session, "Ngozi Williams", monthly_gross=15020.0)
    staff_b = _create_staff(db_session, "Mrs Daniel Eze", monthly_gross=63000.0)
    tx = _create_salary_transaction(db_session, "SOMEONE UNRELATED", amount=63000.0, day="2026-01-30")

    resp = client.post("/payroll/process", json={
        "year": 2026, "month": 1,
        "lines": [
            {"staff_id": staff_a.id, "gross_salary": 15020.0, "transaction_id": tx.id},
            {"staff_id": staff_b.id, "gross_salary": 63000.0, "transaction_id": tx.id},
        ],
    })
    assert resp.status_code == 400
    assert "more than one staff member" in resp.json()["detail"]


def test_manual_transaction_id_rejects_date_outside_payroll_period(client, db_session):
    staff = _create_staff(db_session, "Ngozi Williams", monthly_gross=15020.0)
    tx = _create_salary_transaction(db_session, "ABIGAIL CHIDERA WILLIAMS", amount=15020.0, day="2026-02-01")

    resp = client.post("/payroll/process", json={
        "year": 2026, "month": 1,
        "lines": [{"staff_id": staff.id, "gross_salary": 15020.0, "transaction_id": tx.id}],
    })
    assert resp.status_code == 400
    assert "outside the payroll period" in resp.json()["detail"]
