"""
Reports: export all transactions as CSV or PDF.
"""
import io
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from database import get_db
from models import Transaction

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/export")
def export_report(
    format: str = Query("csv", regex="^(csv|pdf)$"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
):
    q = db.query(Transaction)
    if start_date:
        q = q.filter(Transaction.date >= start_date)
    if end_date:
        q = q.filter(Transaction.date <= end_date)
    transactions = q.order_by(Transaction.date.desc()).all()

    if format == "csv":
        import csv
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["ID", "Date", "Type", "Category", "Description", "Vendor", "Amount", "Currency"])
        for tx in transactions:
            writer.writerow([tx.id, tx.date, tx.type, tx.category, tx.description, tx.vendor or "", tx.amount, tx.currency])
        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=transactions.csv"},
        )

    # PDF
    from reportlab.lib.pagesizes import letter, landscape
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib import colors
    import datetime

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(letter), rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    styles = getSampleStyleSheet()
    elements = [
        Paragraph("Transaction Report", styles["Title"]),
        Paragraph(f"Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}", styles["Normal"]),
        Spacer(1, 12),
    ]

    data = [["ID", "Date", "Type", "Category", "Description", "Vendor", "Amount", "Currency"]]
    for tx in transactions:
        data.append([
            str(tx.id), str(tx.date), tx.type, tx.category,
            (tx.description or "")[:40], tx.vendor or "", f"{tx.amount:.2f}", tx.currency,
        ])

    table = Table(data, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.darkblue),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
        ("FONTSIZE", (0, 0), (-1, 0), 10),
        ("FONTSIZE", (0, 1), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f0f4ff")]),
    ]))

    # Color rows by type
    for i, tx in enumerate(transactions, start=1):
        color = colors.HexColor("#dcfce7") if tx.type == "income" else colors.HexColor("#fee2e2")
        table.setStyle(TableStyle([("BACKGROUND", (2, i), (2, i), color)]))

    elements.append(table)
    doc.build(elements)
    buffer.seek(0)

    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=transactions.pdf"},
    )
