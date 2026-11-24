"""Data-derived reports for the Financial Reports hub. Each builder takes (db, start, end) and returns the
generic report dict the web page renders (see `report`). Everything is read from existing tables."""
from collections import defaultdict
from datetime import date

from sqlalchemy.orm import Session

from utils.account_suggestions import NON_TRADING
from models import Asset, AdvancePayment, PayrollEntry, SchoolLoan, StaffLoan, Transaction

MONEY, TEXT, DATE, PCT = "money", "text", "date", "pct"
AGE_BUCKETS = ((30, "0–30 days"), (60, "31–60 days"), (90, "61–90 days"), (10**9, "Over 90 days"))
# Money moving in or out that is not trading: left out of the sales and expense reports
NOT_SALES = {"Fund from Director", "Director's Loan", "Loans", *NON_TRADING}
NOT_EXPENSE = {"Loans", *NON_TRADING}


def col(key: str, label: str, kind: str = TEXT) -> dict:
    return {"key": key, "label": label, "kind": kind}


def section(title: str, columns: list[dict], rows: list[dict], total: dict | None = None, note: str | None = None) -> dict:
    return {"title": title, "columns": columns, "rows": rows, "total": total, "note": note}


def report(title: str, subtitle: str, summary: list[tuple[str, float | str, str]], sections: list[dict],
           estimate: bool = False, assumptions: list[str] | None = None, current_only: bool = False) -> dict:
    """summary = [(label, value, kind)]. `estimate` flags figures that rest on assumed rates or categories;
    `current_only` marks reports that show today's balances whatever date is chosen."""
    return {"title": title, "subtitle": subtitle, "estimate": estimate, "assumptions": assumptions or [], "current_only": current_only,
            "summary": [{"label": l, "value": v, "kind": k} for l, v, k in summary], "sections": sections}


def money(x: float) -> float:
    return round(x or 0.0, 2)


def _bucket(days: int) -> str:
    return next(label for limit, label in AGE_BUCKETS if days <= limit)


def _aging_summary(rows: list[dict]) -> list[tuple[str, float | str, str]]:
    totals = defaultdict(float)
    for r in rows:
        totals[r["age"]] += r["outstanding"]
    return [(label, money(totals[label]), MONEY) for _, label in AGE_BUCKETS]


# ── Who owes you / who you owe ───────────────────────────────────────────────

def who_owes_you(db: Session, start: date, end: date) -> dict:
    end = date.today()   # balances are today's: payments and recoveries are not dated history
    rows = []
    for loan in db.query(StaffLoan).filter(StaffLoan.is_active == True, StaffLoan.deduction_start <= end):  # noqa: E712
        paid = sum(p.amount_paid for p in loan.payments)
        if loan.loan_amount - paid > 0.005:
            rows.append({"name": loan.employee_name, "kind": "Staff loan", "since": loan.deduction_start.isoformat(),
                         "amount": money(loan.loan_amount), "paid": money(paid), "outstanding": money(loan.loan_amount - paid),
                         "age": _bucket((end - loan.deduction_start).days)})
    for adv in db.query(AdvancePayment).filter(AdvancePayment.is_recovered == False, AdvancePayment.date_issued <= end):  # noqa: E712
        if adv.remaining_amount > 0.005:
            rows.append({"name": adv.staff_member.full_name, "kind": "Salary advance (IOU)", "since": adv.date_issued.isoformat(),
                         "amount": money(adv.amount), "paid": money(adv.amount - adv.remaining_amount),
                         "outstanding": money(adv.remaining_amount), "age": _bucket((end - adv.date_issued).days)})
    rows.sort(key=lambda r: -r["outstanding"])
    total = money(sum(r["outstanding"] for r in rows))
    cols = [col("name", "Who"), col("kind", "What"), col("since", "Since", DATE), col("amount", "Amount", MONEY),
            col("paid", "Repaid", MONEY), col("outstanding", "Still owed", MONEY), col("age", "Age")]
    return report("Who Owes You", f"Money staff owe the school, balances as at today ({end})",
                  [("Total owed to you", total, MONEY), *_aging_summary(rows)], current_only=True, sections=
                  [section("Staff loans and salary advances", cols, rows, {"name": "Total", "outstanding": total},
                           "Fees owed by parents are not tracked in this app, so they do not appear here.")])


def who_you_owe(db: Session, start: date, end: date) -> dict:
    from routers.school_loans import _outstanding, _outstanding_interest, _total_paid   # the Loans page's own figures (today's balances)
    end = date.today()
    rows = []
    for loan in db.query(SchoolLoan).filter(SchoolLoan.is_active == True, SchoolLoan.collected_date <= end):  # noqa: E712
        principal, interest = _outstanding(loan), _outstanding_interest(loan)
        if principal + interest > 0.005:
            rows.append({"name": loan.lender_name, "kind": "Loan", "since": loan.collected_date.isoformat(),
                         "amount": money(loan.loan_amount), "paid": money(_total_paid(loan)), "principal": money(principal), "interest": money(interest), "outstanding": money(principal + interest),
                         "age": _bucket((end - loan.collected_date).days)})
    rows.sort(key=lambda r: -r["outstanding"])
    total = money(sum(r["outstanding"] for r in rows))
    cols = [col("name", "Who"), col("kind", "What"), col("since", "Since", DATE), col("amount", "Borrowed", MONEY),
            col("paid", "Already paid", MONEY), col("principal", "Principal", MONEY),
            col("interest", "Interest due", MONEY), col("outstanding", "Still owed", MONEY), col("age", "Age")]
    return report("Who You Owe", f"Loans the school still has to repay, balances as at today ({end})",
                  [("Total you owe", total, MONEY), *_aging_summary(rows)], current_only=True, sections=[
                      section("Loans", cols, rows, {"name": "Total", "outstanding": total},
                              "Money the director put in is treated as equity (see the Balance Sheet), not a loan. "
                              "Suppliers are not tracked: expenses are recorded when paid.")])


# ── Payroll summary ──────────────────────────────────────────────────────────

def payroll_summary(db: Session, start: date, end: date) -> dict:
    ym = lambda y, m: y * 12 + m
    entries = [e for e in db.query(PayrollEntry).filter(PayrollEntry.period_year.between(start.year, end.year)) if ym(start.year, start.month) <= ym(e.period_year, e.period_month) <= ym(end.year, end.month)]
    fields = ("gross_salary", "bonus", "loan_deduction", "advance_deduction", "other_deductions", "net_salary")

    def group(key) -> list[dict]:
        acc: dict = defaultdict(lambda: {f: 0.0 for f in fields} | {"staff": set(), "paid": 0.0})
        for e in entries:
            a = acc[key(e)]
            for f in fields:
                a[f] += getattr(e, f) or 0.0
            a["staff"].add(e.staff_id)
            a["paid"] += (e.net_salary or 0.0) if e.is_paid else 0.0
        return [{"label": k if isinstance(k, str) else k[1], **{f: money(v[f]) for f in fields}, "paid": money(v["paid"]), "staff": len(v["staff"])} for k, v in sorted(acc.items())]

    cols = [col("label", ""), col("staff", "Staff"), col("gross_salary", "Gross", MONEY), col("bonus", "Bonus", MONEY),
            col("loan_deduction", "Loan ded.", MONEY), col("advance_deduction", "IOU ded.", MONEY),
            col("other_deductions", "Other ded.", MONEY), col("net_salary", "Net pay", MONEY), col("paid", "Paid", MONEY)]
    by_month = group(lambda e: f"{e.period_year}-{e.period_month:02d}")
    by_staff = group(lambda e: (e.staff_id, e.staff_member.full_name))   # by id: two staff may share a name
    tot = {"label": "Total", **{f: money(sum(getattr(e, f) or 0 for e in entries)) for f in fields},
           "paid": money(sum(e.net_salary for e in entries if e.is_paid))}
    return report("Payroll Summary", f"What you paid your staff and what was deducted, {start} to {end}",
                  [("Gross pay", tot["gross_salary"], MONEY), ("Bonuses", tot["bonus"], MONEY),
                   ("Deductions", money(tot["loan_deduction"] + tot["advance_deduction"] + tot["other_deductions"]), MONEY),
                   ("Net pay", tot["net_salary"], MONEY), ("Paid so far", tot["paid"], MONEY)],
                  [section("By month", cols, by_month, tot), section("By staff member", cols, by_staff, tot)])


# ── Capital allowances ───────────────────────────────────────────────────────

# (initial, annual) rates by asset category: assumed from the CITA Second Schedule; edit here if your accountant differs
ALLOWANCE_RATES = {"Land & Buildings": (0.15, 0.10), "Motor Vehicles": (0.50, 0.25), "Furniture & Fittings": (0.25, 0.20),
                   "Plant & Equipment": (0.50, 0.25), "Computer Equipment": (0.50, 0.25)}


def _allowances(asset: Asset, year: int) -> tuple[float, float]:
    """(claimed in earlier years, claimed in `year`) for one asset. Whole-year claims, capped at cost."""
    initial, annual = ALLOWANCE_RATES.get(asset.category, (0.0, 0.0))
    earlier = this = 0.0
    for y in range(asset.purchase_date.year, year + 1):
        want = asset.purchase_cost * annual + (asset.purchase_cost * initial if y == asset.purchase_date.year else 0.0)
        got = max(0.0, min(want, asset.purchase_cost - earlier - this))
        if y == year:
            this = got
        else:
            earlier += got
    return earlier, this


def capital_allowances(db: Session, start: date, end: date) -> dict:
    rows = []
    for a in db.query(Asset).filter(Asset.purchase_date <= end).order_by(Asset.purchase_date):
        earlier, this = _allowances(a, end.year)
        rows.append({"name": a.name, "category": a.category, "bought": a.purchase_date.isoformat(), "cost": money(a.purchase_cost),
                     "earlier": money(earlier), "year": money(this), "twdv": money(a.purchase_cost - earlier - this),
                     "claimable": a.category in ALLOWANCE_RATES})
    cols = [col("name", "Asset"), col("category", "Category"), col("bought", "Bought", DATE), col("cost", "Cost", MONEY),
            col("earlier", "Claimed before", MONEY), col("year", f"Allowance {end.year}", MONEY), col("twdv", "Tax written-down value", MONEY)]
    tot = {"name": "Total", **{k: money(sum(r[k] for r in rows)) for k in ("cost", "earlier", "year", "twdv")}}
    rates = [f"{c}: {i:.0%} initial + {a:.0%} annual" for c, (i, a) in ALLOWANCE_RATES.items()]
    return report("Capital Allowances", f"The tax relief on equipment and property, {end.year}",
                  [("Allowance for the year", tot["year"], MONEY), ("Claimed in earlier years", tot["earlier"], MONEY), ("Tax written-down value", tot["twdv"], MONEY)],
                  [section("By asset", cols, rows, tot)], estimate=True,
                  assumptions=[*rates, "Whole years only (no part-year proration). Categories with no rate (library books, intangibles, other) claim nothing.",
                               "Confirm the rates with your tax adviser before filing."])


# ── Sales and expense reports ────────────────────────────────────────────────

def _trading_report(db: Session, start: date, end: date, kind: str) -> dict:
    from routers.accounting import _entries   # same income/expense direction rule as the Profit & Loss
    skip = NOT_SALES if kind == "income" else NOT_EXPENSE
    es = [e for e in _entries(db, end) if e.type == kind and e.date >= start and e.category not in skip]
    total = sum(e.amount_cents for e in es) / 100

    def group(key) -> list[dict]:
        acc = defaultdict(lambda: [0, 0])
        for e in es:
            acc[key(e)][0] += 1
            acc[key(e)][1] += e.amount_cents
        return [{"label": k, "count": n, "amount": money(c / 100), "share": (c / 100 / total) if total else 0.0}
                for k, (n, c) in sorted(acc.items(), key=lambda kv: -kv[1][1])]

    by_month = sorted(group(lambda e: e.date.strftime("%Y-%m")), key=lambda r: r["label"])
    cols = [col("label", ""), col("count", "Transactions"), col("amount", "Amount", MONEY), col("share", "Share", PCT)]
    tot = {"label": "Total", "count": len(es), "amount": money(total), "share": 1.0 if es else 0.0}
    name, thing = ("Sales Report", "What you sold") if kind == "income" else ("Expense Report", "Everything you spent")
    top = group(lambda e: e.category)
    return report(name, f"{thing}, {start} to {end} (cash basis)",
                  [("Total", money(total), MONEY), ("Transactions", len(es), TEXT),
                   ("Biggest category", top[0]["label"] if top else "—", TEXT)],
                  [section("By category", cols, top, tot), section("By month", cols, by_month, tot)])


def sales_report(db: Session, start: date, end: date) -> dict:
    return _trading_report(db, start, end, "income")


def expense_report(db: Session, start: date, end: date) -> dict:
    return _trading_report(db, start, end, "expense")
