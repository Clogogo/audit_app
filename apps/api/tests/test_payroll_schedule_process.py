"""Process Payroll validated against the reconciliation (schedule vs bank) instead
of the staff directory, plus the "first incomplete month" helper. Names and
amounts are fictional."""
from datetime import date

import pytest

from models import PayrollEntry, Staff, Transaction


def _staff(db, name, gross=15000.0, account=None, **extra):
    s = Staff(full_name=name, monthly_gross=gross, account_number=account, is_active=True, **extra)
    db.add(s)
    db.commit()
    return s


def _salary_tx(db, vendor, amount, day="2026-01-30", account="0000000000"):
    tx = Transaction(
        type="expense", amount=amount, currency="NGN", category="Salary and Wages",
        description=f"Transfer to {vendor} | OPay | {account} | January 2026",
        date=date.fromisoformat(day), vendor=vendor,
    )
    db.add(tx)
    db.commit()
    return tx


def _process(client, lines, schedule, year=2026, month=1):
    return client.post("/payroll/process", json={"year": year, "month": month, "lines": lines, "schedule": schedule})


def _line(staff, gross=15000.0, **kw):
    return {"staff_id": staff.id, "gross_salary": gross, **kw}


def _row(n, name, amount, account=None):
    return {"row_number": n, "name": name, "amount": amount, "account_number": account}


def test_process_links_the_reconciled_payment_when_everything_agrees(client, db_session):
    ada = _staff(db_session, "Ada Obi")
    tx = _salary_tx(db_session, "ADA OBI", 15000.0)
    resp = _process(client, [_line(ada)], [_row(1, "ADA OBI", 15000.0)])
    assert resp.status_code == 200, resp.text
    entry = resp.json()[0]
    assert entry["transaction_id"] == tx.id and entry["is_paid"] is True
    assert entry["net_salary"] == 15000.0 and entry["paid_amount"] == 15000.0
    assert entry["bonus"] == 0.0 and "bonus_excess" not in entry


def test_process_accepts_a_bank_payment_within_100_naira(client, db_session):
    ada = _staff(db_session, "Ada Obi")
    _salary_tx(db_session, "ADA OBI", 14950.0)
    resp = _process(client, [_line(ada)], [_row(1, "ADA OBI", 15000.0)])
    assert resp.status_code == 200, resp.text
    entry = resp.json()[0]
    assert entry["paid_amount"] == 14950.0 and entry["net_salary"] == 15000.0 and entry["bonus"] == 0.0


def test_process_total_with_deductions_must_match_the_schedule(client, db_session):
    ada = _staff(db_session, "Ada Obi")
    _salary_tx(db_session, "ADA OBI", 13000.0)
    resp = _process(client, [_line(ada, other_deductions=2000.0)], [_row(1, "ADA OBI", 13000.0)])
    assert resp.status_code == 200, resp.text
    assert resp.json()[0]["net_salary"] == 13000.0


def _issues(resp):
    assert resp.status_code == 422, resp.text
    return {(i["full_name"], i["kind"]) for i in resp.json()["detail"]["issues"]}


def test_process_goes_ahead_when_the_bank_paid_a_different_amount_and_notes_it(client, db_session):
    ada = _staff(db_session, "Ada Obi")
    tx = _salary_tx(db_session, "ADA OBI", 12000.0)
    resp = _process(client, [_line(ada)], [_row(1, "ADA OBI", 15000.0)])
    assert resp.status_code == 200, resp.text
    entry = db_session.query(PayrollEntry).one()
    assert entry.is_paid and entry.transaction_id == tx.id
    assert "Schedule check" in entry.notes and "less than the schedule" in entry.notes


def test_process_goes_ahead_when_the_bank_overpaid_and_keeps_the_typed_note(client, db_session):
    ada = _staff(db_session, "Ada Obi")
    _salary_tx(db_session, "ADA OBI", 50018.6)
    resp = _process(client, [_line(ada, notes="paid with arrears")], [_row(1, "ADA OBI", 15000.0)])
    assert resp.status_code == 200, resp.text
    notes = db_session.query(PayrollEntry).one().notes
    assert notes.startswith("paid with arrears\n") and "more than the schedule" in notes


def test_process_blocks_when_nothing_was_paid(client, db_session):
    ada = _staff(db_session, "Ada Obi")
    assert ("Ada Obi", "not_paid") in _issues(_process(client, [_line(ada)], [_row(1, "ADA OBI", 15000.0)]))


def test_process_blocks_staff_who_are_not_on_the_schedule(client, db_session):
    ada, kemi = _staff(db_session, "Ada Obi"), _staff(db_session, "Kemi Ala")
    _salary_tx(db_session, "ADA OBI", 15000.0)
    resp = _process(client, [_line(ada), _line(kemi)], [_row(1, "ADA OBI", 15000.0)])
    assert _issues(resp) == {("Kemi Ala", "not_on_schedule")}
    assert db_session.query(PayrollEntry).count() == 0     # all-or-nothing


def test_process_goes_ahead_when_the_directory_total_differs_from_the_schedule_and_notes_it(client, db_session):
    ada = _staff(db_session, "Ada Obi")                       # directory says 15,000
    _salary_tx(db_session, "ADA OBI", 14000.0)
    resp = _process(client, [_line(ada)], [_row(1, "ADA OBI", 14000.0)])   # schedule + bank say 14,000
    assert resp.status_code == 200, resp.text
    entry = db_session.query(PayrollEntry).one()
    assert entry.net_salary == 15000.0 and "payroll total" in entry.notes


def test_process_still_blocks_a_wrong_account_even_with_an_amount_difference(client, db_session):
    ada = _staff(db_session, "Ada Obi", account="0123456789")
    _salary_tx(db_session, "ADA OBI", 12000.0, account="0999999999")
    issues = _issues(_process(client, [_line(ada)], [_row(1, "ADA OBI", 15000.0)]))
    assert ("Ada Obi", "account_differs") in issues
    assert db_session.query(PayrollEntry).count() == 0


def test_process_links_by_account_number_when_names_differ(client, db_session):
    ada = _staff(db_session, "Ada Obi", account="0123456789")
    tx = _salary_tx(db_session, "SOMEONE ELSE ENTIRELY", 15000.0)
    tx.description = "Transfer to SOMEONE ELSE ENTIRELY | OPay | 0123456789 | January 2026"
    db_session.commit()
    resp = _process(client, [_line(ada)], [_row(1, "Different Name", 15000.0, "0123456789")])
    assert resp.status_code == 200, resp.text
    assert resp.json()[0]["transaction_id"] == tx.id


def test_process_refuses_a_payment_already_linked_to_another_entry(client, db_session):
    ada, bola = _staff(db_session, "Ada Obi"), _staff(db_session, "Bola Eze")
    tx = _salary_tx(db_session, "ADA OBI", 15000.0)
    db_session.add(PayrollEntry(staff_id=bola.id, period_year=2026, period_month=1, gross_salary=15000.0,
                                net_salary=15000.0, is_paid=True, transaction_id=tx.id))
    db_session.commit()
    resp = _process(client, [_line(ada)], [_row(1, "ADA OBI", 15000.0)])
    assert ("Ada Obi", "payment_already_linked") in _issues(resp)


def test_process_rejects_a_malformed_schedule(client, db_session):
    ada = _staff(db_session, "Ada Obi")
    assert _process(client, [_line(ada)], [_row(1, "ADA OBI", -5.0)]).status_code == 422
    assert _process(client, [_line(ada)], [_row(1, "", 5.0)]).status_code == 422


def test_process_without_a_schedule_keeps_the_existing_behaviour(client, db_session):
    ada = _staff(db_session, "Ada Obi")
    tx = _salary_tx(db_session, "ADA OBI", 15000.0)
    resp = client.post("/payroll/process", json={"year": 2026, "month": 1, "lines": [_line(ada)]})
    assert resp.status_code == 200 and resp.json()[0]["transaction_id"] == tx.id


# ── first month whose payroll is not complete ─────────────────────────────────

def _months_ago(n):
    today = date.today()
    index = today.year * 12 + (today.month - 1) - n
    return index // 12, index % 12 + 1


def _paid_entry(db, staff, ago, paid=True):
    y, m = _months_ago(ago)
    db.add(PayrollEntry(staff_id=staff.id, period_year=y, period_month=m, gross_salary=1.0, net_salary=1.0, is_paid=paid))
    db.commit()


def _next(client):
    body = client.get("/payroll/next-month").json()
    return body["year"], body["month"]


def test_next_month_is_the_current_month_when_nothing_was_ever_processed(client, db_session):
    _staff(db_session, "Ada Obi")
    assert _next(client) == _months_ago(0)


def test_next_month_is_the_latest_month_that_is_not_fully_processed(client, db_session):
    ada = _staff(db_session, "Ada Obi")
    for ago in (4, 3, 0):
        _paid_entry(db_session, ada, ago)     # two months ago and last month are NOT processed; this month is
    assert _next(client) == _months_ago(1)    # the most recent one, not the oldest (2 months ago)


def test_next_month_still_returns_an_old_month_when_every_later_month_is_complete(client, db_session):
    ada, bola = _staff(db_session, "Ada Obi"), _staff(db_session, "Bola Eze")
    _paid_entry(db_session, ada, 3)
    _paid_entry(db_session, bola, 3)
    _paid_entry(db_session, ada, 2)           # Bola was never paid in that old month...
    for ago in (1, 0):
        _paid_entry(db_session, ada, ago)
        _paid_entry(db_session, bola, ago)    # ...but every month since is complete
    assert _next(client) == _months_ago(2)    # nothing later is pending, so that unfinished month is the one to finish


def test_next_month_counts_unpaid_entries_as_incomplete(client, db_session):
    ada = _staff(db_session, "Ada Obi")
    _paid_entry(db_session, ada, 3)
    _paid_entry(db_session, ada, 2, paid=False)
    for ago in (1, 0):
        _paid_entry(db_session, ada, ago)
    assert _next(client) == _months_ago(2)


def test_next_month_is_current_when_everything_is_complete(client, db_session):
    ada = _staff(db_session, "Ada Obi")
    for ago in (2, 1, 0):
        _paid_entry(db_session, ada, ago)
    assert _next(client) == _months_ago(0)


def test_next_month_ignores_staff_who_had_not_started_yet(client, db_session):
    ada = _staff(db_session, "Ada Obi")
    y1, m1 = _months_ago(1)
    hire = _staff(db_session, "New Hire", start_date=date(y1, m1, 1))     # started last month
    _paid_entry(db_session, ada, 3)
    _paid_entry(db_session, ada, 2)           # New Hire was not needed back then
    _paid_entry(db_session, ada, 0)
    _paid_entry(db_session, hire, 0)
    assert _next(client) == _months_ago(1)    # last month needs both of them, and neither was paid
