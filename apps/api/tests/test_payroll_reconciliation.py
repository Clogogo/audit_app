"""Tests for payroll schedule reconciliation: upload an Excel/CSV schedule of
what each teacher should have been paid and compare it with the Salary and
Wages transactions actually recorded in the bank account. Names and account
numbers are fictional — not real staff or bank data."""
from datetime import date
from io import BytesIO

import pytest
from openpyxl import Workbook

from models import Transaction
from utils.payroll_recon import (
    ScheduleError, ScheduleRow, SkippedRow, parse_schedule, parse_schedule_with_skips, reconcile,
)


def _xlsx(rows: list[list]) -> bytes:
    wb = Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _tx(db_session, vendor: str, amount: float, day: str = "2026-01-30",
        category: str = "Salary and Wages", type_: str = "expense", bank_account_id=None):
    tx = Transaction(
        type=type_, amount=amount, currency="NGN", category=category,
        description=f"Transfer to {vendor} | OPay | 0000000000 | January 2026",
        date=date.fromisoformat(day), vendor=vendor, bank_account_id=bank_account_id,
    )
    db_session.add(tx)
    db_session.commit()
    return tx


# ── parse_schedule ────────────────────────────────────────────────────────────

def test_parse_detects_headers_and_amounts():
    content = _xlsx([
        ["Name", "Account Number", "Net Pay"],
        ["Ngozi Williams", "0123456789", 15020],
        ["Chidi Okoro", "0987654321", "₦20,500.50"],
    ])
    rows = parse_schedule(content, "jan.xlsx")
    assert rows == [
        ScheduleRow(row_number=2, name="Ngozi Williams", amount=15020.0, account_number="0123456789"),
        ScheduleRow(row_number=3, name="Chidi Okoro", amount=20500.5, account_number="0987654321"),
    ]


def test_parse_skips_title_rows_above_header_and_total_row():
    content = _xlsx([
        ["JANUARY 2026 SALARY SCHEDULE"],
        [],
        ["S/N", "Staff Name", "Amount"],
        [1, "Ngozi Williams", 15000],
        [2, "Chidi Okoro", 20000],
        [None, "TOTAL", 35000],
    ])
    rows = parse_schedule(content, "jan.xlsx")
    assert [r.name for r in rows] == ["Ngozi Williams", "Chidi Okoro"]
    assert rows[0].row_number == 4


def test_parse_accepts_csv():
    csv = b"Teacher,Salary\nNgozi Williams,15000\n"
    rows = parse_schedule(csv, "jan.csv")
    assert rows == [ScheduleRow(row_number=2, name="Ngozi Williams", amount=15000.0, account_number=None)]


def test_parse_skips_rows_with_blank_name_or_unreadable_amount():
    content = _xlsx([
        ["Name", "Amount"],
        ["Ngozi Williams", 15000],
        [None, 5000],
        ["Chidi Okoro", "n/a"],
    ])
    assert [r.name for r in parse_schedule(content, "x.xlsx")] == ["Ngozi Williams"]


def test_parse_rejects_missing_columns():
    with pytest.raises(ScheduleError, match="name and amount"):
        parse_schedule(_xlsx([["Foo", "Bar"], ["a", "b"]]), "x.xlsx")


def test_parse_rejects_unsupported_extension_and_corrupt_file():
    with pytest.raises(ScheduleError, match="Unsupported"):
        parse_schedule(b"whatever", "x.pdf")
    with pytest.raises(ScheduleError):
        parse_schedule(b"not really an xlsx", "x.xlsx")


def test_parse_rejects_schedule_with_no_valid_rows():
    with pytest.raises(ScheduleError, match="No payable rows"):
        parse_schedule(_xlsx([["Name", "Amount"], [None, None]]), "x.xlsx")


# ── reconcile ─────────────────────────────────────────────────────────────────

def test_reconcile_classifies_each_row(db_session):
    _tx(db_session, "NGOZI WILLIAMS", 15000.0)           # exact
    _tx(db_session, "CHIDI OKORO", 18000.0)              # underpaid vs 20000
    _tx(db_session, "ADAEZE FALADE", 12500.0)            # overpaid vs 12000
    rows = [
        ScheduleRow(2, "Ngozi Williams", 15000.0, None),
        ScheduleRow(3, "Chidi Okoro", 20000.0, None),
        ScheduleRow(4, "Falade Adaeze", 12000.0, None),
        ScheduleRow(5, "Grace Balogun", 9000.0, None),   # nothing paid
    ]
    txs = db_session.query(Transaction).all()
    result = reconcile(rows, txs)
    by_name = {l["name"]: l for l in result["lines"]}

    assert by_name["Ngozi Williams"]["status"] == "matched"
    assert by_name["Chidi Okoro"]["status"] == "underpaid"
    assert by_name["Chidi Okoro"]["difference"] == -2000.0
    assert by_name["Falade Adaeze" if "Falade Adaeze" in by_name else "Falade Adaeze"]["status"] == "overpaid"
    assert by_name["Grace Balogun"]["status"] == "not_paid"
    assert by_name["Grace Balogun"]["paid_amount"] == 0.0
    s = result["summary"]
    assert (s["matched"], s["underpaid"], s["overpaid"], s["not_paid"]) == (1, 1, 1, 1)
    assert s["expected_total"] == 56000.0
    assert s["paid_total"] == 45500.0


def test_reconcile_reports_payments_not_on_schedule(db_session):
    _tx(db_session, "NGOZI WILLIAMS", 15000.0)
    stray = _tx(db_session, "SOMEONE ELSE", 7000.0)
    result = reconcile([ScheduleRow(2, "Ngozi Williams", 15000.0, None)], db_session.query(Transaction).all())
    assert [t["id"] for t in result["unmatched_transactions"]] == [stray.id]
    assert result["summary"]["unmatched_payments"] == 1
    assert result["summary"]["unmatched_total"] == 7000.0


def test_reconcile_never_reuses_a_transaction_for_two_rows(db_session):
    _tx(db_session, "NGOZI WILLIAMS", 15000.0)
    rows = [ScheduleRow(2, "Ngozi Williams", 15000.0, None), ScheduleRow(3, "Ngozi Williams", 15000.0, None)]
    result = reconcile(rows, db_session.query(Transaction).all())
    assert [l["status"] for l in result["lines"]] == ["matched", "not_paid"]


def test_reconcile_sums_split_payments_to_same_person(db_session):
    a = _tx(db_session, "CHIDI OKORO", 12000.0, "2026-01-28")
    b = _tx(db_session, "CHIDI OKORO", 8000.0, "2026-01-30")
    result = reconcile([ScheduleRow(2, "Chidi Okoro", 20000.0, None)], db_session.query(Transaction).all())
    line = result["lines"][0]
    assert line["status"] == "matched"
    assert line["paid_amount"] == 20000.0
    assert sorted(line["transaction_ids"]) == sorted([a.id, b.id])


def test_reconcile_prefers_exact_amount_over_other_candidates(db_session):
    _tx(db_session, "CHIDI OKORO", 5000.0)
    exact = _tx(db_session, "CHIDI OKORO", 20000.0)
    result = reconcile([ScheduleRow(2, "Chidi Okoro", 20000.0, None)], db_session.query(Transaction).all())
    assert result["lines"][0]["transaction_ids"] == [exact.id]
    assert result["lines"][0]["status"] == "matched"
    assert result["summary"]["unmatched_payments"] == 1


def test_reconcile_matches_on_account_number_when_name_differs(db_session):
    tx = Transaction(
        type="expense", amount=15020.0, currency="NGN", category="Salary and Wages",
        description="Transfer to ABIGAIL CHIDERA | OPay | 0123456789 | January 2026",
        date=date(2026, 1, 30), vendor="ABIGAIL CHIDERA",
    )
    db_session.add(tx)
    db_session.commit()
    rows = [ScheduleRow(2, "Ngozi Williams", 15020.0, "0123456789")]
    result = reconcile(rows, db_session.query(Transaction).all())
    assert result["lines"][0]["status"] == "matched"
    assert result["lines"][0]["transaction_ids"] == [tx.id]


def test_reconcile_tolerates_sub_kobo_rounding(db_session):
    _tx(db_session, "NGOZI WILLIAMS", 15000.004)
    result = reconcile([ScheduleRow(2, "Ngozi Williams", 15000.0, None)], db_session.query(Transaction).all())
    assert result["lines"][0]["status"] == "matched"


# ── endpoint ──────────────────────────────────────────────────────────────────

def _post(client, content: bytes, filename="jan.xlsx", year=2026, month=1, **extra):
    return client.post(
        "/payroll/reconcile",
        data={"year": str(year), "month": str(month), **extra},
        files={"file": (filename, content, "application/octet-stream")},
    )


def test_endpoint_reconciles_month_and_ignores_other_months_and_categories(client, db_session):
    _tx(db_session, "NGOZI WILLIAMS", 15000.0, "2026-01-30")
    _tx(db_session, "NGOZI WILLIAMS", 15000.0, "2026-02-27")                      # other month
    _tx(db_session, "NGOZI WILLIAMS", 15000.0, "2026-01-15", category="Supplies")  # wrong category
    _tx(db_session, "NGOZI WILLIAMS", 15000.0, "2026-01-15", type_="income")       # not an expense
    content = _xlsx([["Name", "Amount"], ["Ngozi Williams", 15000]])
    resp = _post(client, content)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["lines"][0]["status"] == "matched"
    assert body["lines"][0]["paid_amount"] == 15000.0
    assert body["summary"]["unmatched_payments"] == 0
    assert body["year"] == 2026 and body["month"] == 1


def test_endpoint_filters_by_bank_account(client, db_session):
    from models import BankAccount
    acct = BankAccount(bank_name="Test Bank", account_holder_name="Main", account_number="1", opening_balance=0)
    db_session.add(acct)
    db_session.commit()
    _tx(db_session, "NGOZI WILLIAMS", 15000.0, bank_account_id=acct.id)
    content = _xlsx([["Name", "Amount"], ["Ngozi Williams", 15000]])
    acct2 = BankAccount(bank_name="Other Bank", account_holder_name="Other", account_number="2", opening_balance=0)
    db_session.add(acct2)
    db_session.commit()
    other = _post(client, content, bank_account_id=str(acct2.id)).json()
    assert other["lines"][0]["status"] == "not_paid"
    same = _post(client, content, bank_account_id=str(acct.id)).json()
    assert same["lines"][0]["status"] == "matched"


def test_endpoint_does_not_write_anything(client, db_session):
    _tx(db_session, "NGOZI WILLIAMS", 15000.0)
    before = db_session.query(Transaction).count()
    _post(client, _xlsx([["Name", "Amount"], ["Ngozi Williams", 15000]]))
    db_session.expire_all()
    assert db_session.query(Transaction).count() == before


def test_endpoint_rejects_bad_input(client):
    assert _post(client, b"junk", "x.xlsx").status_code == 400
    assert _post(client, b"junk", "x.pdf").status_code == 400
    good = _xlsx([["Name", "Amount"], ["A B", 1]])
    assert _post(client, good, month=13).status_code == 422
    assert _post(client, good, year=1800).status_code == 422


def test_endpoint_rejects_oversized_upload(client):
    big = b"Name,Amount\n" + b"A B,1\n" * 2_000_000   # ~12 MB
    assert _post(client, big, "big.csv").status_code == 413


def test_endpoint_requires_staff_permission(anon_client):
    resp = anon_client.post(
        "/payroll/reconcile", data={"year": "2026", "month": "1"},
        files={"file": ("a.csv", b"Name,Amount\nA B,1\n", "text/csv")},
    )
    assert resp.status_code in (401, 403)


# ── review hardening ──────────────────────────────────────────────────────────

def test_reconcile_exact_payment_is_not_stolen_by_looser_name_match(db_session):
    tx = _tx(db_session, "JOHN MUSA", 80000.0)
    rows = [ScheduleRow(5, "John Adebayo Musa", 100000.0, None), ScheduleRow(9, "John Musa", 80000.0, None)]
    lines = {l["row_number"]: l for l in reconcile(rows, db_session.query(Transaction).all())["lines"]}
    assert lines[9]["status"] == "matched" and lines[9]["transaction_ids"] == [tx.id]
    assert lines[5]["status"] == "not_paid"


def test_reconcile_same_person_on_two_rows_matches_each_exact_payment(db_session):
    a = _tx(db_session, "CHIDI OKORO", 20000.0, "2026-01-28")
    b = _tx(db_session, "CHIDI OKORO", 5000.0, "2026-01-30")
    rows = [ScheduleRow(2, "Chidi Okoro", 5000.0, None), ScheduleRow(3, "Chidi Okoro", 20000.0, None)]
    lines = {l["row_number"]: l for l in reconcile(rows, db_session.query(Transaction).all())["lines"]}
    assert lines[2]["transaction_ids"] == [b.id] and lines[3]["transaction_ids"] == [a.id]


def test_reconcile_flags_contested_payment_instead_of_guessing(db_session):
    _tx(db_session, "JOHN MUSA", 150.0)
    rows = [ScheduleRow(2, "John Musa", 100.0, None), ScheduleRow(3, "John Musa", 200.0, None)]
    result = reconcile(rows, db_session.query(Transaction).all())
    assert [l["status"] for l in result["lines"]] == ["not_paid", "not_paid"]
    assert all("review manually" in l["note"] for l in result["lines"])
    assert result["summary"]["unmatched_payments"] == 1


def test_reconcile_one_kobo_difference_is_not_matched(db_session):
    _tx(db_session, "NGOZI WILLIAMS", 14999.99)
    line = reconcile([ScheduleRow(2, "Ngozi Williams", 15000.0, None)], db_session.query(Transaction).all())["lines"][0]
    assert line["status"] == "underpaid" and line["difference"] == -0.01


def test_parse_picks_name_column_not_staff_id():
    content = _xlsx([["S/N", "Staff ID", "Staff Name", "Amount"], [1, "T-001", "Ngozi Williams", 15000]])
    assert parse_schedule(content, "x.xlsx")[0].name == "Ngozi Williams"


def test_parse_ignores_title_row_that_looks_like_a_header():
    content = _xlsx([
        ["Name of School", "Salary for March"],
        [],
        ["Name", "Amount"],
        ["Ngozi Williams", 15000],
    ])
    rows = parse_schedule(content, "x.xlsx")
    assert [r.name for r in rows] == ["Ngozi Williams"] and rows[0].row_number == 4


@pytest.mark.parametrize("label", ["TOTAL:", "Total Payroll", "Grand Total", "Approved by Head Teacher"])
def test_parse_skips_footer_rows(label):
    content = _xlsx([["Name", "Amount"], ["Ngozi Williams", 15000], [label, 15000]])
    assert [r.name for r in parse_schedule(content, "x.xlsx")] == ["Ngozi Williams"]


def test_parse_skips_total_label_in_another_column():
    content = _xlsx([["S/N", "Name", "Amount"], [1, "Ngozi Williams", 15000], ["Total", None, 15000]])
    assert [r.name for r in parse_schedule(content, "x.xlsx")] == ["Ngozi Williams"]


def test_parse_reports_skipped_rows_and_rejects_ambiguous_amounts():
    content = _xlsx([
        ["Name", "Amount"],
        ["Ngozi Williams", 15000],
        ["Euro Format", "1.234,50"],
        ["Suffix K", "N50k"],
        ["Exponent", "1e5"],
        ["Zero Pay", 0],
        [None, 5000],
    ])
    rows, skipped = parse_schedule_with_skips(content, "x.xlsx")
    assert [r.name for r in rows] == ["Ngozi Williams"]
    assert [s.row_number for s in skipped] == [3, 4, 5, 6, 7]
    assert all(isinstance(s, SkippedRow) and s.reason for s in skipped)


def test_parse_account_number_regains_leading_zero_lost_by_excel():
    content = _xlsx([["Name", "Acc. No", "Amount"], ["Ngozi Williams", 123456789, 15000]])
    assert parse_schedule(content, "x.xlsx")[0].account_number == "0123456789"


def test_parse_recognises_beneficiary_account_column():
    content = _xlsx([["Beneficiary", "Beneficiary Account", "Amount"], ["Ngozi Williams", "0123456789", 15000]])
    assert parse_schedule(content, "x.xlsx")[0].account_number == "0123456789"


def test_parse_rejects_zip_bomb_before_loading():
    import zipfile
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("xl/worksheets/sheet1.xml", b"\0" * (40 * 1024 * 1024))
    assert len(buf.getvalue()) < 1024 * 1024
    with pytest.raises(ScheduleError, match="too large"):
        parse_schedule(buf.getvalue(), "bomb.xlsx")


def test_parse_rejects_too_many_rows_for_csv_and_xlsx():
    csv = b"Name,Amount\n" + b"A B,1\n" * 2500
    with pytest.raises(ScheduleError, match="too many rows"):
        parse_schedule(csv, "big.csv")
    big = _xlsx([["Name", "Amount"]] + [["A B", 1]] * 2500)
    with pytest.raises(ScheduleError, match="too many rows"):
        parse_schedule(big, "big.xlsx")


def test_parse_turns_csv_errors_into_schedule_errors():
    with pytest.raises(ScheduleError):
        parse_schedule(b"Name,Amount\n" + b"x" * 200_000 + b",1\n", "huge-field.csv")
    with pytest.raises(ScheduleError):
        parse_schedule(b"Name,Amount\nA\x00B,1\n", "nul.csv")


def test_endpoint_unknown_bank_account_is_404_and_skipped_rows_returned(client, db_session):
    content = _xlsx([["Name", "Amount"], ["Ngozi Williams", 15000], ["Bad Row", "n/a"]])
    assert _post(client, content, bank_account_id="9999").status_code == 404
    body = _post(client, content).json()
    assert body["skipped_rows"] == [{"row_number": 3, "reason": body["skipped_rows"][0]["reason"]}]
    assert body["skipped_rows"][0]["reason"]


# ── final review fixes ────────────────────────────────────────────────────────

def test_parse_status_column_saying_approved_does_not_drop_rows():
    csv = b"Name,Account Number,Amount,Status\nJohn Doe,0123456789,1000,Approved\nMary Jane,0123456780,2000,\n"
    rows, skipped = parse_schedule_with_skips(csv, "x.csv")
    assert [r.name for r in rows] == ["John Doe", "Mary Jane"] and skipped == []


def test_reconcile_account_number_match_gets_first_claim_on_an_exact_payment(db_session):
    tx = Transaction(
        type="expense", amount=150000.0, currency="NGN", category="Salary and Wages",
        description="Transfer to ADE BOLA TUNDE | OPay | 0123456789 | January 2026",
        date=date(2026, 1, 30), vendor="ADE BOLA TUNDE",
    )
    db_session.add(tx)
    db_session.commit()
    rows = [ScheduleRow(2, "Ade Bola", 150000.0, None), ScheduleRow(3, "Ade Bola Tunde", 150000.0, "0123456789")]
    lines = {l["row_number"]: l for l in reconcile(rows, db_session.query(Transaction).all())["lines"]}
    assert lines[3]["transaction_ids"] == [tx.id] and lines[3]["status"] == "matched"
    assert lines[2]["status"] == "not_paid"


def test_reconcile_payment_also_claimed_by_a_resolved_row_is_not_handed_out(db_session):
    _tx(db_session, "CHIDI OKORO", 20000.0)
    _tx(db_session, "CHIDI OKORO", 3000.0)   # extra payment to a resolved person
    rows = [ScheduleRow(2, "Chidi Okoro", 20000.0, None), ScheduleRow(3, "Okoro Chidi", 9999.0, None)]
    lines = {l["row_number"]: l for l in reconcile(rows, db_session.query(Transaction).all())["lines"]}
    assert lines[2]["status"] == "matched"
    assert lines[3]["status"] == "not_paid" and "review manually" in lines[3]["note"]


@pytest.mark.parametrize("cell", ["9" * 400, 1e308, 1e15])
def test_parse_skips_absurd_amounts_instead_of_crashing(cell):
    content = _xlsx([["Name", "Amount"], ["Ngozi Williams", 15000], ["Huge Pay", cell]])
    rows, skipped = parse_schedule_with_skips(content, "x.xlsx")
    assert [r.name for r in rows] == ["Ngozi Williams"] and [s.row_number for s in skipped] == [3]


def test_parse_trailing_blank_lines_do_not_count_toward_row_cap():
    csv = b"Name,Amount\nA B,1\n" + b"\n" * 3000
    assert [r.name for r in parse_schedule(csv, "x.csv")] == ["A B"]


def test_parse_ignores_columns_beyond_the_cap():
    wide = [["Name", "Amount"] + [None] * 80 + ["junk"]]
    wide.append(["Ngozi Williams", 15000] + [None] * 80 + ["junk"])
    assert [r.name for r in parse_schedule(_xlsx(wide), "x.xlsx")] == ["Ngozi Williams"]
