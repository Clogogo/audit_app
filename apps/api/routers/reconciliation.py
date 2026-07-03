"""
Reconciliation engine: auto-match + manual match + export
"""
import io
import json
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from utils.auth import require_permission
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload

from database import get_db
from models import BankStatement, BankTransaction, Transaction, AuditLog
from schemas import ReconciliationStatus, ManualMatchRequest

router = APIRouter(prefix="/reconcile", tags=["reconciliation"], dependencies=[Depends(require_permission("banking"))])


def _fuzzy_score(a: str, b: str) -> float:
    """Simple token-based similarity score (0-1)."""
    try:
        from rapidfuzz import fuzz
        return fuzz.token_sort_ratio(a.lower(), b.lower()) / 100.0
    except ImportError:
        # Fallback: word overlap
        wa = set(a.lower().split())
        wb = set(b.lower().split())
        if not wa or not wb:
            return 0.0
        return len(wa & wb) / max(len(wa), len(wb))


def _auto_match_statement(db: Session, stmt_id: int, stmt_account_id: int | None) -> int:
    unmatched = (
        db.query(BankTransaction)
        .filter(BankTransaction.statement_id == stmt_id, BankTransaction.match_status == "unmatched")
        .all()
    )
    matched_count = 0

    for btx in unmatched:
        date_start = btx.date - timedelta(days=3)
        date_end = btx.date + timedelta(days=3)

        candidate_query = db.query(Transaction).filter(
            Transaction.amount.between(btx.amount - 0.01, btx.amount + 0.01),
            Transaction.date.between(date_start, date_end),
        )
        if stmt_account_id is not None:
            candidate_query = candidate_query.filter(
                or_(
                    Transaction.bank_account_id == stmt_account_id,
                    Transaction.bank_account_id.is_(None),
                )
            )

        candidate_tx = candidate_query.all()
        best_tx = None
        best_score = 0.0

        for tx in candidate_tx:
            delta = abs((btx.date - tx.date).days)
            # Fuzzy description / vendor match
            vendor = tx.vendor or ""
            score = max(
                _fuzzy_score(btx.description, tx.description),
                _fuzzy_score(btx.description, vendor),
            )
            # Boost score for closer dates
            date_bonus = (3 - delta) / 3 * 0.2
            total = score + date_bonus

            if total > best_score:
                best_score = total
                best_tx = tx

        if best_tx and best_score >= 0.4:
            btx.matched_transaction_id = best_tx.id
            btx.match_status = "matched"
            btx.match_confidence = round(best_score, 3)
            matched_count += 1
            db.add(AuditLog(
                entity_type="reconciliation",
                entity_id=btx.id,
                action="match",
                new_values=json.dumps({
                    "bank_tx_id": btx.id,
                    "transaction_id": best_tx.id,
                    "confidence": round(best_score, 3),
                    "method": "auto",
                }),
            ))

    db.commit()
    return matched_count


@router.post("/{stmt_id}/auto-match")
def auto_match(stmt_id: int, db: Session = Depends(get_db)):
    stmt = db.get(BankStatement, stmt_id)
    if not stmt:
        raise HTTPException(404, "Statement not found")
    matched = _auto_match_statement(db, stmt_id, stmt.bank_account_id)
    return {"matched": matched}


@router.post("/manual-match")
def manual_match(req: ManualMatchRequest, db: Session = Depends(get_db)):
    btx = db.get(BankTransaction, req.bank_transaction_id)
    tx = db.get(Transaction, req.transaction_id)
    if not btx or not tx:
        raise HTTPException(404, "Record not found")

    # Check for discrepancy
    amount_diff = abs(btx.amount - tx.amount)
    date_diff = abs((btx.date - tx.date).days)
    status = "matched"
    if amount_diff > 0.01 or date_diff > 3:
        status = "discrepancy"

    btx.matched_transaction_id = tx.id
    btx.match_status = status
    btx.match_confidence = 1.0 if status == "matched" else 0.5
    db.add(AuditLog(
        entity_type="reconciliation",
        entity_id=btx.id,
        action="match",
        new_values=json.dumps({
            "bank_tx_id": btx.id,
            "transaction_id": tx.id,
            "method": "manual",
            "status": status,
        }),
    ))
    db.commit()
    return {"ok": True, "status": status}


@router.delete("/match/{bank_tx_id}")
def unmatch(bank_tx_id: int, db: Session = Depends(get_db)):
    btx = db.get(BankTransaction, bank_tx_id)
    if not btx:
        raise HTTPException(404, "Bank transaction not found")
    old_match = btx.matched_transaction_id
    btx.matched_transaction_id = None
    btx.match_status = "unmatched"
    btx.match_confidence = None
    db.add(AuditLog(
        entity_type="reconciliation",
        entity_id=bank_tx_id,
        action="unmatch",
        old_values=json.dumps({"matched_transaction_id": old_match}),
    ))
    db.commit()
    return {"ok": True}


@router.get("/{stmt_id}/status", response_model=ReconciliationStatus)
def reconciliation_status(stmt_id: int, db: Session = Depends(get_db)):
    counts = dict(
        db.query(BankTransaction.match_status, func.count(BankTransaction.id))
        .filter(BankTransaction.statement_id == stmt_id)
        .group_by(BankTransaction.match_status)
        .all()
    )
    total = sum(counts.values())
    matched = counts.get("matched", 0)
    discrepancies = counts.get("discrepancy", 0)
    unmatched = counts.get("unmatched", 0)
    return ReconciliationStatus(
        statement_id=stmt_id,
        total=total,
        matched=matched,
        unmatched=unmatched,
        discrepancies=discrepancies,
    )


@router.get("/{stmt_id}/export")
def export_reconciliation(
    stmt_id: int,
    format: str = Query("csv", regex="^(csv|pdf)$"),
    db: Session = Depends(get_db),
):
    stmt = db.get(BankStatement, stmt_id)
    if not stmt:
        raise HTTPException(404, "Statement not found")

    btxs = (
        db.query(BankTransaction)
        .options(joinedload(BankTransaction.matched_transaction))
        .filter(BankTransaction.statement_id == stmt_id)
        .order_by(BankTransaction.date)
        .all()
    )

    if format == "csv":
        import csv
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Bank Date", "Bank Description", "Bank Amount", "Type", "Match Status",
                         "Matched Transaction", "Confidence"])
        for btx in btxs:
            tx_desc = ""
            if btx.matched_transaction:
                tx_desc = f"{btx.matched_transaction.description} (${btx.matched_transaction.amount})"
            writer.writerow([
                btx.date, btx.description, btx.amount, btx.transaction_type,
                btx.match_status, tx_desc, btx.match_confidence or "",
            ])
        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=reconciliation-{stmt_id}.csv"},
        )

    # PDF export
    from reportlab.lib.pagesizes import letter, landscape
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib import colors

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(letter))
    styles = getSampleStyleSheet()
    elements = [
        Paragraph(f"Reconciliation Report — {stmt.bank_name}", styles["Title"]),
        Paragraph(f"Statement ID: {stmt_id} | Generated: {__import__('datetime').datetime.now().strftime('%Y-%m-%d')}", styles["Normal"]),
        Spacer(1, 12),
    ]

    data = [["Date", "Description", "Amount", "Type", "Status", "Matched Transaction", "Confidence"]]
    for btx in btxs:
        tx_desc = ""
        if btx.matched_transaction:
            tx_desc = f"{btx.matched_transaction.description[:30]}"
        data.append([
            str(btx.date), btx.description[:40], f"${btx.amount:.2f}",
            btx.transaction_type, btx.match_status, tx_desc,
            f"{btx.match_confidence:.0%}" if btx.match_confidence else "—",
        ])

    status_colors = {"matched": colors.lightgreen, "discrepancy": colors.lightyellow, "unmatched": colors.lightsalmon}
    table = Table(data, repeatRows=1)
    style = TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.darkblue),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("FONTSIZE", (0, 1), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.lightgrey]),
    ])
    for i, btx in enumerate(btxs, start=1):
        c = status_colors.get(btx.match_status, colors.white)
        style.add("BACKGROUND", (4, i), (4, i), c)
    table.setStyle(style)
    elements.append(table)
    doc.build(elements)
    buffer.seek(0)

    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=reconciliation-{stmt_id}.pdf"},
    )
