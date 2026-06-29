"""Tests for advance payment (IOU) integration with payroll: an advance is
fully deducted from the next payroll run processed after it's recorded,
then marked recovered so it's never deducted twice."""
from datetime import date

from models import AdvancePayment, Staff, Transaction


def _create_staff(db_session, full_name: str, monthly_gross: float) -> Staff:
    staff = Staff(full_name=full_name, monthly_gross=monthly_gross, is_active=True)
    db_session.add(staff)
    db_session.commit()
    return staff


def _create_advance(db_session, staff: Staff, amount: float, date_issued: str, is_recovered: bool = False) -> AdvancePayment:
    advance = AdvancePayment(
        staff_id=staff.id, amount=amount, date_issued=date.fromisoformat(date_issued), is_recovered=is_recovered,
    )
    db_session.add(advance)
    db_session.commit()
    return advance


def test_no_deduction_when_no_advance_recorded(client, db_session):
    staff = _create_staff(db_session, "Ngozi Williams", monthly_gross=100000.0)

    resp = client.get("/payroll/compute", params={"year": 2026, "month": 1})
    assert resp.status_code == 200, resp.text
    line = next(l for l in resp.json() if l["staff_id"] == staff.id)
    assert line["advance_deduction"] == 0.0


def test_deduction_equals_an_advance_issued_before_the_period_end(client, db_session):
    staff = _create_staff(db_session, "Ngozi Williams", monthly_gross=100000.0)
    _create_advance(db_session, staff, amount=15000.0, date_issued="2026-01-10")

    resp = client.get("/payroll/compute", params={"year": 2026, "month": 1})
    assert resp.status_code == 200, resp.text
    line = next(l for l in resp.json() if l["staff_id"] == staff.id)
    assert line["advance_deduction"] == 15000.0


def test_advance_issued_after_the_period_is_not_deducted_yet(client, db_session):
    staff = _create_staff(db_session, "Ngozi Williams", monthly_gross=100000.0)
    _create_advance(db_session, staff, amount=15000.0, date_issued="2026-02-05")

    resp = client.get("/payroll/compute", params={"year": 2026, "month": 1})
    assert resp.status_code == 200, resp.text
    line = next(l for l in resp.json() if l["staff_id"] == staff.id)
    assert line["advance_deduction"] == 0.0


def test_already_recovered_advance_is_not_deducted_again(client, db_session):
    staff = _create_staff(db_session, "Ngozi Williams", monthly_gross=100000.0)
    _create_advance(db_session, staff, amount=15000.0, date_issued="2026-01-10", is_recovered=True)

    resp = client.get("/payroll/compute", params={"year": 2026, "month": 1})
    assert resp.status_code == 200, resp.text
    line = next(l for l in resp.json() if l["staff_id"] == staff.id)
    assert line["advance_deduction"] == 0.0


def test_process_payroll_recovers_the_advance_and_marks_it(client, db_session):
    staff = _create_staff(db_session, "Ngozi Williams", monthly_gross=100000.0)
    advance = _create_advance(db_session, staff, amount=15000.0, date_issued="2026-01-10")

    tx = Transaction(
        type="expense", amount=85000.0, currency="NGN", category="Salary and Wages",
        description="Transfer to Ngozi Williams | OPay | 0000000000 | January 2026",
        date=date(2026, 1, 30), vendor="Ngozi Williams",
    )
    db_session.add(tx)
    db_session.commit()

    resp = client.post("/payroll/process", json={
        "year": 2026, "month": 1,
        "lines": [{"staff_id": staff.id, "gross_salary": 100000.0}],
    })
    assert resp.status_code == 200, resp.text
    entry = resp.json()[0]
    assert entry["advance_deduction"] == 15000.0
    assert entry["net_salary"] == 85000.0

    db_session.refresh(advance)
    assert advance.is_recovered is True
    assert advance.recovered_period_year == 2026
    assert advance.recovered_period_month == 1

    # Second month: no longer deducted, since it's already recovered.
    resp = client.get("/payroll/compute", params={"year": 2026, "month": 2})
    line = next(l for l in resp.json() if l["staff_id"] == staff.id)
    assert line["advance_deduction"] == 0.0


def test_loan_and_advance_deductions_are_capped_together_not_independently(client, db_session):
    # Both a loan payment and an advance recorded for the same staff/month —
    # each individually fits under monthly_gross, but their SUM would
    # exceed it. Capping each independently against the full gross would
    # let both through in full and drive net negative; capped together,
    # the advance only gets whatever room the loan deduction left.
    from models import StaffLoan, StaffLoanPayment

    staff = _create_staff(db_session, "Ngozi Williams", monthly_gross=50000.0)
    loan = StaffLoan(
        staff_id=staff.id, employee_name=staff.full_name, loan_amount=200000.0,
        deduction_rate=0.5, deduction_start=date(2026, 1, 1), is_active=True,
    )
    db_session.add(loan)
    db_session.commit()
    db_session.add(StaffLoanPayment(loan_id=loan.id, amount_paid=40000.0, paid_date=date(2026, 1, 5)))
    db_session.commit()

    _create_advance(db_session, staff, amount=30000.0, date_issued="2026-01-10")

    resp = client.get("/payroll/compute", params={"year": 2026, "month": 1})
    assert resp.status_code == 200, resp.text
    line = next(l for l in resp.json() if l["staff_id"] == staff.id)
    assert line["loan_deduction"] == 40000.0
    assert line["advance_deduction"] == 10000.0  # only the remaining room, not the full 30000
    assert line["net_salary"] == 0.0


def test_partially_capped_advance_is_not_marked_recovered(client, db_session):
    # If process_payroll can only apply part of an advance (capped by other
    # deductions eating into the available room), it must roll over to the
    # next period rather than being marked recovered for less than it's
    # actually worth.
    staff = _create_staff(db_session, "Ngozi Williams", monthly_gross=20000.0)
    advance = _create_advance(db_session, staff, amount=30000.0, date_issued="2026-01-10")

    tx = Transaction(
        type="expense", amount=0.0, currency="NGN", category="Salary and Wages",
        description="Transfer to Ngozi Williams | OPay | 0000000000 | January 2026",
        date=date(2026, 1, 30), vendor="Ngozi Williams",
    )
    db_session.add(tx)
    db_session.commit()

    resp = client.post("/payroll/process", json={
        "year": 2026, "month": 1,
        "lines": [{"staff_id": staff.id, "gross_salary": 20000.0}],
    })
    assert resp.status_code == 200, resp.text
    entry = resp.json()[0]
    assert entry["advance_deduction"] == 20000.0  # capped at gross, not the full 30000
    assert entry["net_salary"] == 0.0

    db_session.refresh(advance)
    assert advance.is_recovered is False
