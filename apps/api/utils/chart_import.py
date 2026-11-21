"""Read the Chart of Accounts CSV and load it into the chart_accounts table."""
import csv
import io
from typing import Any

from sqlalchemy.orm import Session

from models import ChartAccount

REQUIRED = ("Account Code", "Account Name", "Category", "Statement Section", "Normal Balance")
COLUMNS = {
    "Account Code": "code", "Account Name": "name", "Description": "description", "Level": "level",
    "Parent Code": "parent_code", "Category": "category", "Statement Type": "statement_type",
    "Statement Section": "statement_section", "Normal Balance": "normal_balance",
    "Cash Flow Category": "cash_flow_category", "FSLI": "fsli", "Scope": "scope", "Status": "status",
}
CATEGORIES = {"Assets", "Liabilities", "Equity", "Income", "Expenses"}
FIELDS = [*COLUMNS.values(), "is_postable"]


class ChartImportError(ValueError):
    """The file is not a usable chart of accounts; the message is safe to show the user."""


def parse_chart_csv(content: bytes) -> list[dict[str, Any]]:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ChartImportError("That doesn't look like a UTF-8 CSV file.") from exc
    reader = csv.DictReader(io.StringIO(text))
    missing = [c for c in REQUIRED if c not in (reader.fieldnames or [])]
    if missing:
        raise ChartImportError(f"Missing column(s): {', '.join(missing)}.")

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in reader:
        row = {field: (raw.get(column) or "").strip() or None for column, field in COLUMNS.items()}
        if not row["code"]:
            continue
        if row["code"] in seen:
            raise ChartImportError(f"Duplicate account code {row['code']}.")
        seen.add(row["code"])
        if row["category"] not in CATEGORIES:
            raise ChartImportError(f"Account {row['code']} has an unknown category {row['category']!r}.")
        if row["normal_balance"] not in ("Debit", "Credit"):
            raise ChartImportError(f"Account {row['code']} needs a Normal Balance of Debit or Credit.")
        row["status"] = row["status"] or "Active"
        rows.append(row)
    if not rows:
        raise ChartImportError("No accounts found in the file.")

    parents = {r["parent_code"] for r in rows if r["parent_code"]}
    return [{**r, "is_postable": r["code"] not in parents} for r in rows]


def import_chart(db: Session, rows: list[dict[str, Any]]) -> dict[str, int]:
    """Upsert by account code; re-importing the same file changes nothing."""
    existing = {a.code: a for a in db.query(ChartAccount).all()}
    created = updated = 0
    for row in rows:
        account = existing.get(row["code"])
        if account is None:
            db.add(ChartAccount(**row))
            created += 1
        elif any(getattr(account, f) != row[f] for f in FIELDS):
            for field in FIELDS:
                setattr(account, field, row[field])
            updated += 1
    db.commit()
    return {"created": created, "updated": updated, "total": len(rows)}
