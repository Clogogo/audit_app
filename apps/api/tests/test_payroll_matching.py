"""Unit tests for the fuzzy staff-name matcher in routers/payroll.py.

Pure functions, no DB — covers the real-world cases this logic was written
to handle (typos, reordered names, titles, surname variants from bank
narrations) plus the negative case it must NOT match. Names and account
numbers below are fictional — not real staff or bank data.
"""
from routers.payroll import _name_matches_text, _normalize_name_tokens


def test_normalize_strips_titles_and_punctuation():
    assert _normalize_name_tokens("Mrs. Falade Adaeze") == ["falade", "adaeze"]
    assert _normalize_name_tokens("MR OKORO CHIDI") == ["okoro", "chidi"]


def test_normalize_drops_short_tokens():
    assert "a" not in _normalize_name_tokens("A B Smith")


def test_matches_typo_in_bank_narration():
    staff = "ADEYEMI FAITH OLUWASEUN"
    text = "Transfer to ADEYEMMI FAITH OLUWASEUN MISS | First Bank Of Nigeria | 0000000001 | May Payment"
    assert _name_matches_text(staff, text) is True


def test_matches_reordered_name_with_title_stripped():
    staff = "Mrs. Falade Adaeze"
    text = "Transfer to ADAEZE FALADE | OPay | 0000000002 | May Payment"
    assert _name_matches_text(staff, text) is True


def test_matches_title_and_reordered_components():
    staff = "MR OKORO CHIDI"
    text = "Transfer to CHIDI EMEKA OKORO | Zenith Bank | 0000000003 | May Payment"
    assert _name_matches_text(staff, text) is True


def test_matches_extra_middle_name_and_minor_misspelling():
    staff = "BALOGUN GRACE TEMI"
    text = "Transfer to GRASE TEMIDAYO BALOGUN | OPay | 0000000004 | May Payment"
    assert _name_matches_text(staff, text) is True


def test_matches_surname_variant_when_majority_of_tokens_agree():
    staff = "MRS CHIOMA ADAEZE NWACHUKWU"
    text = "Transfer to CHIOMA ADAEZE OKONKWO | PalmPay | 0000000005 | May Payment"
    assert _name_matches_text(staff, text) is True


def test_does_not_match_different_first_name_on_shared_surname_only():
    # Only the surname overlaps; first/middle names are unrelated — must stay
    # unmatched rather than guessing, since this needs human review.
    staff = "Tolu Benson"
    text = "Transfer to KEMI ADAORA BENSON | PalmPay | 0000000006 | May Payment"
    assert _name_matches_text(staff, text) is False


def test_does_not_match_unrelated_name():
    staff = "John Doe"
    text = "Transfer to Acme Corp | Subscription renewal"
    assert _name_matches_text(staff, text) is False


def test_empty_inputs_do_not_match():
    assert _name_matches_text("", "Transfer to John Doe") is False
    assert _name_matches_text("John Doe", "") is False


def test_short_tokens_do_not_spuriously_match_unrelated_text():
    # Production false positive: a short token can coincidentally be a
    # prefix/substring of an unrelated word (e.g. "ade" inside "adeleke", or
    # "anu" inside "january") and still score >=90 on partial_ratio despite
    # being unrelated. Short tokens (<4 chars) must only match exactly, never
    # via fuzzy similarity, or an unrelated staff member can claim someone
    # else's salary transaction.
    staff = "ADELEKE FAVOUR ANU"
    text = "Transfer to ADE BALOGUN OLUWASEUN | OPay | 0000000007 | January 2026"
    assert _name_matches_text(staff, text) is False
