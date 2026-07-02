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


def test_cannot_edit_or_delete_a_recovered_advance(client, db_session):
    from models import AdvancePayment

    staff = _create_staff(db_session, "Ngozi Williams")
    advance = AdvancePayment(
        staff_id=staff.id, amount=15000.0, remaining_amount=0.0, date_issued=date(2026, 1, 10),
        is_recovered=True, recovered_period_year=2026, recovered_period_month=1,
    )
    db_session.add(advance)
    db_session.commit()

    resp = client.put(f"/advance-payments/{advance.id}", json={
        "staff_id": staff.id, "amount": 99999.0, "date_issued": "2026-01-10",
    })
    assert resp.status_code == 400

    resp = client.delete(f"/advance-payments/{advance.id}")
    assert resp.status_code == 400
