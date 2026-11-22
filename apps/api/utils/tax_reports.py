"""Tax reports for the Financial Reports hub. The app does not record VAT, PAYE or withholding tax on each
transaction, so these are ESTIMATES worked out from payroll and from transaction categories with the assumed
rates below. Change the constants (or confirm them with a tax adviser) before filing anything."""
from collections import defaultdict
from datetime import date

from sqlalchemy.orm import Session

from models import PayrollEntry, Transaction
from utils.report_builders import MONEY, TEXT, col, money, report, section

# Annual personal income tax bands (width, rate), applied to gross pay. No reliefs: pension, NHF and rent relief are not recorded.
PIT_BANDS = ((800_000, 0.0), (2_200_000, 0.15), (9_000_000, 0.18), (13_000_000, 0.21), (25_000_000, 0.23), (float("inf"), 0.25))
VAT_RATE = 0.075
# Education supplies (school fees, exams, books) are VAT-exempt, so only these income categories carry output VAT
VAT_OUTPUT_CATEGORIES = {"Stationery", "Uniform", "Software", "Business", "Freelance"}
VAT_INPUT_CATEGORIES = {"Electricity & Power", "Utilities", "Telephone", "Internet Cost", "Fuel Expenses", "Generator Expenses",
                        "Repairs and Maintenance", "Stationeries Expenses", "Stationery", "Other Professional Fees", "Audit Fees",
                        "Security Expenses", "Cleaning & Janitorial Services", "Advertisement & Promotion", "Software Maintenance",
                        "Website Design & Maintenance"}
WHT = {**{c: ("Professional / consultancy", 0.10) for c in ("Other Professional Fees", "Audit Fees", "Freelance", "Research Cost", "Outsourcing Services Expenses")},
       "Rent & Rates": ("Rent", 0.10), "Royalties": ("Royalties", 0.10),
       **{c: ("Contracts and services", 0.05) for c in ("Repairs and Maintenance", "Security Expenses", "Cleaning & Janitorial Services",
                                                        "Generator Expenses", "Software Maintenance", "Website Design & Maintenance",
                                                        "Advertisement & Promotion", "Freight & Transport Expenses")}}


def pit(annual: float) -> float:
    tax, left = 0.0, max(annual, 0.0)
    for width, rate in PIT_BANDS:
        taken = min(left, width)
        tax += taken * rate
        left -= taken
        if left <= 0:
            break
    return tax


def _expenses(db: Session, start: date, end: date, cats) -> list[Transaction]:
    return db.query(Transaction).filter(Transaction.type == "expense", Transaction.category.in_(list(cats)),
                                        Transaction.date >= start, Transaction.date <= end).all()


def _by_category(db: Session, start: date, end: date, kind: str, cats) -> dict[str, float]:
    from routers.accounting import _entries
    acc: dict[str, float] = defaultdict(float)
    for e in _entries(db, end):
        if e.type == kind and e.date >= start and e.category in cats:
            acc[e.category] += e.amount_cents / 100
    return acc


def paye_return(db: Session, start: date, end: date) -> dict:
    ym = lambda y, m: y * 12 + m
    acc: dict = defaultdict(lambda: {"months": 0, "gross": 0.0, "tax": 0.0})
    for e in db.query(PayrollEntry):
        if ym(start.year, start.month) <= ym(e.period_year, e.period_month) <= ym(end.year, end.month):
            salary, bonus = (e.gross_salary or 0.0) * 12, e.bonus or 0.0
            a = acc[(e.staff_id, e.staff_member.full_name)]
            a["months"] += 1
            a["gross"] += (e.gross_salary or 0.0) + bonus
            # salary taxed as one twelfth of the annual figure; a one-off bonus is taxed on top at the rate it reaches
            a["tax"] += pit(salary) / 12 + (pit(salary + bonus) - pit(salary))
    rows = [{"name": n[1], "months": v["months"], "gross": money(v["gross"]), "tax": money(v["tax"])} for n, v in sorted(acc.items())]
    total = {"name": "Total", "gross": money(sum(r["gross"] for r in rows)), "tax": money(sum(r["tax"] for r in rows))}
    return report("PAYE Return", f"Tax to remit on your staff's pay, {start} to {end}",
                  [("Estimated PAYE", total["tax"], MONEY), ("Gross pay", total["gross"], MONEY), ("Staff", len(rows), TEXT)],
                  [section("By staff member", [col("name", "Staff"), col("months", "Months"), col("gross", "Gross pay", MONEY), col("tax", "Estimated PAYE", MONEY)], rows, total)],
                  estimate=True,
                  assumptions=["Payroll does not record PAYE, so it is estimated from gross pay plus bonus.",
                               "Bands: first ₦800,000 a year at 0%, then 15%, 18%, 21%, 23% and 25% above ₦50M.",
                               "No reliefs (pension, NHF, rent) are applied, so this is likely to be on the high side."])


def withholding_tax(db: Session, start: date, end: date) -> dict:
    acc: dict = defaultdict(float)
    for t in _expenses(db, start, end, WHT):
        acc[(t.vendor or "(no vendor)", t.category)] += t.amount
    rows = [{"vendor": v, "nature": WHT[c][0], "category": c, "paid": money(a), "rate": WHT[c][1], "tax": money(a * WHT[c][1])}
            for (v, c), a in sorted(acc.items(), key=lambda kv: -kv[1])]
    total = {"vendor": "Total", "paid": money(sum(r["paid"] for r in rows)), "tax": money(sum(r["tax"] for r in rows))}
    cols = [col("vendor", "Paid to"), col("nature", "Nature"), col("category", "Category"), col("paid", "Paid", MONEY),
            col("rate", "Rate", "pct"), col("tax", "WHT to deduct", MONEY)]
    return report("Withholding Tax", f"Tax you should have held back when paying suppliers, {start} to {end}",
                  [("WHT to deduct", total["tax"], MONEY), ("Payments covered", total["paid"], MONEY)],
                  [section("Payments subject to withholding", cols, rows, total)], estimate=True,
                  assumptions=["The app does not record whether tax was actually withheld: this is what the payments imply.",
                               "Rates are assumed by category (10% professional fees, rent and royalties; 5% contracts and services)."])


def vat_return(db: Session, start: date, end: date) -> dict:
    out = _by_category(db, start, end, "income", VAT_OUTPUT_CATEGORIES)
    inp = _by_category(db, start, end, "expense", VAT_INPUT_CATEGORIES)
    vat = lambda gross: gross * VAT_RATE / (1 + VAT_RATE)   # amounts are treated as VAT-inclusive
    rows = [{"side": "Output VAT (sales)", "category": c, "amount": money(a), "vat": money(vat(a))} for c, a in sorted(out.items())] + \
           [{"side": "Input VAT (purchases)", "category": c, "amount": money(a), "vat": money(vat(a))} for c, a in sorted(inp.items())]
    output_vat, input_vat = money(vat(sum(out.values()))), money(vat(sum(inp.values())))
    cols = [col("side", ""), col("category", "Category"), col("amount", "Amount", MONEY), col("vat", "VAT", MONEY)]
    return report("VAT Return", f"The VAT you owe or can claim back, {start} to {end}",
                  [("Net VAT payable", money(output_vat - input_vat), MONEY), ("Output VAT", output_vat, MONEY), ("Input VAT", input_vat, MONEY)],
                  [section("VAT by category", cols, rows, {"side": "Net payable", "vat": money(output_vat - input_vat)})], estimate=True,
                  assumptions=["VAT is not recorded per transaction: amounts are treated as VAT-inclusive at 7.5% for the categories listed.",
                               "School fees, exams and books are treated as VAT-exempt (education), so they carry no output VAT.",
                               "Input VAT is only recoverable against taxable sales, and most of your income is exempt: do not treat a negative net figure as a refund without advice."])


def personal_income_tax(db: Session, start: date, end: date) -> dict:
    per_year: dict[int, float] = defaultdict(float)
    for t in _expenses(db, start, end, ["Directors Emoluments"]):
        per_year[t.date.year] += t.amount
    paid = sum(per_year.values())
    tax = sum(pit(amount) for amount in per_year.values())   # each calendar year has its own bands
    return report("Personal Income Tax", f"Tax on directors' pay, {start} to {end}",
                  [("Estimated tax", money(tax), MONEY), ("Directors' emoluments paid", money(paid), MONEY)],
                  [section("Directors' emoluments", [col("item", ""), col("amount", "Amount", MONEY)],
                           [{"item": "Emoluments paid in the period", "amount": money(paid)}, {"item": "Estimated personal income tax", "amount": money(tax)}])],
                  estimate=True,
                  assumptions=["The school pays company income tax (CIT). Personal income tax applies to individuals: staff pay is in the PAYE Return.",
                               "Directors' emoluments are treated as one person's income, taxed one calendar year at a time with the same bands and no reliefs as PAYE (a part-year range still gets the full-year free band)."])
