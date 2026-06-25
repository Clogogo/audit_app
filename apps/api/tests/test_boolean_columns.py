"""Regression tests for the boolean-column bug class (b9df25c, 8105da1):
Postgres rejected Python True/False against columns that were declared
Integer instead of Boolean. These tests pass trivially on SQLite even when
the underlying column type is wrong, so they're only meaningful when CI runs
them against the Postgres service container.
"""
from datetime import date

from models import PayrollEntry, Staff


def test_staff_is_active_round_trips_with_python_bool(db_session):
    staff = Staff(full_name="Test Staffer", monthly_gross=100000.0, is_active=True)
    db_session.add(staff)
    db_session.commit()

    found_active = db_session.query(Staff).filter(Staff.is_active == True).first()  # noqa: E712
    assert found_active is not None
    assert found_active.id == staff.id

    staff.is_active = False
    db_session.commit()

    found_inactive = db_session.query(Staff).filter(Staff.is_active == False).first()  # noqa: E712
    assert found_inactive is not None
    assert found_inactive.id == staff.id

    not_found = db_session.query(Staff).filter(Staff.is_active == True).first()  # noqa: E712
    assert not_found is None


def test_payroll_entry_is_paid_round_trips_with_python_bool(db_session):
    staff = Staff(full_name="Payee", monthly_gross=50000.0)
    db_session.add(staff)
    db_session.commit()

    entry = PayrollEntry(
        staff_id=staff.id,
        period_year=2026,
        period_month=1,
        gross_salary=50000.0,
        net_salary=50000.0,
        is_paid=False,
        paid_date=date(2026, 1, 31),
    )
    db_session.add(entry)
    db_session.commit()

    unpaid = db_session.query(PayrollEntry).filter(PayrollEntry.is_paid == False).first()  # noqa: E712
    assert unpaid is not None

    entry.is_paid = True
    db_session.commit()

    paid = db_session.query(PayrollEntry).filter(PayrollEntry.is_paid == True).first()  # noqa: E712
    assert paid is not None
    assert paid.id == entry.id
