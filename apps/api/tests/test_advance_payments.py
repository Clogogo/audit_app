"""CRUD tests for POST/GET/PUT/DELETE /advance-payments/."""
from datetime import date

from models import Staff, Transaction


def _create_staff(db_session, full_name: str, monthly_gross: float = 100000.0) -> Staff:
    staff = Staff(full_name=full_name, monthly_gross=monthly_gross, is_active=True)
    db_session.add(staff)
    db_session.commit()
    return staff


def test_create_and_list_advance_payment(client, db_session):
    staff = _create_staff(db_session, "Ngozi Williams")

    resp = client.post("/advance-payments/", json={
        "staff_id": staff.id, "amount": 15000.0, "date_issued": "2026-01-10", "notes": "Emergency advance",
    })
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["staff_name"] == "Ngozi Williams"
    assert body["amount"] == 15000.0
    assert body["remaining_amount"] == 15000.0
    assert body["is_recovered"] is False
    assert body["verified"] is False

    resp = client.get("/advance-payments/")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_create_advance_payment_for_unknown_staff_fails(client, db_session):
    resp = client.post("/advance-payments/", json={
        "staff_id": 999999, "amount": 5000.0, "date_issued": "2026-01-10",
    })
    assert resp.status_code == 404


def test_update_advance_payment(client, db_session):
    staff = _create_staff(db_session, "Ngozi Williams")
    resp = client.post("/advance-payments/", json={
        "staff_id": staff.id, "amount": 15000.0, "date_issued": "2026-01-10",
    })
    advance_id = resp.json()["id"]

    resp = client.put(f"/advance-payments/{advance_id}", json={
        "staff_id": staff.id, "amount": 20000.0, "date_issued": "2026-01-12", "notes": "Updated",
    })
    assert resp.status_code == 200, resp.text
    assert resp.json()["amount"] == 20000.0
    assert resp.json()["notes"] == "Updated"


def test_delete_advance_payment(client, db_session):
    staff = _create_staff(db_session, "Ngozi Williams")
    resp = client.post("/advance-payments/", json={
        "staff_id": staff.id, "amount": 15000.0, "date_issued": "2026-01-10",
    })
    advance_id = resp.json()["id"]

    resp = client.delete(f"/advance-payments/{advance_id}")
    assert resp.status_code == 204

    resp = client.get("/advance-payments/")
    assert resp.json() == []


def test_linking_a_nonexistent_transaction_returns_404(client, db_session):
    staff = _create_staff(db_session, "Ngozi Williams")
    resp = client.post("/advance-payments/", json={
        "staff_id": staff.id, "amount": 15000.0, "date_issued": "2026-01-10",
        "transaction_id": 999999,
    })
    assert resp.status_code == 404


def test_linking_a_non_expense_transaction_returns_400(client, db_session):
    staff = _create_staff(db_session, "Ngozi Williams")
    income_tx = Transaction(
        type="income", amount=15000.0, currency="NGN", category="Other Income",
        description="Some income", date=date(2026, 1, 10),
    )
    db_session.add(income_tx)
    db_session.commit()
    resp = client.post("/advance-payments/", json={
        "staff_id": staff.id, "amount": 15000.0, "date_issued": "2026-01-10",
        "transaction_id": income_tx.id,
    })
    assert resp.status_code == 400


def test_updating_amount_keeps_remaining_amount_in_sync(client, db_session):
    from models import AdvancePayment

    staff = _create_staff(db_session, "Ngozi Williams")
    # Simulate a partially-deducted advance: ₦15,000 issued, ₦5,000 already deducted.
    advance = AdvancePayment(
        staff_id=staff.id, amount=15000.0, remaining_amount=10000.0,
        date_issued=date(2026, 1, 10), is_recovered=False,
    )
    db_session.add(advance)
    db_session.commit()

    resp = client.put(f"/advance-payments/{advance.id}", json={
        "staff_id": staff.id, "amount": 20000.0, "date_issued": "2026-01-10",
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["amount"] == 20000.0
    # ₦5,000 was already deducted; new outstanding = 20,000 - 5,000 = 15,000
    assert body["remaining_amount"] == 15000.0


def test_cannot_delete_a_recovered_advance(client, db_session):
    from models import AdvancePayment

    staff = _create_staff(db_session, "Ngozi Williams")
    advance = AdvancePayment(
        staff_id=staff.id, amount=15000.0, remaining_amount=0.0, date_issued=date(2026, 1, 10),
        is_recovered=True, recovered_period_year=2026, recovered_period_month=1,
    )
    db_session.add(advance)
    db_session.commit()

    resp = client.delete(f"/advance-payments/{advance.id}")
    assert resp.status_code == 400


def test_editing_a_recovered_advance_amount_up_reopens_it(client, db_session):
    """Raising the amount on a fully-recovered advance must reopen a
    balance for the next payroll run — otherwise the extra money would be
    tracked as owed but never actually deducted (payroll only sums
    remaining_amount for is_recovered == False)."""
    from models import AdvancePayment

    staff = _create_staff(db_session, "Ngozi Williams")
    advance = AdvancePayment(
        staff_id=staff.id, amount=15000.0, remaining_amount=0.0, date_issued=date(2026, 1, 10),
        is_recovered=True, recovered_period_year=2026, recovered_period_month=1,
    )
    db_session.add(advance)
    db_session.commit()

    resp = client.put(f"/advance-payments/{advance.id}", json={
        "staff_id": staff.id, "amount": 20000.0, "date_issued": "2026-01-10",
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["amount"] == 20000.0
    assert body["remaining_amount"] == 5000.0  # 15,000 already deducted
    assert body["is_recovered"] is False
    assert body["recovered_period_year"] is None
    assert body["recovered_period_month"] is None


def test_editing_a_recovered_advance_without_changing_amount_stays_recovered(client, db_session):
    """Editing an unrelated field (notes) on a recovered advance must not
    disturb its recovered status or clear the recorded recovery period."""
    from models import AdvancePayment

    staff = _create_staff(db_session, "Ngozi Williams")
    advance = AdvancePayment(
        staff_id=staff.id, amount=15000.0, remaining_amount=0.0, date_issued=date(2026, 1, 10),
        is_recovered=True, recovered_period_year=2026, recovered_period_month=1,
    )
    db_session.add(advance)
    db_session.commit()

    resp = client.put(f"/advance-payments/{advance.id}", json={
        "staff_id": staff.id, "amount": 15000.0, "date_issued": "2026-01-10", "notes": "Corrected typo",
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["notes"] == "Corrected typo"
    assert body["remaining_amount"] == 0.0
    assert body["is_recovered"] is True
    assert body["recovered_period_year"] == 2026
    assert body["recovered_period_month"] == 1


def test_editing_amount_down_on_active_advance_can_mark_it_recovered(client, db_session):
    """Symmetric direction: lowering the amount below what's already been
    deducted should flip is_recovered on, since there's nothing left owed."""
    from models import AdvancePayment

    staff = _create_staff(db_session, "Ngozi Williams")
    # ₦15,000 issued, ₦5,000 already deducted, ₦10,000 still outstanding.
    advance = AdvancePayment(
        staff_id=staff.id, amount=15000.0, remaining_amount=10000.0,
        date_issued=date(2026, 1, 10), is_recovered=False,
    )
    db_session.add(advance)
    db_session.commit()

    resp = client.put(f"/advance-payments/{advance.id}", json={
        "staff_id": staff.id, "amount": 5000.0, "date_issued": "2026-01-10",
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["remaining_amount"] == 0.0
    assert body["is_recovered"] is True
    # Recovered via edit, not an actual payroll run — stamped with today's
    # period rather than left blank, so it doesn't look like a data gap.
    today = date.today()
    assert body["recovered_period_year"] == today.year
    assert body["recovered_period_month"] == today.month


def test_cannot_reassign_staff_on_an_advance_payroll_already_deducted_against(client, db_session):
    """remaining_amount only means anything relative to one staff member's
    payroll history — reassigning staff after any deduction has happened
    would sever the link between who was actually deducted and whose
    record says recovered."""
    from models import AdvancePayment

    staff_a = _create_staff(db_session, "Ngozi Williams")
    staff_b = _create_staff(db_session, "Chidi Okafor")
    # Partially deducted — not even fully recovered, this should already be blocked.
    advance = AdvancePayment(
        staff_id=staff_a.id, amount=15000.0, remaining_amount=10000.0,
        date_issued=date(2026, 1, 10), is_recovered=False,
    )
    db_session.add(advance)
    db_session.commit()

    resp = client.put(f"/advance-payments/{advance.id}", json={
        "staff_id": staff_b.id, "amount": 15000.0, "date_issued": "2026-01-10",
    })
    assert resp.status_code == 400

    # Editing amount/notes for the SAME staff is still fine.
    resp = client.put(f"/advance-payments/{advance.id}", json={
        "staff_id": staff_a.id, "amount": 20000.0, "date_issued": "2026-01-10",
    })
    assert resp.status_code == 200, resp.text


def test_reassigning_staff_on_an_untouched_advance_is_allowed(client, db_session):
    """No deduction has happened yet, so nothing to desync — reassignment
    should go through same as before this change."""
    from models import AdvancePayment

    staff_a = _create_staff(db_session, "Ngozi Williams")
    staff_b = _create_staff(db_session, "Chidi Okafor")
    advance = AdvancePayment(
        staff_id=staff_a.id, amount=15000.0, remaining_amount=15000.0,
        date_issued=date(2026, 1, 10), is_recovered=False,
    )
    db_session.add(advance)
    db_session.commit()

    resp = client.put(f"/advance-payments/{advance.id}", json={
        "staff_id": staff_b.id, "amount": 15000.0, "date_issued": "2026-01-10",
    })
    assert resp.status_code == 200, resp.text
    assert resp.json()["staff_name"] == "Chidi Okafor"


def test_amount_must_be_positive(client, db_session):
    staff = _create_staff(db_session, "Ngozi Williams")
    resp = client.post("/advance-payments/", json={
        "staff_id": staff.id, "amount": 0, "date_issued": "2026-01-10",
    })
    assert resp.status_code == 422

    resp = client.post("/advance-payments/", json={
        "staff_id": staff.id, "amount": -500.0, "date_issued": "2026-01-10",
    })
    assert resp.status_code == 422
