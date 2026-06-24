"""
One-time import: Teacher Jan-Jun 2026.xlsx → Staff directory + PayrollEntry records.
Run from apps/api/ with the venv active:
  python import_payroll.py
"""
import sys
import calendar
from datetime import date, datetime
from pathlib import Path

# ── Path setup ────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[2]
XLSX = ROOT / "Teacher Jan - April 2026.xlsx"

sys.path.insert(0, str(Path(__file__).parent))

from database import SessionLocal, initialize_database
import models  # noqa – registers all models

initialize_database()

# ── Staff master (deduplicated, canonical name, bank details, gross salary) ───
# Gross = standard monthly salary from the spreadsheet
STAFF_MASTER = [
    # PRIMARY section
    dict(full_name="RUQAYAT OLAMIDE OLA-DAUDA",       role="Pre-School Teacher",  bank_name="OPay",         account_number="9134086687", monthly_gross=25000),
    dict(full_name="Emmanuel Barisua Patience",         role="Teacher",             bank_name="First Bank",   account_number="3058498096", monthly_gross=30000),
    dict(full_name="Esther Kehinde Ibu",                role="Teacher",             bank_name="Polaris Bank", account_number="1010408407", monthly_gross=25000),
    dict(full_name="AJUMOWU MARY NGOZI",                role="Teacher",             bank_name="First Bank",   account_number="3000921786", monthly_gross=30000),
    dict(full_name="Emmanuella Christian",              role="Teacher",             bank_name="PalmPay",      account_number="7083854654", monthly_gross=30000),
    dict(full_name="OLAWALE RACHEAL ANU",               role="Teacher",             bank_name="OPay",         account_number="9131544473", monthly_gross=25000),
    dict(full_name="Mrs. Adedeji Rukayat",              role="Teacher",             bank_name="OPay",         account_number="8135029244", monthly_gross=30000),
    dict(full_name="FALILAT ABIODUN ADAGU",             role="Teacher",             bank_name="OPay",         account_number="8149442807", monthly_gross=35000),
    dict(full_name="ANISHERE KABIRU AKANMU",            role="Cleaner",             bank_name="OPay",         account_number="7044330517", monthly_gross=20000),
    dict(full_name="FEBE ABOSEDE ADALIOUS",             role="Phonetics Teacher",   bank_name="OPay",         account_number="7081076210", monthly_gross=25000),
    dict(full_name="MRS JONATHAN OGOGO",                role="Teacher",             bank_name="OPay",         account_number=None,          monthly_gross=50000),
    # SECONDARY section
    dict(full_name="MOSES EDET BASSEY",                 role="Teacher",             bank_name="OPay",         account_number="8030702819", monthly_gross=50000),
    dict(full_name="MRS ALIMOT OMOLADE ADENIYI",        role="Teacher",             bank_name="PalmPay",      account_number="8143037990", monthly_gross=35000),
    dict(full_name="MR AJOSE BAMIDELE",                 role="Teacher",             bank_name="Zenith Bank",  account_number="4241293144", monthly_gross=35000),
    dict(full_name="GOODNEWS EBENEZER ONYENEKUNUM",     role="Teacher",             bank_name="OPay",         account_number="7048894805", monthly_gross=26000),
    dict(full_name="AYANRONKE OLUWAFUNKE ADEBAYO",      role="Teacher",             bank_name="Stanbic Bank", account_number="0027355731", monthly_gross=35000),
    dict(full_name="MRS OLADAPO MARY KEHINDE",          role="Teacher",             bank_name="OPay",         account_number="8114497471", monthly_gross=35000),
    dict(full_name="TAWARI VERA ROLI",                  role="Teacher",             bank_name="OPay",         account_number="9065749581", monthly_gross=20000),
    dict(full_name="REBECCA ADEJOKE ASIWAJU",           role="Cleaner",             bank_name="OPay",         account_number="7044330517", monthly_gross=20000, notes="Replaced Anishere from May 2026"),
    dict(full_name="Tijani Olawatobiloba",              role="Teacher",             bank_name="Moniepoint",   account_number="9155057128", monthly_gross=20000),
]

# ── Per-month payroll amounts (TOTAL column = net amount actually paid) ───────
# Format: ac_number (or name key) → {(year, month): net_paid}
# Derived directly from the spreadsheet TOTAL column
PAYROLL_BY_AC = {
    "9134086687": {(2026,1):25000, (2026,2):25000, (2026,3):25000, (2026,4):17500, (2026,5):25000, (2026,6):25000},
    "3058498096": {(2026,1):30000, (2026,2):30000, (2026,3):30000, (2026,4):21000, (2026,5):30000, (2026,6):30000},
    "1010408407": {(2026,1):25000, (2026,2):25000, (2026,3):25000, (2026,4):17500, (2026,5):25000, (2026,6):25000},
    "3000921786": {(2026,1):30000, (2026,2):30000, (2026,3):30000, (2026,4):21000, (2026,5):20000, (2026,6):30000},
    "7083854654": {(2026,1):15000, (2026,2):30000, (2026,3):30000, (2026,4):21000, (2026,5):30000, (2026,6):30000},
    "9131544473": {(2026,1):25000, (2026,2):25000, (2026,3):25000, (2026,4):17500, (2026,5):25000, (2026,6):25000},
    "8135029244": {(2026,1):30000, (2026,2):30000, (2026,3):30000, (2026,4):21000, (2026,5):30000, (2026,6):30000},
    "8149442807": {(2026,1):35000, (2026,2):35000, (2026,3):35000, (2026,4):24500, (2026,5):35000, (2026,6):35000},
    # Cleaner: Jan-Mar ac 3450006232; Apr onward 7044330517 (ANISHERE)
    "3450006232": {(2026,1):17000, (2026,2):20000, (2026,3):20000},
    # 7044330517 shared: Apr=Anishere(loan repayment only=7000), May/Jun=Rebecca
    "7044330517_cleaner": {(2026,4):7000},
    "7044330517_rebecca": {(2026,5):10000, (2026,6):10000},
    "7081076210": {(2026,1):20000, (2026,2):20000, (2026,3):25000, (2026,4):0,     (2026,5):25000, (2026,6):25000},
    "MRS_JONATHAN_OGOGO": {(2026,1):63000, (2026,2):50000, (2026,3):50000, (2026,4):35000, (2026,5):60000, (2026,6):50000},
    # Secondary section
    "8030702819": {(2026,1):50000, (2026,2):40000, (2026,3):40000, (2026,4):35000, (2026,5):40000, (2026,6):50000},
    "8143037990": {(2026,1):40000, (2026,2):40000, (2026,3):40000, (2026,4):27000, (2026,5):40000, (2026,6):40000},
    "4241293144": {(2026,1):7500,  (2026,2):27000, (2026,3):30000, (2026,4):17500, (2026,5):25000, (2026,6):35000},
    "7048894805": {(2026,1):26000, (2026,2):26000, (2026,3):26000, (2026,4):6500,  (2026,5):19000, (2026,6):26000},
    "0027355731": {(2026,1):35000, (2026,2):35000, (2026,3):35000, (2026,4):17500, (2026,5):35000, (2026,6):35000},
    "8114497471": {(2026,1):37000, (2026,2):37000, (2026,3):37000, (2026,4):18500, (2026,5):20000, (2026,6):37000},
    "9065749581": {(2026,2):20000, (2026,3):20000, (2026,4):0,     (2026,5):20000, (2026,6):20000},
    "9155057128": {(2026,5):21000, (2026,6):20000},
}

def run():
    db = SessionLocal()
    created_staff = 0
    created_payroll = 0
    skipped = 0

    try:
        for s_data in STAFF_MASTER:
            notes = s_data.pop("notes", None)
            # Check if already exists by account number or name
            existing = None
            if s_data.get("account_number"):
                existing = db.query(models.Staff).filter(
                    models.Staff.account_number == s_data["account_number"],
                    models.Staff.full_name == s_data["full_name"],
                ).first()
            if not existing:
                existing = db.query(models.Staff).filter(
                    models.Staff.full_name == s_data["full_name"]
                ).first()

            if existing:
                # Update with latest info
                for k, v in s_data.items():
                    setattr(existing, k, v)
                if notes:
                    existing.notes = notes
                existing.updated_at = datetime.utcnow()
                staff_obj = existing
                skipped += 1
                print(f"  Updated: {staff_obj.full_name}")
            else:
                staff_obj = models.Staff(**s_data, notes=notes)
                db.add(staff_obj)
                db.flush()
                created_staff += 1
                print(f"  Created: {staff_obj.full_name}")

            db.commit()

        # Map AC → staff id
        all_staff = db.query(models.Staff).all()
        ac_to_staff: dict[str, models.Staff] = {}
        for s in all_staff:
            if s.account_number:
                ac_to_staff[s.account_number] = s

        # Special mappings for shared/name-only entries
        anishere = db.query(models.Staff).filter(models.Staff.full_name == "ANISHERE KABIRU AKANMU").first()
        rebecca = db.query(models.Staff).filter(models.Staff.full_name == "REBECCA ADEJOKE ASIWAJU").first()
        mrs_ogogo = db.query(models.Staff).filter(models.Staff.full_name == "MRS JONATHAN OGOGO").first()

        # Build payroll map: (staff_id, year, month) → net_paid
        payroll_entries: list[tuple[models.Staff, int, int, float]] = []

        for key, monthly_data in PAYROLL_BY_AC.items():
            if key in ("7044330517_cleaner", "3450006232"):
                staff_obj = anishere
            elif key == "7044330517_rebecca":
                staff_obj = rebecca
            elif key == "MRS_JONATHAN_OGOGO":
                staff_obj = mrs_ogogo
            else:
                staff_obj = ac_to_staff.get(key)

            if not staff_obj:
                print(f"  WARNING: No staff found for key {key}")
                continue

            for (year, month), net_paid in monthly_data.items():
                if net_paid > 0:
                    payroll_entries.append((staff_obj, year, month, net_paid))

        print(f"\nCreating {len(payroll_entries)} payroll entries…")
        for staff_obj, year, month, net_paid in payroll_entries:
            # Skip if already exists
            existing_entry = db.query(models.PayrollEntry).filter(
                models.PayrollEntry.staff_id == staff_obj.id,
                models.PayrollEntry.period_year == year,
                models.PayrollEntry.period_month == month,
            ).first()

            pay_date = date(year, month, calendar.monthrange(year, month)[1])
            gross = staff_obj.monthly_gross

            if existing_entry:
                existing_entry.gross_salary = gross
                existing_entry.net_salary = net_paid
                existing_entry.is_paid = True
                existing_entry.paid_date = pay_date
                existing_entry.updated_at = datetime.utcnow()
                skipped += 1
            else:
                entry = models.PayrollEntry(
                    staff_id=staff_obj.id,
                    period_year=year,
                    period_month=month,
                    gross_salary=gross,
                    loan_deduction=0.0,
                    other_deductions=round(max(0, gross - net_paid), 2),
                    net_salary=net_paid,
                    is_paid=True,
                    paid_date=pay_date,
                    notes="Imported from Teacher Jan-April 2026.xlsx",
                )
                # Create matching salary transaction
                tx = models.Transaction(
                    type="expense",
                    amount=net_paid,
                    currency="NGN",
                    category="Salary and Wages",
                    description=f"Salary — {staff_obj.full_name} ({year}-{month:02d})",
                    date=pay_date,
                    vendor=staff_obj.full_name,
                )
                db.add(tx)
                db.flush()
                entry.transaction_id = tx.id
                db.add(entry)
                created_payroll += 1

            db.commit()

        print(f"\n✓ Done.")
        print(f"  Staff created: {created_staff}  |  Staff updated: {skipped}")
        print(f"  Payroll entries created: {created_payroll}")

    except Exception as e:
        db.rollback()
        print(f"ERROR: {e}")
        import traceback; traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    run()
