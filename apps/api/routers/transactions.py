import json
from datetime import date, datetime
from typing import Optional
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func

from database import get_db
from models import Transaction, AuditLog
from pydantic import BaseModel as _BaseModel
from schemas import TransactionCreate, TransactionOut, TransactionUpdate, TransactionSummary, MonthlySummary


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


@router.get("", response_model=list[TransactionOut])
def list_transactions(
    type: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
):
    q = db.query(Transaction)
    if type:
        q = q.filter(Transaction.type == type)
    if category:
        q = q.filter(Transaction.category.ilike(f"%{category}%"))
    if start_date:
        q = q.filter(Transaction.date >= start_date)
    if end_date:
        q = q.filter(Transaction.date <= end_date)
    return q.order_by(Transaction.date.desc(), Transaction.created_at.desc()).all()


@router.get("/summary", response_model=TransactionSummary)
def get_summary(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
):
    q = db.query(Transaction)
    if start_date:
        q = q.filter(Transaction.date >= start_date)
    if end_date:
        q = q.filter(Transaction.date <= end_date)

    transactions = q.all()

    # "transfer" type (inter-account / internal movements) is excluded from both
    # income and expense totals so it does not inflate the dashboard figures.
    total_income = sum(t.amount for t in transactions if t.type == "income")
    total_expenses = sum(t.amount for t in transactions if t.type == "expense")

    by_category: dict[str, float] = defaultdict(float)
    expense_by_category: dict[str, float] = defaultdict(float)
    income_by_category: dict[str, float] = defaultdict(float)
    for t in transactions:
        if t.type == "transfer":
            continue  # transfers don't contribute to category breakdowns
        by_category[t.category] += t.amount
        if t.type == "expense":
            expense_by_category[t.category] += t.amount
        else:
            income_by_category[t.category] += t.amount

    # Build monthly data — sort by YYYY-MM key (not display string) for correct order
    monthly_map: dict[str, dict] = {}
    for t in transactions:
        key = t.date.strftime("%Y-%m")
        if key not in monthly_map:
            monthly_map[key] = {"month": t.date.strftime("%b %Y"), "income": 0.0, "expenses": 0.0}
        if t.type == "income":
            monthly_map[key]["income"] += t.amount
        else:
            monthly_map[key]["expenses"] += t.amount

    monthly = [MonthlySummary(**monthly_map[k]) for k in sorted(monthly_map.keys())]

    return TransactionSummary(
        total_income=total_income,
        total_expenses=total_expenses,
        balance=total_income - total_expenses,
        by_category=dict(by_category),
        expense_by_category=dict(expense_by_category),
        income_by_category=dict(income_by_category),
        monthly=monthly,
    )


@router.post("", response_model=TransactionOut, status_code=201)
def create_transaction(data: TransactionCreate, db: Session = Depends(get_db)):
    tx = Transaction(**data.model_dump())
    db.add(tx)
    db.flush()
    _log(db, tx.id, "create", new=data.model_dump(mode="json"))
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
    db.delete(tx)
    db.commit()
    return {"ok": True}
