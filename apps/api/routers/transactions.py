import json
from datetime import date, datetime
from typing import Optional
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func

from database import get_db
from models import Transaction, AuditLog
from schemas import TransactionCreate, TransactionOut, TransactionUpdate, TransactionSummary, MonthlySummary

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

    total_income = sum(t.amount for t in transactions if t.type == "income")
    total_expenses = sum(t.amount for t in transactions if t.type == "expense")

    by_category: dict[str, float] = defaultdict(float)
    for t in transactions:
        if t.type == "expense":
            by_category[t.category] += t.amount

    # Build monthly data
    monthly_map: dict[str, dict] = {}
    for t in transactions:
        key = t.date.strftime("%Y-%m")
        if key not in monthly_map:
            monthly_map[key] = {"month": t.date.strftime("%b %Y"), "income": 0.0, "expenses": 0.0}
        if t.type == "income":
            monthly_map[key]["income"] += t.amount
        else:
            monthly_map[key]["expenses"] += t.amount

    monthly = [MonthlySummary(**v) for v in sorted(monthly_map.values(), key=lambda x: x["month"])]

    return TransactionSummary(
        total_income=total_income,
        total_expenses=total_expenses,
        balance=total_income - total_expenses,
        by_category=dict(by_category),
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
    for k, v in updates.items():
        setattr(tx, k, v)
    tx.updated_at = datetime.utcnow()

    _log(db, tx_id, "update", old={k: str(v) for k, v in old.items()}, new={k: str(v) for k, v in updates.items()})
    db.commit()
    db.refresh(tx)
    return tx


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
