"""Financial Reports hub: the reports that are built from the database on demand (see utils/report_builders.py and
utils/tax_reports.py). The older statements keep their own pages; the hub links to them."""
from datetime import date
from typing import Callable, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from database import get_db
from utils.auth import require_permission
from utils import report_builders as rb, tax_reports as tr

router = APIRouter(prefix="/financial-reports", tags=["financial-reports"], dependencies=[Depends(require_permission("tax"))])

BUILDERS: dict[str, Callable[[Session, date, date], dict]] = {
    "who-owes-you": rb.who_owes_you, "who-you-owe": rb.who_you_owe, "payroll-summary": rb.payroll_summary,
    "capital-allowances": rb.capital_allowances, "sales": rb.sales_report, "expenses": rb.expense_report,
    "paye": tr.paye_return, "withholding-tax": tr.withholding_tax, "vat": tr.vat_return, "personal-income-tax": tr.personal_income_tax,
}


@router.get("/{slug}")
def get_report(slug: str, as_at: Optional[date] = Query(None), start_date: Optional[date] = Query(None), db: Session = Depends(get_db)):
    builder = BUILDERS.get(slug)
    if builder is None:
        raise HTTPException(404, "Unknown report.")
    end = as_at or date.today()
    start = start_date or date(end.year, 1, 1)
    if start > end:
        raise HTTPException(400, "The start date must not be after the end date.")
    return {**builder(db, start, end), "slug": slug, "start_date": start.isoformat(), "as_at": end.isoformat()}
