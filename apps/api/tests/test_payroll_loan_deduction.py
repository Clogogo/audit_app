"""Tests for _loan_deduction_for_month: the payroll loan deduction must
reflect actual StaffLoanPayment entries recorded for the period, not a
gross_salary * deduction_rate formula."""
from datetime import date

from models import PayrollEntry, Staff, StaffLoan, StaffLoanPayment


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


def test_unpaid_existing_entry_shows_live_deduction_not_a_stale_snapshot(client, db_session):
    # Simulates a staff member who was processed once (entry created with
    # whatever loan_deduction was true at the time), then reset/skipped —
    # is_paid is False but the row still exists. A new loan payment recorded
    # afterward must show up immediately, not require re-processing first.
    staff = _create_staff(db_session, "Ngozi Williams", monthly_gross=100000.0)
    loan = _create_loan(db_session, staff, loan_amount=200000.0)

    stale_entry = PayrollEntry(
        staff_id=staff.id, period_year=2026, period_month=1,
        gross_salary=100000.0, bonus=0.0, loan_deduction=10000.0,
        other_deductions=0.0, net_salary=90000.0, is_paid=False,
    )
    db_session.add(stale_entry)
    db_session.commit()

    _add_payment(db_session, loan, amount_paid=25000.0, paid_date="2026-01-10")

    resp = client.get("/payroll/compute", params={"year": 2026, "month": 1})
    assert resp.status_code == 200, resp.text
    line = next(l for l in resp.json() if l["staff_id"] == staff.id)
    assert line["loan_deduction"] == 25000.0
    assert line["net_salary"] == 75000.0
    assert line["is_paid"] is False


def test_unpaid_entry_caps_deduction_against_its_own_reduced_gross_override(client, db_session):
    # _loan_deduction_for_month caps against the Staff record's current
    # monthly_gross (100000), but this draft line has its own reduced
    # gross override (20000) — the recomputed deduction must be capped
    # against THAT, not the staff record's higher gross, or net_salary
    # would go negative.
    staff = _create_staff(db_session, "Ngozi Williams", monthly_gross=100000.0)
    loan = _create_loan(db_session, staff, loan_amount=200000.0)

    draft_entry = PayrollEntry(
        staff_id=staff.id, period_year=2026, period_month=1,
        gross_salary=20000.0, bonus=0.0, loan_deduction=0.0,
        other_deductions=0.0, net_salary=20000.0, is_paid=False,
    )
    db_session.add(draft_entry)
    db_session.commit()

    _add_payment(db_session, loan, amount_paid=60000.0, paid_date="2026-01-10")

    resp = client.get("/payroll/compute", params={"year": 2026, "month": 1})
    assert resp.status_code == 200, resp.text
    line = next(l for l in resp.json() if l["staff_id"] == staff.id)
    assert line["loan_deduction"] == 20000.0
    assert line["net_salary"] == 0.0


def test_paid_existing_entry_keeps_its_frozen_snapshot(client, db_session):
    # Once truly processed (is_paid=True), the entry is a historical record
    # — a loan payment recorded afterward must NOT retroactively change it.
    staff = _create_staff(db_session, "Ngozi Williams", monthly_gross=100000.0)
    loan = _create_loan(db_session, staff, loan_amount=200000.0)

    paid_entry = PayrollEntry(
        staff_id=staff.id, period_year=2026, period_month=1,
        gross_salary=100000.0, bonus=0.0, loan_deduction=10000.0,
        other_deductions=0.0, net_salary=90000.0, is_paid=True,
        paid_date=date(2026, 1, 31),
    )
    db_session.add(paid_entry)
    db_session.commit()

    _add_payment(db_session, loan, amount_paid=25000.0, paid_date="2026-01-10")

    resp = client.get("/payroll/compute", params={"year": 2026, "month": 1})
    assert resp.status_code == 200, resp.text
    line = next(l for l in resp.json() if l["staff_id"] == staff.id)
    assert line["loan_deduction"] == 10000.0
    assert line["is_paid"] is True


def test_process_payroll_caps_deduction_against_the_submitted_lines_own_earnings(client, db_session):
    # Same cap as compute_payroll's draft branch, but exercised through the
    # actual POST /payroll/process path (Phase 1's net_by_staff and Phase 2's
    # persisted entry.loan_deduction) — a Copilot review finding: the cap had
    # only been applied in compute_payroll, leaving process_payroll able to
    # persist a negative net_salary.
    from models import Transaction

    staff = _create_staff(db_session, "Ngozi Williams", monthly_gross=100000.0)
    loan = _create_loan(db_session, staff, loan_amount=200000.0)
    _add_payment(db_session, loan, amount_paid=60000.0, paid_date="2026-01-10")

    tx = Transaction(
        type="expense", amount=20000.0, currency="NGN", category="Salary and Wages",
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
    assert entry["loan_deduction"] == 20000.0
    assert entry["net_salary"] == 0.0


def test_unpaid_entry_net_salary_is_clamped_when_other_deductions_alone_exceed_earnings(client, db_session):
    # _capped_deductions only caps loan_deduction/advance_deduction against
    # this line's earnings — other_deductions isn't capped by anything and
    # is taken at face value from the user's draft override. A Copilot
    # review finding: an other_deductions value that alone exceeds
    # gross+bonus could still drive net_salary negative, which would make
    # the salary-transaction fallback matcher's amount >= net check too
    # permissive.
    staff = _create_staff(db_session, "Ngozi Williams", monthly_gross=100000.0)

    draft_entry = PayrollEntry(
        staff_id=staff.id, period_year=2026, period_month=1,
        gross_salary=20000.0, bonus=0.0, loan_deduction=0.0,
        other_deductions=30000.0, net_salary=0.0, is_paid=False,
    )
    db_session.add(draft_entry)
    db_session.commit()

    resp = client.get("/payroll/compute", params={"year": 2026, "month": 1})
    assert resp.status_code == 200, resp.text
    line = next(l for l in resp.json() if l["staff_id"] == staff.id)
    assert line["net_salary"] == 0.0


def test_process_payroll_net_salary_is_clamped_when_other_deductions_alone_exceed_earnings(client, db_session):
    from models import Transaction

    staff = _create_staff(db_session, "Ngozi Williams", monthly_gross=20000.0)

    tx = Transaction(
        type="expense", amount=0.0, currency="NGN", category="Salary and Wages",
        description="Transfer to Ngozi Williams | OPay | 0000000000 | January 2026",
        date=date(2026, 1, 30), vendor="Ngozi Williams",
    )
    db_session.add(tx)
    db_session.commit()

    resp = client.post("/payroll/process", json={
        "year": 2026, "month": 1,
        "lines": [{"staff_id": staff.id, "gross_salary": 20000.0, "other_deductions": 30000.0}],
    })
    assert resp.status_code == 200, resp.text
    entry = resp.json()[0]
    assert entry["net_salary"] == 0.0
