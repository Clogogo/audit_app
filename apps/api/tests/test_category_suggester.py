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
