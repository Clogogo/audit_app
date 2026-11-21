"""Chart of Accounts, category -> account mapping, and the Trial Balance / Profit & Loss /
ledger reports computed from transactions (see utils/accounting.py)."""
from datetime import date
from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import get_db
from models import AccountMapping, BankAccount, ChartAccount, Transaction
from utils.account_suggestions import suggest_account
from utils.accounting import CASH_CODE, Account, Entry, ledger, profit_and_loss, trial_balance
from routers.bank_statements import _is_intra_account_transfer, _transfer_is_income
from utils.auth import require_permission
from utils.chart_import import ChartImportError, import_chart, parse_chart_csv

router = APIRouter(prefix="/accounting", tags=["accounting"], dependencies=[Depends(require_permission("tax"))])

BUNDLED_CHART = Path(__file__).resolve().parent.parent / "data" / "chart_of_accounts.csv"
MAX_CHART_BYTES = 2 * 1024 * 1024
TxType = Literal["income", "expense"]


# ── helpers ───────────────────────────────────────────────────────────────────

def _chart(db: Session) -> dict[str, Account]:
    return {a.code: Account(a.code, a.name, a.category, a.statement_section, a.normal_balance) for a in db.query(ChartAccount)}


def _mapping(db: Session) -> dict[tuple[str, str], str]:
    """Only mappings that still point at an active, postable account (never the bank itself)."""
    usable = _postable_codes(db) - {CASH_CODE}
    return {(m.category, m.tx_type): m.account_code for m in db.query(AccountMapping) if m.account_code in usable}


def _entries(db: Session, end: date) -> list[Entry]:
    rows = db.query(Transaction).filter(Transaction.type.in_(["income", "expense", "transfer"]), Transaction.date <= end).all()
    entries = []
    for t in rows:
        kind = t.type
        if kind == "transfer":  # same rule as /transactions/summary: skip intra-account, else direction by debit/credit
            if not t.bank_account or _is_intra_account_transfer(t):
                continue
            kind = "income" if _transfer_is_income(t, t.bank_account.bank_name, db) else "expense"
        entries.append(Entry(t.id, t.date, kind, round(t.amount * 100), t.category))
    return entries


def _opening_cash_cents(db: Session) -> int:
    return round((db.query(func.coalesce(func.sum(BankAccount.opening_balance), 0.0)).scalar() or 0.0) * 100)


def _period(start_date: date, end_date: date) -> tuple[date, date]:
    if start_date > end_date:
        raise HTTPException(400, "The start date must not be after the end date.")
    return start_date, end_date


def _combos(db: Session) -> list:
    return (
        db.query(Transaction.category, Transaction.type, func.count(Transaction.id).label("n"), func.sum(Transaction.amount).label("total"))
        .filter(Transaction.type.in_(["income", "expense"])).group_by(Transaction.category, Transaction.type)        .order_by(Transaction.type, Transaction.category).all()
    )


def _postable_codes(db: Session) -> set[str]:
    return {c for (c,) in db.query(ChartAccount.code).filter(ChartAccount.is_postable == True, ChartAccount.status == "Active")}  # noqa: E712


# ── chart of accounts ─────────────────────────────────────────────────────────

@router.get("/chart")
def get_chart(db: Session = Depends(get_db)):
    accounts = db.query(ChartAccount).all()
    accounts.sort(key=lambda a: [int(p) if p.isdigit() else 0 for p in a.code.split(".")])
    return {"imported": bool(accounts), "accounts": [
        {"code": a.code, "name": a.name, "description": a.description, "category": a.category, "statement_section": a.statement_section,
         "normal_balance": a.normal_balance, "scope": a.scope, "is_postable": a.is_postable, "status": a.status} for a in accounts]}


@router.post("/chart/import")
def import_chart_file(file: Optional[UploadFile] = File(None), db: Session = Depends(get_db)):
    """Import the uploaded CSV, or the chart bundled with the app when no file is given. Safe to repeat."""
    content = file.file.read(MAX_CHART_BYTES + 1) if file else BUNDLED_CHART.read_bytes()
    if len(content) > MAX_CHART_BYTES:
        raise HTTPException(413, "File too large.")
    try:
        return import_chart(db, parse_chart_csv(content))
    except ChartImportError as exc:
        raise HTTPException(400, str(exc)) from exc


# ── category mapping ──────────────────────────────────────────────────────────

class MappingIn(BaseModel):
    category: str = Field(max_length=100)
    type: TxType
    account_code: Optional[str] = Field(None, max_length=40)


@router.get("/mappings")
def get_mappings(db: Session = Depends(get_db)):
    mapped = _mapping(db)
    return {"chart_imported": db.query(ChartAccount.id).first() is not None, "rows": [
        {"category": r.category, "type": r.type, "tx_count": r.n, "total": round(r.total or 0.0, 2),
         "account_code": mapped.get((r.category, r.type)), "suggested_code": suggest_account(r.category, r.type)}
        for r in _combos(db)]}


@router.put("/mappings")
def set_mapping(body: MappingIn, db: Session = Depends(get_db)):
    existing = db.query(AccountMapping).filter_by(category=body.category, tx_type=body.type).first()
    if body.account_code is None:
        if existing:
            db.delete(existing)
            db.commit()
        return {"category": body.category, "type": body.type, "account_code": None}
    account = db.query(ChartAccount).filter_by(code=body.account_code).first()
    if account is None:
        raise HTTPException(400, f"There is no account {body.account_code} in the chart.")
    if account.code == CASH_CODE:
        raise HTTPException(400, "The bank account is the other side of every entry: choose an income or expense account.")
    if account.status != "Active":
        raise HTTPException(400, f"{account.code} {account.name} is not active.")
    if not account.is_postable:
        raise HTTPException(400, f"{account.code} {account.name} is a group heading: choose one of its sub-accounts.")
    if existing:
        existing.account_code = account.code
    else:
        db.add(AccountMapping(category=body.category, tx_type=body.type, account_code=account.code))
    db.commit()
    return {"category": body.category, "type": body.type, "account_code": account.code}


@router.post("/mappings/apply-suggestions")
def apply_suggestions(db: Session = Depends(get_db)):
    """Fill the rows that have no mapping yet with the suggested account (never overwrites a choice)."""
    mapped, postable = _mapping(db), _postable_codes(db)
    applied = without = 0
    for r in _combos(db):
        if (r.category, r.type) in mapped:
            continue
        code = suggest_account(r.category, r.type)
        if code in postable:
            db.add(AccountMapping(category=r.category, tx_type=r.type, account_code=code))
            applied += 1
        else:
            without += 1
    db.commit()
    return {"applied": applied, "without_suggestion": without}


# ── reports ───────────────────────────────────────────────────────────────────

@router.get("/trial-balance")
def get_trial_balance(start_date: date = Query(...), end_date: date = Query(...), db: Session = Depends(get_db)):
    start, end = _period(start_date, end_date)
    result = trial_balance(_entries(db, end), _mapping(db), _chart(db), _opening_cash_cents(db), start, end)
    return {**result, "start_date": start.isoformat(), "end_date": end.isoformat()}


@router.get("/profit-and-loss")
def get_profit_and_loss(start_date: date = Query(...), end_date: date = Query(...), db: Session = Depends(get_db)):
    start, end = _period(start_date, end_date)
    result = profit_and_loss(_entries(db, end), _mapping(db), _chart(db), start, end)
    return {**result, "start_date": start.isoformat(), "end_date": end.isoformat()}


@router.get("/ledger")
def get_ledger(account: str = Query(...), start_date: date = Query(...), end_date: date = Query(...), db: Session = Depends(get_db)):
    """The transactions behind one line of the Trial Balance or Profit & Loss."""
    start, end = _period(start_date, end_date)
    result = ledger(_entries(db, end), _mapping(db), _chart(db), account, start, end)
    ids = [r["id"] for r in result["rows"]]
    details = {t.id: t for t in db.query(Transaction.id, Transaction.description, Transaction.vendor).filter(Transaction.id.in_(ids))} if ids else {}
    rows = [{**r, "description": details[r["id"]].description, "vendor": details[r["id"]].vendor} for r in result["rows"]]
    return {**result, "rows": rows, "start_date": start.isoformat(), "end_date": end.isoformat()}
