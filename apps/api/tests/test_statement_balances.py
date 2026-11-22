"""Opening/closing balance and totals read from an uploaded statement, checked against its rows and the account record."""
import io

import pandas as pd

from models import BankAccount, BankStatement


def _statement(opening, closing, total_debit, total_credit, rows=None):
    rows = rows if rows is not None else [["2026-11-02", "Payment to supplier", 100.0, None], ["2026-11-03", "Fees received", None, 600.0]]
    top = [[None, "Account Summary", None, None], ["", "Opening Balance:", opening, None], ["", "Closing Balance:", closing, None],
           ["", "Total Debit:", total_debit, None], ["", "Total Credit:", total_credit, None], [None] * 4]
    buf = io.BytesIO()
    with pd.ExcelWriter(buf) as w:
        pd.DataFrame(top + [["Date", "Description", "Debit", "Credit"]] + rows).to_excel(w, header=False, index=False)
    return buf.getvalue()


def _upload(client, content):
    return client.post("/bank-statements", files={"file": ("s.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
                       data={"bank_name": "Moniepoint"})


def _checks(client, stmt_id):
    return {c["name"]: c for c in client.get(f"/bank-statements/{stmt_id}/validate").json()["checks"]}


def test_upload_captures_the_statement_summary(client, db_session):
    out = _upload(client, _statement(1000.0, 1500.0, 100.0, 600.0))
    assert out.status_code == 201, out.text
    stmt = db_session.get(BankStatement, out.json()["id"])
    assert (stmt.opening_balance, stmt.closing_balance, stmt.total_debit, stmt.total_credit) == (1000.0, 1500.0, 100.0, 600.0)


def test_matching_statement_and_account_record_pass(client, db_session):
    db_session.add(BankAccount(bank_name="Moniepoint", opening_balance=1000.0))
    db_session.commit()
    checks = _checks(client, _upload(client, _statement(1000.0, 1500.0, 100.0, 600.0)).json()["id"])
    assert {checks[n]["status"] for n in ("Statement Totals", "Statement Balance", "Account Record")} == {"pass"}


def test_alerts_when_the_statement_disagrees_with_its_rows_and_the_account_record(client, db_session):
    db_session.add(BankAccount(bank_name="Moniepoint", opening_balance=900.0))
    db_session.commit()
    checks = _checks(client, _upload(client, _statement(1000.0, 1700.0, 150.0, 600.0)).json()["id"])
    assert checks["Statement Totals"]["status"] == "warn"    # rows debit 100, statement says 150
    assert checks["Statement Balance"]["status"] == "warn"   # 1000 + 600 - 150 != 1700
    assert checks["Account Record"]["status"] == "warn" and "900.00" in checks["Account Record"]["message"]


def test_no_account_record_check_when_the_app_balance_starts_after_the_statement(client, db_session):
    from datetime import date
    db_session.add(BankAccount(bank_name="Moniepoint", opening_balance=5.0, opening_balance_date=date(2026, 12, 1)))
    db_session.commit()
    checks = _checks(client, _upload(client, _statement(1000.0, 1500.0, 100.0, 600.0)).json()["id"])
    assert "Account Record" not in checks


def test_no_balance_checks_when_the_file_has_no_summary(client, db_session):
    buf = io.BytesIO()
    with pd.ExcelWriter(buf) as w:
        pd.DataFrame([["Date", "Description", "Debit", "Credit"], ["2026-11-02", "Payment", 100.0, None]]).to_excel(w, header=False, index=False)
    checks = _checks(client, _upload(client, buf.getvalue()).json()["id"])
    assert not {"Statement Totals", "Statement Balance", "Account Record"} & set(checks)
