"""CRUD tests for /teacher-bonuses/, plus the /types advisory list and the
computed `amount` field."""
from datetime import date

from models import Term


def _create_staff(client, full_name="Ngozi Williams", monthly_gross=150000.0) -> dict:
    resp = client.post("/staff-directory/", json={
        "full_name": full_name, "monthly_gross": monthly_gross, "is_active": True,
    })
    assert resp.status_code == 201, resp.text
    return resp.json()


def _bonus_payload(staff_id, **overrides):
    payload = {
        "staff_id": staff_id, "bonus_type": "performance",
        "percentage": 10.0, "basis_amount": 150000.0,
        "period_year": 2026, "period_month": 3,
        "notes": "Class average 85%, Term 2",
        **overrides,
    }
    return payload


def test_types_endpoint_returns_all_six_seed_types(client):
    resp = client.get("/teacher-bonuses/types")
    assert resp.status_code == 200
    keys = {t["key"] for t in resp.json()}
    assert keys == {
        "performance", "punctuality", "student_referral",
        "teacher_referral", "loyalty", "annual_high_performance",
    }


def test_create_bonus_type_slugifies_label_and_defaults_active(client):
    resp = client.post("/teacher-bonuses/types", json={"label": "Christmas Gift", "calculation_method": "flat_amount"})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["key"] == "christmas_gift"
    assert body["is_active"] is True
    assert body["default_percentage"] == 0.0


def test_create_bonus_type_rejects_duplicate_label(client):
    client.post("/teacher-bonuses/types", json={"label": "Christmas Gift"})
    resp = client.post("/teacher-bonuses/types", json={"label": "christmas gift"})
    assert resp.status_code == 400


def test_create_bonus_type_rejects_unknown_calculation_method(client):
    resp = client.post("/teacher-bonuses/types", json={"label": "Mystery Bonus", "calculation_method": "bogus"})
    assert resp.status_code == 400


def test_update_bonus_type_renames_label_but_keeps_key(client):
    created = client.post("/teacher-bonuses/types", json={"label": "Christmas Gift", "calculation_method": "flat_amount"}).json()
    resp = client.put(f"/teacher-bonuses/types/{created['id']}", json={
        "label": "Festive Season Gift", "calculation_method": "flat_amount",
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["key"] == "christmas_gift"
    assert body["label"] == "Festive Season Gift"


def test_retire_bonus_type_is_soft_delete(client):
    created = client.post("/teacher-bonuses/types", json={"label": "Christmas Gift", "calculation_method": "flat_amount"}).json()
    resp = client.delete(f"/teacher-bonuses/types/{created['id']}")
    assert resp.status_code == 204

    active = client.get("/teacher-bonuses/types", params={"active_only": True}).json()
    assert not any(t["key"] == "christmas_gift" for t in active)

    everyone = client.get("/teacher-bonuses/types").json()
    retired = next(t for t in everyone if t["key"] == "christmas_gift")
    assert retired["is_active"] is False


def test_retired_bonus_type_still_resolves_on_existing_bonus(client):
    created = client.post("/teacher-bonuses/types", json={"label": "Christmas Gift", "calculation_method": "flat_amount"}).json()
    staff = _create_staff(client)
    bonus = client.post("/teacher-bonuses/", json=_bonus_payload(
        staff["id"], bonus_type="christmas_gift", percentage=100.0, basis_amount=20000.0,
    ))
    assert bonus.status_code == 201, bonus.text

    client.delete(f"/teacher-bonuses/types/{created['id']}")

    resp = client.get("/teacher-bonuses/", params={"staff_id": staff["id"]})
    assert resp.json()[0]["bonus_type"] == "christmas_gift"


def test_flat_amount_type_bonus_amount_equals_entered_amount(client):
    client.post("/teacher-bonuses/types", json={"label": "Christmas Gift", "calculation_method": "flat_amount"})
    staff = _create_staff(client)
    resp = client.post("/teacher-bonuses/", json=_bonus_payload(
        staff["id"], bonus_type="christmas_gift", percentage=100.0, basis_amount=20000.0,
    ))
    assert resp.status_code == 201, resp.text
    assert resp.json()["amount"] == 20000.0


def test_create_bonus_rejects_unknown_bonus_type(client):
    staff = _create_staff(client)
    resp = client.post("/teacher-bonuses/", json=_bonus_payload(staff["id"], bonus_type="not_a_real_type"))
    assert resp.status_code == 400


def test_create_computes_amount_from_percentage_and_basis(client):
    staff = _create_staff(client)
    resp = client.post("/teacher-bonuses/", json=_bonus_payload(staff["id"], percentage=10.0, basis_amount=150000.0))
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["amount"] == 15000.0
    assert body["staff_name"] == "Ngozi Williams"
    assert body["term_id"] is None
    assert body["term_name"] is None


def test_student_referral_uses_student_fee_as_basis_not_salary(client):
    # The one bonus type whose basis is NOT the teacher's own salary.
    staff = _create_staff(client, monthly_gross=150000.0)
    resp = client.post("/teacher-bonuses/", json=_bonus_payload(
        staff["id"], bonus_type="student_referral", percentage=10.0, basis_amount=25000.0,
        notes="Referred Chidinma Okafor, JSS1, ₦25,000 fee",
    ))
    assert resp.status_code == 201, resp.text
    assert resp.json()["amount"] == 2500.0


def test_create_with_term_includes_term_name(client, db_session):
    staff = _create_staff(client)
    term = Term(name="Second Term", start_date=date(2026, 1, 5), end_date=date(2026, 4, 3))
    db_session.add(term)
    db_session.commit()

    resp = client.post("/teacher-bonuses/", json=_bonus_payload(staff["id"], term_id=term.id))
    assert resp.status_code == 201, resp.text
    assert resp.json()["term_id"] == term.id
    assert resp.json()["term_name"] == "Second Term"


def test_create_for_unknown_staff_404s(client):
    resp = client.post("/teacher-bonuses/", json=_bonus_payload(999999))
    assert resp.status_code == 404


def test_create_for_unknown_term_404s(client):
    staff = _create_staff(client)
    resp = client.post("/teacher-bonuses/", json=_bonus_payload(staff["id"], term_id=999999))
    assert resp.status_code == 404


def test_create_rejects_negative_percentage(client):
    staff = _create_staff(client)
    resp = client.post("/teacher-bonuses/", json=_bonus_payload(staff["id"], percentage=-5.0))
    assert resp.status_code == 400


def test_create_rejects_invalid_month(client):
    staff = _create_staff(client)
    resp = client.post("/teacher-bonuses/", json=_bonus_payload(staff["id"], period_month=13))
    assert resp.status_code == 400


def test_update_recomputes_amount(client):
    staff = _create_staff(client)
    created = client.post("/teacher-bonuses/", json=_bonus_payload(staff["id"], percentage=10.0, basis_amount=150000.0)).json()

    resp = client.put(f"/teacher-bonuses/{created['id']}", json=_bonus_payload(staff["id"], percentage=20.0, basis_amount=150000.0))
    assert resp.status_code == 200, resp.text
    assert resp.json()["amount"] == 30000.0


def test_delete_bonus(client):
    staff = _create_staff(client)
    created = client.post("/teacher-bonuses/", json=_bonus_payload(staff["id"])).json()

    resp = client.delete(f"/teacher-bonuses/{created['id']}")
    assert resp.status_code == 204

    resp = client.get("/teacher-bonuses/")
    assert resp.json() == []


def test_list_filters_by_staff_type_and_period(client):
    staff_a = _create_staff(client, full_name="Ngozi Williams")
    staff_b = _create_staff(client, full_name="Chidi Okafor")

    a_performance = client.post("/teacher-bonuses/", json=_bonus_payload(staff_a["id"], bonus_type="performance", period_month=3)).json()
    client.post("/teacher-bonuses/", json=_bonus_payload(staff_a["id"], bonus_type="loyalty", period_month=7))
    b_performance = client.post("/teacher-bonuses/", json=_bonus_payload(staff_b["id"], bonus_type="performance", period_month=3)).json()

    resp = client.get("/teacher-bonuses/", params={"staff_id": staff_a["id"]})
    assert len(resp.json()) == 2

    resp = client.get("/teacher-bonuses/", params={"bonus_type": "performance"})
    assert {b["id"] for b in resp.json()} == {a_performance["id"], b_performance["id"]}

    resp = client.get("/teacher-bonuses/", params={"period_month": 7})
    assert len(resp.json()) == 1
    assert resp.json()[0]["bonus_type"] == "loyalty"
