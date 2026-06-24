"""
Reports: export all transactions as CSV or PDF.
"""
import io
import os
import datetime
from collections import defaultdict
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import get_db
from models import Transaction, BankAccount
from schemas import BankAccountReport, BankAccountReportSummary

router = APIRouter(prefix="/reports", tags=["reports"])

# ── Unicode font registration (runs once on module load) ──────────────────────
_PDF_BODY = "Helvetica"
_PDF_BOLD = "Helvetica-Bold"
try:
    from reportlab.pdfbase import pdfmetrics as _pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont as _TTFont
    for _fp in [
        "/Library/Fonts/Arial Unicode.ttf",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    ]:
        if os.path.exists(_fp):
            _pdfmetrics.registerFont(_TTFont("UniFont", _fp))
            _pdfmetrics.registerFont(_TTFont("UniFont-Bold", _fp))
            _PDF_BODY, _PDF_BOLD = "UniFont", "UniFont-Bold"
            break
except Exception:
    pass


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


# ── Audit Report ─────────────────────────────────────────────────────────────

@router.get("/audit-report")
def export_audit_report(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    opinion: str = Query("unqualified", regex="^(unqualified|qualified)$"),
    qualification_note: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """Generate a formal financial audit report PDF for the given period."""
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
        HRFlowable, PageBreak,
    )
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors
    from reportlab.lib.units import cm
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_JUSTIFY

    SCHOOL = "Marvellous Lite Schools Ltd"
    NAVY   = colors.HexColor("#1e3a5f")
    LIGHT  = colors.HexColor("#f0f4ff")
    GREEN  = colors.HexColor("#16a34a")
    RED    = colors.HexColor("#dc2626")
    GREY   = colors.HexColor("#6b7280")
    RULE   = colors.HexColor("#cbd5e1")
    NAIRA  = "₦"  # ₦ U+20A6 — rendered via _PDF_BODY (Arial Unicode)

    # A4 usable width: 595.27 pt − 2 × 1.8 cm ≈ 17.4 cm
    PAGE_W = A4[0] - 2 * 1.8 * cm

    # ── data ─────────────────────────────────────────────────────────────────
    q = db.query(Transaction).filter(Transaction.type != "transfer")
    if start_date:
        q = q.filter(Transaction.date >= start_date)
    if end_date:
        q = q.filter(Transaction.date <= end_date)
    transactions = q.order_by(Transaction.date).all()

    income_txns  = [t for t in transactions if t.type == "income"]
    expense_txns = [t for t in transactions if t.type == "expense"]

    total_income   = sum(t.amount for t in income_txns)
    total_expenses = sum(t.amount for t in expense_txns)
    surplus        = total_income - total_expenses

    income_by_cat:  dict[str, float] = defaultdict(float)
    expense_by_cat: dict[str, float] = defaultdict(float)
    for t in income_txns:
        income_by_cat[t.category or "Other"] += t.amount
    for t in expense_txns:
        expense_by_cat[t.category or "Other"] += t.amount

    monthly: dict[str, dict] = {}
    for t in transactions:
        ym = t.date.strftime("%b %Y")
        if ym not in monthly:
            monthly[ym] = {"income": 0.0, "expense": 0.0}
        monthly[ym]["income" if t.type == "income" else "expense"] += t.amount

    if transactions:
        actual_start = min(t.date for t in transactions)
        actual_end   = max(t.date for t in transactions)
        period_label = (
            f"{actual_start.strftime('%d %B %Y')} to {actual_end.strftime('%d %B %Y')}"
        )
    else:
        period_label = "No transactions recorded"

    # ── styles ────────────────────────────────────────────────────────────────
    base = getSampleStyleSheet()

    def style(name, **kw):
        return ParagraphStyle(name, parent=base["Normal"], **kw)

    # Description wrap style — uses unicode font so ₦ renders in wrapped cells
    desc_style = ParagraphStyle(
        "desc", parent=base["Normal"],
        fontName=_PDF_BODY, fontSize=8.5, leading=11, spaceAfter=0, spaceBefore=0,
    )

    S = {
        "cover_school": style("cs", fontSize=22, textColor=NAVY, fontName=_PDF_BOLD, alignment=TA_CENTER, spaceAfter=18),
        "cover_title":  style("ct", fontSize=15, textColor=NAVY, fontName=_PDF_BODY, alignment=TA_CENTER, spaceAfter=4),
        "cover_period": style("cp", fontSize=11, textColor=GREY, fontName=_PDF_BODY, alignment=TA_CENTER, spaceAfter=2),
        "cover_gen":    style("cg", fontSize=9,  textColor=GREY, fontName=_PDF_BODY, alignment=TA_CENTER),
        "section":      style("sh", fontSize=12, textColor=NAVY, fontName=_PDF_BOLD, spaceBefore=14, spaceAfter=6),
        "body":         style("bd", fontSize=9.5, fontName=_PDF_BODY, leading=14, alignment=TA_JUSTIFY, spaceAfter=4),
        "body_right":   style("br_s", fontSize=9.5, fontName=_PDF_BODY, alignment=TA_RIGHT),
        "label":        style("lb", fontSize=9,  fontName=_PDF_BODY, textColor=GREY),
        "bold":         style("bo", fontSize=9.5, fontName=_PDF_BOLD),
        "italic":       style("it", fontSize=9.5, fontName=_PDF_BODY),
        "small":        style("sm", fontSize=8,  fontName=_PDF_BODY, textColor=GREY),
    }

    def fmt(amount: float) -> str:
        """Format amount as ₦#,##0.00; negatives as (₦#,##0.00) accounting style."""
        if amount < 0:
            return f"({NAIRA}{abs(amount):,.2f})"
        return f"{NAIRA}{amount:,.2f}"

    def wrap(text: str) -> Paragraph:
        """Wrap description text so long strings flow within the cell."""
        return Paragraph(str(text), desc_style)

    def tbl_style(extra=None):
        """Base table style using the unicode font so ₦ renders in all cells."""
        return TableStyle([
            ("FONTNAME",     (0, 0), (-1, -1), _PDF_BODY),
            ("FONTNAME",     (0, 0), (-1, 0),  _PDF_BOLD),
            ("FONTSIZE",     (0, 0), (-1, -1), 9),
            ("BACKGROUND",   (0, 0), (-1, 0),  NAVY),
            ("TEXTCOLOR",    (0, 0), (-1, 0),  colors.white),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
            ("GRID",         (0, 0), (-1, -1), 0.3, RULE),
            ("LEFTPADDING",  (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING",   (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING",(0, 0), (-1, -1), 4),
            ("VALIGN",       (0, 0), (-1, -1), "TOP"),
        ] + (extra or []))

    # ── build elements ────────────────────────────────────────────────────────
    E = []

    # PAGE 1 — Cover
    E += [
        Spacer(1, 3 * cm),
        Paragraph(SCHOOL, S["cover_school"]),
        HRFlowable(width="60%", thickness=2, color=NAVY, spaceBefore=4, spaceAfter=20),
        Paragraph("INDEPENDENT AUDITOR'S REPORT", S["cover_title"]),
        Paragraph(f"Financial Period: {period_label}", S["cover_period"]),
        Spacer(1, 0.4 * cm),
        Paragraph(
            f"Report type: {'Unqualified (Clean) Opinion' if opinion == 'unqualified' else 'Qualified Opinion'}",
            S["cover_period"],
        ),
        Spacer(1, 4 * cm),
        Paragraph(f"Date generated: {datetime.date.today().strftime('%d %B %Y')}", S["cover_gen"]),
        Paragraph("Prepared by: Finance & Audit System", S["cover_gen"]),
        PageBreak(),
    ]

    # PAGE 2 — Auditor's Report
    E += [
        Paragraph("INDEPENDENT AUDITOR'S REPORT", S["section"]),
        Paragraph(f"To the Management of {SCHOOL}", S["body"]),
        Spacer(1, 0.2 * cm),
        Paragraph("<b>Report on the Financial Statements</b>", S["body"]),
        Paragraph(
            f"We have examined the financial records of {SCHOOL} for the period {period_label}. "
            "The financial statements have been prepared on the basis of transactions recorded in the "
            "school's accounting system and comprise the Statement of Comprehensive Income, schedules "
            "of income and expenditure, and supporting transaction listings.",
            S["body"],
        ),
        Spacer(1, 0.2 * cm),
        Paragraph("<b>Management's Responsibility</b>", S["body"]),
        Paragraph(
            "Management is responsible for the preparation of these financial statements in accordance "
            "with applicable accounting standards, and for such internal controls as management determines "
            "are necessary to enable the preparation of financial statements that are free from material "
            "misstatement, whether due to fraud or error.",
            S["body"],
        ),
        Spacer(1, 0.2 * cm),
        Paragraph("<b>Auditor's Responsibility</b>", S["body"]),
        Paragraph(
            "Our responsibility is to express an opinion on these financial statements based on our review "
            "of the accounting records, bank statements, and supporting documentation. We conducted our "
            "review in accordance with generally accepted auditing standards. Those standards require that "
            "we comply with ethical requirements and plan and perform the audit to obtain reasonable "
            "assurance about whether the financial statements are free from material misstatement.",
            S["body"],
        ),
        Spacer(1, 0.2 * cm),
        Paragraph("<b>Opinion</b>", S["body"]),
    ]

    if opinion == "unqualified":
        E.append(Paragraph(
            f"In our opinion, the financial statements present fairly, in all material respects, the financial "
            f"performance of {SCHOOL} for the period {period_label}, in accordance with the accounting "
            f"records maintained by the school.",
            S["body"],
        ))
    else:
        E.append(Paragraph(
            f"Except for the matter described in the Basis for Qualified Opinion paragraph below, in our "
            f"opinion, the financial statements present fairly, in all material respects, the financial "
            f"performance of {SCHOOL} for the period {period_label}.",
            S["body"],
        ))
        if qualification_note:
            E += [
                Spacer(1, 0.2 * cm),
                Paragraph("<b>Basis for Qualified Opinion</b>", S["body"]),
                Paragraph(qualification_note, S["body"]),
            ]

    E += [
        Spacer(1, 0.3 * cm),
        HRFlowable(width="100%", thickness=0.5, color=RULE),
        Spacer(1, 0.2 * cm),
        Paragraph(
            f"Signed: ________________________________     Date: {datetime.date.today().strftime('%d %B %Y')}",
            S["body"],
        ),
        Paragraph("Authorised Signatory / Management Representative", S["small"]),
        PageBreak(),
    ]

    # PAGE 3 — Statement of Comprehensive Income
    E += [
        Paragraph("STATEMENT OF COMPREHENSIVE INCOME", S["section"]),
        Paragraph(f"{SCHOOL}  |  Period: {period_label}", S["label"]),
        Spacer(1, 0.3 * cm),
    ]

    stmt_data = [["Description", NAIRA]]
    stmt_data.append(["INCOME", ""])
    for cat, amt in sorted(income_by_cat.items(), key=lambda x: -x[1]):
        stmt_data.append([f"    {cat}", fmt(amt)])
    stmt_data.append(["Total Income", fmt(total_income)])
    stmt_data.append(["", ""])
    stmt_data.append(["EXPENDITURE", ""])
    for cat, amt in sorted(expense_by_cat.items(), key=lambda x: -x[1]):
        stmt_data.append([f"    {cat}", fmt(amt)])
    stmt_data.append(["Total Expenditure", fmt(total_expenses)])
    stmt_data.append(["", ""])
    stmt_data.append(["SURPLUS / (DEFICIT) FOR THE PERIOD", fmt(surplus)])

    income_row  = 2 + len(income_by_cat)
    expense_row = income_row + 3 + len(expense_by_cat)
    surplus_row = expense_row + 2

    stmt_tbl = Table(stmt_data, colWidths=[13 * cm, 4.4 * cm])
    stmt_tbl.setStyle(TableStyle([
        ("FONTNAME",     (0, 0), (-1, -1), _PDF_BODY),
        ("FONTNAME",     (0, 0), (-1, 0),  _PDF_BOLD),
        ("FONTSIZE",     (0, 0), (-1, -1), 9.5),
        ("LEFTPADDING",  (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING",   (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 3),
        ("ALIGN",        (1, 0), (1, -1),  "RIGHT"),
        ("VALIGN",       (0, 0), (-1, -1), "MIDDLE"),
        ("BACKGROUND",   (0, 0), (-1, 0),  NAVY),
        ("TEXTCOLOR",    (0, 0), (-1, 0),  colors.white),
        # Section labels
        ("FONTNAME",   (0, 1), (0, 1), _PDF_BOLD),
        ("BACKGROUND", (0, 1), (-1, 1), LIGHT),
        ("FONTNAME",   (0, income_row + 2), (0, income_row + 2), _PDF_BOLD),
        ("BACKGROUND", (0, income_row + 2), (-1, income_row + 2), LIGHT),
        # Subtotal rows
        ("FONTNAME",   (0, income_row),  (-1, income_row),  _PDF_BOLD),
        ("LINEABOVE",  (0, income_row),  (-1, income_row),  0.5, NAVY),
        ("FONTNAME",   (0, expense_row), (-1, expense_row), _PDF_BOLD),
        ("LINEABOVE",  (0, expense_row), (-1, expense_row), 0.5, NAVY),
        # Surplus row
        ("FONTNAME",   (0, surplus_row), (-1, surplus_row), _PDF_BOLD),
        ("BACKGROUND", (0, surplus_row), (-1, surplus_row), NAVY if surplus >= 0 else colors.HexColor("#fee2e2")),
        ("TEXTCOLOR",  (0, surplus_row), (-1, surplus_row), colors.white if surplus >= 0 else RED),
        ("LINEABOVE",  (0, surplus_row), (-1, surplus_row), 1, NAVY),
        ("GRID",       (0, 0), (-1, -1), 0.3, RULE),
    ]))
    E += [stmt_tbl, PageBreak()]

    # PAGE 4 — Monthly Summary
    if monthly:
        E += [
            Paragraph("MONTHLY INCOME & EXPENDITURE SUMMARY", S["section"]),
            Paragraph(f"{SCHOOL}  |  Period: {period_label}", S["label"]),
            Spacer(1, 0.3 * cm),
        ]
        m_data = [[
            "Month",
            f"Income ({NAIRA})",
            f"Expenditure ({NAIRA})",
            f"Net ({NAIRA})",
        ]]
        for ym, v in monthly.items():
            net = v["income"] - v["expense"]
            m_data.append([ym, fmt(v["income"]), fmt(v["expense"]), fmt(net)])
        m_data.append(["TOTAL", fmt(total_income), fmt(total_expenses), fmt(surplus)])

        m_extra = [
            ("FONTNAME", (0, len(m_data) - 1), (-1, len(m_data) - 1), _PDF_BOLD),
            ("BACKGROUND", (0, len(m_data) - 1), (-1, len(m_data) - 1), NAVY),
            ("TEXTCOLOR", (0, len(m_data) - 1), (-1, len(m_data) - 1), colors.white),
            ("LINEABOVE", (0, len(m_data) - 1), (-1, len(m_data) - 1), 1, NAVY),
            ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ]
        for i, (_, v) in enumerate(monthly.items(), start=1):
            net = v["income"] - v["expense"]
            m_extra.append(("TEXTCOLOR", (3, i), (3, i), GREEN if net >= 0 else RED))
        m_tbl = Table(m_data, colWidths=[PAGE_W / 4] * 4)
        m_tbl.setStyle(tbl_style(m_extra))
        E += [m_tbl, PageBreak()]

    # Schedule column widths: 1.8 + 7.5 + 3.2 + 2.4 + 2.5 = 17.4 cm
    SCHED_COLS = [1.8 * cm, 7.5 * cm, 3.2 * cm, 2.4 * cm, 2.5 * cm]

    # PAGE 5 — Income Schedule
    E += [
        Paragraph("SCHEDULE OF INCOME", S["section"]),
        Paragraph(f"{SCHOOL}  |  Period: {period_label}", S["label"]),
        Spacer(1, 0.3 * cm),
    ]
    inc_data = [["Date", "Description", "Category", "Bank", f"Amount ({NAIRA})"]]
    for t in income_txns:
        inc_data.append([
            str(t.date),
            wrap(t.description or ""),
            t.category or "",
            t.bank or "",
            fmt(t.amount),
        ])
    inc_data.append(["", "", "", "TOTAL", fmt(total_income)])

    inc_tbl = Table(inc_data, colWidths=SCHED_COLS, repeatRows=1)
    inc_extra = [
        ("ALIGN",      (4, 0), (4, -1), "RIGHT"),
        ("FONTNAME",   (0, len(inc_data) - 1), (-1, len(inc_data) - 1), _PDF_BOLD),
        ("BACKGROUND", (0, len(inc_data) - 1), (-1, len(inc_data) - 1), colors.HexColor("#dcfce7")),
        ("LINEABOVE",  (0, len(inc_data) - 1), (-1, len(inc_data) - 1), 1, GREEN),
    ]
    inc_tbl.setStyle(tbl_style(inc_extra))
    E += [inc_tbl, PageBreak()]

    # PAGE 6 — Expenditure Schedule
    E += [
        Paragraph("SCHEDULE OF EXPENDITURE", S["section"]),
        Paragraph(f"{SCHOOL}  |  Period: {period_label}", S["label"]),
        Spacer(1, 0.3 * cm),
    ]
    exp_data = [["Date", "Description", "Category", "Bank", f"Amount ({NAIRA})"]]
    for t in expense_txns:
        exp_data.append([
            str(t.date),
            wrap(t.description or ""),
            t.category or "",
            t.bank or "",
            fmt(t.amount),
        ])
    exp_data.append(["", "", "", "TOTAL", fmt(total_expenses)])

    exp_tbl = Table(exp_data, colWidths=SCHED_COLS, repeatRows=1)
    exp_extra = [
        ("ALIGN",      (4, 0), (4, -1), "RIGHT"),
        ("FONTNAME",   (0, len(exp_data) - 1), (-1, len(exp_data) - 1), _PDF_BOLD),
        ("BACKGROUND", (0, len(exp_data) - 1), (-1, len(exp_data) - 1), colors.HexColor("#fee2e2")),
        ("LINEABOVE",  (0, len(exp_data) - 1), (-1, len(exp_data) - 1), 1, RED),
    ]
    exp_tbl.setStyle(tbl_style(exp_extra))
    E.append(exp_tbl)

    # ── render ────────────────────────────────────────────────────────────────
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        rightMargin=1.8 * cm, leftMargin=1.8 * cm,
        topMargin=2.2 * cm, bottomMargin=2.0 * cm,
        title=f"Audit Report - {SCHOOL}",
        author=SCHOOL,
    )

    def _header_footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(GREY)
        canvas.line(1.8 * cm, A4[1] - 1.3 * cm, A4[0] - 1.8 * cm, A4[1] - 1.3 * cm)
        canvas.drawString(1.8 * cm, A4[1] - 1.1 * cm, SCHOOL)
        canvas.drawRightString(A4[0] - 1.8 * cm, A4[1] - 1.1 * cm, f"Audit Report  |  {period_label}")
        canvas.line(1.8 * cm, 1.3 * cm, A4[0] - 1.8 * cm, 1.3 * cm)
        canvas.drawString(1.8 * cm, 0.9 * cm, "CONFIDENTIAL - for authorised recipients only")
        canvas.drawRightString(A4[0] - 1.8 * cm, 0.9 * cm, f"Page {doc.page}")
        canvas.restoreState()

    doc.build(E, onFirstPage=_header_footer, onLaterPages=_header_footer)
    buf.seek(0)

    safe_period = period_label.replace(" ", "_").replace(",", "")
    filename = f"Audit_Report_{SCHOOL.replace(' ', '_')}_{safe_period}.pdf"
    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=\"{filename}\""},
    )


# ── Bank Account Reports ──────────────────────────────────────────────────────


@router.get("/bank-accounts", response_model=list[BankAccountReportSummary])
def get_bank_account_reports(
    start_date: Optional[date] = Query(None, description="Filter transactions from this date"),
    end_date: Optional[date] = Query(None, description="Filter transactions to this date"),
    db: Session = Depends(get_db)
):
    """
    Get income and expense summary for all bank accounts.
    Returns totals for each bank account within the specified date range.
    """
    # Get all bank accounts
    bank_accounts = db.query(BankAccount).all()

    reports = []

    for account in bank_accounts:
        # Build query for this account's transactions
        query = db.query(Transaction).filter(
            Transaction.bank_account_id == account.id
        )

        # Apply date filters if provided
        if start_date:
            query = query.filter(Transaction.date >= start_date)
        if end_date:
            query = query.filter(Transaction.date <= end_date)

        # Get all transactions for calculations
        transactions = query.all()

        # Calculate totals
        total_income = sum(t.amount for t in transactions if t.type == 'income')
        total_expense = sum(t.amount for t in transactions if t.type == 'expense')
        total_transfer = sum(t.amount for t in transactions if t.type == 'transfer')

        # Count transactions
        income_count = sum(1 for t in transactions if t.type == 'income')
        expense_count = sum(1 for t in transactions if t.type == 'expense')
        transfer_count = sum(1 for t in transactions if t.type == 'transfer')

        # Get date range
        transaction_dates = [t.date for t in transactions]
        first_transaction = min(transaction_dates) if transaction_dates else None
        last_transaction = max(transaction_dates) if transaction_dates else None

        # Calculate net (income - expense)
        net_amount = total_income - total_expense

        reports.append(BankAccountReportSummary(
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
            currency="NGN",  # Default to NGN for Nigerian banks
        ))

    return reports


@router.get("/bank-accounts/{account_id}", response_model=BankAccountReport)
def get_bank_account_report(
    account_id: int,
    start_date: Optional[date] = Query(None, description="Filter transactions from this date"),
    end_date: Optional[date] = Query(None, description="Filter transactions to this date"),
    db: Session = Depends(get_db)
):
    """
    Get detailed income and expense report for a specific bank account.
    Includes breakdown by category and monthly trends.
    """
    from fastapi import HTTPException

    account = db.get(BankAccount, account_id)
    if not account:
        raise HTTPException(404, "Bank account not found")

    # Build query
    query = db.query(Transaction).filter(
        Transaction.bank_account_id == account_id
    )

    # Apply date filters
    if start_date:
        query = query.filter(Transaction.date >= start_date)
    if end_date:
        query = query.filter(Transaction.date <= end_date)

    transactions = query.all()

    # Calculate totals
    total_income = sum(t.amount for t in transactions if t.type == 'income')
    total_expense = sum(t.amount for t in transactions if t.type == 'expense')
    total_transfer = sum(t.amount for t in transactions if t.type == 'transfer')

    # Count transactions
    income_count = sum(1 for t in transactions if t.type == 'income')
    expense_count = sum(1 for t in transactions if t.type == 'expense')
    transfer_count = sum(1 for t in transactions if t.type == 'transfer')

    # Category breakdown for expenses
    expense_by_category = {}
    for t in transactions:
        if t.type == 'expense':
            category = t.category or 'Uncategorized'
            expense_by_category[category] = expense_by_category.get(category, 0) + t.amount

    # Category breakdown for income
    income_by_category = {}
    for t in transactions:
        if t.type == 'income':
            category = t.category or 'Uncategorized'
            income_by_category[category] = income_by_category.get(category, 0) + t.amount

    # Monthly trends
    monthly_data = {}
    for t in transactions:
        month_key = t.date.strftime('%Y-%m')
        if month_key not in monthly_data:
            monthly_data[month_key] = {'income': 0, 'expense': 0, 'transfer': 0}

        if t.type == 'income':
            monthly_data[month_key]['income'] += t.amount
        elif t.type == 'expense':
            monthly_data[month_key]['expense'] += t.amount
        elif t.type == 'transfer':
            monthly_data[month_key]['transfer'] += t.amount

    # Get date range
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
