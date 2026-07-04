"""
LLM-Based Bank Statement Parser Routes
Endpoints for uploading and parsing Nigerian bank statements using Claude's vision API
"""
import io
import json
import logging
from datetime import date as date_type
from collections import defaultdict
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from utils.auth import require_permission
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import get_db
from models import BankStatement, BankTransaction, Transaction, AuditLog, BankAccount
from schemas import (
    LLMStatementUploadResult,
    LLMBankStatementMetadata,
    LLMStatementParseResult,
    LLMStatementImportRequest,
    LLMStatementImportResult,
    BankTransactionOut,
)
from llm_statement_parser import (
    LLMBankStatementParser,
    NigerianBankClassifier,
    StatementValidator,
)
import ai_worker
import os as _os

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/bank-statements-llm", tags=["bank-statements-llm"], dependencies=[Depends(require_permission("banking"))])


BASE_DIR = Path(__file__).parent.parent.parent.parent
UPLOAD_DIR = Path(_os.getenv("UPLOAD_DIR", str(BASE_DIR / "uploads")))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


# ── Helper Functions ──────────────────────────────────────────────────────────

def _save_uploaded_file(file: UploadFile) -> str:
    """Save uploaded file and return path."""
    file_name = file.filename or "statement.pdf"
    file_path = UPLOAD_DIR / "bank_statements" / file_name

    file_path.parent.mkdir(parents=True, exist_ok=True)

    with open(file_path, "wb") as f:
        f.write(file.file.read())

    logger.info(f"Saved bank statement: {file_path}")
    return str(file_path)


def _metadata_to_schema(metadata) -> LLMBankStatementMetadata:
    """Convert parser metadata to Pydantic schema."""
    return LLMBankStatementMetadata(
        bank_name=metadata.bank_name,
        account_number=metadata.account_number,
        account_holder=metadata.account_holder,
        statement_period_start=metadata.statement_period_start,
        statement_period_end=metadata.statement_period_end,
        opening_balance=metadata.opening_balance,
        closing_balance=metadata.closing_balance,
        currency=metadata.currency,
        statement_date=metadata.statement_date,
    )


def _resolve_bank_account_id(db: Session, requested_account_id: Optional[int], metadata) -> Optional[int]:
    if requested_account_id is not None:
        return requested_account_id

    bank_name = getattr(metadata, "bank_name", None)
    account_number = getattr(metadata, "account_number", None)
    if not bank_name or not account_number:
        return None

    normalized_bank_name = bank_name.strip().lower()
    normalized_account_number = account_number.strip()

    exact_match = (
        db.query(BankAccount.id)
        .filter(
            func.lower(BankAccount.bank_name) == normalized_bank_name,
            BankAccount.account_number == normalized_account_number,
        )
        .scalar()
    )

    if exact_match is not None:
        return exact_match

    if len(normalized_account_number) >= 4:
        suffix_matches = (
            db.query(BankAccount.id)
            .filter(
                func.lower(BankAccount.bank_name) == normalized_bank_name,
                BankAccount.account_number.like(f"%{normalized_account_number[-4:]}")
            )
            .all()
        )
        if len(suffix_matches) == 1:
            return suffix_matches[0][0]

    return None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/parse", response_model=LLMStatementParseResult)
async def parse_bank_statement(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """
    Upload and parse a Nigerian bank statement using LLM (Claude Vision API).

    Supports:
    - PDF bank statements
    - All major Nigerian banks (GTBank, Access, Zenith, UBA, etc.)
    - Moniepoint, OPay, and other fintech statements

    Returns:
    - Extracted metadata (bank name, account info, period, balances)
    - All transactions with categorization suggestions
    - Quality assessment and validation issues
    """
    try:
        # Validate file type
        if file.content_type != "application/pdf":
            raise HTTPException(
                status_code=400,
                detail=f"Invalid file type: {file.content_type}. Only PDF supported.",
            )

        # Save file
        file_path = _save_uploaded_file(file)

        # Parse with LLM
        logger.info(f"Parsing statement: {file.filename}")
        parser = LLMBankStatementParser()
        parsed_statement = parser.parse_statement(file_path)

        # Validate
        validation_issues = StatementValidator.get_validation_issues(
            parsed_statement.metadata, parsed_statement.transactions
        )

        # Convert to schema
        result = LLMStatementParseResult(
            metadata=_metadata_to_schema(parsed_statement.metadata),
            transactions=[
                {
                    "date": tx.date,
                    "description": tx.description,
                    "amount": tx.amount,
                    "transaction_type": tx.transaction_type,
                    "balance_after": tx.balance_after,
                    "reference": tx.reference,
                    "vendor": tx.vendor,
                    "category_suggested": tx.category_suggested,
                    "confidence": tx.confidence,
                }
                for tx in parsed_statement.transactions
            ],
            extraction_quality=parsed_statement.extraction_quality,
            validation_issues=validation_issues,
        )

        logger.info(f"Successfully parsed {len(parsed_statement.transactions)} transactions")
        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to parse bank statement: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to parse statement: {str(e)}",
        )


@router.post("/upload", response_model=LLMStatementUploadResult, status_code=201)
async def upload_bank_statement(
    file: UploadFile = File(...),
    bank_account_id: Optional[int] = Form(None),
    db: Session = Depends(get_db),
):
    """
    Upload a Nigerian bank statement PDF and create a statement record with extracted transactions.

    The statement is parsed using LLM and transactions are stored in the database.
    You can link it to a bank account and later review/import transactions.

    Query params:
    - bank_account_id: Link statement to a specific bank account (optional)

    Returns:
    - Statement ID
    - Parsed metadata (bank name, account info, dates, balances)
    - Number of transactions extracted
    - Extraction quality and validation issues
    """
    try:
        # Validate file type
        if file.content_type != "application/pdf":
            raise HTTPException(
                status_code=400,
                detail=f"Invalid file type: {file.content_type}. Only PDF supported.",
            )

        # Save file
        file_path = _save_uploaded_file(file)

        # Parse with LLM
        logger.info(f"Uploading and parsing: {file.filename}")
        parser = LLMBankStatementParser()
        parsed_statement = parser.parse_statement(file_path)

        # Validate
        validation_issues = StatementValidator.get_validation_issues(
            parsed_statement.metadata, parsed_statement.transactions
        )

        # Identify bank
        bank_code = NigerianBankClassifier.identify_bank(parsed_statement.metadata.bank_name)
        resolved_bank_account_id = _resolve_bank_account_id(
            db,
            bank_account_id,
            parsed_statement.metadata,
        )

        # Create BankStatement record
        account_last4 = None
        if parsed_statement.metadata.account_number:
            account_last4 = parsed_statement.metadata.account_number[-4:]

        stmt = BankStatement(
            bank_name=parsed_statement.metadata.bank_name,
            account_last4=account_last4,
            bank_account_id=resolved_bank_account_id,
            statement_period_start=_parse_date(
                parsed_statement.metadata.statement_period_start
            ),
            statement_period_end=_parse_date(
                parsed_statement.metadata.statement_period_end
            ),
            file_path=file_path,
            file_type="pdf",
            status="pending",
        )
        db.add(stmt)
        db.flush()

        # Create BankTransaction records
        for idx, tx in enumerate(parsed_statement.transactions):
            bank_tx = BankTransaction(
                statement_id=stmt.id,
                date=_parse_date(tx.date),
                description=tx.description,
                amount=tx.amount,
                transaction_type=tx.transaction_type,
                reference=tx.reference,
                vendor=tx.vendor,
                suggested_category=tx.category_suggested,
                suggested_type="expense" if tx.transaction_type == "debit" else "income",
                match_status="unmatched",
                match_confidence=tx.confidence,
            )
            db.add(bank_tx)

        db.commit()

        # Log audit
        audit_log = AuditLog(
            entity_type="bank_statement",
            entity_id=stmt.id,
            action="created",
            new_values=json.dumps(
                {
                    "bank_name": stmt.bank_name,
                    "transaction_count": len(parsed_statement.transactions),
                    "extraction_quality": parsed_statement.extraction_quality,
                }
            ),
        )
        db.add(audit_log)
        db.commit()

        return LLMStatementUploadResult(
            statement_id=stmt.id,
            file_name=file.filename,
            bank_name=parsed_statement.metadata.bank_name,
            statement_period_start=parsed_statement.metadata.statement_period_start,
            statement_period_end=parsed_statement.metadata.statement_period_end,
            transaction_count=len(parsed_statement.transactions),
            extraction_quality=parsed_statement.extraction_quality,
            validation_issues=validation_issues,
            metadata=_metadata_to_schema(parsed_statement.metadata),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to upload bank statement: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to upload statement: {str(e)}",
        )


@router.get("/{stmt_id}/transactions", response_model=list[BankTransactionOut])
async def get_statement_transactions(
    stmt_id: int,
    db: Session = Depends(get_db),
):
    """Get all transactions from an uploaded bank statement."""
    stmt = db.query(BankStatement).filter(BankStatement.id == stmt_id).first()
    if not stmt:
        raise HTTPException(status_code=404, detail="Statement not found")

    transactions = (
        db.query(BankTransaction)
        .filter(BankTransaction.statement_id == stmt_id)
        .all()
    )

    return [
        BankTransactionOut(
            id=tx.id,
            statement_id=tx.statement_id,
            date=tx.date,
            description=tx.description,
            amount=tx.amount,
            transaction_type=tx.transaction_type,
            reference=tx.reference,
            vendor=tx.vendor,
            matched_transaction_id=tx.matched_transaction_id,
            match_status=tx.match_status,
            match_confidence=tx.match_confidence,
            suggested_category=tx.suggested_category,
            suggested_type=tx.suggested_type,
            created_at=tx.created_at,
        )
        for tx in transactions
    ]


@router.post("/{stmt_id}/import", response_model=LLMStatementImportResult, status_code=201)
async def import_statement_transactions(
    stmt_id: int,
    request: LLMStatementImportRequest,
    db: Session = Depends(get_db),
):
    """
    Import selected transactions from a bank statement into the system.

    Transactions are created in the Transaction table for use in financial tracking.
    """
    stmt = db.query(BankStatement).filter(BankStatement.id == stmt_id).first()
    if not stmt:
        raise HTTPException(status_code=404, detail="Statement not found")

    saved_count = 0
    reconciled_count = 0
    bank_transactions = (
        db.query(BankTransaction)
        .filter(BankTransaction.statement_id == stmt_id)
        .order_by(BankTransaction.id)
        .all()
    )
    request_dates = sorted({item.date for item in request.items})
    item_indices = [item.transaction_index for item in request.items]
    if len(set(item_indices)) != len(item_indices):
        raise HTTPException(status_code=400, detail="Duplicate transaction_index values in import request")
    existing_transactions = (
        db.query(Transaction)
        .filter(Transaction.date.in_(request_dates))
        .all()
    )
    transactions_by_date: dict[date_type, list[Transaction]] = defaultdict(list)
    for candidate in existing_transactions:
        transactions_by_date[candidate.date].append(candidate)
    used_transaction_ids: set[int] = set()

    for item in request.items:
        # Get the bank transaction for context
        bank_tx = bank_transactions[item.transaction_index] if 0 <= item.transaction_index < len(bank_transactions) else None

        # Create or find matching transaction
        item_description = item.description.lower()
        candidates_for_date = transactions_by_date.get(item.date, [])
        existing_tx = next(
            (
                candidate
                for candidate in candidates_for_date
                if abs(candidate.amount - item.amount) < 0.01
                and item_description in candidate.description.lower()
                and candidate.id not in used_transaction_ids
            ),
            None,
        )

        if existing_tx:
            # Link to existing transaction (reconciliation)
            if bank_tx:
                bank_tx.matched_transaction_id = existing_tx.id
                bank_tx.match_status = "matched"
            used_transaction_ids.add(existing_tx.id)
            reconciled_count += 1
        else:
            # Create new transaction
            tx = Transaction(
                type=item.type,
                amount=item.amount,
                currency=item.currency,
                category=item.category,
                description=item.description,
                date=item.date,
                vendor=item.vendor,
                bank=stmt.bank_name,
                bank_account_id=request.bank_account_id or stmt.bank_account_id,
            )
            db.add(tx)
            db.flush()

            # Link bank transaction if exists
            if bank_tx and not bank_tx.matched_transaction_id:
                bank_tx.matched_transaction_id = tx.id
                bank_tx.match_status = "matched"

            saved_count += 1

    db.commit()

    # Update statement status
    stmt.status = "reconciled"
    db.commit()

    # Log audit
    audit_log = AuditLog(
        entity_type="bank_statement",
        entity_id=stmt_id,
        action="imported",
        new_values=json.dumps(
            {
                "saved_transactions": saved_count,
                "reconciled_transactions": reconciled_count,
            }
        ),
    )
    db.add(audit_log)
    db.commit()

    return LLMStatementImportResult(
        saved=saved_count,
        reconciled=reconciled_count,
        statement_id=stmt_id,
    )


@router.delete("/{stmt_id}", status_code=204)
async def delete_statement(
    stmt_id: int,
    db: Session = Depends(get_db),
):
    """Delete a bank statement and all its transactions."""
    stmt = db.query(BankStatement).filter(BankStatement.id == stmt_id).first()
    if not stmt:
        raise HTTPException(status_code=404, detail="Statement not found")

    # Delete associated transactions
    db.query(BankTransaction).filter(BankTransaction.statement_id == stmt_id).delete()

    # Delete statement
    db.delete(stmt)
    db.commit()

    logger.info(f"Deleted statement {stmt_id}")


# ── Helper for date parsing ─────────────────────────────────────────────────

def _parse_date(date_str: Optional[str]) -> Optional[date_type]:
    """Parse ISO date string to date object."""
    if not date_str:
        return None
    try:
        # Assume ISO format YYYY-MM-DD
        year, month, day = date_str.split("-")
        return date_type(int(year), int(month), int(day))
    except (ValueError, AttributeError):
        return None
