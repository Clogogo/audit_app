"""Tests for GET/PATCH /users — admin-only user management."""
from models import AuditLog, User
from utils.auth import hash_password


def _create_user(db_session, email: str, is_admin: bool = False, is_active: bool = True, user_id: int | None = None) -> User:
    user = User(
        id=user_id, email=email, hashed_password=hash_password("password123"),
        full_name="Test User", is_active=is_active, is_admin=is_admin,
    )
    db_session.add(user)
    db_session.commit()
    return user


def test_non_admin_gets_403_from_list_and_update(client, db_session):
    target = _create_user(db_session, "target@example.com")

    resp = client.get("/users")
    assert resp.status_code == 403

    resp = client.patch(f"/users/{target.id}", json={"is_active": False})
    assert resp.status_code == 403


def test_admin_can_list_users(admin_client, db_session):
    _create_user(db_session, "a@example.com", user_id=2)
    _create_user(db_session, "b@example.com", is_admin=True, user_id=3)

    resp = admin_client.get("/users")
    assert resp.status_code == 200
    emails = {u["email"] for u in resp.json()}
    assert emails == {"a@example.com", "b@example.com"}
    assert all("is_admin" in u for u in resp.json())


def test_admin_can_deactivate_another_user(admin_client, db_session):
    # user_id=2, distinct from admin_client's fake self (id=1) — otherwise
    # an autoincrement collision would trip the self-block instead.
    target = _create_user(db_session, "target@example.com", user_id=2)

    resp = admin_client.patch(f"/users/{target.id}", json={"is_active": False})
    assert resp.status_code == 200, resp.text
    assert resp.json()["is_active"] is False

    log = db_session.query(AuditLog).filter(AuditLog.entity_type == "user", AuditLog.entity_id == target.id).first()
    assert log is not None
    assert log.action == "admin_update"


def test_admin_can_promote_another_user(admin_client, db_session):
    target = _create_user(db_session, "target@example.com", user_id=2)

    resp = admin_client.patch(f"/users/{target.id}", json={"is_admin": True})
    assert resp.status_code == 200, resp.text
    assert resp.json()["is_admin"] is True


def test_admin_cannot_deactivate_or_demote_self(admin_client, db_session):
    # admin_client's fake identity is id=1 — a real row is needed since the
    # endpoint looks the target up fresh from the DB.
    _create_user(db_session, "admin@example.com", is_admin=True, user_id=1)

    resp = admin_client.patch("/users/1", json={"is_active": False})
    assert resp.status_code == 400

    resp = admin_client.patch("/users/1", json={"is_admin": False})
    assert resp.status_code == 400


def test_admin_cannot_demote_the_last_remaining_admin(admin_client, db_session):
    # Only one admin exists in the DB (id=2, explicitly distinct from the
    # acting identity id=1, which has no persisted row here) — demoting it
    # must be blocked by the last-admin guard, not the (inapplicable) self-guard.
    only_admin = _create_user(db_session, "only-admin@example.com", is_admin=True, user_id=2)

    resp = admin_client.patch(f"/users/{only_admin.id}", json={"is_admin": False})
    assert resp.status_code == 400
    assert "last remaining admin" in resp.json()["detail"]


def test_update_unknown_user_returns_404(admin_client, db_session):
    resp = admin_client.patch("/users/999999", json={"is_active": False})
    assert resp.status_code == 404


def test_explicit_null_in_patch_body_does_not_500_or_change_anything(admin_client, db_session):
    # {"is_active": null} must be treated as "not provided", not as "set the
    # column to NULL" — the latter would violate the NOT NULL constraint.
    target = _create_user(db_session, "target@example.com", user_id=2)

    resp = admin_client.patch(f"/users/{target.id}", json={"is_active": None, "is_admin": None})
    assert resp.status_code == 200, resp.text
    assert resp.json()["is_active"] is True
    assert resp.json()["is_admin"] is False

    logs = db_session.query(AuditLog).filter(AuditLog.entity_type == "user", AuditLog.entity_id == target.id).all()
    assert logs == []


def test_empty_patch_body_does_not_write_an_audit_entry(admin_client, db_session):
    target = _create_user(db_session, "target@example.com", user_id=2)

    resp = admin_client.patch(f"/users/{target.id}", json={})
    assert resp.status_code == 200, resp.text

    logs = db_session.query(AuditLog).filter(AuditLog.entity_type == "user", AuditLog.entity_id == target.id).all()
    assert logs == []
