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
from models import Transaction, BankAccount
from schemas import BankAccountReport, BankAccountReportSummary

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
