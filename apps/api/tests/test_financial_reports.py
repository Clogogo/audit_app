"""Financial Reports hub endpoints: each report is derived from existing tables."""
from datetime import date

import pytest

from models import AdvancePayment, Asset, PayrollEntry, SchoolLoan, Staff, StaffLoan, StaffLoanPayment, Transaction

AS_AT = {"as_at": "2026-11-21", "start_date": "2026-01-01"}


def _get(client, slug, **params):
    r = client.get(f"/financial-reports/{slug}", params={**AS_AT, **params})
    assert r.status_code == 200, r.text
    return r.json()


def _tx(db, type_, amount, category, day="2026-08-10", vendor="V"):
    db.add(Transaction(type=type_, amount=amount, currency="NGN", category=category, description="d", date=date.fromisoformat(day), vendor=vendor))
    db.commit()


def test_unknown_report_and_bad_dates(client):
    assert client.get("/financial-reports/nope").status_code == 404
    assert client.get("/financial-reports/sales", params={"as_at": "2026-01-01", "start_date": "2026-02-01"}).status_code == 400


def test_who_owes_you_lists_loan_balances_and_unrecovered_advances(client, db_session):
    staff = Staff(full_name="Ada", monthly_gross=100000)
    db_session.add(staff)
    db_session.flush()
    loan = StaffLoan(staff_id=staff.id, employee_name="Ada", loan_amount=1000, deduction_start=date(2026, 6, 1))
    db_session.add(loan)
    db_session.flush()
    db_session.add_all([StaffLoanPayment(loan_id=loan.id, amount_paid=400, paid_date=date(2026, 7, 1)),
                        AdvancePayment(staff_id=staff.id, amount=300, remaining_amount=300, date_issued=date(2026, 11, 1))])
    db_session.commit()
    out = _get(client, "who-owes-you")
    rows = out["sections"][0]["rows"]
    assert {(r["kind"], r["outstanding"]) for r in rows} == {("Staff loan", 600.0), ("Salary advance (IOU)", 300.0)}
    assert out["summary"][0]["value"] == 900.0


def test_who_you_owe_lists_loans_only_and_says_balances_are_current(client, db_session):
    _tx(db_session, "income", 5000, "Fund from Director")   # equity, not a debt
    db_session.add(SchoolLoan(lender_name="Bank A", loan_amount=2000, total_interest_due=100, collected_date=date(2026, 3, 1)))
    db_session.commit()
    out = _get(client, "who-you-owe", as_at="2026-04-01")
    assert [(r["name"], r["outstanding"]) for r in out["sections"][0]["rows"]] == [("Bank A", 2100.0)]
    assert out["current_only"] is True


def test_payroll_summary_and_paye_estimate(client, db_session):
    staff = Staff(full_name="Ada", monthly_gross=1000000)
    db_session.add(staff)
    db_session.flush()
    db_session.add(PayrollEntry(staff_id=staff.id, period_year=2026, period_month=10, gross_salary=1000000, net_salary=900000, loan_deduction=100000, is_paid=True))
    db_session.commit()
    pay = _get(client, "payroll-summary")
    assert pay["sections"][0]["rows"][0]["label"] == "2026-10" and pay["summary"][3]["value"] == 900000.0
    paye = _get(client, "paye")
    # 12M a year: 0 on 800k, 15% of 2.2M = 330k, 18% of 9M = 1.62M (to 12M) -> 1.95M / 12 = 162,500 a month
    assert paye["estimate"] is True and paye["sections"][0]["rows"][0]["tax"] == 162500.0


def test_a_bonus_is_taxed_on_top_of_salary_not_annualised(client, db_session):
    staff = Staff(full_name="Bola", monthly_gross=200000)
    db_session.add(staff)
    db_session.flush()
    db_session.add(PayrollEntry(staff_id=staff.id, period_year=2026, period_month=10, gross_salary=200000, bonus=300000, net_salary=500000))
    db_session.commit()
    # salary 2.4M/yr: 15% of 1.6M = 240k -> 20k a month. Bonus lifts the year to 2.7M: +15% of 300k = 45k
    assert _get(client, "paye")["sections"][0]["rows"][0]["tax"] == 65000.0


def test_capital_allowances_follow_the_category_rates(client, db_session):
    db_session.add_all([Asset(name="Bus", category="Motor Vehicles", purchase_date=date(2026, 2, 1), purchase_cost=1000000),
                        Asset(name="Books", category="Library Books & Educational Materials", purchase_date=date(2026, 2, 1), purchase_cost=50000)])
    db_session.commit()
    rows = {r["name"]: r for r in _get(client, "capital-allowances")["sections"][0]["rows"]}
    assert rows["Bus"]["year"] == 750000.0 and rows["Bus"]["twdv"] == 250000.0   # 50% initial + 25% annual
    assert rows["Books"]["year"] == 0.0


def test_sales_and_expense_reports_leave_out_non_trading_money(client, db_session):
    _tx(db_session, "income", 1000, "School Fees")
    _tx(db_session, "income", 9999, "Fund from Director")
    _tx(db_session, "expense", 400, "Telephone")
    _tx(db_session, "expense", 7777, "Loans")
    sales, exp = _get(client, "sales"), _get(client, "expenses")
    assert sales["summary"][0]["value"] == 1000.0 and sales["sections"][0]["rows"][0]["label"] == "School Fees"
    assert exp["summary"][0]["value"] == 400.0 and exp["sections"][1]["rows"][0]["label"] == "2026-08"


def test_withholding_and_vat_are_flagged_as_estimates(client, db_session):
    _tx(db_session, "expense", 100000, "Other Professional Fees", vendor="Acme Consulting")
    _tx(db_session, "income", 107500, "Stationery")
    wht, vat = _get(client, "withholding-tax"), _get(client, "vat")
    assert wht["estimate"] and wht["sections"][0]["rows"][0] == {"vendor": "Acme Consulting", "nature": "Professional / consultancy",
                                                                "category": "Other Professional Fees", "paid": 100000.0, "rate": 0.1, "tax": 10000.0}
    assert vat["estimate"] and vat["summary"][1]["value"] == 7500.0   # 107,500 incl. 7.5% VAT


def test_personal_income_tax_uses_directors_emoluments(client, db_session):
    _tx(db_session, "expense", 3000000, "Directors Emoluments")
    out = _get(client, "personal-income-tax")
    assert out["summary"][0]["value"] == 330000.0 and out["estimate"]   # 15% of 2.2M above the free 800k


def test_staff_reports_also_need_the_staff_permission():
    from fastapi.testclient import TestClient
    from main import app
    from models import Permission, Role, User
    from utils.auth import get_current_user
    role = Role(id=1, name="Tax only", is_system=False)
    role.permissions = [Permission(key="tax", label="tax")]
    user = User(id=1, email="t@example.com", hashed_password="x", full_name="T", is_active=True)
    user.role = role
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        tc = TestClient(app)
        assert tc.get("/financial-reports/sales", params=AS_AT).status_code == 200
        for slug in ("payroll-summary", "paye", "who-owes-you"):
            assert tc.get(f"/financial-reports/{slug}", params=AS_AT).status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_requires_the_tax_permission(anon_client):
    assert anon_client.get("/financial-reports/sales").status_code in (401, 403)
