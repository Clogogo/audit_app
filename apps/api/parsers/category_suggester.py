"""
Category and Type Suggestion
Smart categorization using keyword rules and AI fallback for Nigerian bank statements.
"""
import json
import logging
import re
from typing import List, Tuple

logger = logging.getLogger(__name__)

# ── Keyword Patterns ──────────────────────────────────────────────────────────

TRANSFER_KEYWORDS = [
    "auto-save to owealth", "auto save to owealth",
    "owealth withdrawal", "owealth balance",
    "own account transfer", "own-account transfer",
    "own account",  # catches "Transfer to X - own account" style descriptions
    "inter-account", "internal transfer", "self transfer",
    "wallet to wallet", "wallet transfer",
]

# (category, forced_type) pairs — checked first for income-only categories
INCOME_KEYWORD_MAP: List[Tuple[str, List[str]]] = [
    ("Salary",     ["salary", "salaries", "payroll", "monthly pay", "remuneration",
                    "staff pay", "wages", "pay day",
                    "(salary)", "(january", "(february", "(march", "(april",
                    "(may", "(june", "(july", "(august", "(september",
                    "(october", "(november", "(december"]),
    ("Investment", ["interest earn", "owealth interest", "investment income", "dividend",
                    "fixed deposit return", "savings interest", "interest credit",
                    "treasury", "lien release", "yield"]),
    ("Freelance",  ["freelance", "upwork", "fiverr", "gig income", "contract pay"]),
    ("Gift",       ["gift received", "cash gift"]),
    ("Refund",     ["refund", "reversal", "chargeback", "return credit",
                    "clawback reversal"]),
    ("Business",   ["sales proceed", "business income", "revenue credit"]),
    ("School Fees", ["transfer from", "trf from", "trf frm", "trfr from", "tfr from",
                    "received from", "rcv from", "rcvd from",
                    "payment from", "pmt from", "funds from",
                    "nip from", "neft from", "credit from", "lodgment from"]),
    ("Loans",      ["loan received", "loan credit", "loan disbursement",
                    "credit facility", "overdraft credit"]),
]

# Expense/neutral categories (type follows the bank direction — debit=expense, credit=income)
NEUTRAL_KEYWORD_MAP: List[Tuple[str, List[str]]] = [
    ("Food & Dining",       ["restaurant", "eatery", "kitchen", "bakery", "pastry",
                              "fast food", "pizza", "burger", "shawarma", "suya",
                              "indomie", "groceries", "supermarket", "shoprite", "spar",
                              "kfc", "chicken republic", "mr biggs", "domino", "cafe",
                              "coldstone", "ice cream", "food", "canteen", "cafeteria"]),
    ("Transportation",      ["uber", "bolt", "taxify", "transport", "bus fare",
                              "fare", "petrol", "diesel", "fuel station", "car wash",
                              "parking", "toll gate", "logistics", "dispatch", "ride"]),
    ("Shopping",            ["jumia", "konga", "amazon", "aliexpress", "shopping",
                              "purchase", "market", "store", "mall", "clothes",
                              "fashion", "shoes", "bag", "accessories"]),
    ("Bills & Utilities",   ["electricity", "nepa", "phcn", "electric bill",
                              "water bill", "water rate", "dstv", "startimes", "gotv",
                              "cable tv", "internet", "broadband", "wifi", "wi-fi",
                              "airtime", "data subscription", "data purchase",
                              "recharge", "postpaid", "prepaid", "utility", "gas bill",
                              "power bill", "mtn", "airtel", "glo", "9mobile",
                              "etisalat", "subscription"]),
    ("Housing",             ["rent", "landlord", "house rent", "estate",
                              "apartment rent", "mortgage", "property", "agency fee",
                              "caution fee", "agreement fee"]),
    ("Healthcare",          ["hospital", "pharmacy", "chemist", "medicine", "doctor",
                              "clinic", "medical", "drug", "treatment", "lab test",
                              "laboratory", "prescription", "health insurance",
                              "health fee"]),
    ("School Fees",         ["school fees", "school fee", "tuition fee", "sch fees",
                              "primary school", "secondary school", "nursery school",
                              "boarding fee", "school levy"]),
    ("Education",           ["tuition", "exam fee", "university", "college", "academy",
                              "course fee", "training fee", "tutorial", "lesson",
                              "educational"]),
    ("Administration",      ["admin", "administration", "administrative", "office supply",
                              "stationery", "printing", "photocopying", "secretarial",
                              "management fee", "office expense", "operational"]),
    ("Travel",              ["hotel", "airbnb", "flight", "airline", "airport",
                              "visa fee", "travel", "booking", "accommodation",
                              "vacation", "holiday"]),
    ("Entertainment",       ["netflix", "spotify", "apple music", "youtube premium",
                              "cinema", "movie ticket", "game", "sport", "gym",
                              "event ticket", "concert"]),
    ("Bank Charges & Fees", ["bank charge", "stamp duty", "sms alert",
                              "card maintenance", "maintenance fee", "commission",
                              "transfer fee", "transaction fee", "service charge",
                              "account maintenance", "atm fee", "pos fee",
                              "interbank fee", "vat on", "withholding"]),
    ("Repairs",             ["repair", "maintenance", "servicing", "spare part",
                              "technician", "mechanic", "electrician", "plumber",
                              "renovation", "fix", "overhaul", "refurbish"]),
    ("Internal Transfer",   ["auto-save", "owealth"]),
    ("Loans",               ["loan repayment", "loan payment", "loan deduction",
                              "repayment of loan", "loan recovery", "debt repayment",
                              "advance repayment", "loan charge"]),
]

VALID_CATEGORIES = {
    "Food & Dining", "Transportation", "Shopping", "Entertainment",
    "Bills & Utilities", "Healthcare", "Travel", "Education", "School Fees",
    "Housing", "Administration", "Repairs",
    "Salary", "Freelance", "Investment", "Business", "Loans",
    "Bank Charges & Fees", "Internal Transfer", "Refund", "Gift", "Other",
}

# Own-account patterns that legitimately warrant type=transfer
OWN_ACCOUNT_PATTERNS = [
    "own account", "inter-account", "owealth", "auto-save",
    "wallet to wallet", "wallet transfer", "self transfer",
    "internal transfer",
]


# ── Suggestion Functions ──────────────────────────────────────────────────────

def suggest_category_keyword(description: str, tx_type: str) -> Tuple[str, str]:
    """
    Return (category, suggested_type) using keyword rules.

    Priority:
      1. Transfer patterns → ("Internal Transfer", "transfer")
      2. Income-specific patterns → (category, "income")
      3. Neutral patterns → (category, "income" if credit else "expense")
      4. Fall-through → ("Other", "income" if credit else "expense")
    """
    desc = description.lower()
    default_type = "income" if tx_type == "credit" else "expense"

    # 1. Transfer
    if any(p in desc for p in TRANSFER_KEYWORDS):
        return "Internal Transfer", "transfer"

    # 2. Income-specific categories (direction-aware for Salary)
    for cat, patterns in INCOME_KEYWORD_MAP:
        if any(p in desc for p in patterns):
            # Salary paid out (debit) = expense; salary received (credit) = income
            if cat == "Salary" and tx_type == "debit":
                return "Salary", "expense"
            return cat, "income"

    # 3. Neutral categories
    for cat, patterns in NEUTRAL_KEYWORD_MAP:
        if any(p in desc for p in patterns):
            return cat, default_type

    # 4. Default: credit transactions are School Fees (this is a school account)
    if tx_type == "credit":
        return "School Fees", "income"

    return "Other", default_type


def ai_suggest_categories_batch(rows: list[dict]) -> list[dict]:
    """
    For rows whose keyword-based category is still "Other", ask the AI to
    suggest a category and type in a single batch request.

    Returns the same rows list with 'suggested_category' and 'suggested_type'
    updated where the AI provided a confident answer.
    Falls back silently on any AI failure.
    """
    import ai_worker

    # Only send rows where we don't already have a specific category
    undecided_idx = [
        i for i, r in enumerate(rows) if r.get("suggested_category") == "Other"
    ]
    if not undecided_idx:
        return rows

    items = [
        {"i": i, "desc": rows[i]["description"], "dir": rows[i]["transaction_type"]}
        for i in undecided_idx
    ]

    prompt = (
        "You are a Nigerian bank statement categorizer.\n"
        "For each transaction below, return ONLY a JSON array with objects:\n"
        '  {"i": <index>, "category": "<category>", "type": "<expense|income|transfer>"}\n\n'
        "Valid categories: Food & Dining, Transportation, Shopping, Entertainment, "
        "Bills & Utilities, Healthcare, Travel, Education, School Fees, Housing, Administration, Repairs, "
        "Salary, Freelance, Investment, Business, Loans, Bank Charges & Fees, Internal Transfer, Refund, Gift, Other\n\n"
        "Rules:\n"
        "- 'salary', 'payroll' → Salary / income\n"
        "- 'electricity', 'nepa', 'dstv', 'airtime', 'internet' → Bills & Utilities / expense\n"
        "- 'uber', 'fuel', 'petrol', 'bolt', 'fare' → Transportation / expense\n"
        "- 'auto-save', 'owealth', 'own account', 'inter-account', 'wallet transfer' → Internal Transfer / transfer\n"
        "- 'refund', 'reversal' → Refund / income\n"
        "- 'bank charge', 'stamp duty', 'commission' → Bank Charges & Fees / expense\n"
        "- 'loan repayment', 'loan deduction', 'debt repayment', 'advance repayment' → Loans / expense\n"
        "- 'loan received', 'loan disbursement', 'credit facility', 'loan credit' → Loans / income\n"
        "- 'school fees', 'school fee', 'tuition fee', 'sch fees' → School Fees\n"
        "- 'Transfer from PERSON_NAME' or 'Received from PERSON_NAME' = School Fees / income (payment received from student/parent)\n"
        "- Debits (dir=debit) are usually expenses; credits (dir=credit) are usually income\n"
        "- IMPORTANT: Only use type=transfer for movements between the account owner's OWN accounts (e.g. own account, inter-account, wallet). A credit received from another person is INCOME, not transfer.\n"
        "- Only extract data visible in the description. Do NOT guess.\n\n"
        "Transactions:\n"
        + json.dumps(items, ensure_ascii=False)
        + "\n\nReturn JSON array only, no explanation:"
    )

    try:
        raw = ai_worker._call_ai_text(prompt)
        raw = ai_worker._clean_json(raw)
        arr_match = re.search(r"\[[\s\S]*\]", raw)
        if not arr_match:
            return rows

        suggestions = json.loads(arr_match.group())
        for s in suggestions:
            idx = int(s.get("i", -1))
            # Only update rows we actually asked about — prevents the AI
            # hallucinating items for indices it was never given
            if idx not in undecided_idx:
                continue
            cat = str(s.get("category", "Other")).strip()
            typ = str(s.get("type", "")).strip().lower()
            # Validate category against known list to reject malformed values
            # like "Bills & Utilities / expense" that the AI sometimes returns
            if cat in VALID_CATEGORIES and cat != "Other":
                rows[idx]["suggested_category"] = cat
            if typ in ("expense", "income", "transfer"):
                # Guard: don't let AI reclassify a received-from-person credit as
                # "transfer". Only honour type=transfer when the description clearly
                # signals an own-account movement.
                if typ == "transfer":
                    desc_lower = rows[idx]["description"].lower()
                    if not any(p in desc_lower for p in OWN_ACCOUNT_PATTERNS):
                        # Fall back to direction-based default
                        typ = "income" if rows[idx]["transaction_type"] == "credit" else "expense"
                rows[idx]["suggested_type"] = typ
    except Exception as e:
        logger.warning(f"AI batch categorization failed: {e}")

    return rows
