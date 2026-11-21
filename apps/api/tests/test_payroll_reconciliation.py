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
    ScheduleError, ScheduleRow, SkippedRow, link_staff_to_rows, parse_payment_recipient, parse_schedule,
    parse_schedule_full, parse_schedule_with_skips, reconcile,
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
    _tx(db_session, "JOHN MUSA", 150000.0)
    rows = [ScheduleRow(2, "John Musa", 100000.0, None), ScheduleRow(3, "John Musa", 200000.0, None)]
    result = reconcile(rows, db_session.query(Transaction).all())
    assert [l["status"] for l in result["lines"]] == ["not_paid", "not_paid"]
    assert all("review manually" in l["note"] for l in result["lines"])
    assert result["summary"]["unmatched_payments"] == 1


def test_reconcile_difference_under_100_naira_counts_as_paid(db_session):
    _tx(db_session, "NGOZI WILLIAMS", 14900.01)
    line = reconcile([ScheduleRow(2, "Ngozi Williams", 15000.0, None)], db_session.query(Transaction).all())["lines"][0]
    assert line["status"] == "matched" and line["difference"] == -99.99
    assert line["paid_amount"] == 14900.01   # the real bank amount is still reported


def test_reconcile_difference_of_100_naira_or_more_is_not_paid_in_full(db_session):
    _tx(db_session, "NGOZI WILLIAMS", 14900.0)
    under = reconcile([ScheduleRow(2, "Ngozi Williams", 15000.0, None)], db_session.query(Transaction).all())["lines"][0]
    assert under["status"] == "underpaid" and under["difference"] == -100.0
    over = reconcile([ScheduleRow(2, "Ngozi Williams", 14800.0, None)], db_session.query(Transaction).all())["lines"][0]
    assert over["status"] == "overpaid"


def test_reconcile_prefers_the_closest_payment_within_tolerance(db_session):
    _tx(db_session, "NGOZI WILLIAMS", 14950.0, "2026-01-20")
    best = _tx(db_session, "NGOZI WILLIAMS", 15000.0, "2026-01-30")
    line = reconcile([ScheduleRow(2, "Ngozi Williams", 15000.0, None)], db_session.query(Transaction).all())["lines"][0]
    assert line["transaction_ids"] == [best.id]


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


def test_endpoint_returns_skipped_rows_and_ignores_a_stray_bank_account_field(client, db_session):
    content = _xlsx([["Name", "Amount"], ["Ngozi Williams", 15000], ["Bad Row", "n/a"]])
    body = _post(client, content, bank_account_id="9999").json()
    assert [(r["row_number"], r["ignored"]) for r in body["skipped_rows"]] == [(3, False)]
    assert body["skipped_rows"][0]["reason"] and body["skipped_rows"][0]["label"] == "Bad Row"
    assert body["notes"] == []


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


# ── pasted / header-less sheets (made-up names, same layout as a real payroll sheet) ──

def _row(name="", basic="", deduction="", bonus="", net="", account="", bank="", note=""):
    """One tab-separated line: name, 2 blanks, basic, gross, deduction, bonus, blank, net, account, bank, note."""
    return "\t".join([name, "", "", basic, basic, deduction, bonus, "", net, account, bank, note])


PASTED_SHEET = "\n".join([
    _row("ADA OBI", "₦25,000.00", net="₦25,000.00", account="0123456781", bank="OPAY"),
    _row("BOLA EZE", "₦30,000.00", bonus="₦100,000.00", net="₦130,000.00", account="3012345678", bank="FIRSTBANK",
         note="Paid Bonus Award 100,000"),
    _row("MRS TUNDE LAW", "₦30,000.00", net="₦30,000.00", account="8112345678", bank="OPAY"),
    _row("MRS TUNDE LAW", net="₦0.00"),
    "",
    _row("MRS OKE ADE", "₦50,000.00", net="₦50,000.00", bank="OPAY"),
    "",
    _row("TOTAL", "₦135,000.00", net="₦235,000.00"),
    "",
    "SENIOR SCHOOL",
    "",
    "FULL TIME",
    _row("KEMI ALA", "₦50,000.00", deduction="₦10,000.00", net="₦40,000.00", account="8012345678", bank="OPAY"),
    "PART TIME",
    _row("SEGUN OJO", "₦35,000.00", deduction="₦10,000.00", bonus="₦2,000.00", net="₦27,000.00",
         account="4212345678", bank="Zenith Bank", note="Additional subject Bonus"),
    _row("", "₦85,000.00", deduction="₦20,000.00", net="₦67,000.00"),
])


def test_parse_pasted_sheet_without_header_uses_net_pay_and_account_columns():
    rows, skipped = parse_schedule_with_skips(PASTED_SHEET.encode(), "pasted.tsv")
    assert [(r.name, r.amount, r.account_number) for r in rows] == [
        ("ADA OBI", 25000.0, "0123456781"),
        ("BOLA EZE", 130000.0, "3012345678"),
        ("MRS TUNDE LAW", 30000.0, "8112345678"),
        ("MRS OKE ADE", 50000.0, None),
        ("KEMI ALA", 40000.0, "8012345678"),
        ("SEGUN OJO", 27000.0, "4212345678"),
    ]
    assert [r.row_number for r in rows] == [1, 2, 3, 6, 13, 15]
    # nothing vanishes silently: the ₦0.00 duplicate is a problem; labels and
    # totals rows are listed as "ignored" with their text so they can be eyeballed
    assert [(s.row_number, s.ignored) for s in skipped] == [
        (4, False), (8, True), (10, True), (12, True), (14, True), (16, True),
    ]
    assert "greater than zero" in skipped[0].reason
    assert [s.label for s in skipped if s.ignored][:4] == ["TOTAL", "SENIOR SCHOOL", "FULL TIME", "PART TIME"]


def test_parse_headerless_xlsx_and_csv_with_plain_numbers():
    rows = parse_schedule(_xlsx([["Ngozi Williams", 15000, "0123456789"], ["Chidi Okoro", 20000, "0987654321"]]), "x.xlsx")
    assert [(r.name, r.amount, r.account_number) for r in rows] == [
        ("Ngozi Williams", 15000.0, "0123456789"), ("Chidi Okoro", 20000.0, "0987654321"),
    ]
    assert [r.amount for r in parse_schedule(b"Ngozi Williams,15000\nChidi Okoro,20000\n", "x.csv")] == [15000.0, 20000.0]


def test_parse_headerless_sheet_with_no_money_is_rejected():
    with pytest.raises(ScheduleError, match="name and amount"):
        parse_schedule(b"ADA OBI\tOPAY\nBOLA EZE\tZENITH\n", "x.tsv")


def test_parse_lone_name_row_is_listed_as_ignored_not_dropped_silently():
    content = _xlsx([["Name", "Amount"], ["SENIOR SCHOOL", None], ["Ngozi Williams", 15000], ["Bola Ade", None]])
    rows, skipped = parse_schedule_with_skips(content, "x.xlsx")
    assert [r.name for r in rows] == ["Ngozi Williams"]
    assert [(s.row_number, s.label, s.ignored) for s in skipped] == [(2, "SENIOR SCHOOL", True), (4, "Bola Ade", True)]


def test_parse_nameless_row_with_two_numbers_is_listed_not_dropped_silently():
    content = _xlsx([["Name", "Gross", "Net"], ["Ada Oko", 6000, 5000], [None, 7000, 6000]])
    rows, skipped = parse_schedule_with_skips(content, "x.xlsx")
    assert [r.name for r in rows] == ["Ada Oko"]
    assert [(s.row_number, s.ignored) for s in skipped] == [(3, True)]


def test_parse_headerless_bare_name_row_is_reported():
    rows, skipped = parse_schedule_with_skips(b"ADA OKO,100,90\nBOLA ADE\nJOY ZED,100,80\n", "x.csv")
    assert [r.name for r in rows] == ["ADA OKO", "JOY ZED"]
    assert [(s.row_number, s.label) for s in skipped] == [(2, "BOLA ADE")]


def test_parse_headerless_sheet_says_which_columns_it_used():
    csv = b"ADA OKO,100,90\nJOY ZED,100,80\n"
    full = parse_schedule_full(csv, "x.csv")
    assert any("column C" in n and "amount" in n.lower() for n in full.notes)
    with_header = parse_schedule_full(b"Name,Amount\nADA OKO,90\n", "x.csv")
    assert with_header.notes == []


def test_parse_headerless_warns_when_amount_column_is_sparse():
    csv = b"ADA OKO,100,90\nBOLA ADE,100,\nJOY ZED,100,\nSEGUN OJO,100,\nKEMI ALA,100,80\n"
    notes = parse_schedule_full(csv, "x.csv").notes
    assert any("check" in n.lower() for n in notes)


def test_parse_headerless_name_column_is_not_a_repeated_title_column():
    rows = parse_schedule(b"MR,ADA OKO,100\nMR,BOLA ADE,200\nMRS,JOY ZED,300\n", "x.csv")
    assert [r.name for r in rows] == ["ADA OKO", "BOLA ADE", "JOY ZED"]


def test_parse_header_row_without_data_below_falls_back_to_inference():
    rows = parse_schedule(b"Teacher,Salary,\nADA OKO,,5000\nBOLA ADE,,6000\n", "x.csv")
    assert [(r.name, r.amount) for r in rows] == [("ADA OKO", 5000.0), ("BOLA ADE", 6000.0)]


def test_reconcile_matches_on_the_alternate_name_in_brackets(db_session):
    tx = _tx(db_session, "JOY ADA OKO", 15000.0)
    rows = [ScheduleRow(1, "ACADEMY EXTRA LESSONS (JOY ADA OKO)", 15000.0, None)]
    line = reconcile(rows, db_session.query(Transaction).all())["lines"][0]
    assert line["status"] == "matched" and line["transaction_ids"] == [tx.id]


def test_endpoint_accepts_pasted_tsv(client, db_session):
    _tx(db_session, "ADA OBI", 25000.0)
    _tx(db_session, "KEMI ALA", 35000.0)
    resp = _post(client, PASTED_SHEET.encode(), "pasted.tsv")
    assert resp.status_code == 200, resp.text
    by_name = {l["name"]: l["status"] for l in resp.json()["lines"]}
    assert by_name["ADA OBI"] == "matched"
    assert by_name["KEMI ALA"] == "underpaid"
    assert by_name["BOLA EZE"] == "not_paid"
    assert resp.json()["summary"]["rows"] == 6
    assert any("amount" in n.lower() for n in resp.json()["notes"])


# ── linking schedule rows to the staff directory ──────────────────────────────

def _staff_obj(id_, name, account=None):
    from types import SimpleNamespace
    return SimpleNamespace(id=id_, full_name=name, account_number=account)


def test_link_account_number_wins_over_name():
    rows = [ScheduleRow(1, "Totally Different", 100.0, "0123456789")]
    assert link_staff_to_rows([_staff_obj(1, "Ada Obi", "0123456789")], rows) == {1: rows[0]}


def test_link_account_number_ignores_a_lost_leading_zero():
    rows = [ScheduleRow(1, "Someone", 100.0, "123456789")]
    assert link_staff_to_rows([_staff_obj(1, "Ada Obi", "0123456789")], rows) == {1: rows[0]}


def test_link_by_reordered_titled_name():
    rows = [ScheduleRow(1, "MRS ADA OBI", 100.0, None)]
    assert link_staff_to_rows([_staff_obj(1, "Obi Ada")], rows) == {1: rows[0]}


def test_link_prefers_the_identical_name_over_a_looser_one():
    rows = [ScheduleRow(1, "John Adebayo Musa", 100.0, None), ScheduleRow(2, "John Musa", 100.0, None)]
    links = link_staff_to_rows([_staff_obj(7, "John Musa")], rows)
    assert links == {7: rows[1]}


def test_link_leaves_ambiguous_matches_unlinked_and_never_reuses_a_row():
    rows = [ScheduleRow(1, "Ada Obi", 100.0, None)]
    both = link_staff_to_rows([_staff_obj(1, "Ada Obi Eze"), _staff_obj(2, "Ada Obi Ife")], rows)
    assert both == {}                       # two staff could own one row: don't guess
    assert link_staff_to_rows([_staff_obj(1, "Zed Qux")], rows) == {}


def test_endpoint_links_rows_to_staff_and_flags_out_of_sync_salary(client, db_session):
    from models import Staff
    ada = Staff(full_name="Ada Obi", monthly_gross=15000.0, is_active=True)
    bola = Staff(full_name="Bola Eze", monthly_gross=20000.0, is_active=True)
    kemi = Staff(full_name="Kemi Ala", monthly_gross=10000.0, is_active=True)   # not on the schedule
    db_session.add_all([ada, bola, kemi])
    db_session.commit()
    _tx(db_session, "ADA OBI", 15000.0)
    _tx(db_session, "BOLA EZE", 18000.0)
    content = _xlsx([["Name", "Amount"], ["Ada Obi", 15000], ["Bola Eze", 18000], ["Segun Ojo", 9000]])
    body = _post(client, content).json()
    by_name = {l["name"]: l for l in body["lines"]}

    assert by_name["Ada Obi"]["staff_id"] == ada.id and by_name["Ada Obi"]["in_sync"] is True
    assert by_name["Ada Obi"]["computed_net"] == 15000.0
    assert by_name["Bola Eze"]["status"] == "matched"            # bank matches the schedule...
    assert by_name["Bola Eze"]["in_sync"] is False               # ...but the directory total does not
    assert by_name["Bola Eze"]["net_difference"] == 2000.0
    assert by_name["Segun Ojo"]["staff_id"] is None and by_name["Segun Ojo"]["in_sync"] is None
    assert body["unlinked_staff"] == [{"staff_id": kemi.id, "full_name": "Kemi Ala", "computed_net": 10000.0}]


def test_reconcile_flags_a_second_payment_to_a_row_that_is_already_paid(db_session):
    first = _tx(db_session, "NGOZI WILLIAMS", 15000.0, "2026-01-20")
    second = _tx(db_session, "NGOZI WILLIAMS", 15000.0, "2026-01-30")
    result = reconcile([ScheduleRow(2, "Ngozi Williams", 15000.0, None)], db_session.query(Transaction).all())
    line = result["lines"][0]
    assert line["status"] == "matched" and line["transaction_ids"] == [first.id]
    assert line["extra_payment_ids"] == [second.id] and line["extra_paid_amount"] == 15000.0
    assert result["summary"]["unmatched_payments"] == 1


def test_reconcile_has_no_extra_payment_flag_for_unpaid_or_clean_rows(db_session):
    _tx(db_session, "NGOZI WILLIAMS", 15000.0)
    rows = [ScheduleRow(2, "Ngozi Williams", 15000.0, None), ScheduleRow(3, "Grace Balogun", 9000.0, None)]
    lines = reconcile(rows, db_session.query(Transaction).all())["lines"]
    assert [l["extra_payment_ids"] for l in lines] == [[], []]


# ── account details: directory fills blanks, the bank is the truth ───────────

def _acct_tx(db, vendor, amount, account, bank="OPay", day="2026-01-30"):
    tx = Transaction(
        type="expense", amount=amount, currency="NGN", category="Salary and Wages",
        description=f"Transfer to {vendor} | {bank} | {account} | January 2026", date=date.fromisoformat(day), vendor=vendor,
    )
    db.add(tx)
    db.commit()
    return tx


def test_parse_payment_recipient_reads_name_bank_and_account():
    assert parse_payment_recipient("Transfer to PATRICIA OGOGO | OPay | 7038692765 | August Salary") == ("PATRICIA OGOGO", "OPay", "7038692765")


def test_parse_payment_recipient_ignores_masked_dummy_and_non_transfer_accounts():
    assert parse_payment_recipient("Transfer to X | OPay | 955****234 | note") == ("X", "OPay", None)
    assert parse_payment_recipient("Transfer to X | OPay | 0000000000 | note") == ("X", "OPay", None)
    assert parse_payment_recipient("Transfer from X | OPay | 7038692765") == (None, None, None)
    assert parse_payment_recipient("something else") == (None, None, None)


def test_endpoint_uses_the_directory_account_when_the_sheet_has_none(client, db_session):
    from models import Staff
    jon = Staff(full_name="MRS JONATHAN OGOGO", monthly_gross=50000.0, account_number="7038692765", is_active=True)
    db_session.add(jon)
    db_session.commit()
    tx = _acct_tx(db_session, "PATRICIA NKECHI OGOGO", 50000.0, "7038692765")     # paid to another name
    line = _post(client, _xlsx([["Name", "Amount"], ["MRS JONATHAN OGOGO", 50000]])).json()["lines"][0]
    assert line["status"] == "matched" and line["transaction_ids"] == [tx.id]
    assert line["staff_id"] == jon.id and line["account_source"] == "directory"
    assert line["account_check"] == "ok" and line["paid_account"] == "7038692765" and line["paid_to"] == "PATRICIA NKECHI OGOGO"


def test_endpoint_prefers_the_sheet_account_and_flags_a_different_directory_account(client, db_session):
    from models import Staff
    db_session.add(Staff(full_name="Ada Obi", monthly_gross=15000.0, account_number="0999999999", is_active=True))
    db_session.commit()
    _acct_tx(db_session, "ADA OBI", 15000.0, "0123456789")
    sheet = _xlsx([["Name", "Account Number", "Amount"], ["Ada Obi", "0123456789", 15000]])
    line = _post(client, sheet).json()["lines"][0]
    assert line["status"] == "matched" and line["account_source"] == "sheet"
    assert line["account_check"] == "differs" and line["directory_account"] == "0999999999"
    assert line["paid_account"] == "0123456789" and line["paid_bank"] == "OPay"


def test_endpoint_asks_for_an_account_when_the_directory_has_none(client, db_session):
    from models import Staff
    db_session.add(Staff(full_name="Ada Obi", monthly_gross=15000.0, is_active=True))
    db_session.commit()
    _acct_tx(db_session, "ADA OBI", 15000.0, "0123456789")
    line = _post(client, _xlsx([["Name", "Amount"], ["Ada Obi", 15000]])).json()["lines"][0]
    assert line["account_check"] == "missing" and line["directory_account"] is None


def test_endpoint_does_not_judge_accounts_it_cannot_read(client, db_session):
    from models import Staff
    db_session.add(Staff(full_name="Ada Obi", monthly_gross=15000.0, account_number="0999999999", is_active=True))
    db_session.commit()
    _tx(db_session, "ADA OBI", 15000.0)                       # narration account is a dummy 0000000000
    assert _post(client, _xlsx([["Name", "Amount"], ["Ada Obi", 15000]])).json()["lines"][0]["account_check"] is None


def test_unpaid_row_suggests_the_unclaimed_payment_of_the_same_amount(db_session):
    big = _acct_tx(db_session, "PATRICIA NKECHI OGOGO", 50000.0, "7038692765", day="2026-01-28")
    _acct_tx(db_session, "PATRICIA NKECHI OGOGO", 5000.0, "7038692765", day="2026-01-29")
    result = reconcile([ScheduleRow(1, "MRS JONATHAN OGOGO", 50000.0, None)], db_session.query(Transaction).all())
    line = result["lines"][0]
    assert line["status"] == "not_paid"
    assert line["suggested_payments"] == [{
        "id": big.id, "date": "2026-01-28", "amount": 50000.0, "vendor": "PATRICIA NKECHI OGOGO",
        "account": "7038692765", "bank": "OPay",
    }]


def test_no_suggestion_when_nothing_is_close_in_amount(db_session):
    _acct_tx(db_session, "PATRICIA NKECHI OGOGO", 5000.0, "7038692765")
    line = reconcile([ScheduleRow(1, "MRS JONATHAN OGOGO", 50000.0, None)], db_session.query(Transaction).all())["lines"][0]
    assert line["suggested_payments"] == []


# ── review hardening: stale / shared accounts and suggestions ─────────────────

def test_stale_directory_account_does_not_hide_the_real_payment(client, db_session):
    from models import Staff
    db_session.add(Staff(full_name="Alice Ade", monthly_gross=50000.0, account_number="7038692765", is_active=True))
    db_session.commit()
    _acct_tx(db_session, "ALICE ADE", 10000.0, "7038692765", day="2026-01-10")        # an advance to her old account
    real = _acct_tx(db_session, "ALICE ADE", 50000.0, "0123456789", bank="GTB")      # salary to her new bank
    line = _post(client, _xlsx([["Name", "Amount"], ["Alice Ade", 50000]])).json()["lines"][0]
    assert line["status"] == "matched" and line["transaction_ids"] == [real.id]
    assert line["account_check"] == "differs" and line["paid_account"] == "0123456789"


def test_shared_account_does_not_let_one_person_take_anothers_payment(db_session):
    bob = _acct_tx(db_session, "BOB BELLO", 50000.0, "7038692765")
    rows = [ScheduleRow(1, "Alice Ade", 50000.0, "7038692765"), ScheduleRow(2, "Bob Bello", 50000.0, "7038692765")]
    lines = {l["row_number"]: l for l in reconcile(rows, db_session.query(Transaction).all())["lines"]}
    assert lines[2]["transaction_ids"] == [bob.id] and lines[2]["status"] == "matched"
    assert lines[1]["status"] == "not_paid"


def test_a_payment_is_not_suggested_to_two_unpaid_rows(db_session):
    _acct_tx(db_session, "ZED KING", 50000.0, "7038692765")
    rows = [ScheduleRow(1, "Alice Ade", 50000.0, None), ScheduleRow(2, "Bob Bello", 50000.0, None)]
    lines = reconcile(rows, db_session.query(Transaction).all())["lines"]
    assert [l["suggested_payments"] for l in lines] == [[], []]
