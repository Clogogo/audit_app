"""Trial Balance, Profit & Loss and ledger computed from transactions (cash basis, double entry)."""
from datetime import date

from utils.accounting import (
    BF_CODE, CASH_CODE, UNMAPPED_EXPENSE, UNMAPPED_INCOME, Account, Entry, ledger, post, profit_and_loss, trial_balance,
)


def A(code, name, category, section, normal):
    return Account(code, name, category, section, normal)


CHART = {a.code: a for a in [
    A("4.1.1.3.2", "Tuition & School Fees", "Income", "Operating Revenue", "Credit"),
    A("4.2.2.9", "Sundry Income", "Income", "Non-Operating and Finance Income", "Credit"),
    A("5.1.1.1.2", "Learning Materials", "Expenses", "Cost of Sales", "Debit"),
    A("5.2.1.1.2", "Teaching Staff Costs", "Expenses", "Operating Expenses (OpEx)", "Debit"),
    A("5.3.2.1", "Bank Charges", "Expenses", "Finance Costs", "Debit"),
    A("5.4.1.4", "Minimum Tax", "Expenses", "Tax Expenses", "Debit"),
    A("1.1.1.12", "Capital Work-in-Progress", "Assets", "Non-Current Assets", "Debit"),
    A("2.2.7.3", "Director Current Account", "Liabilities", "Current Liabilities", "Credit"),
    A("1.2.4.1", "Operating Bank Accounts", "Assets", "Current Assets", "Debit"),
]}
MAP = {
    ("School Fees", "income"): "4.1.1.3.2", ("Salary and Wages", "expense"): "5.2.1.1.2", ("Books", "expense"): "5.1.1.1.2",
    ("Bank Charges", "expense"): "5.3.2.1", ("Capital Project", "expense"): "1.1.1.12", ("Loans", "income"): "2.2.7.3",
    ("Refund", "income"): "4.2.2.9",
}


def E(i, day, type_, amount, category):
    return Entry(i, date.fromisoformat(day), type_, round(amount * 100), category)


def test_posting_rules_debit_the_account_for_expenses_and_the_bank_for_income():
    assert post(E(1, "2026-08-01", "expense", 10, "Salary and Wages"), MAP, CHART) == ("5.2.1.1.2", CASH_CODE)
    assert post(E(2, "2026-08-01", "income", 10, "School Fees"), MAP, CHART) == (CASH_CODE, "4.1.1.3.2")
    assert post(E(3, "2026-08-01", "expense", 10, "Mystery"), MAP, CHART) == (UNMAPPED_EXPENSE, CASH_CODE)
    assert post(E(4, "2026-08-01", "income", 10, "Mystery"), MAP, CHART) == (CASH_CODE, UNMAPPED_INCOME)


def test_profit_and_loss_groups_by_statement_section_and_computes_the_subtotals():
    entries = [
        E(1, "2026-08-02", "income", 1000, "School Fees"), E(2, "2026-08-03", "income", 50, "Refund"),
        E(3, "2026-08-04", "expense", 200, "Books"), E(4, "2026-08-05", "expense", 400, "Salary and Wages"),
        E(5, "2026-08-06", "expense", 100, "Bank Charges"),
    ]
    pl = profit_and_loss(entries, MAP, CHART, date(2026, 8, 1), date(2026, 8, 31))
    sections = {s["section"]: s for s in pl["sections"]}
    assert sections["Operating Revenue"]["total"] == 1000.0 and sections["Cost of Sales"]["total"] == 200.0
    assert sections["Operating Expenses (OpEx)"]["accounts"] == [{"code": "5.2.1.1.2", "name": "Teaching Staff Costs", "amount": 400.0}]
    assert pl["gross_profit"] == 800.0 and pl["operating_profit"] == 400.0
    assert pl["profit_before_tax"] == 400.0 + 50.0 - 100.0 and pl["net_profit"] == 350.0


def test_profit_and_loss_only_counts_the_period_and_ignores_balance_sheet_postings():
    entries = [
        E(1, "2026-07-31", "income", 999, "School Fees"), E(2, "2026-08-10", "income", 100, "School Fees"),
        E(3, "2026-09-01", "income", 999, "School Fees"),
        E(4, "2026-08-11", "expense", 500, "Capital Project"), E(5, "2026-08-12", "income", 700, "Loans"),
    ]
    pl = profit_and_loss(entries, MAP, CHART, date(2026, 8, 1), date(2026, 8, 31))
    assert pl["net_profit"] == 100.0                       # capex and a loan are not profit or loss


def test_a_refund_in_the_opposite_direction_reduces_the_account():
    entries = [E(1, "2026-08-02", "income", 1000, "School Fees"), E(2, "2026-08-03", "expense", 150, "School Fees"),
               E(3, "2026-08-04", "expense", 300, "Salary and Wages"), E(4, "2026-08-05", "income", 40, "Salary and Wages")]
    pl = profit_and_loss(entries, {**MAP, ("School Fees", "expense"): "4.1.1.3.2", ("Salary and Wages", "income"): "5.2.1.1.2"},
                         CHART, date(2026, 8, 1), date(2026, 8, 31))
    sections = {s["section"]: s["total"] for s in pl["sections"]}
    assert sections["Operating Revenue"] == 850.0 and sections["Operating Expenses (OpEx)"] == 260.0


def test_unmapped_transactions_stay_visible_and_are_included_in_the_result():
    entries = [E(1, "2026-08-02", "income", 100, "School Fees"), E(2, "2026-08-03", "income", 30, "Mystery"),
               E(3, "2026-08-04", "expense", 20, "Other"), E(4, "2026-08-05", "expense", 5, "Other")]
    pl = profit_and_loss(entries, MAP, CHART, date(2026, 8, 1), date(2026, 8, 31))
    assert pl["unmapped_income"] == 30.0 and pl["unmapped_expense"] == 25.0
    assert pl["net_profit"] == 100.0 + 30.0 - 25.0
    assert pl["unmapped"] == [{"category": "Mystery", "type": "income", "count": 1, "amount": 30.0},
                              {"category": "Other", "type": "expense", "count": 2, "amount": 25.0}]


def _tb(entries, opening=0.0, start=date(2026, 8, 1), end=date(2026, 8, 31)):
    return trial_balance(entries, MAP, CHART, round(opening * 100), start, end)


def test_trial_balance_balances_and_shows_cash_closing_balance():
    tb = _tb([E(1, "2026-08-02", "income", 1000, "School Fees"), E(2, "2026-08-03", "expense", 400, "Salary and Wages"),
              E(3, "2026-08-04", "expense", 300, "Capital Project"), E(4, "2026-08-05", "income", 500, "Loans")], opening=200)
    rows = {r["code"]: r for r in tb["rows"]}
    assert tb["balanced"] is True and tb["total_debit"] == tb["total_credit"]
    assert rows[CASH_CODE]["debit"] == 200 + 1000 - 400 - 300 + 500            # 1000
    assert rows["1.1.1.12"]["debit"] == 300.0 and rows["2.2.7.3"]["credit"] == 500.0
    assert rows["4.1.1.3.2"]["credit"] == 1000.0 and rows["5.2.1.1.2"]["debit"] == 400.0
    assert rows[BF_CODE]["credit"] == 200.0                                      # opening cash brought forward


def test_trial_balance_carries_earlier_profit_into_brought_forward_and_keeps_balance_sheet_cumulative():
    tb = _tb([E(1, "2026-06-01", "income", 600, "School Fees"), E(2, "2026-06-02", "expense", 100, "Salary and Wages"),
              E(3, "2026-06-03", "expense", 300, "Capital Project"),
              E(4, "2026-08-10", "income", 50, "School Fees")], opening=100)
    rows = {r["code"]: r for r in tb["rows"]}
    assert tb["balanced"] is True
    assert "5.2.1.1.2" not in rows and rows["4.1.1.3.2"]["credit"] == 50.0       # earlier P&L is not in this period
    assert rows["1.1.1.12"]["debit"] == 300.0                                    # but the asset is still there
    assert rows[CASH_CODE]["debit"] == 100 + 600 - 100 - 300 + 50
    assert rows[BF_CODE]["credit"] == 100 + 600 - 100                            # opening cash + earlier profit


def test_trial_balance_ignores_transactions_after_the_end_date_and_flags_unmapped():
    tb = _tb([E(1, "2026-08-02", "income", 100, "School Fees"), E(2, "2026-09-02", "income", 900, "School Fees"),
              E(3, "2026-08-03", "expense", 25, "Mystery")])
    rows = {r["code"]: r for r in tb["rows"]}
    assert rows[CASH_CODE]["debit"] == 75.0 and rows[UNMAPPED_EXPENSE]["debit"] == 25.0 and tb["balanced"] is True
    assert tb["unmapped"] == [{"category": "Mystery", "type": "expense", "count": 1, "amount": 25.0}]


def test_ledger_lists_the_transactions_behind_an_account_line():
    entries = [E(1, "2026-08-02", "income", 100, "School Fees"), E(2, "2026-08-03", "expense", 40, "Salary and Wages"),
               E(3, "2026-07-03", "income", 5, "School Fees")]
    fees = ledger(entries, MAP, CHART, "4.1.1.3.2", date(2026, 8, 1), date(2026, 8, 31))
    assert [(r["id"], r["debit"], r["credit"]) for r in fees["rows"]] == [(1, 0.0, 100.0)]
    cash = ledger(entries, MAP, CHART, CASH_CODE, date(2026, 8, 1), date(2026, 8, 31))
    assert [(r["id"], r["debit"], r["credit"]) for r in cash["rows"]] == [(1, 100.0, 0.0), (2, 0.0, 40.0)]
    assert cash["total_debit"] == 100.0 and cash["total_credit"] == 40.0
