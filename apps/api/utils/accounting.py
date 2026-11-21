"""Trial Balance, Profit & Loss and ledger computed from transactions.

Cash-basis double entry: every income/expense transaction posts one leg to the chart account its
category maps to and the other leg to the bank (CASH_CODE). A category with no mapping posts to a
visible UNMAPPED account instead of disappearing, so totals always tie back to the transactions.
Pure functions over plain values (amounts in integer kobo) so they are easy to test.
"""
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable, Optional

CASH_CODE = "1.2.4.1"                      # every bank account posts here for now
BF_CODE = "B/F"                            # opening cash + earlier profit, brought forward
UNMAPPED_INCOME = "UNMAPPED-INCOME"
UNMAPPED_EXPENSE = "UNMAPPED-EXPENSE"
PL_CATEGORIES = {"Income", "Expenses"}
PL_SECTIONS = [
    "Operating Revenue", "Cost of Sales", "Operating Expenses (OpEx)",
    "Non-Operating and Finance Income", "Finance Costs", "Tax Expenses",
]
_PSEUDO = {
    BF_CODE: ("Accumulated funds brought forward", "Equity"),
    UNMAPPED_INCOME: ("Unmapped income (choose an account)", "Income"),
    UNMAPPED_EXPENSE: ("Unmapped expenses (choose an account)", "Expenses"),
}


@dataclass(frozen=True)
class Account:
    code: str
    name: str
    category: str            # Assets | Liabilities | Equity | Income | Expenses
    statement_section: str
    normal_balance: str


@dataclass(frozen=True)
class Entry:
    id: int
    date: date
    type: str                # income | expense
    amount_cents: int
    category: str


def _money(cents: int) -> float:
    return round(cents / 100, 2)


def _meta(code: str, chart: dict[str, Account]) -> tuple[str, str]:
    """(name, category) for any account code, including the built-in pseudo accounts."""
    if code in _PSEUDO:
        return _PSEUDO[code]
    if code in chart:
        return chart[code].name, chart[code].category
    return ("Cash at bank", "Assets") if code == CASH_CODE else (code, "Assets")


def _is_pl(code: str, chart: dict[str, Account]) -> bool:
    return _meta(code, chart)[1] in PL_CATEGORIES


def _account_for(entry: Entry, mapping: dict[tuple[str, str], str], chart: dict[str, Account]) -> str:
    code = mapping.get((entry.category, entry.type))
    if code in chart:
        return code
    return UNMAPPED_INCOME if entry.type == "income" else UNMAPPED_EXPENSE


def post(entry: Entry, mapping: dict[tuple[str, str], str], chart: dict[str, Account]) -> tuple[str, str]:
    """(debit account, credit account) for one transaction."""
    code = _account_for(entry, mapping, chart)
    return (CASH_CODE, code) if entry.type == "income" else (code, CASH_CODE)


def _code_key(code: str) -> tuple:
    parts = code.split(".")
    return (0, tuple(int(p) for p in parts)) if all(p.isdigit() for p in parts) else (1, (code,))


def _unmapped_summary(entries: Iterable[Entry], mapping: dict, chart: dict) -> list[dict[str, Any]]:
    found: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
    for e in entries:
        if _account_for(e, mapping, chart) in (UNMAPPED_INCOME, UNMAPPED_EXPENSE):
            found[(e.category, e.type)][0] += 1
            found[(e.category, e.type)][1] += e.amount_cents
    return [{"category": c, "type": t, "count": n, "amount": _money(a)} for (c, t), (n, a) in sorted(found.items())]


def trial_balance(
    entries: list[Entry], mapping: dict, chart: dict[str, Account], opening_cash_cents: int, start: date, end: date,
) -> dict[str, Any]:
    """Balance-sheet accounts are cumulative up to `end`; profit & loss accounts cover only start..end.
    Cash starts from the banks' opening balances; the opening cash plus any profit earned before
    `start` is carried in B/F so the trial balance always balances."""
    balances: dict[str, int] = defaultdict(int)
    pl_before = 0
    for e in entries:
        if e.date > end:
            continue
        debit, credit = post(e, mapping, chart)
        for code, sign in ((debit, 1), (credit, -1)):
            if not _is_pl(code, chart):
                balances[code] += sign * e.amount_cents
            elif e.date >= start:
                balances[code] += sign * e.amount_cents
            else:
                pl_before += sign * e.amount_cents
    balances[CASH_CODE] += opening_cash_cents
    balances[BF_CODE] += pl_before - opening_cash_cents

    rows = []
    for code in sorted((c for c, b in balances.items() if b != 0), key=_code_key):
        name, category = _meta(code, chart)
        b = balances[code]
        rows.append({"code": code, "name": name, "category": category,
                     "debit": _money(b) if b > 0 else 0.0, "credit": _money(-b) if b < 0 else 0.0})
    total_debit = sum(b for b in balances.values() if b > 0)
    total_credit = -sum(b for b in balances.values() if b < 0)
    period = [e for e in entries if start <= e.date <= end]
    return {"rows": rows, "total_debit": _money(total_debit), "total_credit": _money(total_credit),
            "balanced": total_debit == total_credit, "unmapped": _unmapped_summary(period, mapping, chart)}


def profit_and_loss(entries: list[Entry], mapping: dict, chart: dict[str, Account], start: date, end: date) -> dict[str, Any]:
    period = [e for e in entries if start <= e.date <= end]
    amounts: dict[str, int] = defaultdict(int)       # positive = income earned / cost incurred
    for e in period:
        code = _account_for(e, mapping, chart)
        category = _meta(code, chart)[1]
        if category == "Income":
            amounts[code] += e.amount_cents if e.type == "income" else -e.amount_cents
        elif category == "Expenses":
            amounts[code] += e.amount_cents if e.type == "expense" else -e.amount_cents

    by_section: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for code, cents in amounts.items():
        if code not in _PSEUDO and cents != 0:
            by_section[chart[code].statement_section].append((code, cents))
    order = PL_SECTIONS + sorted(set(by_section) - set(PL_SECTIONS))
    sections, totals = [], {}
    for name in order:
        lines = sorted(by_section.get(name, []), key=lambda x: _code_key(x[0]))
        totals[name] = sum(c for _, c in lines)
        sections.append({"section": name, "total": _money(totals[name]),
                         "accounts": [{"code": c, "name": chart[c].name, "amount": _money(v)} for c, v in lines]})

    unmapped_income, unmapped_expense = amounts[UNMAPPED_INCOME], amounts[UNMAPPED_EXPENSE]
    income_total = sum(v for c, v in amounts.items() if _meta(c, chart)[1] == "Income")
    expense_total = sum(v for c, v in amounts.items() if _meta(c, chart)[1] == "Expenses")
    net = income_total - expense_total
    gross = totals["Operating Revenue"] - totals["Cost of Sales"]
    return {
        "sections": sections, "gross_profit": _money(gross),
        "operating_profit": _money(gross - totals["Operating Expenses (OpEx)"]),
        "profit_before_tax": _money(net + totals["Tax Expenses"]), "net_profit": _money(net),
        "unmapped_income": _money(unmapped_income), "unmapped_expense": _money(unmapped_expense),
        "unmapped": _unmapped_summary(period, mapping, chart),
    }


def ledger(entries: list[Entry], mapping: dict, chart: dict[str, Account], account_code: str, start: date, end: date) -> dict[str, Any]:
    """The transactions that post to one account in the period."""
    rows, total_debit, total_credit = [], 0, 0
    for e in sorted((e for e in entries if start <= e.date <= end), key=lambda e: (e.date, e.id)):
        debit, credit = post(e, mapping, chart)
        if account_code not in (debit, credit):
            continue
        is_debit = account_code == debit
        total_debit += e.amount_cents if is_debit else 0
        total_credit += 0 if is_debit else e.amount_cents
        rows.append({"id": e.id, "date": e.date.isoformat(), "type": e.type, "category": e.category,
                     "debit": _money(e.amount_cents) if is_debit else 0.0, "credit": 0.0 if is_debit else _money(e.amount_cents)})
    name, category = _meta(account_code, chart)
    return {"code": account_code, "name": name, "category": category, "rows": rows,
            "total_debit": _money(total_debit), "total_credit": _money(total_credit)}
