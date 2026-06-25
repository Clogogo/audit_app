import json
import logging
from datetime import date, datetime
from typing import Optional
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, select as sa_select

from database import get_db
from llm_providers import get_llm_client
from models import Transaction, AuditLog, BankAccount
from pydantic import BaseModel as _BaseModel
from schemas import TransactionCreate, TransactionOut, TransactionPage, TransactionUpdate, TransactionSummary, TransactionAISummary, MonthlySummary
from routers.bank_statements import _transfer_is_income, _is_intra_account_transfer


class _BatchCategoryUpdate(_BaseModel):
    ids: list[int]
    category: str

router = APIRouter(prefix="/transactions", tags=["transactions"])
logger = logging.getLogger(__name__)


def _log(db: Session, entity_id: int, action: str, old: dict = None, new: dict = None):
    db.add(AuditLog(
        entity_type="transaction",
        entity_id=entity_id,
        action=action,
        old_values=json.dumps(old) if old else None,
        new_values=json.dumps(new) if new else None,
    ))


@router.get("", response_model=TransactionPage)
def list_transactions(
    type: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    bank: Optional[str] = Query(None),
    vendor: Optional[str] = Query(None),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    q = db.query(Transaction)
    if type:
        q = q.filter(Transaction.type == type)
    if category:
        cats = [c.strip() for c in category.split(",") if c.strip()]
        if len(cats) == 1:
            q = q.filter(Transaction.category.ilike(f"%{cats[0]}%"))
        elif cats:
            q = q.filter(Transaction.category.in_(cats))
    if bank:
        q = q.filter(Transaction.bank.ilike(f"%{bank}%"))
    if vendor:
        q = q.filter(Transaction.vendor.ilike(f"%{vendor}%"))
    if start_date:
        q = q.filter(Transaction.date >= start_date)
    if end_date:
        q = q.filter(Transaction.date <= end_date)
    total = q.count()
    items = q.order_by(Transaction.date.desc(), Transaction.created_at.desc()).limit(limit).offset(offset).all()
    return TransactionPage(items=items, total=total, limit=limit, offset=offset)


@router.get("/years", response_model=list[int])
def get_transaction_years(db: Session = Depends(get_db)):
    """Return distinct years that have at least one transaction, sorted descending."""
    # extract() is portable across SQLite and Postgres; strftime() is SQLite-only.
    year_col = func.extract("year", Transaction.date)
    rows = db.query(year_col).distinct().order_by(year_col.desc()).all()
    return [int(r[0]) for r in rows if r[0]]


@router.get("/summary", response_model=TransactionSummary)
def get_summary(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    bank: Optional[str] = Query(None),
    vendor: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    # Shared WHERE conditions — transfer direction is resolved per-row below,
    # the same way Bank Account Reports' Book Balance does it, so the two pages
    # reconcile instead of silently disagreeing.
    base_conds = []
    if start_date:
        base_conds.append(Transaction.date >= start_date)
    if end_date:
        base_conds.append(Transaction.date <= end_date)
    if bank:
        base_conds.append(Transaction.bank.ilike(f"%{bank}%"))
    if vendor:
        base_conds.append(Transaction.vendor.ilike(f"%{vendor}%"))

    # Total income / expense via SQL SUM — no full ORM load
    income_total: float = db.execute(
        sa_select(func.coalesce(func.sum(Transaction.amount), 0.0))
        .where(Transaction.type == "income", *base_conds)
    ).scalar() or 0.0

    expense_total: float = db.execute(
        sa_select(func.coalesce(func.sum(Transaction.amount), 0.0))
        .where(Transaction.type == "expense", *base_conds)
    ).scalar() or 0.0

    # Category breakdowns via GROUP BY (transfers handled separately below)
    cat_rows = db.execute(
        sa_select(Transaction.type, Transaction.category, func.sum(Transaction.amount).label("total"))
        .where(Transaction.type != "transfer", *base_conds)
        .group_by(Transaction.type, Transaction.category)
    ).all()

    by_category: dict[str, float] = defaultdict(float)
    expense_by_category: dict[str, float] = defaultdict(float)
    income_by_category: dict[str, float] = defaultdict(float)
    for tx_type, cat, total in cat_rows:
        by_category[cat] += total
        if tx_type == "expense":
            expense_by_category[cat] += total
        else:
            income_by_category[cat] += total

    # Monthly aggregation via GROUP BY (transfers handled separately below).
    # extract() is portable across SQLite and Postgres; strftime() is SQLite-only.
    year_col = func.extract("year", Transaction.date)
    month_col = func.extract("month", Transaction.date)
    monthly_rows = db.execute(
        sa_select(
            year_col.label("yr"),
            month_col.label("mo"),
            Transaction.type,
            func.sum(Transaction.amount).label("total"),
        )
        .where(Transaction.type != "transfer", *base_conds)
        .group_by("yr", "mo", Transaction.type)
        .order_by("yr", "mo")
    ).all()

    monthly_map: dict[str, dict] = {}
    for yr, mo, tx_type, total in monthly_rows:
        ym = f"{int(yr):04d}-{int(mo):02d}"
        if ym not in monthly_map:
            monthly_map[ym] = {"month": date(int(yr), int(mo), 1).strftime("%b %Y"), "income": 0.0, "expenses": 0.0}
        if tx_type == "income":
            monthly_map[ym]["income"] += total
        else:
            monthly_map[ym]["expenses"] += total

    # ── Transfers: direction by actual debit/credit, mirroring Book Balance ──
    # Intra-account transfers (auto-saves, vaults) are excluded entirely. Every
    # other transfer counts as income or expense by its own recorded direction
    # (not by account type — any account can both send and receive). Transfers
    # with no linked account are skipped — direction can't be determined without one.
    transfers = (
        db.query(Transaction)
        .filter(Transaction.type == "transfer", Transaction.bank_account_id.isnot(None), *base_conds)
        .all()
    )
    for t in transfers:
        if not t.bank_account or _is_intra_account_transfer(t):
            continue
        ym = t.date.strftime("%Y-%m")
        if ym not in monthly_map:
            monthly_map[ym] = {"month": t.date.strftime("%b %Y"), "income": 0.0, "expenses": 0.0}

        by_category[t.category] += t.amount
        if _transfer_is_income(t, t.bank_account.bank_name, db):
            income_total += t.amount
            income_by_category[t.category] += t.amount
            monthly_map[ym]["income"] += t.amount
        else:
            expense_total += t.amount
            expense_by_category[t.category] += t.amount
            monthly_map[ym]["expenses"] += t.amount

    monthly = [MonthlySummary(**monthly_map[k]) for k in sorted(monthly_map.keys())]

    # ── Opening balances: sum across accounts in scope, mirroring Book Balance's
    # "opening + income − expense" so the headline balance reconciles too.
    accounts_q = db.query(BankAccount)
    if bank:
        accounts_q = accounts_q.filter(BankAccount.bank_name.ilike(f"%{bank}%"))
    total_opening_balance = sum(a.opening_balance or 0.0 for a in accounts_q.all())

    return TransactionSummary(
        total_income=income_total,
        total_expenses=expense_total,
        balance=total_opening_balance + income_total - expense_total,
        by_category=dict(by_category),
        expense_by_category=dict(expense_by_category),
        income_by_category=dict(income_by_category),
        monthly=monthly,
    )


# ── AI narrative summary ────────────────────────────────────────────────────
# Cached by the *content* of the summary, not just a TTL: identical totals
# always serve the same cached narrative (no redundant AI spend), but the
# moment the underlying numbers change, the key changes and a fresh call is
# made. Capped to bound memory (simple FIFO eviction), same in-memory-cache
# style as routers/financial_statements.py.
_AI_SUMMARY_CACHE: dict[tuple, str] = {}
_AI_SUMMARY_CACHE_MAX = 64


def _ai_summary_cache_key(
    start_date: Optional[date], end_date: Optional[date], bank: Optional[str],
    vendor: Optional[str], summary: TransactionSummary,
) -> tuple:
    return (
        start_date, end_date, bank, vendor,
        round(summary.total_income, 2),
        round(summary.total_expenses, 2),
        tuple(sorted((k, round(v, 2)) for k, v in summary.by_category.items())),
    )


def _build_ai_summary_prompt(summary: TransactionSummary) -> str:
    top_categories = sorted(summary.by_category.items(), key=lambda kv: -abs(kv[1]))[:5]
    categories_text = ", ".join(f"{name}: ₦{amount:,.2f}" for name, amount in top_categories)
    monthly_text = "; ".join(
        f"{m.month}: income ₦{m.income:,.2f}, expenses ₦{m.expenses:,.2f}"
        for m in summary.monthly[-6:]
    )
    return (
        "You are a financial assistant summarizing transaction data for a small "
        "organization in Nigeria. All amounts are in Nigerian Naira — always use "
        "the ₦ symbol, never £, $, or any other currency. Write a concise 2-4 "
        "sentence plain-English summary highlighting the overall financial "
        "position, notable spending categories, and any trend over the recent "
        "months. Do not just list raw numbers for every category — focus on "
        "what matters.\n\n"
        f"Total income: ₦{summary.total_income:,.2f}\n"
        f"Total expenses: ₦{summary.total_expenses:,.2f}\n"
        f"Balance: ₦{summary.balance:,.2f}\n"
        f"Top categories: {categories_text}\n"
        f"Recent months: {monthly_text}"
    )


@router.get("/ai-summary", response_model=TransactionAISummary)
def get_ai_summary(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    bank: Optional[str] = Query(None),
    vendor: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """AI-generated narrative over the same data as GET /transactions/summary.
    Never raises on AI failure — returns available=False instead, so the
    frontend can simply omit the summary card rather than show an error."""
    summary = get_summary(start_date=start_date, end_date=end_date, bank=bank, vendor=vendor, db=db)

    cache_key = _ai_summary_cache_key(start_date, end_date, bank, vendor, summary)
    cached = _AI_SUMMARY_CACHE.get(cache_key)
    if cached is not None:
        return TransactionAISummary(narrative=cached, available=True)

    try:
        client = get_llm_client()
        narrative = client.create_message(
            messages=[{"role": "user", "content": _build_ai_summary_prompt(summary)}],
            max_tokens=300,
        )
    except Exception as e:
        logger.warning(f"AI summary generation failed, returning available=False: {e}")
        return TransactionAISummary(narrative=None, available=False)

    if len(_AI_SUMMARY_CACHE) >= _AI_SUMMARY_CACHE_MAX:
        _AI_SUMMARY_CACHE.pop(next(iter(_AI_SUMMARY_CACHE)))
    _AI_SUMMARY_CACHE[cache_key] = narrative

    return TransactionAISummary(narrative=narrative, available=True)


@router.post("", response_model=TransactionOut, status_code=201)
def create_transaction(data: TransactionCreate, db: Session = Depends(get_db)):
    tx_data = data.model_dump()
    
    # Auto-link bank account if bank name is provided but bank_account_id is not
    if not tx_data.get("bank_account_id") and tx_data.get("bank"):
        from models import BankAccount
        # Try to find bank account by matching bank name (case-insensitive)
        bank_name = tx_data["bank"].strip().lower()
        bank_account = db.query(BankAccount).filter(
            func.lower(BankAccount.bank_name) == bank_name
        ).first()
        
        if bank_account:
            tx_data["bank_account_id"] = bank_account.id
    
    tx = Transaction(**tx_data)
    db.add(tx)
    db.flush()
    _log(db, tx.id, "create", new=data.model_dump(mode="json"))

    # Auto-detect duplicates using fuzzy matching
    from routers.duplicates import detect_duplicates_for_transaction, mark_as_duplicates
    matches = detect_duplicates_for_transaction(db, tx)
    if matches:
        # Link to the best match (highest confidence)
        best_match, confidence = matches[0]
        mark_as_duplicates(db, tx, best_match, confidence)

    db.commit()
    db.refresh(tx)
    return tx


@router.put("/{tx_id}", response_model=TransactionOut)
def update_transaction(tx_id: int, data: TransactionUpdate, db: Session = Depends(get_db)):
    tx = db.get(Transaction, tx_id)
    if not tx:
        raise HTTPException(404, "Transaction not found")

    old = {c.name: getattr(tx, c.name) for c in Transaction.__table__.columns}
    updates = data.model_dump(exclude_none=True)
    # Parse date string to date object (TransactionUpdate.date is Optional[str])
    if "date" in updates:
        try:
            updates["date"] = date.fromisoformat(str(updates["date"])[:10])
        except ValueError:
            raise HTTPException(400, "Invalid date format, expected YYYY-MM-DD")
    for k, v in updates.items():
        setattr(tx, k, v)
    tx.updated_at = datetime.utcnow()

    _log(db, tx_id, "update", old={k: str(v) for k, v in old.items()}, new={k: str(v) for k, v in updates.items()})
    db.commit()
    db.refresh(tx)
    return tx


@router.patch("/batch-category")
def batch_update_category(data: _BatchCategoryUpdate, db: Session = Depends(get_db)):
    """Set the same category on multiple transactions at once."""
    updated = 0
    for tx_id in data.ids:
        tx = db.get(Transaction, tx_id)
        if not tx:
            continue
        old_cat = tx.category
        tx.category = data.category
        tx.updated_at = datetime.utcnow()
        _log(db, tx_id, "update",
             old={"category": old_cat},
             new={"category": data.category})
        updated += 1
    db.commit()
    return {"updated": updated}


@router.delete("/{tx_id}")
def delete_transaction(tx_id: int, db: Session = Depends(get_db)):
    tx = db.get(Transaction, tx_id)
    if not tx:
        raise HTTPException(404, "Transaction not found")
    old = {c.name: str(getattr(tx, c.name)) for c in Transaction.__table__.columns}
    _log(db, tx_id, "delete", old=old)

    # Clear reconciliation links so bank transactions don't keep a dangling reference
    from models import BankTransaction
    db.query(BankTransaction).filter(
        BankTransaction.matched_transaction_id == tx_id
    ).update(
        {"matched_transaction_id": None, "match_status": "unmatched"},
        synchronize_session=False,
    )

    # Clear duplicate links on transactions that pointed at this one
    db.query(Transaction).filter(
        Transaction.duplicate_of_id == tx_id
    ).update(
        {"duplicate_of_id": None, "is_potential_duplicate": False,
         "duplicate_reviewed": False, "duplicate_confidence": None},
        synchronize_session=False,
    )

    db.delete(tx)
    db.commit()
    return {"ok": True}
