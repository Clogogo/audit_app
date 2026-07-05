import json
import logging
from datetime import date, datetime
from typing import Optional
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Query
from utils.auth import require_permission
from utils.errors import get_or_404
from sqlalchemy.orm import Session
from sqlalchemy import func, select as sa_select

from database import get_db
from llm_providers import get_llm_client
from models import Transaction, AuditLog, BankAccount, Staff, PayrollEntry, Term
from pydantic import BaseModel as _BaseModel
from schemas import TransactionCreate, TransactionOut, TransactionPage, TransactionUpdate, TransactionSummary, TransactionAISummary, MonthlySummary
from routers.bank_statements import _transfer_is_income, _is_intra_account_transfer


class _BatchCategoryUpdate(_BaseModel):
    ids: list[int]
    category: str

router = APIRouter(prefix="/transactions", tags=["transactions"], dependencies=[Depends(require_permission("transactions"))])


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
    forecast: Optional[dict] = None,
) -> tuple:
    # The projection moves forward every day even when no new transactions
    # exist, so today's date must be part of the key whenever a forecast is
    # active — otherwise yesterday's forecast would be served forever.
    forecast_key = (
        forecast["term_id"], date.today().isoformat(),
        round(forecast["remaining_payroll"], 2),
        round(forecast["projected_income_remaining"], 2),
        round(forecast["projected_nonpayroll_expense_remaining"], 2),
        round(forecast["projected_term_end_surplus"], 2),
    ) if forecast is not None else None
    return (
        start_date, end_date, bank, vendor,
        round(summary.total_income, 2),
        round(summary.total_expenses, 2),
        round(summary.balance, 2),
        tuple((m.month, round(m.income, 2), round(m.expenses, 2)) for m in summary.monthly[-6:]),
        tuple(sorted((k, round(v, 2)) for k, v in summary.by_category.items())),
        forecast_key,
    )


def _iter_year_months(start: date, end: date):
    """Yield (year, month) tuples from start through end, inclusive."""
    if start > end:
        return
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield y, m
        m += 1
        if m > 12:
            m = 1
            y += 1


def _build_term_forecast(term: Term, summary: TransactionSummary, db: Session) -> dict:
    """
    Forecast whether this term's profit will cover the remaining staff
    payroll before the term ends, and the projected surplus/deficit after.

    Uses a simple linear run-rate on this term's own income/expense pace so
    far — no seasonal modeling, no comparison to prior terms. Salary expenses
    already paid ("Salary and Wages" transactions) are split out of the
    historical total so they aren't double-counted against the
    forward-looking remaining_payroll figure below.
    """
    today = date.today()
    total_days = (term.end_date - term.start_date).days + 1
    elapsed_days = max(0, min((today - term.start_date).days + 1, total_days))
    remaining_days = total_days - elapsed_days

    active_staff = db.query(Staff).filter(Staff.is_active == True).all()
    active_staff_ids = [s.id for s in active_staff]
    active_monthly_cost = sum(s.monthly_gross for s in active_staff)

    remaining_months = 0
    if active_staff_ids:
        walk_start = max(today, term.start_date)
        months = list(_iter_year_months(walk_start, term.end_date))
        if months:
            # One query for every candidate month, not one query per month.
            paid_rows = (
                db.query(PayrollEntry.period_year, PayrollEntry.period_month, func.count(PayrollEntry.id))
                .filter(
                    PayrollEntry.staff_id.in_(active_staff_ids),
                    PayrollEntry.is_paid == True,
                    PayrollEntry.period_year.in_({year for year, _ in months}),
                )
                .group_by(PayrollEntry.period_year, PayrollEntry.period_month)
                .all()
            )
            paid_counts = {(year, month): count for year, month, count in paid_rows}
            # A month with only some active staff already paid still counts
            # as fully remaining — a simplification, not precise partial
            # tracking, since that would need a per-staff shortfall figure.
            for year, month in months:
                if paid_counts.get((year, month), 0) < len(active_staff_ids):
                    remaining_months += 1
    remaining_payroll = round(active_monthly_cost * remaining_months, 2)

    salary_expense_so_far = db.execute(
        sa_select(func.coalesce(func.sum(Transaction.amount), 0.0))
        .where(
            Transaction.type == "expense",
            Transaction.category == "Salary and Wages",
            Transaction.date >= term.start_date,
            Transaction.date <= term.end_date,
        )
    ).scalar() or 0.0

    non_payroll_expenses_so_far = summary.total_expenses - salary_expense_so_far
    daily_income_rate = summary.total_income / elapsed_days if elapsed_days > 0 else 0.0
    daily_nonpayroll_expense_rate = non_payroll_expenses_so_far / elapsed_days if elapsed_days > 0 else 0.0
    projected_income_remaining = round(daily_income_rate * remaining_days, 2)
    projected_nonpayroll_expense_remaining = round(daily_nonpayroll_expense_rate * remaining_days, 2)

    current_net_position = round(summary.total_income - summary.total_expenses, 2)
    projected_term_end_surplus = round(
        current_net_position
        + projected_income_remaining
        - projected_nonpayroll_expense_remaining
        - remaining_payroll,
        2,
    )

    return {
        "term_id": term.id,
        "term_name": term.name,
        "start_date": term.start_date.isoformat(),
        "end_date": term.end_date.isoformat(),
        "total_days": total_days,
        "elapsed_days": elapsed_days,
        "remaining_days": remaining_days,
        "active_staff_count": len(active_staff_ids),
        "remaining_months": remaining_months,
        "remaining_payroll": remaining_payroll,
        "current_net_position": current_net_position,
        "projected_income_remaining": projected_income_remaining,
        "projected_nonpayroll_expense_remaining": projected_nonpayroll_expense_remaining,
        "projected_term_end_surplus": projected_term_end_surplus,
    }


def _build_ai_summary_prompt(summary: TransactionSummary, forecast: Optional[dict] = None) -> str:
    top_categories = sorted(summary.by_category.items(), key=lambda kv: -abs(kv[1]))[:5]
    categories_text = ", ".join(f"{name}: ₦{amount:,.2f}" for name, amount in top_categories)
    monthly_text = "; ".join(
        f"{m.month}: income ₦{m.income:,.2f}, expenses ₦{m.expenses:,.2f}"
        for m in summary.monthly[-6:]
    )

    forecast_instruction = ""
    forecast_text = ""
    if forecast:
        forecast_instruction = (
            " In the Forecast section, state whether the school's profit is on "
            "track to cover the remaining staff payroll before the term ends, "
            "and whether a surplus or shortfall is projected."
        )
        forecast_text = (
            f"\n\nTerm: {forecast['term_name']} ({forecast['start_date']} to {forecast['end_date']}), "
            f"{forecast['elapsed_days']} of {forecast['total_days']} days elapsed, "
            f"{forecast['remaining_days']} days remaining.\n"
            f"Remaining staff payroll obligation for the rest of the term "
            f"({forecast['remaining_months']} month(s) not yet paid, "
            f"{forecast['active_staff_count']} active staff): ₦{forecast['remaining_payroll']:,.2f}\n"
            f"Current net position this term so far (income minus expenses): "
            f"₦{forecast['current_net_position']:,.2f}\n"
            f"Projected income for the remaining {forecast['remaining_days']} days "
            f"(based on this term's pace so far): ₦{forecast['projected_income_remaining']:,.2f}\n"
            f"Projected non-payroll expenses for the remaining days: "
            f"₦{forecast['projected_nonpayroll_expense_remaining']:,.2f}\n"
            f"Projected surplus/deficit at the end of the term after paying all "
            f"remaining staff salaries: ₦{forecast['projected_term_end_surplus']:,.2f}"
        )

    return (
        "You are advising the leadership of a small school organization in "
        "Nigeria, wearing four hats at once: financial analyst, fund manager, "
        "financial controller, and development manager. All amounts are in "
        "Nigerian Naira — always use the ₦ symbol, never £, $, or any other "
        "currency.\n\n"
        "Answer exactly these questions, in this order, as four short "
        "paragraphs (2-3 sentences each), plain prose with no bullet points "
        "or numbered lists. Start each paragraph with its bold label exactly "
        "as written below, followed by a colon, then a blank line between "
        "paragraphs:\n\n"
        "**Financial Position:** What is my financial statement right now — "
        "overall position, notable spending categories, and any trend over "
        "the recent months?\n"
        "**Areas to Improve:** Given this data, what specifically should be "
        "improved — overspending categories, inefficiencies, or missed "
        "revenue opportunities?\n"
        "**Plan:** What concrete actions should leadership prioritize over "
        "the next period to act on that?\n"
        "**Forecast:** Based on the recent trend, where is this heading "
        f"next, and what should be planned for?{forecast_instruction}\n\n"
        f"Total income: ₦{summary.total_income:,.2f}\n"
        f"Total expenses: ₦{summary.total_expenses:,.2f}\n"
        f"Balance: ₦{summary.balance:,.2f}\n"
        f"Top categories: {categories_text}\n"
        f"Recent months: {monthly_text}"
        f"{forecast_text}"
    )


@router.get("/ai-summary", response_model=TransactionAISummary)
def get_ai_summary(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    bank: Optional[str] = Query(None),
    vendor: Optional[str] = Query(None),
    term_id: Optional[int] = Query(None, description="When set, also forecasts whether profit covers the remaining term payroll"),
    db: Session = Depends(get_db),
):
    """AI-generated narrative over the same data as GET /transactions/summary.
    When term_id is given, the term's own start/end dates are authoritative —
    they override start_date/end_date so the narrative and the payroll
    forecast always describe the same period, regardless of what date_range
    the caller separately passed. Never raises on AI failure — returns
    available=False instead, so the frontend can simply omit the summary
    card rather than show an error."""
    term = None
    if term_id is not None:
        term = get_or_404(db, Term, term_id, "Term")
        start_date, end_date = term.start_date, term.end_date

    summary = get_summary(start_date=start_date, end_date=end_date, bank=bank, vendor=vendor, db=db)

    forecast = _build_term_forecast(term, summary, db) if term is not None else None

    cache_key = _ai_summary_cache_key(start_date, end_date, bank, vendor, summary, forecast)
    cached = _AI_SUMMARY_CACHE.get(cache_key)
    if cached is not None:
        return TransactionAISummary(narrative=cached, available=True)

    try:
        client = get_llm_client()
        narrative = client.create_message(
            messages=[{"role": "user", "content": _build_ai_summary_prompt(summary, forecast)}],
            max_tokens=1500,
            # The configured model may be a reasoning model whose internal
            # chain-of-thought is billed against max_tokens too — on "medium"/
            # default effort it can consume the whole budget before ever
            # writing the four-section answer. Providers that don't support
            # this field simply ignore it.
            extra_body={"reasoning": {"effort": "low"}},
        )
    except Exception as e:
        logger.warning(
            "AI summary generation failed, returning available=False: %s",
            e,
            exc_info=True,
        )
        return TransactionAISummary(narrative=None, available=False)

    if len(_AI_SUMMARY_CACHE) >= _AI_SUMMARY_CACHE_MAX:
        try:
            _AI_SUMMARY_CACHE.pop(next(iter(_AI_SUMMARY_CACHE)))
        except (StopIteration, KeyError):
            pass
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
