"""
Category and Type Suggestion
Smart categorization for Nigerian bank statements.

Categorization is fully deterministic (keyword rules) by default and requires
no AI/network access. An optional AI pass can be enabled for the residual
"Other" rows by setting ENABLE_AI_CATEGORIZATION=true.
"""
import json
import logging
import os
import re
from typing import List, Tuple

logger = logging.getLogger(__name__)


def ai_categorization_enabled() -> bool:
    """
    Whether the optional AI categorization pass is enabled.

    Off by default so statement upload works fully offline with no AI/network
    dependency. Enable explicitly with ENABLE_AI_CATEGORIZATION=true.
    """
    return os.getenv("ENABLE_AI_CATEGORIZATION", "false").strip().lower() in (
        "1", "true", "yes", "on",
    )

# ── Keyword Patterns ──────────────────────────────────────────────────────────

TRANSFER_KEYWORDS = [
    "auto-save to owealth", "auto save to owealth",
    "owealth withdrawal", "owealth balance",
    "own account transfer", "own-account transfer",
    "own account",  # catches "Transfer to X - own account" style descriptions
    "inter-account", "internal transfer", "self transfer",
    "wallet to wallet", "wallet transfer",
]

# (category, forced_type) pairs — income-only categories, checked first.
# "Fund from Director" is listed first so explicit director-funding phrases win.
INCOME_KEYWORD_MAP: List[Tuple[str, List[str]]] = [
    ("Fund from Director", ["fund from director", "funds from director",
                    "from director", "director fund", "director funding",
                    "directors fund", "director's fund", "proprietor fund",
                    "from proprietor", "proprietress fund", "from proprietress"]),
    ("Investment", ["interest earn", "owealth interest", "investment income", "dividend",
                    "fixed deposit return", "savings interest", "interest credit",
                    "treasury", "lien release", "yield"]),
    ("Business",   ["pos settlement", "merchant settlement", "settlement from",
                    "pos credit", "agent commission", "sales proceed",
                    "business income", "revenue credit"]),
    ("Freelance",  ["freelance", "upwork", "fiverr", "gig income", "contract pay"]),
    ("Gift",       ["gift received", "cash gift"]),
    ("Refund",     ["refund", "reversal", "chargeback", "return credit",
                    "clawback reversal"]),
    ("School Fees", ["transfer from", "trf from", "trf frm", "trfr from", "tfr from",
                    "received from", "rcv from", "rcvd from",
                    "payment from", "pmt from", "funds from",
                    "nip from", "neft from", "credit from", "lodgment from"]),
    ("Loans",      ["loan received", "loan credit", "loan disbursement",
                    "credit facility", "overdraft credit"]),
]

# Expense/neutral categories (type follows the bank direction — debit=expense,
# credit=income). Maps to the formal expense chart of accounts. Order matters:
# the first matching keyword wins, so school-specific and specific terms come
# before generic ones.
NEUTRAL_KEYWORD_MAP: List[Tuple[str, List[str]]] = [
    # ── School-operational (highest priority) ──
    ("Exam",                ["exam fee", "exam fees", "examination", "exam levy",
                              "waec", "neco", "jamb", "common entrance",
                              "mock exam", "exam registration", "test fee", "exam"]),
    ("Books",               ["book", "textbook", "text book", "library book",
                              "workbook", "course book", "book fee", "book fees",
                              "book money", "lesson note", "lesson notes", "reading book"]),
    ("Uniform",             ["uniform", "school wear", "school sandal", "cardigan",
                              "sweater", "house wear", "sportswear", "sports wear",
                              "crested", "school cardigan"]),
    ("Stationeries Expenses", ["stationery", "stationary", "stationeries",
                              "exercise book", "exercise books", "writing material",
                              "writing materials", "school supplies", "biro and",
                              "cardboard", "a4 paper", "photocopy paper", "printing"]),
    # ── Energy / power / fuel ──
    ("Generator Expenses",  ["generator", "gen set", "genset", "gen fuel",
                              "generator fuel", "generator servicing", "plant fuel"]),
    ("AGO-Diesel",          ["ago-diesel", "ago diesel", "diesel"]),
    ("PMS",                 ["pms purchase", "premium motor spirit"]),
    ("Fuel Expenses",       ["fuel", "school fuel running", "fuel running",
                              "running fuel", "petrol", "fuel station", "fuelling",
                              "fueling", "fuel money"]),
    ("Electricity & Power", ["electricity", "nepa", "phcn", "electric bill",
                              "power bill", "light bill", "prepaid meter", "meter token",
                              "ikeja electric", "eko electric", "band a", "energy bill"]),
    # ── Communications ──
    ("Internet Cost",       ["internet", "broadband", "wifi", "wi-fi",
                              "data subscription", "data purchase", "data bundle",
                              "spectranet", "smile data", "mtn data"]),
    ("Telephone",           ["airtime", "recharge", "call card", "phone credit",
                              "mtn", "airtel", "glo", "9mobile", "etisalat",
                              "postpaid", "prepaid airtime"]),
    ("Utilities",           ["utility", "water bill", "water rate", "waste bill",
                              "sewage", "gas bill", "dstv", "gotv", "startimes",
                              "cable tv", "disposal fee", "lawma"]),
    # ── People costs ──
    ("IOU (Advance Salary)", ["iou", "i.o.u", "advance salary", "salary advance",
                              "staff advance", "advance payment to staff",
                              "advance to staff", "salary loan", "advance payroll"]),
    ("Salary and Wages",    ["salary", "salaries", "payroll", "monthly pay",
                              "remuneration", "staff pay", "wages", "pay day",
                              "(salary)", "(january", "(february", "(march", "(april",
                              "(may", "(june", "(july", "(august", "(september",
                              "(october", "(november", "(december"]),
    ("Pension and Gratuity", ["pension", "gratuity", "pencom", "rsa contribution"]),
    ("Staff Allowances",    ["staff allowance", "feeding allowance",
                              "transport allowance", "housing allowance",
                              "duty allowance", "allowance"]),
    ("Employee Benefit Expenses", ["staff welfare", "employee benefit", "welfare package"]),
    ("Directors Emoluments", ["director emolument", "directors emolument", "board fee",
                              "sitting allowance", "directors fee", "board allowance"]),
    ("Training and Development", ["training", "seminar", "workshop", "conference",
                              "capacity building", "staff development", "retreat"]),
    # ── Premises / operations ──
    ("Rent & Rates",        ["rent payment", "house rent", "office rent", "shop rent",
                              "annual rent", "rent for", "landlord", "apartment rent",
                              "agency fee", "caution fee", "agreement fee"]),
    ("Rates",               ["tenement rate", "property rate", "ground rate"]),
    ("Rooms/Accommodation Cost", ["accommodation", "lodging", "hostel", "guest house"]),
    ("Repairs and Maintenance", ["repair", "maintenance", "servicing", "spare part",
                              "technician", "mechanic", "electrician", "plumber",
                              "renovation", "overhaul", "refurbish", "painting",
                              "carpenter", "welder"]),
    ("Security Expenses",   ["security guard", "gate guard", "gateman", "gate man",
                              "vigilante", "cctv", "security man", "security expense",
                              "security service"]),
    ("Cleaning & Janitorial Services", ["cleaning", "janitor", "janitorial",
                              "fumigation", "sanitation", "pest control", "cleaner",
                              "detergent", "disinfectant"]),
    ("Health, Safety and Environmental Expenses", ["safety", "hse",
                              "health and safety", "environmental", "fire extinguisher",
                              "first aid"]),
    ("Medical Expenses",    ["hospital", "pharmacy", "chemist", "medicine", "doctor",
                              "clinic", "medical", "drug", "treatment", "lab test",
                              "laboratory", "prescription", "health insurance", "health fee"]),
    # ── Admin / professional / IT ──
    ("Software Maintenance", ["software", "saas", "antivirus",
                              "school management software", "result software",
                              "result checker", "management software",
                              "software subscription", "software licence",
                              "software license", "microsoft", "office 365", "adobe",
                              "canva pro", "google workspace", "zoom subscription"]),
    ("Website Design & Maintenance", ["website", "web design", "web development",
                              "web hosting", "hosting", "domain name", "web maintenance"]),
    ("Subscription & Dues", ["subscription", "membership due", "association fee",
                              "union due", "annual dues", "membership fee"]),
    ("Audit Fees",          ["audit fee", "auditor", "statutory audit"]),
    ("Other Professional Fees", ["professional fee", "consultancy", "consultant",
                              "legal fee", "lawyer", "solicitor", "accountant fee",
                              "retainer"]),
    ("Service Charge",      ["estate service charge", "facility charge", "service charge"]),
    # ── Marketing & relations ──
    ("Advertisement & Promotion", ["advert", "advertisement", "promotion", "billboard",
                              "flyer", "banner", "signage", "handbill", "jingle"]),
    ("Corporate Promotion", ["corporate promotion", "brand promotion"]),
    ("Public Relation",     ["public relation", "pr expense"]),
    ("Publication Cost",    ["publication", "bulletin", "newsletter"]),
    ("Newspaper & Periodicals", ["newspaper", "magazine", "periodical", "gazette"]),
    ("Trade Fairs & Exhibitions", ["trade fair", "exhibition", "expo"]),
    ("Sponsorship",         ["sponsor", "sponsorship"]),
    ("Corporate Social Responsibilities", ["csr", "social responsibility",
                              "community development"]),
    ("Donations",           ["donation", "charity", "alms"]),
    ("Entertainment Expenses", ["restaurant", "eatery", "refreshment", "catering",
                              "reception", "hospitality", "birthday party",
                              "end of year party", "entertainment", "canteen", "cafeteria"]),
    ("Travel Expenses",     ["flight", "airline", "airport", "hotel", "airbnb",
                              "travel", "business trip", "field trip", "road trip",
                              "visa fee", "per diem", "estacode"]),
    # ── Logistics ──
    ("Postages",            ["postage", "courier", "dhl", "fedex", "redstar",
                              "dispatch rider", "gig logistics"]),
    ("Freight & Transport Expenses", ["freight", "haulage", "waybill", "cargo", "truck"]),
    ("Transport of Supplies", ["transport of supplies", "supply delivery", "delivery fee"]),
    # ── Finance / statutory ──
    ("Bank Charges",        ["bank charge", "stamp duty", "sms alert", "card maintenance",
                              "maintenance fee", "commission", "transfer fee",
                              "transaction fee", "account maintenance", "atm fee",
                              "pos fee", "interbank fee", "vat on", "value added tax",
                              "withholding", "cot"]),
    ("Loans",               ["loan repayment", "loan payment", "loan deduction",
                              "repayment of loan", "loan recovery", "debt repayment",
                              "advance repayment", "loan charge", "loan refund",
                              "repay loan", "cooperative loan"]),
    ("Interest Expense",    ["interest charge", "overdraft interest", "loan interest",
                              "interest on loan", "finance charge"]),
    ("Government and Regulatory Costs", ["paye remittance", "vat payment",
                              "withholding tax", "tax payment", "tax remittance",
                              "cac filing", "firs tax", "lirs tax", "regulatory fee",
                              "regulatory levy", "company tax"]),
    ("Other Statutory Charges & Levies", ["development levy", "signage levy", "levy",
                              "statutory charge"]),
    ("Licences & Leases Charges", ["licence fee", "license fee", "lease payment",
                              "equipment lease", "vehicle lease", "leasing",
                              "practising licence"]),
    ("Permits",             ["permit", "approval fee"]),
    ("Royalties",           ["royalty", "royalties"]),
    ("Penalties",           ["penalty", "penalties", "default charge", "late charge"]),
    ("Fines",               ["traffic fine", "late fine", "fine payment", "penalty fine"]),
    ("AMCON Charges",       ["amcon"]),
    ("Realized Foreign Exchange Loss", ["exchange loss", "forex loss", "fx loss"]),
    ("Depreciation",        ["depreciation"]),
    ("Amortisation of Intangible Assets", ["amortisation", "amortization"]),
    ("Bad Debt Written Off", ["bad debt", "debt written off"]),
    ("Staff Loan Written Off", ["staff loan written off", "staff loan write"]),
    ("Loss on Sale of Property, Plant and Equipment", ["loss on sale", "loss on disposal"]),
    ("Research Cost",       ["research cost", "research expense"]),
    ("Outsourcing Services Expenses", ["outsourcing", "outsourced"]),
    ("Selling & Distribution Expenses", ["distribution expense", "selling expense",
                              "sales commission"]),
    ("Head Office Cost",    ["head office"]),
    # ── Generic fallbacks ──
    ("Internal Transfer",   ["auto-save", "owealth"]),
]

# All categories the system recognises (formal expense chart + income + system).
VALID_CATEGORIES = {
    # Income
    "School Fees", "Exam", "Stationery", "Books", "Uniform", "Software",
    "Fund from Director", "Freelance", "Investment", "Business", "Loans",
    "Gift", "Refund",
    # Expense — formal chart of accounts
    "Salary and Wages", "IOU (Advance Salary)", "Employee Benefit Expenses",
    "Directors Emoluments", "Directors Expenses", "Staff Allowances",
    "Staff Loan Written Off", "Staff Gratuity", "Pension and Gratuity",
    "Other Staff & Related Cost",
    "Depreciation", "Amortisation of Intangible Assets",
    "Government and Regulatory Costs", "Bad Debt Written Off", "Interest Expense",
    "Bank Charges", "Audit Fees", "Other Professional Fees", "AMCON Charges",
    "Realized Foreign Exchange Loss", "Fines", "Penalties",
    "Other Statutory Charges & Levies", "Licences & Leases Charges", "Permits",
    "Rates", "Royalties", "Advertisement & Promotion", "Corporate Promotion",
    "Public Relation", "Publication Cost", "Newspaper & Periodicals",
    "Trade Fairs & Exhibitions", "Sponsorship", "Corporate Social Responsibilities",
    "Donations", "Rent & Rates", "Rooms/Accommodation Cost", "Head Office Cost",
    "Electricity & Power", "Utilities", "Internet Cost", "Telephone", "Postages",
    "Fuel Expenses", "AGO-Diesel", "PMS", "Generator Expenses",
    "Repairs and Maintenance", "Security Expenses", "Cleaning & Janitorial Services",
    "Health, Safety and Environmental Expenses", "Medical Expenses",
    "Entertainment Expenses", "Stationeries Expenses", "Software Maintenance",
    "Website Design & Maintenance", "Subscription & Dues", "Service Charge",
    "Training and Development", "Research Cost", "Outsourcing Services Expenses",
    "Selling & Distribution Expenses", "Freight & Transport Expenses",
    "Transport of Supplies", "Travel Expenses",
    "Loss on Sale of Property, Plant and Equipment",
    # System
    "Internal Transfer", "Other",
}

# Own-account patterns that legitimately warrant type=transfer
OWN_ACCOUNT_PATTERNS = [
    "own account", "inter-account", "owealth", "auto-save",
    "wallet to wallet", "wallet transfer", "self transfer",
    "internal transfer",
]


# ── Self-transfer detection ───────────────────────────────────────────────────

def is_self_transfer(description: str, account_holder_name: str | None) -> bool:
    """
    True ONLY when a row is an internal movement between the account holder's
    OWN accounts (e.g. "Transfer from MARVELLOUS LITE SCHOOLS LTD", "transfer
    to own account"). Such rows are typed as transfer so they're excluded from
    income/expense and never double-counted across the holder's accounts.

    Critically, this must NOT catch incoming payments where the holder is merely
    the *beneficiary*, e.g. "LASISI STORE ENTERPRISES TO MARVELLOUS LITE SCHOOLS
    LTD" — that is a third party paying the school (income), not a self-transfer.
    The holder's name appearing in the narration is not enough; it must be the
    counterparty of the movement with no distinct external party named.
    """
    if not description:
        return False
    # Flatten punctuation so reference codes like "/TRF|..." don't leak into
    # word matching and so "from/to <name>" phrases parse cleanly.
    flat = re.sub(r"[^a-z0-9 ]", " ", description.lower())
    flat = re.sub(r"\s+", " ", flat).strip()

    # 1. Explicit own-account phrases (bank-agnostic, unambiguous)
    if any(p in flat for p in (
        "own account", "to own ", "from own ", "self transfer",
        "inter account", "internal transfer",
    )):
        return True

    if not account_holder_name:
        return False

    # Core of the holder name (drop company suffixes & punctuation)
    core = re.sub(
        r"\b(ltd|limited|plc|enterprises?|nig|nigeria|int'?l|international)\b",
        " ", account_holder_name.lower(),
    )
    core = re.sub(r"[^a-z0-9 ]", " ", core)
    core = re.sub(r"\s+", " ", core).strip()
    if len(core) < 5 or core not in flat:
        return False

    # 2. "<external sender> TO <holder>" → holder is the RECIPIENT → this is an
    #    incoming payment (income), NOT a self-transfer. Only treat as self when
    #    the text before "to <holder>" is empty once bank/channel/ref tokens are
    #    stripped (i.e. there is no real third-party sender).
    m = re.search(r"(.*?)\bto\b\s+" + re.escape(core), flat)
    if m:
        prefix = re.sub(
            r"\b(transfer|trf|tfr|trsf|wa|fip|mb|nip|neft|opay|moniepoint|"
            r"cba|mobile|pos|web|ussd|to|from)\b",
            " ", m.group(1),
        )
        prefix = re.sub(r"[0-9]+", " ", prefix)
        prefix = re.sub(r"\s+", " ", prefix).strip()
        if len(prefix) >= 3:
            return False  # a real third-party sender precedes "to <holder>"

    # 3. Holder is the explicit transfer counterparty with no external party:
    #    "transfer from <holder>" / "transfer to <holder>" → genuine self-transfer.
    if re.search(r"\btransfer\s+(from|to)\s+" + re.escape(core), flat):
        return True

    return False


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

    # 2. Income-specific categories (forced income)
    for cat, patterns in INCOME_KEYWORD_MAP:
        if any(p in desc for p in patterns):
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

    No-op unless ENABLE_AI_CATEGORIZATION is set — by default the keyword pass
    is the only categorizer and statement upload makes no AI/network calls.
    """
    if not ai_categorization_enabled():
        return rows

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
