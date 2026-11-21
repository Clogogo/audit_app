"""Suggested Chart of Accounts account for each transaction category.

A suggestion is only a starting point: the user reviews and can change every mapping.
Direction matters ("Books" bought is a cost, "Books" sold is revenue), so there is one table per
direction; a category missing from one direction falls back to the other (a refund posts back to
the same account). "Other" is deliberately never guessed.
"""
import time

# Money coming in (income transactions)
INCOME = {
    "School Fees": "4.1.1.3.2", "Exam": "4.1.1.3.3", "Stationery": "4.1.1.1", "Books": "4.1.1.1", "Uniform": "4.1.1.1",
    "Software": "4.1.1.4", "Business": "4.1.1.1", "Freelance": "4.1.1.3.1", "Investment": "4.2.1.1",
    "Gift": "4.2.2.9", "Refund": "4.2.2.9", "Other": "4.2.2.9",
    "Loans": "2.2.7.3", "Fund from Director": "2.2.7.3", "Director's Loan": "2.1.1.4",
    "Internal Transfer": "1.2.5.5",
}

# Money going out (expense transactions)
EXPENSE = {
    # people
    "Salary and Wages": "5.2.1.1.2", "Staff Allowances": "5.2.1.1.1", "IOU (Advance Salary)": "1.2.2.5",
    "Employee Benefit Expenses": "5.2.1.5", "Other Staff & Related Cost": "5.2.1.5", "Medical Expenses": "5.2.1.5",
    "Directors Emoluments": "5.2.1.8", "Directors Expenses": "5.2.1.8", "Pension and Gratuity": "5.2.1.2",
    "Staff Gratuity": "5.2.1.10", "Training and Development": "5.2.1.7",
    "Staff Loan Written Off": "5.2.6.2", "Bad Debt Written Off": "5.2.6.2",
    # premises and running costs
    "Rent & Rates": "5.2.2.1", "Rates": "5.2.2.1", "Electricity & Power": "5.2.2.3", "Utilities": "5.2.2.3",
    "Fuel Expenses": "5.2.2.2", "AGO-Diesel": "5.2.2.2", "PMS": "5.2.2.2", "Generator Expenses": "5.2.2.5",
    "Repairs and Maintenance": "5.2.2.5", "Security Expenses": "5.2.2.4", "Cleaning & Janitorial Services": "5.2.2.4",
    # administration
    "Other Professional Fees": "5.2.3.1", "Outsourcing Services Expenses": "5.2.3.1", "Royalties": "5.2.3.1", "Freelance": "5.2.3.1",
    "Audit Fees": "5.2.3.2", "Software Maintenance": "5.2.3.3", "Website Design & Maintenance": "5.2.3.3", "Software": "5.2.3.3",
    "Stationeries Expenses": "5.2.3.4", "Stationery": "5.2.3.4", "Head Office Cost": "5.2.3.4", "Postages": "5.2.3.4",
    "Government and Regulatory Costs": "5.2.3.5", "AMCON Charges": "5.2.3.5", "Fines": "5.2.3.5", "Penalties": "5.2.3.5",
    "Other Statutory Charges & Levies": "5.2.3.5", "Licences & Leases Charges": "5.2.3.5", "Permits": "5.2.3.5", "Exam": "5.2.3.5",
    "Internet Cost": "5.2.3.9", "Telephone": "5.2.3.9", "Research Cost": "5.2.3.10",
    "Subscription & Dues": "5.2.3.11", "Newspaper & Periodicals": "5.2.3.11",
    "Donations": "5.2.3.12", "Corporate Social Responsibilities": "5.2.3.12", "Gift": "5.2.3.12",
    "Health, Safety and Environmental Expenses": "5.2.3.13",
    # selling, travel, hospitality
    "Advertisement & Promotion": "5.2.4.1", "Corporate Promotion": "5.2.4.1", "Public Relation": "5.2.4.1",
    "Publication Cost": "5.2.4.1", "Trade Fairs & Exhibitions": "5.2.4.1", "Sponsorship": "5.2.4.1",
    "Selling & Distribution Expenses": "5.2.4.2", "Freight & Transport Expenses": "5.2.4.3", "Transport of Supplies": "5.2.4.3",
    "Travel Expenses": "5.2.4.4", "Rooms/Accommodation Cost": "5.2.4.4", "Entertainment Expenses": "5.2.4.5",
    # direct costs, depreciation, finance
    "Books": "5.1.1.1.2", "Uniform": "5.1.1.1.2",
    "Depreciation": "5.2.5.1", "Amortisation of Intangible Assets": "5.2.5.3",
    "Interest Expense": "5.3.1.1", "Bank Charges": "5.3.2.1", "Service Charge": "5.3.2.1", "Realized Foreign Exchange Loss": "5.3.3.1",
    # balance sheet items
    "Capital Project": "1.1.1.12", "Investment": "1.1.5.1", "Internal Transfer": "1.2.5.5",
}

# Categories that must never fall back to the other direction's account
DIRECT_ONLY = {"Other", "Business"}


def suggest_account(category: str, tx_type: str) -> str | None:
    first, second = (INCOME, EXPENSE) if tx_type == "income" else (EXPENSE, INCOME)
    if category in first:
        return first[category]
    return None if category in DIRECT_ONLY else second.get(category)


def all_suggested_codes() -> set[str]:
    return set(INCOME.values()) | set(EXPENSE.values())


def ai_suggest_accounts(rows: list[tuple[str, str]], accounts: dict[str, list[tuple[str, str]]]) -> dict[tuple[str, str], str]:
    """Ask the AI (OpenRouter) which account each (category, type) belongs to.
    `accounts` = {"income": [(code, name)...], "expense": [...]}. Only codes from that list are accepted;
    anything else the model returns is dropped. Returns {} when the AI is unavailable."""
    out: dict[tuple[str, str], str] = {}
    deadline = time.monotonic() + AI_BUDGET_SECONDS
    for start in range(0, len(rows), AI_BATCH):  # small batches: the model's reply is capped, one failed batch loses only itself
        if time.monotonic() > deadline:
            break   # stop starting batches; what is mapped so far is kept, the rest can be done with another click
        out.update(_ai_batch(rows[start:start + AI_BATCH], accounts, deadline))
    return out


AI_BATCH = 20
AI_TRIES = 2
AI_BUDGET_SECONDS = 240   # under the browser's 300s timeout, so a slow free model can't leave work running after the page gave up
AI_MAX_TOKENS = 4000   # the prompt lists ~90 accounts; free reasoning models spend a lot of the budget thinking


def _ai_batch(rows: list[tuple[str, str]], accounts: dict[str, list[tuple[str, str]]], deadline: float) -> dict[tuple[str, str], str]:
    import json
    import re

    import ai_worker

    items = [{"i": i, "category": c, "type": t} for i, (c, t) in enumerate(rows)]
    prompt = (
        "You map a Nigerian school's transaction categories to its chart of accounts.\n"
        "For each item choose ONE account code from the list for its type (income items -> income accounts, "
        "expense items -> expense accounts). Use the code exactly as written. If nothing fits, use null.\n\n"
        "Income accounts:\n" + "\n".join(f"{c} {n}" for c, n in accounts["income"]) + "\n\n"
        "Expense accounts:\n" + "\n".join(f"{c} {n}" for c, n in accounts["expense"]) + "\n\n"
        "Items:\n" + json.dumps(items, ensure_ascii=False) + "\n\n"
        'Return ONLY a JSON array: [{"i": <index>, "code": "<account code or null>"}]'
    )
    answers: list = []
    for _ in range(AI_TRIES):
        if time.monotonic() > deadline:
            break
        # the free router lands on a different model each call; some return nothing
        match = re.search(r"\[[\s\S]*\]", ai_worker._clean_json(ai_worker.call_ai_text(prompt, AI_MAX_TOKENS)))
        try:
            answers = json.loads(match.group()) if match else []
        except ValueError:
            answers = []
        if isinstance(answers, list) and answers:
            break
    allowed = {t: {c for c, _ in accounts[t]} for t in accounts}
    out: dict[tuple[str, str], str] = {}
    for a in answers if isinstance(answers, list) else []:
        try:
            category, tx_type = rows[int(a["i"])]
        except (KeyError, TypeError, ValueError, IndexError):
            continue
        code = str(a.get("code") or "").split(" ")[0]   # some models answer "4.1.1.3.2 Tuition & School Fees"
        if code in allowed[tx_type]:
            out[(category, tx_type)] = code
    return out
