"""Tests for monthly recurring TeacherBonus records — both the router's own
CRUD/validation (frequency, end period, live-recomputed amount) and how a
recurring bonus feeds into GET /payroll/compute for months after its start.
"""
from models import Staff, TeacherBonus


def _create_staff(db_session, full_name="Ngozi Williams", monthly_gross=150000.0) -> Staff:
    staff = Staff(full_name=full_name, monthly_gross=monthly_gross, is_active=True)
    db_session.add(staff)
    db_session.commit()
    return staff


def _bonus_payload(staff_id, **overrides):
    payload = {
        "staff_id": staff_id, "bonus_type": "performance",
        "percentage": 10.0, "basis_amount": 150000.0,
        "frequency": "onetime", "period_year": 2026, "period_month": 3,
        **overrides,
    }
    return payload


def _line_for(client, year, month, staff_id):
    resp = client.get("/payroll/compute", params={"year": year, "month": month})
    assert resp.status_code == 200, resp.text
    return next(l for l in resp.json() if l["staff_id"] == staff_id)


# ── router-level: CRUD + validation ─────────────────────────────────────────

def test_create_monthly_bonus_defaults_to_no_end_date(client, db_session):
    staff = _create_staff(db_session)
    resp = client.post("/teacher-bonuses/", json=_bonus_payload(staff.id, frequency="monthly"))
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["frequency"] == "monthly"
    assert body["end_year"] is None
    assert body["end_month"] is None


def test_create_rejects_unknown_frequency(client, db_session):
    staff = _create_staff(db_session)
    resp = client.post("/teacher-bonuses/", json=_bonus_payload(staff.id, frequency="weekly"))
    assert resp.status_code == 400


def test_create_rejects_end_period_before_start(client, db_session):
    staff = _create_staff(db_session)
    resp = client.post("/teacher-bonuses/", json=_bonus_payload(
        staff.id, frequency="monthly", period_year=2026, period_month=6, end_year=2026, end_month=3,
    ))
    assert resp.status_code == 400


def test_create_rejects_mismatched_end_year_and_month(client, db_session):
    staff = _create_staff(db_session)
    resp = client.post("/teacher-bonuses/", json=_bonus_payload(
        staff.id, frequency="monthly", end_year=2026, end_month=None,
    ))
    assert resp.status_code == 400


def test_switching_to_onetime_clears_end_period(client, db_session):
    staff = _create_staff(db_session)
    resp = client.post("/teacher-bonuses/", json=_bonus_payload(
        staff.id, frequency="monthly", end_year=2026, end_month=12,
    ))
    bonus_id = resp.json()["id"]

    resp = client.put(f"/teacher-bonuses/{bonus_id}", json=_bonus_payload(staff.id, frequency="onetime"))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["frequency"] == "onetime"
    assert body["end_year"] is None
    assert body["end_month"] is None


def test_monthly_bonus_amount_is_recomputed_live_from_current_salary(client, db_session):
    """The list endpoint's `amount` for a monthly bonus must reflect the
    staff member's CURRENT salary, not whatever it was at creation — a raise
    should flow through without editing the bonus record."""
    staff = _create_staff(db_session, monthly_gross=100000.0)
    resp = client.post("/teacher-bonuses/", json=_bonus_payload(
        staff.id, frequency="monthly", percentage=10.0, basis_amount=100000.0,
    ))
    assert resp.status_code == 201, resp.text
    assert resp.json()["amount"] == 10000.0

    staff.monthly_gross = 200000.0
    db_session.commit()

    resp = client.get("/teacher-bonuses/")
    body = next(b for b in resp.json() if b["staff_id"] == staff.id)
    assert body["amount"] == 20000.0  # 10% of the new 200,000 salary


def test_onetime_bonus_amount_stays_frozen_despite_salary_change(client, db_session):
    """Regression guard: the live-recompute behavior must only apply to
    monthly bonuses — one-time bonuses keep their historical semantics."""
    staff = _create_staff(db_session, monthly_gross=100000.0)
    resp = client.post("/teacher-bonuses/", json=_bonus_payload(
        staff.id, frequency="onetime", percentage=10.0, basis_amount=100000.0,
    ))
    assert resp.json()["amount"] == 10000.0

    staff.monthly_gross = 200000.0
    db_session.commit()

    resp = client.get("/teacher-bonuses/")
    body = next(b for b in resp.json() if b["staff_id"] == staff.id)
    assert body["amount"] == 10000.0  # unchanged


# ── payroll integration ──────────────────────────────────────────────────────

def test_monthly_bonus_does_not_apply_before_its_start_month(client, db_session):
    staff = _create_staff(db_session)
    client.post("/teacher-bonuses/", json=_bonus_payload(
        staff.id, frequency="monthly", period_year=2026, period_month=3,
    ))
    line = _line_for(client, 2026, 2, staff.id)
    assert line["bonus"] == 0.0


def test_monthly_bonus_applies_to_its_start_month_and_every_month_after(client, db_session):
    staff = _create_staff(db_session, monthly_gross=150000.0)
    client.post("/teacher-bonuses/", json=_bonus_payload(
        staff.id, frequency="monthly", percentage=10.0, basis_amount=150000.0,
        period_year=2026, period_month=3,
    ))
    assert _line_for(client, 2026, 3, staff.id)["bonus"] == 15000.0
    assert _line_for(client, 2026, 4, staff.id)["bonus"] == 15000.0
    assert _line_for(client, 2027, 1, staff.id)["bonus"] == 15000.0


def test_monthly_bonus_stops_after_its_end_month(client, db_session):
    staff = _create_staff(db_session)
    client.post("/teacher-bonuses/", json=_bonus_payload(
        staff.id, frequency="monthly", period_year=2026, period_month=3,
        end_year=2026, end_month=5,
    ))
    assert _line_for(client, 2026, 5, staff.id)["bonus"] > 0.0
    assert _line_for(client, 2026, 6, staff.id)["bonus"] == 0.0


def test_monthly_bonus_payroll_amount_uses_current_salary_not_creation_time_salary(client, db_session):
    staff = _create_staff(db_session, monthly_gross=100000.0)
    client.post("/teacher-bonuses/", json=_bonus_payload(
        staff.id, frequency="monthly", percentage=10.0, basis_amount=100000.0,
        period_year=2026, period_month=3,
    ))
    assert _line_for(client, 2026, 3, staff.id)["bonus"] == 10000.0

    staff.monthly_gross = 300000.0
    db_session.commit()

    assert _line_for(client, 2026, 4, staff.id)["bonus"] == 30000.0


def test_monthly_and_onetime_bonuses_in_the_same_month_sum_together(client, db_session):
    staff = _create_staff(db_session, monthly_gross=150000.0)
    client.post("/teacher-bonuses/", json=_bonus_payload(
        staff.id, frequency="monthly", bonus_type="loyalty",
        percentage=10.0, basis_amount=150000.0, period_year=2026, period_month=1,
    ))
    client.post("/teacher-bonuses/", json=_bonus_payload(
        staff.id, frequency="onetime", bonus_type="performance",
        percentage=5.0, basis_amount=150000.0, period_year=2026, period_month=3,
    ))
    line = _line_for(client, 2026, 3, staff.id)
    assert line["bonus"] == 15000.0 + 7500.0


def test_student_referral_monthly_bonus_uses_manual_basis_not_current_salary(client, db_session):
    """basis_is_salary=False types (e.g. student_referral) have nothing to
    recompute from the staff member's salary — the manually entered
    basis_amount (the referred student's fee) repeats unchanged."""
    staff = _create_staff(db_session, monthly_gross=100000.0)
    client.post("/teacher-bonuses/", json=_bonus_payload(
        staff.id, frequency="monthly", bonus_type="student_referral",
        percentage=20.0, basis_amount=25000.0, period_year=2026, period_month=1,
    ))
    staff.monthly_gross = 500000.0
    db_session.commit()

    line = _line_for(client, 2026, 4, staff.id)
    assert line["bonus"] == 5000.0  # 20% of the fixed 25,000 fee, unaffected by the salary change
