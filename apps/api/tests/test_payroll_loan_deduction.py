"""Tests for _loan_deduction_for_month: the payroll loan deduction must
reflect actual StaffLoanPayment entries recorded for the period, not a
gross_salary * deduction_rate formula."""
from datetime import date

from models import Staff, StaffLoan, StaffLoanPayment


def _create_staff(db_session, full_name: str, monthly_gross: float) -> Staff:
    staff = Staff(full_name=full_name, monthly_gross=monthly_gross, is_active=True)
    db_session.add(staff)
    db_session.commit()
    return staff


def _create_loan(db_session, staff: Staff, loan_amount: float, is_active: bool = True) -> StaffLoan:
    loan = StaffLoan(
        staff_id=staff.id,
        employee_name=staff.full_name,
        loan_amount=loan_amount,
        deduction_rate=0.5,
        deduction_start=date(2026, 1, 1),
        is_active=is_active,
    )
    db_session.add(loan)
    db_session.commit()
    return loan


def _add_payment(db_session, loan: StaffLoan, amount_paid: float, paid_date: str) -> StaffLoanPayment:
    payment = StaffLoanPayment(loan_id=loan.id, amount_paid=amount_paid, paid_date=date.fromisoformat(paid_date))
    db_session.add(payment)
    db_session.commit()
    return payment


def test_no_deduction_when_no_payment_recorded_for_the_month(client, db_session):
    staff = _create_staff(db_session, "Ngozi Williams", monthly_gross=100000.0)
    _create_loan(db_session, staff, loan_amount=200000.0)

    resp = client.get("/payroll/compute", params={"year": 2026, "month": 1})
    assert resp.status_code == 200, resp.text
    line = next(l for l in resp.json() if l["staff_id"] == staff.id)
    assert line["loan_deduction"] == 0.0


def test_deduction_equals_the_recorded_payment_amount(client, db_session):
    staff = _create_staff(db_session, "Ngozi Williams", monthly_gross=100000.0)
    loan = _create_loan(db_session, staff, loan_amount=200000.0)
    _add_payment(db_session, loan, amount_paid=15000.0, paid_date="2026-01-15")

    resp = client.get("/payroll/compute", params={"year": 2026, "month": 1})
    assert resp.status_code == 200, resp.text
    line = next(l for l in resp.json() if l["staff_id"] == staff.id)
    assert line["loan_deduction"] == 15000.0


def test_deduction_ignores_payments_outside_the_month(client, db_session):
    staff = _create_staff(db_session, "Ngozi Williams", monthly_gross=100000.0)
    loan = _create_loan(db_session, staff, loan_amount=200000.0)
    _add_payment(db_session, loan, amount_paid=15000.0, paid_date="2026-02-01")

    resp = client.get("/payroll/compute", params={"year": 2026, "month": 1})
    assert resp.status_code == 200, resp.text
    line = next(l for l in resp.json() if l["staff_id"] == staff.id)
    assert line["loan_deduction"] == 0.0


def test_deduction_sums_multiple_payments_in_the_same_month(client, db_session):
    staff = _create_staff(db_session, "Ngozi Williams", monthly_gross=100000.0)
    loan = _create_loan(db_session, staff, loan_amount=200000.0)
    _add_payment(db_session, loan, amount_paid=10000.0, paid_date="2026-01-05")
    _add_payment(db_session, loan, amount_paid=5000.0, paid_date="2026-01-20")

    resp = client.get("/payroll/compute", params={"year": 2026, "month": 1})
    assert resp.status_code == 200, resp.text
    line = next(l for l in resp.json() if l["staff_id"] == staff.id)
    assert line["loan_deduction"] == 15000.0


def test_deduction_caps_at_gross_if_a_recorded_payment_exceeds_it(client, db_session):
    # A sanity guard, not a reintroduction of the old gross*rate estimate —
    # an over-recorded payment must not be able to drive net_salary negative
    # or make the salary-transaction fallback match accept any amount.
    staff = _create_staff(db_session, "Ngozi Williams", monthly_gross=50000.0)
    loan = _create_loan(db_session, staff, loan_amount=200000.0)
    _add_payment(db_session, loan, amount_paid=80000.0, paid_date="2026-01-15")

    resp = client.get("/payroll/compute", params={"year": 2026, "month": 1})
    assert resp.status_code == 200, resp.text
    line = next(l for l in resp.json() if l["staff_id"] == staff.id)
    assert line["loan_deduction"] == 50000.0


def test_deduction_still_counts_a_payment_on_a_now_inactive_loan(client, db_session):
    # The final payment on a loan flips is_active to False (see
    # add_payment in staff_loans.py) — that must not erase the deduction
    # for the month the final payment actually happened in.
    staff = _create_staff(db_session, "Ngozi Williams", monthly_gross=100000.0)
    loan = _create_loan(db_session, staff, loan_amount=10000.0, is_active=False)
    _add_payment(db_session, loan, amount_paid=10000.0, paid_date="2026-01-30")

    resp = client.get("/payroll/compute", params={"year": 2026, "month": 1})
    assert resp.status_code == 200, resp.text
    line = next(l for l in resp.json() if l["staff_id"] == staff.id)
    assert line["loan_deduction"] == 10000.0
