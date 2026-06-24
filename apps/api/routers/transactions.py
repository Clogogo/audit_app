import json
from datetime import date, datetime
from typing import Optional
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, select as sa_select

from database import get_db
from models import Transaction, AuditLog, BankAccount
from pydantic import BaseModel as _BaseModel
from schemas import TransactionCreate, TransactionOut, TransactionPage, TransactionUpdate, TransactionSummary, MonthlySummary
from routers.bank_statements import _transfer_is_income, _is_intra_account_transfer


class _BatchCategoryUpdate(_BaseModel):
    ids: list[int]
    category: str

router = APIRouter(prefix="/transactions", tags=["transactions"])


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
    rows = (
        db.query(func.strftime('%Y', Transaction.date))
        .distinct()
        .order_by(func.strftime('%Y', Transaction.date).desc())
        .all()
    )
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

    # Monthly aggregation via GROUP BY (transfers handled separately below)
    monthly_rows = db.execute(
        sa_select(
            func.strftime("%Y-%m", Transaction.date).label("ym"),
            Transaction.type,
            func.sum(Transaction.amount).label("total"),
        )
        .where(Transaction.type != "transfer", *base_conds)
        .group_by("ym", Transaction.type)
        .order_by("ym")
    ).all()

    monthly_map: dict[str, dict] = {}
    for ym, tx_type, total in monthly_rows:
        if ym not in monthly_map:
            y, m = ym.split("-")
            monthly_map[ym] = {"month": date(int(y), int(m), 1).strftime("%b %Y"), "income": 0.0, "expenses": 0.0}
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
