from parsers.category_suggester import suggest_category_keyword


def test_loan_from_director_is_loans_not_school_fees():
    cat, typ = suggest_category_keyword(
        "Transfer from LUCKY CHIGOZIE OGOGO | Stanbic-ibtc Bank Plc | loan from director",
        "credit",
    )
    assert (cat, typ) == ("Loans", "income")


def test_plain_loan_credit_is_loans_not_school_fees():
    cat, typ = suggest_category_keyword(
        "Transfer from LUCKY CHIGOZIE OGOGO | PalmPay | 704****037 | Loan",
        "credit",
    )
    assert (cat, typ) == ("Loans", "income")


def test_director_fund_without_loan_word_is_unaffected():
    cat, typ = suggest_category_keyword(
        "Transfer from director | school running cost", "credit",
    )
    assert cat == "Fund from Director"


def test_loan_repayment_debit_stays_expense_not_income():
    cat, typ = suggest_category_keyword(
        "Transfer to BLESSED HOPE COOPERATIVE | loan repayment", "debit",
    )
    assert (cat, typ) == ("Loans", "expense")


def test_construction_terms_map_to_repairs_and_maintenance():
    for desc in [
        "150 blocks for construction",
        "Additional Cement for construction",
        "for plumbing construction",
        "85 percent workmanship contruction",
        "for school doors payment",
        "for pvc materials",
    ]:
        cat, typ = suggest_category_keyword(desc, "debit")
        assert cat == "Repairs and Maintenance", f"{desc!r} -> {cat}"
        assert typ == "expense"


def test_parenthesized_month_keywords_still_match_word_boundary_fix():
    # Regression: the word-boundary fix for bare "loan" (see above) broke
    # keywords that start/end with punctuation, like "(salary)" and
    # "(january" — \b can never match next to a non-word character, so
    # these never fired at all until _keyword_matches fell back to plain
    # substring containment for them specifically.
    for desc in [
        "Mrs Adeyemi Pay (Salary)",
        "Staff Pay (January) 2026",
        "Teacher wages (february) disbursement",
    ]:
        cat, typ = suggest_category_keyword(desc, "debit")
        assert cat == "Salary and Wages", f"{desc!r} -> {cat}"
        assert typ == "expense"


# ── optional AI pass (ENABLE_AI_CATEGORIZATION) ───────────────────────────────

def _ai_rows():
    return [
        {"description": "POS PURCHASE SUNRISE STATIONERY EXERCISE BOOKS", "suggested_category": "Other", "transaction_type": "debit"},
        {"description": "TRANSFER TO PRIMEPOWER GENERATOR FUEL", "suggested_category": "Other", "transaction_type": "debit"},
        {"description": "AIRTIME PURCHASE MTN", "suggested_category": "Other", "transaction_type": "debit"},
    ]


def _fake_model(monkeypatch, reply):
    import json as _json
    import ai_worker
    seen = {}
    monkeypatch.setenv("ENABLE_AI_CATEGORIZATION", "true")

    def fake(prompt):
        seen["prompt"] = prompt
        return reply if isinstance(reply, str) else _json.dumps(reply)
    monkeypatch.setattr(ai_worker, "_call_ai_text", fake)
    return seen


def test_ai_pass_applies_categories_from_the_apps_own_chart_of_accounts(monkeypatch):
    from parsers.category_suggester import ai_suggest_categories_batch
    _fake_model(monkeypatch, [
        {"i": 0, "category": "Stationeries Expenses", "type": "expense"},
        {"i": 1, "category": "Fuel Expenses", "type": "expense"},
        {"i": 2, "category": "Telephone", "type": "expense"},
    ])
    out = ai_suggest_categories_batch(_ai_rows())
    assert [r["suggested_category"] for r in out] == ["Stationeries Expenses", "Fuel Expenses", "Telephone"]


def test_ai_prompt_offers_the_apps_categories_not_generic_ones(monkeypatch):
    from parsers.category_suggester import VALID_CATEGORIES, ai_suggest_categories_batch
    seen = _fake_model(monkeypatch, "[]")
    ai_suggest_categories_batch(_ai_rows())
    listed = seen["prompt"].split("Valid categories", 1)[1].split("Rules:", 1)[0]
    assert all(category in listed for category in ("Salary and Wages", "Repairs and Maintenance", "Fuel Expenses", "School Fees"))
    assert "Food & Dining" not in seen["prompt"] and "Entertainment," not in listed
    rule_names = {"Salary and Wages", "Electricity & Power", "Telephone", "Internet Cost", "Fuel Expenses", "Travel Expenses",
                  "Bank Charges", "Loans", "School Fees", "Refund", "Internal Transfer"}
    assert rule_names <= VALID_CATEGORIES


def test_ai_pass_still_rejects_categories_outside_the_chart(monkeypatch):
    from parsers.category_suggester import ai_suggest_categories_batch
    _fake_model(monkeypatch, [{"i": 0, "category": "Shopping", "type": "expense"}, {"i": 1, "category": "Bills & Utilities / expense", "type": "expense"}])
    assert [r["suggested_category"] for r in ai_suggest_categories_batch(_ai_rows())] == ["Other", "Other", "Other"]


def test_ai_pass_does_nothing_when_off_or_when_the_model_returns_nothing(monkeypatch):
    from parsers.category_suggester import ai_suggest_categories_batch
    monkeypatch.delenv("ENABLE_AI_CATEGORIZATION", raising=False)
    assert [r["suggested_category"] for r in ai_suggest_categories_batch(_ai_rows())] == ["Other"] * 3
    _fake_model(monkeypatch, "")
    assert [r["suggested_category"] for r in ai_suggest_categories_batch(_ai_rows())] == ["Other"] * 3
