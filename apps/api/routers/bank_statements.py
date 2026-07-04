"""
Bank statement import: CSV, Excel, PDF

Parsing and categorization are fully deterministic (pandas + pdfplumber +
keyword rules) and require no AI. An optional AI categorization pass can be
enabled for residual "Other" rows via ENABLE_AI_CATEGORIZATION=true.
"""
import json
import logging
import uuid
from datetime import date
from pathlib import Path
from typing import Optional

import pandas as pd
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from utils.auth import require_permission
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import get_db
from models import AuditLog, BankAccount, BankStatement, BankTransaction, Transaction
from parsers.category_suggester import ai_suggest_categories_batch, suggest_category_keyword, is_self_transfer
from utils import get_or_404, AuditLogger, TransactionQueryBuilder
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

router = APIRouter(prefix="/bank-statements", tags=["bank-statements"], dependencies=[Depends(require_permission("banking"))])


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
    already_matched_ids: Optional[set[int]] = None,
) -> Optional[Transaction]:
    """
    Check if a matching Transaction already exists in the database.

    Priority:
    1. Reference match — unique transaction reference (e.g. OPay transaction ID).
    2. Exact date + amount + bank + compatible description — the description check
       is critical: multiple workers can receive the same salary amount on the same
       date, so date+amount alone is insufficient.  Two descriptions are "compatible"
       when they share the same first 40 normalised characters.
    3. Exact date + amount + compatible description (no bank info) — only when there
       is exactly one such candidate.

    already_matched_ids: transaction IDs already consumed as matches in this import
    session.  Excluding them ensures that when a bank uses identical descriptions for
    multiple same-amount rows (e.g. "SEPT SALARY" × 3), each row finds a distinct
    existing transaction rather than all mapping to the same one.
    """
    from sqlalchemy import func

    excluded = already_matched_ids or set()
    item_desc = (item.description or "").strip().lower()

    def _desc_compatible(existing: Optional[str]) -> bool:
        ed = (existing or "").strip().lower()
        if not item_desc or not ed:
            return True  # Can't distinguish empty descriptions; be conservative
        return item_desc[:40] == ed[:40]

    # ── Reference-based match ─────────────────────────────────────────────────
    # Priority 1a: a BankTransaction with the same reference already exists and
    # is matched to a Transaction — same reference = definitely the same row,
    # regardless of description. This is the only reliable dedup signal for
    # banks like OPay where multiple rows on the same day share identical
    # descriptions and amounts (e.g. 19 OWealth Withdrawal ₦50 entries on a
    # busy salary day) — they can only be told apart by their unique references.
    if reference:
        existing_bank_tx = (
            db.query(BankTransaction)
            .filter(
                BankTransaction.reference == reference,
                BankTransaction.matched_transaction_id.isnot(None),
                BankTransaction.matched_transaction_id.notin_(excluded) if excluded else True,
            )
            .first()
        )
        if existing_bank_tx:
            return db.get(Transaction, existing_bank_tx.matched_transaction_id)

    # Priority 1b (legacy): reference embedded in the Transaction description
    # — kept for banks that write the reference into the narration field.
    if reference:
        ref_match = (
            db.query(Transaction)
            .filter(
                Transaction.description.contains(reference),
                Transaction.id.notin_(excluded) if excluded else True,
            )
            .first()
        )
        if ref_match:
            return ref_match

    # ── Exact date + exact amount (excluding already-consumed matches) ─────────
    candidates = (
        db.query(Transaction)
        .filter(
            Transaction.date == item.date,
            func.abs(Transaction.amount - item.amount) <= 0.01,
            Transaction.id.notin_(excluded) if excluded else True,
        )
        .all()
    )
    if not candidates:
        return None

    # Require matching bank AND compatible description.
    bank_matches = [tx for tx in candidates if tx.bank and tx.bank.lower() == bank_name.lower()]
    if bank_matches:
        desc_matches = [tx for tx in bank_matches if _desc_compatible(tx.description)]
        return desc_matches[0] if desc_matches else None

    # No same-bank match. Only fall back to an unattributed candidate (no bank
    # set at all) — a candidate already tagged to a *different* bank is a
    # same-day, same-amount coincidence across two real accounts, not a
    # duplicate, no matter how compatible the description looks.
    unattributed = [tx for tx in candidates if not tx.bank]
    desc_matches = [tx for tx in unattributed if _desc_compatible(tx.description)]
    if len(desc_matches) == 1:
        return desc_matches[0]

    return None


# ─────────────────────────────────────────────────────────────────────────────
# API Endpoints
# ─────────────────────────────────────────────────────────────────────────────


@router.post("", response_model=BankStatementOut, status_code=201)
async def upload_bank_statement(
    file: UploadFile = File(...),
    bank_name: str = Form(...),
    account_holder_name: Optional[str] = Form(None),
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
    # Pass 1: deterministic keyword rules — handles the vast majority of common
    # Nigerian statement descriptions with no AI/network dependency.
    # Self-transfers (movements between the holder's own accounts) are forced to
    # type=transfer so they're excluded from income/expense and not double-counted.
    for r in rows:
        if is_self_transfer(r["description"], account_holder_name):
            r["suggested_category"] = "Internal Transfer"
            r["suggested_type"] = "transfer"
        else:
            cat, stype = suggest_category_keyword(r["description"], r["transaction_type"])
            r["suggested_category"] = cat
            r["suggested_type"] = stype

    # Pass 2 (optional): AI refinement for rows still marked "Other".
    # No-op unless ENABLE_AI_CATEGORIZATION=true, so upload stays AI-free by default.
    rows = ai_suggest_categories_batch(rows)

    # Find or create bank account
    from sqlalchemy import func
    bank_account = db.query(BankAccount).filter(
        func.lower(BankAccount.bank_name) == bank_name.lower()
    ).first()

    if not bank_account:
        # Seed the actual balance from the statement's own running-balance
        # column (the most recent dated row), so new accounts aren't left
        # blank until someone manually types a balance in.
        dated_balances = [(r["date"], r["balance"]) for r in rows if r.get("balance")]
        latest_balance = max(dated_balances, default=(None, None))[1]

        bank_account = BankAccount(
            bank_name=bank_name,
            account_holder_name=account_holder_name,
            current_balance=latest_balance,
        )
        db.add(bank_account)
        db.flush()
    elif account_holder_name and not bank_account.account_holder_name:
        # Update existing account if holder name is provided and not set
        bank_account.account_holder_name = account_holder_name
        db.flush()

    # Save statement and transactions
    stmt = BankStatement(
        bank_name=bank_name,
        bank_account_id=bank_account.id,
        file_path=str(stored_path) if stored_path else None,
        file_type=file_type,
        status="pending",
    )
    db.add(stmt)
    db.flush()

    for row in rows:
        bt_fields = {k: v for k, v in row.items() if k != "balance"}
        db.add(BankTransaction(statement_id=stmt.id, **bt_fields))

    # Record statement period from transaction dates for future overlap checks
    raw_dates = [r["date"] for r in rows if r.get("date") is not None]
    if raw_dates:
        from datetime import date as _date_type
        parsed_dates = []
        for d in raw_dates:
            if isinstance(d, _date_type):
                parsed_dates.append(d)
            elif hasattr(d, "date"):  # pd.Timestamp
                parsed_dates.append(d.date())
        if parsed_dates:
            stmt.statement_period_start = min(parsed_dates)
            stmt.statement_period_end = max(parsed_dates)

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
    stmt = get_or_404(db, BankStatement, stmt_id, "Statement")
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
        try:
            stmt = get_or_404(db, BankStatement, stmt_id, "Statement")
            db.delete(stmt)
            deleted += 1
        except HTTPException:
            # Skip if not found
            continue
    db.commit()
    return {"deleted": deleted}


class _ValidationCheck(_PydanticBase):
    name: str
    status: str  # "pass" | "warn" | "fail"
    message: str
    count: int = 0
    details: list[dict] = []


class _ValidationReport(_PydanticBase):
    statement_id: int
    total_transactions: int
    can_import: bool
    error_count: int
    warning_count: int
    checks: list[_ValidationCheck]


@router.get("/{stmt_id}/validate", response_model=_ValidationReport)
def validate_bank_statement(stmt_id: int, db: Session = Depends(get_db)):
    """
    3-tier pre-import validation of a parsed bank statement.

    Tier 1 — Row completeness: missing fields, zero amounts.
    Tier 2 — Duplicate risk: transactions already present in the ledger.
    Tier 3 — Period overlap + category coverage.
    """
    stmt = get_or_404(db, BankStatement, stmt_id, "Statement")
    txs = (
        db.query(BankTransaction)
        .filter(BankTransaction.statement_id == stmt_id)
        .order_by(BankTransaction.date)
        .all()
    )

    checks: list[_ValidationCheck] = []

    # ── Tier 1: Row completeness ──────────────────────────────────────────────
    incomplete: list[dict] = []
    for tx in txs:
        issues = []
        if not tx.description or not tx.description.strip():
            issues.append("missing description")
        if tx.amount is None or tx.amount == 0:
            issues.append("zero/missing amount")
        if tx.date is None:
            issues.append("missing date")
        if issues:
            incomplete.append({
                "id": tx.id,
                "date": str(tx.date),
                "description": (tx.description or "")[:40],
                "issues": issues,
            })

    if not incomplete:
        checks.append(_ValidationCheck(
            name="Row Completeness",
            status="pass",
            message=f"All {len(txs)} rows have required fields.",
        ))
    else:
        ratio = len(incomplete) / len(txs) if txs else 1.0
        checks.append(_ValidationCheck(
            name="Row Completeness",
            status="fail" if ratio > 0.2 else "warn",
            message=f"{len(incomplete)} row(s) have missing or invalid fields.",
            count=len(incomplete),
            details=incomplete[:10],
        ))

    # ── Tier 2: Duplicate risk ────────────────────────────────────────────────
    duplicate_hits: list[dict] = []
    for tx in txs:
        candidates = (
            db.query(Transaction)
            .filter(
                Transaction.date == tx.date,
                func.abs(Transaction.amount - tx.amount) <= 0.01,
            )
            .all()
        )
        if candidates:
            bank_matches = [
                c for c in candidates
                if c.bank and c.bank.lower() == stmt.bank_name.lower()
            ]
            # A candidate already tagged to a *different* bank is a same-day,
            # same-amount coincidence across two real accounts, not a duplicate —
            # only fall back to an unattributed (no bank set) single candidate.
            unattributed = [c for c in candidates if not c.bank]
            match = bank_matches[0] if bank_matches else (unattributed[0] if len(unattributed) == 1 else None)
            if match:
                duplicate_hits.append({
                    "bank_tx_id": tx.id,
                    "date": str(tx.date),
                    "amount": tx.amount,
                    "description": (tx.description or "")[:40],
                    "existing_id": match.id,
                })

    if not duplicate_hits:
        checks.append(_ValidationCheck(
            name="Duplicate Transactions",
            status="pass",
            message="No transactions match existing ledger records.",
        ))
    else:
        dup_pct = len(duplicate_hits) / len(txs) if txs else 0.0
        msg = (
            f"{len(duplicate_hits)} of {len(txs)} transactions ({dup_pct:.0%}) already exist — "
            "this may be a re-upload."
            if dup_pct > 0.4
            else f"{len(duplicate_hits)} transaction(s) match existing records and will be reconciled automatically."
        )
        checks.append(_ValidationCheck(
            name="Duplicate Transactions",
            status="warn",
            message=msg,
            count=len(duplicate_hits),
            details=duplicate_hits[:10],
        ))

    # ── Tier 3a: Period overlap ───────────────────────────────────────────────
    if txs:
        tx_dates = [tx.date for tx in txs if tx.date]
        this_start = min(tx_dates)
        this_end = max(tx_dates)

        overlap_hits: list[dict] = []
        if stmt.bank_account_id:
            other_stmts = (
                db.query(BankStatement)
                .filter(
                    BankStatement.bank_account_id == stmt.bank_account_id,
                    BankStatement.id != stmt_id,
                )
                .all()
            )
            for other in other_stmts:
                if other.statement_period_start and other.statement_period_end:
                    o_start, o_end = other.statement_period_start, other.statement_period_end
                else:
                    other_rows = (
                        db.query(BankTransaction.date)
                        .filter(BankTransaction.statement_id == other.id)
                        .all()
                    )
                    other_dates = [r[0] for r in other_rows if r[0]]
                    if not other_dates:
                        continue
                    o_start, o_end = min(other_dates), max(other_dates)

                if this_start <= o_end and this_end >= o_start:
                    overlap_hits.append({
                        "statement_id": other.id,
                        "period": f"{o_start} – {o_end}",
                        "uploaded": other.created_at.strftime("%Y-%m-%d"),
                    })

        if not overlap_hits:
            checks.append(_ValidationCheck(
                name="Period Overlap",
                status="pass",
                message=f"Date range {this_start} – {this_end} has no overlap with other statements.",
            ))
        else:
            checks.append(_ValidationCheck(
                name="Period Overlap",
                status="warn",
                message=(
                    f"Date range overlaps with {len(overlap_hits)} other statement(s). "
                    "Transactions may already be imported."
                ),
                count=len(overlap_hits),
                details=overlap_hits,
            ))
    else:
        checks.append(_ValidationCheck(
            name="Period Overlap",
            status="pass",
            message="No transactions to validate.",
        ))

    # ── Tier 3b: Category coverage ───────────────────────────────────────────
    uncategorized = [
        tx for tx in txs
        if not tx.suggested_category or tx.suggested_category == "Other"
    ]
    coverage = 1.0 - len(uncategorized) / len(txs) if txs else 1.0
    checks.append(_ValidationCheck(
        name="Category Coverage",
        status="pass" if coverage >= 0.8 else "warn",
        message=(
            f"{coverage:.0%} of transactions auto-categorized ({len(uncategorized)} as 'Other')."
            if coverage >= 0.8
            else f"Only {coverage:.0%} auto-categorized — {len(uncategorized)} row(s) need manual categories."
        ),
        count=len(uncategorized),
    ))

    # ── Aggregate ─────────────────────────────────────────────────────────────
    error_count = sum(1 for c in checks if c.status == "fail")
    warning_count = sum(1 for c in checks if c.status == "warn")

    return _ValidationReport(
        statement_id=stmt_id,
        total_transactions=len(txs),
        can_import=error_count == 0,
        error_count=error_count,
        warning_count=warning_count,
        checks=checks,
    )


@router.get("/{stmt_id}/transactions", response_model=list[BankTransactionOut])
def list_bank_transactions(stmt_id: int, db: Session = Depends(get_db)):
    """List all bank transactions for a statement."""
    get_or_404(db, BankStatement, stmt_id, "Statement")
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
    stmt = get_or_404(db, BankStatement, stmt_id, "Statement")

    saved_count = 0
    reconciled_count = 0
    new_transactions = []
    # Track which existing transaction IDs have been consumed as matches so far.
    # This prevents multiple identical rows (same date + amount + description, e.g.
    # "SEPT SALARY" × 3) from all matching the same single existing transaction.
    already_matched_ids: set[int] = set()

    for item in req.items:
        bank_tx = db.get(BankTransaction, item.bank_transaction_id)
        if not bank_tx or bank_tx.statement_id != stmt_id:
            continue

        # Already matched — skip entirely
        if bank_tx.match_status == "matched" and bank_tx.matched_transaction_id:
            already_matched_ids.add(bank_tx.matched_transaction_id)
            reconciled_count += 1
            continue

        # Duplicate check — pass the consumed-IDs set so each match is unique
        existing = _find_duplicate_transaction(
            db, item, stmt.bank_name, bank_tx.reference, already_matched_ids
        )

        if existing:
            already_matched_ids.add(existing.id)  # consume this match
            bank_tx.matched_transaction_id = existing.id
            bank_tx.match_status = "matched"
            bank_tx.match_confidence = 1.0
            AuditLogger.log_action(
                db,
                "reconciliation",
                bank_tx.id,
                "match",
                new_values={
                    "bank_tx_id": bank_tx.id,
                    "transaction_id": existing.id,
                    "method": "duplicate_import",
                    "reason": "same date and amount already in transactions",
                },
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
            bank_account_id=req.bank_account_id or stmt.bank_account_id,
        )
        db.add(tx)
        db.flush()

        # Never match a *later* row in this same import against a transaction
        # *this same import* just created — two statement rows are siblings,
        # not duplicates of each other, even when same-day/same-amount/same
        # generic description (e.g. two families both paying a "school fee"
        # of the same amount). Re-import dedup is for separate, earlier imports.
        already_matched_ids.add(tx.id)

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
                # Always keep the transaction already in the DB — never override
                # an existing record with one from a re-upload.
                best_match.is_potential_duplicate = False
                best_match.duplicate_reviewed = True
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


def _is_intra_account_transfer(t: Transaction) -> bool:
    """
    Check if this is an intra-account transfer to a savings wallet or pocket.
    Examples: Auto-save to OWealth, savings wallet, vault transfers.
    """
    if t.type != "transfer":
        return False

    keywords = ["owealth", "auto-save", "auto save", "savings wallet", "vault", "pocket"]
    text = (t.description + " " + (t.vendor or "")).lower()
    return any(keyword in text for keyword in keywords)


# Keywords that identify savings / wallet accounts where incoming transfers are
# the primary funding source (e.g. OPay, OWealth, PiggyVest). For these accounts
# transfers should NOT reduce the book balance because they are inflows.
_SAVINGS_WALLET_KEYWORDS = frozenset(["opay", "owealth", "wealth", "piggyvest", "cowrywise", "kuda"])


def _is_savings_wallet_account(bank_name: str) -> bool:
    """Return True when the account is a savings/wallet that receives transfers as income."""
    lower = bank_name.lower()
    return any(kw in lower for kw in _SAVINGS_WALLET_KEYWORDS)


def _transfer_is_income(t: Transaction, bank_name: str, db: Session) -> bool:
    """
    Direction of a (non-intra-account) transfer: True = money received (income),
    False = money sent (expense).

    Uses the original debit/credit recorded on the linked bank statement row —
    the authoritative source — not an account-type guess. A transfer can go
    either direction regardless of account (a "savings wallet" can send money
    out too), so the per-account heuristic alone misclassifies real transfers.

    Statements re-imported more than once can link multiple bank_transactions
    rows to the same Transaction; when their recorded directions disagree, the
    earliest import wins (deterministic — never an arbitrary lazy-loaded row).
    Falls back to the account-type heuristic only when no statement row is
    linked (e.g. a manually entered transfer with no import history).
    """
    earliest_match = (
        db.query(BankTransaction)
        .filter(BankTransaction.matched_transaction_id == t.id)
        .order_by(BankTransaction.created_at.asc(), BankTransaction.id.asc())
        .first()
    )
    if earliest_match is not None:
        return earliest_match.transaction_type == "credit"
    return _is_savings_wallet_account(bank_name)


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
        transactions = (
            TransactionQueryBuilder(db)
            .filter_bank_account(account.id)
            .filter_date_range(start_date, end_date)
            .build()
            .all()
        )

        # Transfers (excluding intra-account auto-saves/vaults) count as income or
        # expense per-transaction, by their actual debit/credit direction — not by
        # an account-type guess, since any account can both send and receive.
        inter_transfers = [
            t for t in transactions
            if t.type == "transfer" and not _is_intra_account_transfer(t)
        ]
        transfer_income = [t for t in inter_transfers if _transfer_is_income(t, account.bank_name, db)]
        transfer_expense = [t for t in inter_transfers if not _transfer_is_income(t, account.bank_name, db)]

        total_income = (
            sum(t.amount for t in transactions if t.type == "income")
            + sum(t.amount for t in transfer_income)
        )
        income_count = (
            sum(1 for t in transactions if t.type == "income") + len(transfer_income)
        )
        total_expense = (
            sum(t.amount for t in transactions if t.type == "expense")
            + sum(t.amount for t in transfer_expense)
        )
        expense_count = (
            sum(1 for t in transactions if t.type == "expense") + len(transfer_expense)
        )

        # Inter-account transfers shown separately for reference (never intra-account).
        total_transfer = sum(
            t.amount for t in transactions
            if t.type == "transfer" and not _is_intra_account_transfer(t)
        )
        transfer_count = sum(
            1 for t in transactions
            if t.type == "transfer" and not _is_intra_account_transfer(t)
        )

        transaction_dates = [t.date for t in transactions]
        first_transaction = min(transaction_dates) if transaction_dates else None
        last_transaction = max(transaction_dates) if transaction_dates else None

        opening_balance = account.opening_balance or 0.0
        net_amount = opening_balance + total_income - total_expense

        reports.append(
            BankAccountReportSummary(
                bank_account_id=account.id,
                bank_name=account.bank_name,
                account_holder_name=account.account_holder_name,
                account_number=account.account_number,
                opening_balance=opening_balance,
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
    account = get_or_404(db, BankAccount, account_id, "Bank account")

    transactions = (
        TransactionQueryBuilder(db)
        .filter_bank_account(account_id)
        .filter_date_range(start_date, end_date)
        .build()
        .all()
    )

    # Transfers (excluding intra-account auto-saves/vaults) count as income or
    # expense per-transaction, by their actual debit/credit direction — not by
    # an account-type guess, since any account can both send and receive.
    inter_transfers = [
        t for t in transactions
        if t.type == "transfer" and not _is_intra_account_transfer(t)
    ]
    transfer_income = [t for t in inter_transfers if _transfer_is_income(t, account.bank_name, db)]
    transfer_expense = [t for t in inter_transfers if not _transfer_is_income(t, account.bank_name, db)]

    total_income = (
        sum(t.amount for t in transactions if t.type == "income")
        + sum(t.amount for t in transfer_income)
    )
    income_count = (
        sum(1 for t in transactions if t.type == "income") + len(transfer_income)
    )
    total_expense = (
        sum(t.amount for t in transactions if t.type == "expense")
        + sum(t.amount for t in transfer_expense)
    )
    expense_count = (
        sum(1 for t in transactions if t.type == "expense") + len(transfer_expense)
    )

    # Inter-account transfers for the separate reference strip (never intra-account).
    total_transfer = sum(t.amount for t in inter_transfers)
    transfer_count = len(inter_transfers)

    # Expense breakdown.
    expense_by_category: dict[str, float] = {}
    for t in transactions:
        if t.type == "expense":
            category = t.category or "Uncategorized"
            expense_by_category[category] = expense_by_category.get(category, 0) + t.amount
    for t in transfer_expense:
        category = t.category or "Uncategorized"
        expense_by_category[category] = expense_by_category.get(category, 0) + t.amount

    # Income breakdown.
    income_by_category: dict[str, float] = {}
    for t in transactions:
        if t.type == "income":
            category = t.category or "Uncategorized"
            income_by_category[category] = income_by_category.get(category, 0) + t.amount
    for t in transfer_income:
        category = t.category or "Uncategorized"
        income_by_category[category] = income_by_category.get(category, 0) + t.amount

    # Keep transfer_by_category for backward compat (inter-account only).
    transfer_by_category: dict[str, float] = {}
    for t in inter_transfers:
        category = t.category or "Uncategorized"
        transfer_by_category[category] = transfer_by_category.get(category, 0) + t.amount

    transfer_income_ids = {t.id for t in transfer_income}
    inter_transfer_ids = {t.id for t in inter_transfers}
    monthly_data: dict[str, dict[str, float]] = {}
    for t in transactions:
        month_key = t.date.strftime("%Y-%m")
        if month_key not in monthly_data:
            monthly_data[month_key] = {"income": 0, "expense": 0, "transfer": 0}

        if t.type == "income":
            monthly_data[month_key]["income"] += t.amount
        elif t.type == "expense":
            monthly_data[month_key]["expense"] += t.amount
        elif t.id in inter_transfer_ids:
            if t.id in transfer_income_ids:
                monthly_data[month_key]["income"] += t.amount
            else:
                monthly_data[month_key]["expense"] += t.amount

    transaction_dates = [t.date for t in transactions]
    first_transaction = min(transaction_dates) if transaction_dates else None
    last_transaction = max(transaction_dates) if transaction_dates else None

    opening_balance = account.opening_balance or 0.0
    return BankAccountReport(
        bank_account_id=account.id,
        bank_name=account.bank_name,
        account_holder_name=account.account_holder_name,
        account_number=account.account_number,
        opening_balance=opening_balance,
        total_income=total_income,
        total_expense=total_expense,
        total_transfer=total_transfer,
        net_amount=opening_balance + total_income - total_expense,
        income_count=income_count,
        expense_count=expense_count,
        transfer_count=transfer_count,
        total_transactions=len(transactions),
        expense_by_category=expense_by_category,
        income_by_category=income_by_category,
        transfer_by_category=transfer_by_category,
        monthly_breakdown=monthly_data,
        first_transaction_date=first_transaction,
        last_transaction_date=last_transaction,
        currency="NGN",
    )
