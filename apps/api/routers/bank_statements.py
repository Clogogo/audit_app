"""
Bank statement import: CSV, Excel, PDF
Leverages modular parsers for all file formats with AI fallback for PDF
"""
import json
import logging
import uuid
from datetime import date
from pathlib import Path
from typing import Optional

import pandas as pd
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

import ai_worker
from database import get_db
from models import AuditLog, BankAccount, BankStatement, BankTransaction, Transaction
from parsers.category_suggester import ai_suggest_categories_batch, suggest_category_keyword
from parsers.file_parsers import detect_file_type, parse_csv, parse_excel, parse_pdf
from parsers.statement_parser import (
    find_header_row_index,
    normalize_dataframe,
    replace_blank_column_names,
)
from routers.duplicates import detect_duplicates_for_transaction, mark_as_duplicates
from schemas import (
    BankAccountReport,
    BankAccountReportSummary,
    BankStatementOut,
    BankTransactionOut,
    StatementImportItem,
    StatementImportRequest,
    StatementImportResult,
    TransactionOut,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/bank-statements", tags=["bank-statements"])

import os
BASE_DIR = Path(__file__).parent.parent.parent.parent
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", str(BASE_DIR / "uploads")))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _parse_dataframe(df_raw: pd.DataFrame, bank_name: str = None) -> list[dict]:
    """
    Try to parse with existing column names.
    If that yields nothing, scan for the actual header row first.
    """
    # Attempt 1: use existing columns
    df = replace_blank_column_names(df_raw)
    rows = normalize_dataframe(df, bank_name=bank_name)
    if rows:
        return rows

    # Attempt 2: find the header row and slice from there
    header_idx = find_header_row_index(df_raw)
    if header_idx is None:
        logger.warning("Could not locate a header row in DataFrame")
        return []

    new_df = df_raw.iloc[header_idx + 1 :].copy()
    new_df.columns = [str(v) for v in df_raw.iloc[header_idx]]
    new_df = replace_blank_column_names(new_df)
    return normalize_dataframe(new_df, bank_name=bank_name)


def _find_duplicate_transaction(
    db: Session,
    item: StatementImportItem,
    bank_name: str,
    reference: Optional[str] = None,
) -> Optional[Transaction]:
    """
    Check if a matching Transaction already exists in the database.

    Priority:
    1. Reference match — if the bank transaction has a unique reference (e.g. OPay
       transaction ID), look for an existing Transaction whose description contains it.
    2. Exact date + exact amount + same bank — high-confidence duplicate.
    3. Exact date + exact amount (no bank info) — medium-confidence duplicate,
       only returned if there is exactly one candidate.
    """
    from sqlalchemy import func

    # ── Reference-based match ─────────────────────────────────────────────────
    if reference:
        ref_match = db.query(Transaction).filter(Transaction.description.contains(reference)).first()
        if ref_match:
            return ref_match

    # ── Exact date + exact amount ─────────────────────────────────────────────
    candidates = (
        db.query(Transaction)
        .filter(
            Transaction.date == item.date,
            func.abs(Transaction.amount - item.amount) <= 0.01,
        )
        .all()
    )
    if not candidates:
        return None

    # Prefer matches that also share the same bank
    bank_matches = [tx for tx in candidates if tx.bank and tx.bank.lower() == bank_name.lower()]
    if bank_matches:
        return bank_matches[0]

    # Only return if unambiguous (exactly one candidate)
    if len(candidates) == 1:
        return candidates[0]

    return None


# ─────────────────────────────────────────────────────────────────────────────
# API Endpoints
# ─────────────────────────────────────────────────────────────────────────────


@router.post("", response_model=BankStatementOut, status_code=201)
async def upload_bank_statement(
    file: UploadFile = File(...),
    bank_name: str = Form(...),
    db: Session = Depends(get_db),
):
    """Upload and parse a bank statement (CSV, Excel, or PDF)."""
    contents = await file.read()
    file_type = detect_file_type(file.content_type or "", file.filename or "")

    # Only save PDFs to disk (pdfplumber requires file path)
    # CSV/Excel are parsed from memory and don't need to be saved
    stored_path = None
    if file_type == "pdf":
        ext = Path(file.filename or "file").suffix
        stored_name = f"{uuid.uuid4().hex}{ext}"
        stored_path = UPLOAD_DIR / stored_name
        stored_path.write_bytes(contents)

    # Parse based on file type
    if file_type == "csv":
        rows = parse_csv(contents, bank_name=bank_name)
    elif file_type == "excel":
        rows = parse_excel(contents, bank_name=bank_name)
    else:
        rows = parse_pdf(str(stored_path))

    if not rows:
        # Add debugging info to help user understand why parsing failed
        error_msg = (
            "No transactions were parsed from this file. "
            "Check that the file is a valid bank statement with Date, "
            "Description and Amount/Debit/Credit columns."
        )

        # Try to get column info from the raw data for debugging
        debug_info = None
        try:
            if file_type == "csv":
                import pandas as pd
                from io import BytesIO
                df = pd.read_csv(BytesIO(contents), nrows=5)
                debug_info = f"Columns found: {', '.join(df.columns.tolist())}"
            elif file_type == "excel":
                import pandas as pd
                from io import BytesIO
                df = pd.read_excel(BytesIO(contents), nrows=5)
                debug_info = f"Columns found: {', '.join(df.columns.tolist())}"
        except Exception as e:
            logger.debug(f"Could not extract column info for debugging: {e}")

        if debug_info:
            error_msg += f" {debug_info}"

        raise HTTPException(422, error_msg)

    # ── Category & type suggestions ──────────────────────────────────────────
    # Pass 1: fast keyword rules (~85% of common descriptions)
    for r in rows:
        cat, stype = suggest_category_keyword(r["description"], r["transaction_type"])
        r["suggested_category"] = cat
        r["suggested_type"] = stype

    # Pass 2: AI for rows marked as "Other"
    rows = ai_suggest_categories_batch(rows)

    # Save statement and transactions
    stmt = BankStatement(
        bank_name=bank_name,
        file_path=str(stored_path) if stored_path else None,
        file_type=file_type,
        status="pending",
    )
    db.add(stmt)
    db.flush()

    for row in rows:
        db.add(BankTransaction(statement_id=stmt.id, **row))

    db.commit()
    db.refresh(stmt)

    out = BankStatementOut.model_validate(stmt)
    out.transaction_count = len(rows)
    out.matched_count = 0
    return out


@router.get("", response_model=list[BankStatementOut])
def list_bank_statements(db: Session = Depends(get_db)):
    """List all bank statements."""
    statements = db.query(BankStatement).order_by(BankStatement.created_at.desc()).all()
    result = []
    for s in statements:
        out = BankStatementOut.model_validate(s)
        out.transaction_count = len(s.bank_transactions)
        out.matched_count = sum(1 for t in s.bank_transactions if t.match_status == "matched")
        result.append(out)
    return result


@router.delete("/{stmt_id}", status_code=204)
def delete_bank_statement(stmt_id: int, db: Session = Depends(get_db)):
    """Delete a bank statement and all its bank transactions."""
    stmt = db.get(BankStatement, stmt_id)
    if not stmt:
        raise HTTPException(404, "Statement not found")
    db.delete(stmt)  # cascade deletes all BankTransaction rows
    db.commit()


from pydantic import BaseModel as _PydanticBase


class _BatchDeleteRequest(_PydanticBase):
    ids: list[int]


@router.post("/batch-delete", status_code=200)
def batch_delete_bank_statements(body: _BatchDeleteRequest, db: Session = Depends(get_db)):
    """Delete multiple bank statements by ID."""
    deleted = 0
    for stmt_id in body.ids:
        stmt = db.get(BankStatement, stmt_id)
        if stmt:
            db.delete(stmt)
            deleted += 1
    db.commit()
    return {"deleted": deleted}


@router.get("/{stmt_id}/transactions", response_model=list[BankTransactionOut])
def list_bank_transactions(stmt_id: int, db: Session = Depends(get_db)):
    """List all bank transactions for a statement."""
    stmt = db.get(BankStatement, stmt_id)
    if not stmt:
        raise HTTPException(404, "Statement not found")
    return (
        db.query(BankTransaction)
        .filter(BankTransaction.statement_id == stmt_id)
        .order_by(BankTransaction.date)
        .all()
    )


@router.post("/{stmt_id}/import-transactions", response_model=StatementImportResult, status_code=201)
def import_statement_transactions(
    stmt_id: int,
    req: StatementImportRequest,
    db: Session = Depends(get_db),
):
    """
    Convert selected BankTransactions into real Transactions.
    Automatically detects duplicates and links them to existing transactions
    for reconciliation instead of creating duplicates.
    """
    stmt = db.get(BankStatement, stmt_id)
    if not stmt:
        raise HTTPException(404, "Statement not found")

    saved_count = 0
    reconciled_count = 0
    new_transactions = []

    for item in req.items:
        bank_tx = db.get(BankTransaction, item.bank_transaction_id)
        if not bank_tx or bank_tx.statement_id != stmt_id:
            continue

        # Already matched — skip entirely
        if bank_tx.match_status == "matched" and bank_tx.matched_transaction_id:
            reconciled_count += 1
            continue

        # Duplicate check
        existing = _find_duplicate_transaction(
            db, item, stmt.bank_name, bank_tx.reference
        )

        if existing:
            bank_tx.matched_transaction_id = existing.id
            bank_tx.match_status = "matched"
            bank_tx.match_confidence = 1.0
            db.add(
                AuditLog(
                    entity_type="reconciliation",
                    entity_id=bank_tx.id,
                    action="match",
                    new_values=json.dumps(
                        {
                            "bank_tx_id": bank_tx.id,
                            "transaction_id": existing.id,
                            "method": "duplicate_import",
                            "reason": "same date and amount already in transactions",
                        }
                    ),
                )
            )
            reconciled_count += 1
            continue

        # Create new Transaction
        tx_vendor = item.vendor or bank_tx.vendor

        tx = Transaction(
            type=item.type,
            amount=item.amount,
            currency=item.currency,
            category=item.category,
            description=item.description,
            date=item.date,
            vendor=tx_vendor,
            bank=stmt.bank_name,
            bank_account_id=req.bank_account_id,
        )
        db.add(tx)
        db.flush()

        bank_tx.matched_transaction_id = tx.id
        bank_tx.match_status = "matched"
        bank_tx.match_confidence = 1.0

        db.add(
            AuditLog(
                entity_type="transaction",
                entity_id=tx.id,
                action="create",
                new_values=json.dumps(
                    {
                        "type": item.type,
                        "amount": item.amount,
                        "category": item.category,
                        "description": item.description,
                        "date": str(item.date),
                        "bank": stmt.bank_name,
                        "source": "statement_import",
                    }
                ),
            )
        )
        saved_count += 1
        new_transactions.append(tx)

    db.commit()

    # ── Duplicate Detection & Resolution ──────────────────────────────────────
    duplicates_flagged = 0
    duplicates_resolved = 0
    resolution_mode = req.resolution_mode.lower()

    if resolution_mode not in ["manual", "auto"]:
        resolution_mode = "manual"

    for tx in new_transactions:
        matches = detect_duplicates_for_transaction(db, tx)

        if matches:
            best_match, confidence = matches[0]

            if resolution_mode == "manual":
                mark_as_duplicates(db, tx, best_match, confidence)
                duplicates_flagged += 1

            elif resolution_mode == "auto":
                if tx.created_at >= best_match.created_at:
                    best_match.is_potential_duplicate = False
                    best_match.duplicate_reviewed = True
                    db.add(
                        AuditLog(
                            entity_type="transaction",
                            entity_id=best_match.id,
                            action="auto_resolve_duplicate",
                            old_values=json.dumps(
                                {"deleted_as_duplicate_of": tx.id}
                            ),
                        )
                    )
                    db.delete(best_match)
                else:
                    tx.is_potential_duplicate = False
                    tx.duplicate_reviewed = True
                    db.add(
                        AuditLog(
                            entity_type="transaction",
                            entity_id=tx.id,
                            action="auto_resolve_duplicate",
                            old_values=json.dumps(
                                {"deleted_as_duplicate_of": best_match.id}
                            ),
                        )
                    )
                    db.delete(tx)
                    saved_count -= 1

                duplicates_resolved += 1

    db.commit()

    return StatementImportResult(
        saved=saved_count,
        reconciled=reconciled_count,
        duplicates_flagged=duplicates_flagged,
        duplicates_resolved=duplicates_resolved,
        statement_id=stmt_id,
    )


# ── Bank Account Reports ─────────────────────────────────────────────────────


@router.get("/bank-accounts", response_model=list[BankAccountReportSummary])
def get_bank_account_reports(
    start_date: Optional[date] = Query(
        None, description="Filter transactions from this date"
    ),
    end_date: Optional[date] = Query(None, description="Filter transactions to this date"),
    db: Session = Depends(get_db),
):
    """Get income and expense summary for all bank accounts."""
    bank_accounts = db.query(BankAccount).all()
    reports = []

    for account in bank_accounts:
        query = db.query(Transaction).filter(
            Transaction.bank_account_id == account.id
        )

        if start_date:
            query = query.filter(Transaction.date >= start_date)
        if end_date:
            query = query.filter(Transaction.date <= end_date)

        transactions = query.all()

        total_income = sum(t.amount for t in transactions if t.type == "income")
        total_expense = sum(t.amount for t in transactions if t.type == "expense")
        total_transfer = sum(t.amount for t in transactions if t.type == "transfer")

        income_count = sum(1 for t in transactions if t.type == "income")
        expense_count = sum(1 for t in transactions if t.type == "expense")
        transfer_count = sum(1 for t in transactions if t.type == "transfer")

        transaction_dates = [t.date for t in transactions]
        first_transaction = min(transaction_dates) if transaction_dates else None
        last_transaction = max(transaction_dates) if transaction_dates else None

        net_amount = total_income - total_expense

        reports.append(
            BankAccountReportSummary(
                bank_account_id=account.id,
                bank_name=account.bank_name,
                account_number=account.account_number,
                total_income=total_income,
                total_expense=total_expense,
                total_transfer=total_transfer,
                net_amount=net_amount,
                income_count=income_count,
                expense_count=expense_count,
                transfer_count=transfer_count,
                total_transactions=len(transactions),
                first_transaction_date=first_transaction,
                last_transaction_date=last_transaction,
                currency="NGN",
            )
        )

    return reports


@router.get("/bank-accounts/{account_id}", response_model=BankAccountReport)
def get_bank_account_report(
    account_id: int,
    start_date: Optional[date] = Query(
        None, description="Filter transactions from this date"
    ),
    end_date: Optional[date] = Query(None, description="Filter transactions to this date"),
    db: Session = Depends(get_db),
):
    """Get detailed income and expense report for a specific bank account."""
    account = db.get(BankAccount, account_id)
    if not account:
        raise HTTPException(404, "Bank account not found")

    query = db.query(Transaction).filter(Transaction.bank_account_id == account_id)

    if start_date:
        query = query.filter(Transaction.date >= start_date)
    if end_date:
        query = query.filter(Transaction.date <= end_date)

    transactions = query.all()

    total_income = sum(t.amount for t in transactions if t.type == "income")
    total_expense = sum(t.amount for t in transactions if t.type == "expense")
    total_transfer = sum(t.amount for t in transactions if t.type == "transfer")

    income_count = sum(1 for t in transactions if t.type == "income")
    expense_count = sum(1 for t in transactions if t.type == "expense")
    transfer_count = sum(1 for t in transactions if t.type == "transfer")

    expense_by_category = {}
    for t in transactions:
        if t.type == "expense":
            category = t.category or "Uncategorized"
            expense_by_category[category] = expense_by_category.get(category, 0) + t.amount

    income_by_category = {}
    for t in transactions:
        if t.type == "income":
            category = t.category or "Uncategorized"
            income_by_category[category] = income_by_category.get(category, 0) + t.amount

    monthly_data = {}
    for t in transactions:
        month_key = t.date.strftime("%Y-%m")
        if month_key not in monthly_data:
            monthly_data[month_key] = {"income": 0, "expense": 0, "transfer": 0}

        if t.type == "income":
            monthly_data[month_key]["income"] += t.amount
        elif t.type == "expense":
            monthly_data[month_key]["expense"] += t.amount
        elif t.type == "transfer":
            monthly_data[month_key]["transfer"] += t.amount

    transaction_dates = [t.date for t in transactions]
    first_transaction = min(transaction_dates) if transaction_dates else None
    last_transaction = max(transaction_dates) if transaction_dates else None

    return BankAccountReport(
        bank_account_id=account.id,
        bank_name=account.bank_name,
        account_number=account.account_number,
        total_income=total_income,
        total_expense=total_expense,
        total_transfer=total_transfer,
        net_amount=total_income - total_expense,
        income_count=income_count,
        expense_count=expense_count,
        transfer_count=transfer_count,
        total_transactions=len(transactions),
        expense_by_category=expense_by_category,
        income_by_category=income_by_category,
        monthly_breakdown=monthly_data,
        first_transaction_date=first_transaction,
        last_transaction_date=last_transaction,
        currency="NGN",
    )
