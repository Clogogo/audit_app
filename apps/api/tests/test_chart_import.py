"""Importing the Chart of Accounts CSV and the suggested category -> account mapping."""
from pathlib import Path

import pytest

from models import ChartAccount
from utils.account_suggestions import suggest_account
from utils.chart_import import ChartImportError, import_chart, parse_chart_csv

BUNDLED = Path(__file__).resolve().parents[1] / "data" / "chart_of_accounts.csv"
HEADER = "Account Code,Account Name,Description,Level,Parent Code,Parent Path,Category,Statement Type,Statement Section,Normal Balance,Cash Flow Category,FSLI,Sub Ledger,IFRS Reference,Scope,Status"


def _csv(*rows: str) -> bytes:
    return ("\n".join([HEADER, *rows]) + "\n").encode("utf-8-sig")


GROUP = '4.1.1.3,Service Revenue,Services.,L4,4.1.1,Op Rev,Income,Income Statement,Operating Revenue,Credit,Operating,Rev,,IFRS 15,Core,Active'
LEAF_A = '4.1.1.3.2,Tuition & School Fees,School fees.,L5,4.1.1.3,Op Rev,Income,Income Statement,Operating Revenue,Credit,Operating,Rev,,,Industry:Education & Training,Active'
LEAF_B = '5.2.3.4,Office Stationery,Stationery.,L4,5.2.3,OpEx,Expenses,Income Statement,Operating Expenses (OpEx),Debit,Operating,Admin,,IAS 1,Core,Active'


def test_parse_reads_columns_and_marks_only_accounts_without_children_as_postable():
    rows = {r["code"]: r for r in parse_chart_csv(_csv(GROUP, LEAF_A, LEAF_B))}
    assert rows["4.1.1.3.2"]["name"] == "Tuition & School Fees" and rows["4.1.1.3.2"]["category"] == "Income"
    assert rows["4.1.1.3.2"]["statement_section"] == "Operating Revenue" and rows["4.1.1.3.2"]["normal_balance"] == "Credit"
    assert rows["4.1.1.3"]["is_postable"] is False        # has a child
    assert rows["4.1.1.3.2"]["is_postable"] is True and rows["5.2.3.4"]["is_postable"] is True


def test_parse_rejects_missing_columns_duplicates_and_empty_files():
    with pytest.raises(ChartImportError, match="Account Code"):
        parse_chart_csv(b"Name,Value\nA,1\n")
    with pytest.raises(ChartImportError, match="Duplicate"):
        parse_chart_csv(_csv(LEAF_B, LEAF_B))
    with pytest.raises(ChartImportError, match="No accounts"):
        parse_chart_csv(_csv())
    with pytest.raises(ChartImportError):
        parse_chart_csv(b"\xff\xfe\x00 not csv")


def test_import_is_idempotent_and_updates_changed_rows(db_session):
    assert import_chart(db_session, parse_chart_csv(_csv(GROUP, LEAF_A))) == {"created": 2, "updated": 0, "total": 2}
    renamed = LEAF_A.replace("Tuition & School Fees", "Tuition Fees")
    assert import_chart(db_session, parse_chart_csv(_csv(GROUP, renamed, LEAF_B))) == {"created": 1, "updated": 1, "total": 3}
    assert db_session.query(ChartAccount).filter_by(code="4.1.1.3.2").one().name == "Tuition Fees"
    assert db_session.query(ChartAccount).count() == 3


def test_the_bundled_chart_imports_with_235_postable_accounts(db_session):
    stats = import_chart(db_session, parse_chart_csv(BUNDLED.read_bytes()))
    assert stats["total"] == 240
    assert db_session.query(ChartAccount).filter_by(is_postable=True).count() == 235


# ── suggested mapping ─────────────────────────────────────────────────────────

def test_suggestions_depend_on_whether_money_came_in_or_went_out():
    assert suggest_account("School Fees", "income") == "4.1.1.3.2"
    assert suggest_account("Books", "income") == "4.1.1.1"           # books SOLD
    assert suggest_account("Books", "expense") == "5.1.1.1.2"        # books BOUGHT
    assert suggest_account("Salary and Wages", "expense") == "5.2.1.1.2"


def test_a_refund_in_the_other_direction_falls_back_to_the_same_account():
    assert suggest_account("Repairs and Maintenance", "income") == suggest_account("Repairs and Maintenance", "expense")
    assert suggest_account("School Fees", "expense") == "4.1.1.3.2"     # fees refunded
    assert suggest_account("Loans", "expense") == suggest_account("Loans", "income")


def test_unknown_or_deliberately_unmapped_categories_have_no_suggestion():
    assert suggest_account("Something New", "expense") is None
    assert suggest_account("Other", "expense") is None                  # the user decides what "Other" is


def test_every_suggested_account_exists_and_can_receive_postings(db_session):
    from utils.account_suggestions import all_suggested_codes
    import_chart(db_session, parse_chart_csv(BUNDLED.read_bytes()))
    postable = {a.code for a in db_session.query(ChartAccount).filter_by(is_postable=True)}
    assert not (all_suggested_codes() - postable), sorted(all_suggested_codes() - postable)
