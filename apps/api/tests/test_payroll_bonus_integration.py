"""Tests for TeacherBonus feeding automatically into GET /payroll/compute —
see the "else" branch (no existing PayrollEntry yet) in compute_payroll."""
from datetime import date

from models import AdvancePayment, PayrollEntry, Staff, StaffLoan, StaffLoanPayment, TeacherBonus


def _create_staff(db_session, full_name="Ngozi Williams", monthly_gross=150000.0) -> Staff:
    staff = Staff(full_name=full_name, monthly_gross=monthly_gross, is_active=True)
    db_session.add(staff)
    db_session.commit()
    return staff


def _create_bonus(db_session, staff_id, amount, year=2026, month=3, bonus_type="performance") -> TeacherBonus:
    bonus = TeacherBonus(
        staff_id=staff_id, bonus_type=bonus_type, percentage=10.0, basis_amount=amount * 10,
        amount=amount, period_year=year, period_month=month,
    )
    db_session.add(bonus)
    db_session.commit()
    return bonus


def _line_for(client, year, month, staff_id):
    resp = client.get("/payroll/compute", params={"year": year, "month": month})
    assert resp.status_code == 200, resp.text
    return next(l for l in resp.json() if l["staff_id"] == staff_id)


def test_bonus_shows_up_automatically_for_a_brand_new_line(client, db_session):
    staff = _create_staff(db_session)
    _create_bonus(db_session, staff.id, amount=15000.0, year=2026, month=3)

    line = _line_for(client, 2026, 3, staff.id)
    assert line["bonus"] == 15000.0
    assert line["net_salary"] == staff.monthly_gross + 15000.0
    assert line["entry_id"] is None  # still a fresh, unprocessed line


def test_multiple_bonuses_for_the_same_period_sum_together(client, db_session):
    staff = _create_staff(db_session)
    _create_bonus(db_session, staff.id, amount=15000.0, year=2026, month=3, bonus_type="performance")
    _create_bonus(db_session, staff.id, amount=7500.0, year=2026, month=3, bonus_type="punctuality")

    line = _line_for(client, 2026, 3, staff.id)
    assert line["bonus"] == 22500.0


def test_bonus_targeting_a_different_month_does_not_leak_in(client, db_session):
    staff = _create_staff(db_session)
    _create_bonus(db_session, staff.id, amount=15000.0, year=2026, month=3)

    line = _line_for(client, 2026, 4, staff.id)
    assert line["bonus"] == 0.0


def test_bonus_for_a_different_staff_member_does_not_leak_in(client, db_session):
    staff_a = _create_staff(db_session, "Ngozi Williams")
    staff_b = _create_staff(db_session, "Chidi Okafor")
    _create_bonus(db_session, staff_a.id, amount=15000.0, year=2026, month=3)

    line_b = _line_for(client, 2026, 3, staff_b.id)
    assert line_b["bonus"] == 0.0


def test_already_processed_month_is_unaffected_by_a_later_bonus(client, db_session):
    # Frozen-record regression guard: a bonus added after payroll was
    # already processed for that month must not retroactively change it —
    # same rule that already applies to loans/advances added afterward.
    staff = _create_staff(db_session, monthly_gross=50000.0)
    entry = PayrollEntry(
        staff_id=staff.id, period_year=2026, period_month=3,
        gross_salary=50000.0, bonus=0.0, net_salary=50000.0, is_paid=True,
        paid_date=date(2026, 3, 31),
    )
    db_session.add(entry)
    db_session.commit()

    _create_bonus(db_session, staff.id, amount=15000.0, year=2026, month=3)

    line = _line_for(client, 2026, 3, staff.id)
    assert line["bonus"] == 0.0
    assert line["is_paid"] is True


def test_loan_and_advance_capping_uses_the_real_bonus_total(client, db_session):
    # Regression for the bug this feature fixes in passing: _capped_deductions
    # used to always be called with bonus=0.0 for a brand-new line, so a loan
    # + advance that together exceeded bare gross (but fit within gross +
    # bonus) got the advance truncated for no real reason.
    staff = _create_staff(db_session, monthly_gross=50000.0)

    loan = StaffLoan(staff_id=staff.id, employee_name=staff.full_name, loan_amount=100000.0, deduction_start=date(2026, 1, 1))
    db_session.add(loan)
    db_session.commit()
    db_session.add(StaffLoanPayment(loan_id=loan.id, amount_paid=30000.0, paid_date=date(2026, 3, 15)))
    db_session.add(AdvancePayment(staff_id=staff.id, amount=30000.0, remaining_amount=30000.0, date_issued=date(2026, 3, 1), is_recovered=False))
    db_session.commit()

    # Without a bonus: available = gross (50000), loan_ded = 30000, so
    # advance would be truncated to the remaining 20000 of room. With the
    # 20000 bonus: available = 70000, both deductions fit in full.
    _create_bonus(db_session, staff.id, amount=20000.0, year=2026, month=3)
    line = _line_for(client, 2026, 3, staff.id)
    assert line["bonus"] == 20000.0
    assert line["loan_deduction"] == 30000.0
    assert line["advance_deduction"] == 30000.0  # full amount — not truncated to 20000
