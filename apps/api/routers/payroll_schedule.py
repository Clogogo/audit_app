"""Process Payroll validated by the reconciliation, and "which month is next".

When the request carries the payroll schedule, a teacher is only marked paid if
  1. the schedule row for them is found and the bank paid it to the right account, and
  2. a bank payment exists for them.
If the bank amount or the app's computed total (gross + bonus - loans - advances -
other deductions) differs from the schedule by ₦100 or more, they are still processed
and the difference is saved as a note on their entry (SOFT_KINDS). Everything else is
all-or-nothing, so the staff directory is cross-checked against the schedule instead
of being the sole source of truth.

Trust boundary: the schedule itself is typed/uploaded by the user and echoed back
in the request, so it is NOT independent evidence. What the server does verify
is that every schedule amount is backed by real Salary and Wages bank payments
(re-matched here, never taken from the client) and that the app's own computed
total agrees with it.
"""
import calendar
from dataclasses import dataclass
from datetime import date
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models import PayrollEntry, Staff, Transaction
from routers.payroll import (
    PayrollEntryOut, PayrollLineIn, ProcessRequest, _capped_deductions, compute_payroll, upsert_payroll_entry,
)
from utils.auth import require_permission
from utils.payroll_recon import ScheduleRow, check_account, link_and_fill, reconcile, within_tolerance

router = APIRouter(prefix="/payroll", tags=["payroll"], dependencies=[Depends(require_permission("staff"))])

SALARY_CATEGORY = "Salary and Wages"
# Differences that do not stop processing: they are recorded in the entry's notes instead.
SOFT_KINDS = {"underpaid", "overpaid", "net_mismatch"}


def _cents(amount: float) -> int:
    return round(amount * 100)


def _money(amount: float) -> str:
    return f"\u20a6{amount:,.2f}"


@dataclass(frozen=True)
class _Plan:
    line: PayrollLineIn
    staff: Staff
    loan_ded: float
    advance_ded: float
    net: float
    transaction_id: int
    paid_amount: float
    note: Optional[str] = None


def _issue(staff: Staff, kind: str, message: str, **numbers: Optional[float]) -> dict[str, Any]:
    return {"staff_id": staff.id, "full_name": staff.full_name, "kind": kind, "message": message,
            "expected": None, "paid": None, "computed": None, **numbers}


def _month_salary_payments(db: Session, year: int, month: int) -> list[Transaction]:
    return (
        db.query(Transaction)
        .filter(
            Transaction.type == "expense",
            Transaction.category == SALARY_CATEGORY,
            Transaction.date >= date(year, month, 1),
            Transaction.date <= date(year, month, calendar.monthrange(year, month)[1]),
        )
        .all()
    )


def _row_issues(staff: Staff, rline: dict[str, Any]) -> list[dict[str, Any]]:
    """Why the bank payment for this schedule row isn't an acceptable payment."""
    status, expected, paid = rline["status"], rline["expected_amount"], rline["paid_amount"]
    if status == "matched":
        return []
    if rline.get("note"):
        return [_issue(staff, "ambiguous", rline["note"], expected=expected, paid=paid)]
    text = {
        "not_paid": f"No bank payment found for the schedule amount {_money(expected)}.",
        "underpaid": f"Bank paid {_money(paid)}, {_money(expected - paid)} less than the schedule ({_money(expected)}).",
        "overpaid": f"Bank paid {_money(paid)}, {_money(paid - expected)} more than the schedule ({_money(expected)}).",
    }[status]
    return [_issue(staff, status, text, expected=expected, paid=paid)]


def _hard(issues: list[dict[str, Any]], has_payment: bool) -> list[dict[str, Any]]:
    """The issues that stop processing: everything except SOFT_KINDS, and a bank difference with no payment to link."""
    return [i for i in issues if i["kind"] not in SOFT_KINDS or (i["kind"] != "net_mismatch" and not has_payment)]


def _plan_line(
    line: PayrollLineIn, staff: Staff, row: Optional[ScheduleRow], recon: dict[int, dict[str, Any]],
    req: ProcessRequest, db: Session,
) -> tuple[Optional[_Plan], list[dict[str, Any]]]:
    # Re-processing a paid month would drain the staff member's advance a second
    # time; the month has to be reopened with "Edit Payroll" first.
    if db.query(PayrollEntry).filter(
        PayrollEntry.staff_id == staff.id, PayrollEntry.period_year == req.year,
        PayrollEntry.period_month == req.month, PayrollEntry.is_paid == True,  # noqa: E712
    ).first():
        return None, [_issue(staff, "already_processed",
                             "Already processed for this month — use Edit Payroll to reopen it first.")]
    loan_ded, advance_ded = _capped_deductions(
        staff, req.year, req.month, line.gross_salary, line.bonus, line.other_deductions, db,
    )
    net = max(0.0, round(line.gross_salary + line.bonus - loan_ded - advance_ded - line.other_deductions, 2))
    if row is None:
        return None, [_issue(staff, "not_on_schedule", "Not found on the payroll schedule.", computed=net)]

    rline = recon[row.row_number]
    issues = _row_issues(staff, rline)
    if check_account(staff.account_number, rline.get("paid_account")) == "differs":
        issues.append(_issue(
            staff, "account_differs",
            f"The bank paid account {rline['paid_account']} ({rline['paid_to']}) but the staff directory has "
            f"{staff.account_number}. Confirm the bank's account and update the directory.",
            expected=row.amount, paid=rline["paid_amount"],
        ))
    if not within_tolerance(_cents(net) - _cents(row.amount)):
        issues.append(_issue(
            staff, "net_mismatch",
            f"The payroll total {_money(net)} does not match the schedule {_money(row.amount)} "
            "(check the salary in the staff directory, bonus, loans, advances and other deductions).",
            expected=row.amount, computed=net,
        ))
    tx_ids = rline["transaction_ids"]
    tx_id = tx_ids[0] if tx_ids else None   # a split payment links its first part; paid_amount is the sum
    hard = _hard(issues, bool(tx_ids))
    if tx_ids and hard == [] and (
        db.query(PayrollEntry).filter(PayrollEntry.transaction_id.in_(tx_ids), PayrollEntry.staff_id != staff.id).first()
    ):
        issues.append(_issue(staff, "payment_already_linked",
                             "This bank payment is already linked to another staff member's payroll entry.",
                             expected=row.amount, paid=rline["paid_amount"]))
    hard = _hard(issues, bool(tx_ids))
    if hard:
        return None, issues
    note = "Schedule check: " + " ".join(i["message"] for i in issues) if issues else None
    return _Plan(line, staff, loan_ded, advance_ded, net, tx_id, rline["paid_amount"], note), []


def _entry_out(db: Session, entry: PayrollEntry, paid_amount: Optional[float]) -> PayrollEntryOut:
    staff = db.get(Staff, entry.staff_id)
    return PayrollEntryOut(
        id=entry.id, staff_id=entry.staff_id, full_name=staff.full_name if staff else "",
        period_year=entry.period_year, period_month=entry.period_month, gross_salary=entry.gross_salary,
        bonus=entry.bonus, loan_deduction=entry.loan_deduction, advance_deduction=entry.advance_deduction,
        other_deductions=entry.other_deductions, net_salary=entry.net_salary, is_paid=bool(entry.is_paid),
        paid_date=entry.paid_date, transaction_id=entry.transaction_id, notes=entry.notes,
        created_at=entry.created_at, updated_at=entry.updated_at, paid_amount=paid_amount,
    )


def process_with_schedule(req: ProcessRequest, db: Session) -> list[PayrollEntryOut]:
    rows = [ScheduleRow(r.row_number, r.name.strip(), round(r.amount, 2), r.account_number) for r in req.schedule or []]

    line_ids = [l.staff_id for l in req.lines]
    if len(line_ids) != len(set(line_ids)):
        raise HTTPException(400, "A staff member cannot appear twice in the same request")

    staff_list: list[Staff] = []
    for line in req.lines:
        staff = db.get(Staff, line.staff_id)
        if not staff:
            raise HTTPException(404, f"Staff {line.staff_id} not found")
        staff_list.append(staff)
    # Link against everyone the preview linked against (all eligible staff, not just
    # the ones submitted now), so a skipped colleague's row can't be claimed by a
    # look-alike name; then only the submitted staff are validated.
    population = {s.id: s for s in staff_list}
    for payroll_line in compute_payroll(req.year, req.month, db):
        if payroll_line.staff_id not in population and (other := db.get(Staff, payroll_line.staff_id)):
            population[other.id] = other
    filled, links, _ = link_and_fill(rows, list(population.values()))
    recon = {ln["row_number"]: ln for ln in reconcile(filled, _month_salary_payments(db, req.year, req.month))["lines"]}

    plans: list[_Plan] = []
    issues: list[dict[str, Any]] = []
    for line, staff in zip(req.lines, staff_list):
        plan, found = _plan_line(line, staff, links.get(staff.id), recon, req, db)
        issues.extend(found)
        if plan:
            plans.append(plan)
    if issues:
        names = len({i["staff_id"] for i in issues})
        raise HTTPException(422, detail={
            "message": f"Cannot process payroll: {names} staff member(s) do not agree with the schedule and bank payments",
            "issues": issues,
        })

    entries = [
        (upsert_payroll_entry(
            db, p.line.model_copy(update={"notes": "\n".join(filter(None, [p.line.notes, p.note])) or None}), p.staff, req.year, req.month, bonus=p.line.bonus, loan_ded=p.loan_ded,
            advance_ded=p.advance_ded, net=p.net, transaction_id=p.transaction_id,
        ), p.paid_amount)
        for p in plans
    ]
    db.commit()

    from routers.financial_statements import _cache_bust
    _cache_bust()
    return [_entry_out(db, entry, paid) for entry, paid in entries]


# ── Latest month whose payroll is not complete ────────────────────────────────

class NextMonthOut(BaseModel):
    year: int
    month: int


def _eligible_staff_ids(staff: list[Staff], year: int, month: int, first_entry: dict[int, int]) -> set[int]:
    """Staff who owe a payroll entry for this month: active, employed then, and
    already on payroll by then (someone added later, or one who was never paid at
    all, must not drag the page back to the first month forever)."""
    first, last = date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])
    index = year * 12 + month - 1
    return {
        s.id for s in staff
        if (s.start_date is None or s.start_date <= last) and (s.end_date is None or s.end_date >= first)
        and s.id in first_entry and first_entry[s.id] <= index
    }


@router.get("/next-month", response_model=NextMonthOut)
def next_incomplete_month(db: Session = Depends(get_db)):
    """The LATEST month (up to today) that is not fully processed, i.e. some active staff
    member has no paid payroll entry; today's month if every month is complete or nothing
    was ever processed. Older unfinished months are not forced on the user: they can step
    back to them with the month arrows."""
    today = date.today()
    current = NextMonthOut(year=today.year, month=today.month)
    earliest = db.query(PayrollEntry.period_year, PayrollEntry.period_month).order_by(
        PayrollEntry.period_year, PayrollEntry.period_month).first()
    if earliest is None:
        return current

    staff = db.query(Staff).filter(Staff.is_active == True).all()  # noqa: E712
    entries = db.query(PayrollEntry.staff_id, PayrollEntry.period_year, PayrollEntry.period_month, PayrollEntry.is_paid).all()
    first_entry: dict[int, int] = {}
    for sid, y, m, _paid in entries:
        first_entry[sid] = min(first_entry.get(sid, y * 12 + m - 1), y * 12 + m - 1)
    paid = {(y, m, sid) for sid, y, m, is_paid in entries if is_paid}
    first, index = earliest[0] * 12 + earliest[1] - 1, today.year * 12 + today.month - 1
    while index >= first:                                   # newest month first
        year, month = index // 12, index % 12 + 1
        if any((year, month, sid) not in paid for sid in _eligible_staff_ids(staff, year, month, first_entry)):
            return NextMonthOut(year=year, month=month)
        index -= 1
    return current
