"""Unit tests for the fuzzy staff-name matcher in routers/payroll.py.

Pure functions, no DB — covers the real-world cases this logic was written
to handle (typos, reordered names, titles, surname variants from bank
narrations) plus the negative case it must NOT match.
"""
from routers.payroll import _name_matches_text, _normalize_name_tokens


def test_normalize_strips_titles_and_punctuation():
    assert _normalize_name_tokens("Mrs. Adedeji Rukayat") == ["adedeji", "rukayat"]
    assert _normalize_name_tokens("MR AJOSE BAMIDELE") == ["ajose", "bamidele"]


def test_normalize_drops_short_tokens():
    assert "a" not in _normalize_name_tokens("A B Smith")


def test_matches_typo_in_bank_narration():
    staff = "AJUMOWU MARY NGOZI"
    text = "Transfer to AJUMONWU MARY NGOZI MISS | First Bank Of Nigeria | 3000921786 | May Payment"
    assert _name_matches_text(staff, text) is True


def test_matches_reordered_name_with_title_stripped():
    staff = "Mrs. Adedeji Rukayat"
    text = "Transfer to RUKAYAT ADEDEJI | OPay | 8135029244 | May Payment"
    assert _name_matches_text(staff, text) is True


def test_matches_title_and_reordered_components():
    staff = "MR AJOSE BAMIDELE"
    text = "Transfer to BAMIDELE BOLAJI AJOSE | Zenith Bank | 4241293144 | May Payment"
    assert _name_matches_text(staff, text) is True


def test_matches_extra_middle_name_and_minor_misspelling():
    staff = "OLAWALE RACHEAL ANU"
    text = "Transfer to RACHAEL ANUOLUWAPO OLAWALE | OPay | 9131544473 | May Payment"
    assert _name_matches_text(staff, text) is True


def test_matches_surname_variant_when_majority_of_tokens_agree():
    staff = "MRS ALIMOT OMOLADE ADENIYI"
    text = "Transfer to ALIMOT OMOLADE OLATEJU | PalmPay | 8143037990 | May Payment"
    assert _name_matches_text(staff, text) is True


def test_does_not_match_different_first_name_on_shared_surname_only():
    # Only "christian" overlaps; first/middle names are unrelated — must stay
    # unmatched rather than guessing, since this needs human review.
    staff = "Emmanuella Christian"
    text = "Transfer to HELEN CHINENYE CHRISTIAN | PalmPay | 7083854654 | May Payment"
    assert _name_matches_text(staff, text) is False


def test_does_not_match_unrelated_name():
    staff = "John Doe"
    text = "Transfer to Acme Corp | Subscription renewal"
    assert _name_matches_text(staff, text) is False


def test_empty_inputs_do_not_match():
    assert _name_matches_text("", "Transfer to John Doe") is False
    assert _name_matches_text("John Doe", "") is False
