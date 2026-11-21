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
    assert entry["bonus_excess"] == 0.0 and entry["bonus"] == 0.0


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


def test_process_blocks_when_the_bank_paid_a_different_amount(client, db_session):
    ada = _staff(db_session, "Ada Obi")
    _salary_tx(db_session, "ADA OBI", 12000.0)
    resp = _process(client, [_line(ada)], [_row(1, "ADA OBI", 15000.0)])
    assert ("Ada Obi", "underpaid") in _issues(resp)
    assert db_session.query(PayrollEntry).count() == 0


def test_process_blocks_when_nothing_was_paid(client, db_session):
    ada = _staff(db_session, "Ada Obi")
    assert ("Ada Obi", "not_paid") in _issues(_process(client, [_line(ada)], [_row(1, "ADA OBI", 15000.0)]))


def test_process_blocks_staff_who_are_not_on_the_schedule(client, db_session):
    ada, kemi = _staff(db_session, "Ada Obi"), _staff(db_session, "Kemi Ala")
    _salary_tx(db_session, "ADA OBI", 15000.0)
    resp = _process(client, [_line(ada), _line(kemi)], [_row(1, "ADA OBI", 15000.0)])
    assert _issues(resp) == {("Kemi Ala", "not_on_schedule")}
    assert db_session.query(PayrollEntry).count() == 0     # all-or-nothing


def test_process_blocks_when_the_directory_total_differs_from_the_schedule(client, db_session):
    ada = _staff(db_session, "Ada Obi")                       # directory says 15,000
    _salary_tx(db_session, "ADA OBI", 14000.0)
    resp = _process(client, [_line(ada)], [_row(1, "ADA OBI", 14000.0)])   # schedule + bank say 14,000
    issues = resp.json()["detail"]["issues"]
    mismatch = next(i for i in issues if i["kind"] == "net_mismatch")
    assert mismatch["computed"] == 15000.0 and mismatch["expected"] == 14000.0


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


def test_next_month_is_the_first_incomplete_month(client, db_session):
    ada = _staff(db_session, "Ada Obi")
    _paid_entry(db_session, ada, 4)
    _paid_entry(db_session, ada, 3)          # 2 months ago has no entry
    assert _next(client) == _months_ago(2)


def test_next_month_counts_unpaid_entries_and_missing_staff_as_incomplete(client, db_session):
    ada, bola = _staff(db_session, "Ada Obi"), _staff(db_session, "Bola Eze")
    _paid_entry(db_session, ada, 3)
    _paid_entry(db_session, bola, 3)
    _paid_entry(db_session, ada, 2)          # Bola missing in that month
    assert _next(client) == _months_ago(2)


def test_next_month_is_current_when_everything_is_complete(client, db_session):
    ada = _staff(db_session, "Ada Obi")
    for ago in (2, 1, 0):
        _paid_entry(db_session, ada, ago)
    assert _next(client) == _months_ago(0)


def test_next_month_ignores_staff_who_had_not_started_or_already_left(client, db_session):
    ada = _staff(db_session, "Ada Obi")
    y1, m1 = _months_ago(1)
    _staff(db_session, "New Hire", start_date=date(y1, m1, 1))     # started last month
    _paid_entry(db_session, ada, 3)
    _paid_entry(db_session, ada, 2)           # New Hire not needed back then
    assert _next(client) == _months_ago(1)    # but last month needs both


# ── review hardening ──────────────────────────────────────────────────────────

def test_process_refuses_a_month_that_is_already_processed_for_that_staff(client, db_session):
    ada = _staff(db_session, "Ada Obi")
    _salary_tx(db_session, "ADA OBI", 15000.0)
    assert _process(client, [_line(ada)], [_row(1, "ADA OBI", 15000.0)]).status_code == 200
    again = _process(client, [_line(ada)], [_row(1, "ADA OBI", 15000.0)])
    assert ("Ada Obi", "already_processed") in _issues(again)
    assert db_session.query(PayrollEntry).count() == 1


def test_process_rejects_the_same_staff_twice_in_one_request(client, db_session):
    ada = _staff(db_session, "Ada Obi")
    _salary_tx(db_session, "ADA OBI", 15000.0)
    resp = _process(client, [_line(ada), _line(ada)], [_row(1, "ADA OBI", 15000.0)])
    assert resp.status_code == 400
    assert db_session.query(PayrollEntry).count() == 0


def test_process_does_not_link_to_a_row_that_belongs_to_a_staff_member_not_in_the_request(client, db_session):
    john = _staff(db_session, "John Musa")
    _staff(db_session, "John Adebayo Musa")                  # skipped this run, but owns the row below
    _salary_tx(db_session, "JOHN ADEBAYO MUSA", 15000.0)
    resp = _process(client, [_line(john)], [_row(1, "JOHN ADEBAYO MUSA", 15000.0)])
    assert _issues(resp) == {("John Musa", "not_on_schedule")}


def test_process_checks_every_part_of_a_split_payment_for_existing_links(client, db_session):
    ada, bola = _staff(db_session, "Ada Obi"), _staff(db_session, "Bola Eze")
    first = _salary_tx(db_session, "ADA OBI", 7500.0, "2026-01-20")
    second = _salary_tx(db_session, "ADA OBI", 7500.0, "2026-01-30")
    db_session.add(PayrollEntry(staff_id=bola.id, period_year=2026, period_month=1, gross_salary=1.0,
                                net_salary=1.0, is_paid=True, transaction_id=second.id))
    db_session.commit()
    resp = _process(client, [_line(ada)], [_row(1, "ADA OBI", 15000.0)])
    assert ("Ada Obi", "payment_already_linked") in _issues(resp)
    assert first.id != second.id


def test_process_accepts_a_split_payment_that_adds_up(client, db_session):
    ada = _staff(db_session, "Ada Obi")
    _salary_tx(db_session, "ADA OBI", 7500.0, "2026-01-20")
    _salary_tx(db_session, "ADA OBI", 7500.0, "2026-01-30")
    resp = _process(client, [_line(ada)], [_row(1, "ADA OBI", 15000.0)])
    assert resp.status_code == 200, resp.text
    assert resp.json()[0]["paid_amount"] == 15000.0


def test_next_month_ignores_staff_who_never_had_a_payroll_entry(client, db_session):
    ada = _staff(db_session, "Ada Obi")
    _staff(db_session, "Hired Later")                       # no start date, never paid
    for ago in (3, 2, 1, 0):
        _paid_entry(db_session, ada, ago)
    assert _next(client) == _months_ago(0)


def test_next_month_does_not_require_staff_before_their_first_entry(client, db_session):
    ada, bola = _staff(db_session, "Ada Obi"), _staff(db_session, "Bola Eze")
    for ago in (3, 2):
        _paid_entry(db_session, ada, ago)
    _paid_entry(db_session, bola, 1)                        # Bola first appears one month ago
    _paid_entry(db_session, ada, 1)
    assert _next(client) == _months_ago(0)                  # months 3 and 2 never needed Bola


# ── account details: directory fills blanks, the bank is the truth ───────────

def test_process_uses_the_directory_account_when_the_schedule_has_none(client, db_session):
    jon = _staff(db_session, "MRS JONATHAN OGOGO", gross=50000.0, account="7038692765")
    tx = _salary_tx(db_session, "PATRICIA NKECHI OGOGO", 50000.0, account="7038692765")   # paid to someone else's name
    resp = _process(client, [_line(jon, gross=50000.0)], [_row(1, "MRS JONATHAN OGOGO", 50000.0)])
    assert resp.status_code == 200, resp.text
    assert resp.json()[0]["transaction_id"] == tx.id


def test_process_blocks_when_the_bank_paid_a_different_account_than_the_directory_has(client, db_session):
    ada = _staff(db_session, "Ada Obi", account="0999999999")
    _salary_tx(db_session, "ADA OBI", 15000.0, account="0123456789")
    resp = _process(client, [_line(ada)], [_row(1, "ADA OBI", 15000.0)])
    assert ("Ada Obi", "account_differs") in _issues(resp)
    assert db_session.query(PayrollEntry).count() == 0


def test_process_allows_a_directory_with_no_account_yet(client, db_session):
    ada = _staff(db_session, "Ada Obi")
    _salary_tx(db_session, "ADA OBI", 15000.0, account="0123456789")
    assert _process(client, [_line(ada)], [_row(1, "ADA OBI", 15000.0)]).status_code == 200
