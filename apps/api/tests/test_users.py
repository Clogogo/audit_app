"""Tests for GET/PATCH /users — gated by the user_management permission."""
from models import AuditLog, Permission, Role, User
from utils.auth import hash_password


def _create_role(db_session, name: str, permission_keys: list[str], is_system: bool = False) -> Role:
    permissions = []
    for key in permission_keys:
        existing = db_session.query(Permission).filter(Permission.key == key).first()
        permissions.append(existing or Permission(key=key, label=key))
    role = Role(name=name, is_system=is_system)
    role.permissions = permissions
    db_session.add(role)
    db_session.commit()
    return role


def _create_user(db_session, email: str, role: Role | None = None, is_active: bool = True, user_id: int | None = None) -> User:
    user = User(
        id=user_id, email=email, hashed_password=hash_password("password123"),
        full_name="Test User", is_active=is_active,
    )
    if role is not None:
        user.role = role
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
    role = _create_role(db_session, "Front Desk", ["staff"])
    _create_user(db_session, "a@example.com", role=role, user_id=2)
    _create_user(db_session, "b@example.com", user_id=3)

    resp = admin_client.get("/users")
    assert resp.status_code == 200
    emails = {u["email"] for u in resp.json()}
    assert emails == {"a@example.com", "b@example.com"}

    with_role = next(u for u in resp.json() if u["email"] == "a@example.com")
    assert with_role["role"]["name"] == "Front Desk"
    assert with_role["role"]["permissions"] == ["staff"]

    without_role = next(u for u in resp.json() if u["email"] == "b@example.com")
    assert without_role["role"] is None


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


def test_admin_can_change_another_users_role(admin_client, db_session):
    target = _create_user(db_session, "target@example.com", user_id=2)
    new_role = _create_role(db_session, "Front Desk", ["staff"])

    resp = admin_client.patch(f"/users/{target.id}", json={"role_id": new_role.id})
    assert resp.status_code == 200, resp.text
    assert resp.json()["role"]["name"] == "Front Desk"


def test_admin_cannot_deactivate_or_demote_self(admin_client, db_session):
    # admin_client's fake identity is id=1 — a real row is needed since the
    # endpoint looks the target up fresh from the DB.
    admin_role = _create_role(db_session, "Admin", ["user_management"], is_system=True)
    _create_user(db_session, "admin@example.com", role=admin_role, user_id=1)
    other_role = _create_role(db_session, "Front Desk", ["staff"])

    resp = admin_client.patch("/users/1", json={"is_active": False})
    assert resp.status_code == 400

    resp = admin_client.patch("/users/1", json={"role_id": other_role.id})
    assert resp.status_code == 400


def test_admin_cannot_demote_the_last_remaining_admin(admin_client, db_session):
    # Only one user_management holder exists in the DB (id=2, explicitly
    # distinct from the acting identity id=1, which has no persisted row
    # here) — demoting it must be blocked by the last-holder guard, not the
    # (inapplicable) self-guard.
    admin_role = _create_role(db_session, "Admin", ["user_management"], is_system=True)
    only_admin = _create_user(db_session, "only-admin@example.com", role=admin_role, user_id=2)
    other_role = _create_role(db_session, "Front Desk", ["staff"])

    resp = admin_client.patch(f"/users/{only_admin.id}", json={"role_id": other_role.id})
    assert resp.status_code == 400
    assert "last remaining user with User Management access" in resp.json()["detail"]


def test_cannot_deactivate_the_last_remaining_user_management_holder(admin_client, db_session):
    # Distinct from the last-admin role-change guard: deactivating (not
    # demoting) the last other holder must be blocked too, or the system
    # ends up with nobody who can reach User/Role Management.
    admin_role = _create_role(db_session, "Admin", ["user_management"], is_system=True)
    only_admin = _create_user(db_session, "only-admin@example.com", role=admin_role, user_id=2)

    resp = admin_client.patch(f"/users/{only_admin.id}", json={"is_active": False})
    assert resp.status_code == 400
    assert "last remaining user with User Management access" in resp.json()["detail"]


def test_an_inactive_holder_does_not_count_as_an_other_holder(admin_client, db_session):
    # An already-deactivated user can't actually reach anything, so their
    # role shouldn't count toward "someone else still has this access" —
    # otherwise the last real holder could be demoted while believing a
    # dead account was a valid backup.
    admin_role = _create_role(db_session, "Admin", ["user_management"], is_system=True)
    _create_user(db_session, "inactive-admin@example.com", role=admin_role, is_active=False, user_id=2)
    only_active_admin = _create_user(db_session, "active-admin@example.com", role=admin_role, user_id=3)
    other_role = _create_role(db_session, "Front Desk", ["staff"])

    resp = admin_client.patch(f"/users/{only_active_admin.id}", json={"role_id": other_role.id})
    assert resp.status_code == 400
    assert "last remaining user with User Management access" in resp.json()["detail"]


def test_update_unknown_user_returns_404(admin_client, db_session):
    resp = admin_client.patch("/users/999999", json={"is_active": False})
    assert resp.status_code == 404


def test_update_to_unknown_role_returns_404(admin_client, db_session):
    target = _create_user(db_session, "target@example.com", user_id=2)
    resp = admin_client.patch(f"/users/{target.id}", json={"role_id": 999999})
    assert resp.status_code == 404


def test_explicit_null_in_patch_body_does_not_500_or_change_anything(admin_client, db_session):
    # {"is_active": null} must be treated as "not provided", not as "set the
    # column to NULL" — the latter would violate the NOT NULL constraint.
    target = _create_user(db_session, "target@example.com", user_id=2)

    resp = admin_client.patch(f"/users/{target.id}", json={"is_active": None, "role_id": None})
    assert resp.status_code == 200, resp.text
    assert resp.json()["is_active"] is True
    assert resp.json()["role"] is None

    logs = db_session.query(AuditLog).filter(AuditLog.entity_type == "user", AuditLog.entity_id == target.id).all()
    assert logs == []


def test_empty_patch_body_does_not_write_an_audit_entry(admin_client, db_session):
    target = _create_user(db_session, "target@example.com", user_id=2)

    resp = admin_client.patch(f"/users/{target.id}", json={})
    assert resp.status_code == 200, resp.text

    logs = db_session.query(AuditLog).filter(AuditLog.entity_type == "user", AuditLog.entity_id == target.id).all()
    assert logs == []
