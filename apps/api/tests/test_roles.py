"""Tests for GET/POST/PUT/DELETE /roles and GET /roles/permissions —
gated by the user_management permission."""
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


def _create_user(db_session, email: str, role: Role | None = None, user_id: int | None = None) -> User:
    user = User(
        id=user_id, email=email, hashed_password=hash_password("password123"),
        full_name="Test User", is_active=True,
    )
    if role is not None:
        user.role = role
    db_session.add(user)
    db_session.commit()
    return user


def _ensure_permissions(db_session, keys: list[str]) -> None:
    for key in keys:
        if not db_session.query(Permission).filter(Permission.key == key).first():
            db_session.add(Permission(key=key, label=key))
    db_session.commit()


ALL_KEYS = ["transactions", "banking", "tax", "staff", "audit_log", "user_management"]


def test_non_admin_gets_403(client, db_session):
    resp = client.get("/roles")
    assert resp.status_code == 403
    resp = client.get("/roles/permissions")
    assert resp.status_code == 403


def test_admin_can_list_roles_and_permissions(admin_client, db_session):
    _create_role(db_session, "Front Desk", ["staff"])

    resp = admin_client.get("/roles")
    assert resp.status_code == 200
    names = {r["name"] for r in resp.json()}
    assert "Front Desk" in names

    resp = admin_client.get("/roles/permissions")
    assert resp.status_code == 200
    assert {"staff"}.issubset({p["key"] for p in resp.json()})


def test_admin_can_create_a_role(admin_client, db_session):
    _ensure_permissions(db_session, ALL_KEYS)

    resp = admin_client.post("/roles", json={
        "name": "Front Desk", "description": "Reception staff", "permission_keys": ["staff"],
    })
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["name"] == "Front Desk"
    assert body["permissions"] == ["staff"]
    assert body["is_system"] is False


def test_creating_a_role_with_a_duplicate_name_fails(admin_client, db_session):
    _create_role(db_session, "Front Desk", ["staff"])

    resp = admin_client.post("/roles", json={"name": "Front Desk", "permission_keys": []})
    assert resp.status_code == 400


def test_creating_a_role_with_an_unknown_permission_key_fails(admin_client, db_session):
    resp = admin_client.post("/roles", json={"name": "Front Desk", "permission_keys": ["not_a_real_key"]})
    assert resp.status_code == 400


def test_admin_can_update_a_role(admin_client, db_session):
    role = _create_role(db_session, "Front Desk", ["staff"])
    _ensure_permissions(db_session, ["banking"])

    resp = admin_client.put(f"/roles/{role.id}", json={
        "name": "Front Office", "permission_keys": ["staff", "banking"],
    })
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "Front Office"
    assert set(resp.json()["permissions"]) == {"staff", "banking"}

    log = db_session.query(AuditLog).filter(AuditLog.entity_type == "role", AuditLog.entity_id == role.id).first()
    assert log is not None
    assert log.action == "update"


def test_cannot_delete_a_system_role(admin_client, db_session):
    role = _create_role(db_session, "Admin", ["user_management"], is_system=True)

    resp = admin_client.delete(f"/roles/{role.id}")
    assert resp.status_code == 400


def test_cannot_delete_a_role_with_assigned_users(admin_client, db_session):
    role = _create_role(db_session, "Front Desk", ["staff"])
    _create_user(db_session, "target@example.com", role=role, user_id=2)

    resp = admin_client.delete(f"/roles/{role.id}")
    assert resp.status_code == 400


def test_can_delete_an_unused_non_system_role(admin_client, db_session):
    role = _create_role(db_session, "Front Desk", ["staff"])

    resp = admin_client.delete(f"/roles/{role.id}")
    assert resp.status_code == 204

    assert db_session.query(Role).filter(Role.id == role.id).first() is None


def test_cannot_update_a_role_to_strand_user_management(admin_client, db_session):
    # Only one role holds user_management, and a real user (not the acting
    # fake admin, id=1) depends on it — removing the permission must be
    # blocked, since nobody would be left who could reach this page.
    role = _create_role(db_session, "Admin", ["user_management"], is_system=False)
    _create_user(db_session, "only-admin@example.com", role=role, user_id=2)

    resp = admin_client.put(f"/roles/{role.id}", json={"name": "Admin", "permission_keys": ["staff"]})
    assert resp.status_code == 400
    assert "User Management" in resp.json()["detail"]


def test_can_update_a_role_to_remove_user_management_when_another_holder_exists(admin_client, db_session):
    role_a = _create_role(db_session, "Admin A", ["user_management"])
    role_b = _create_role(db_session, "Admin B", ["user_management"])
    _create_user(db_session, "other-admin@example.com", role=role_b, user_id=2)
    _ensure_permissions(db_session, ["staff"])

    # role_a has no users assigned, so removing its permission is harmless.
    resp = admin_client.put(f"/roles/{role_a.id}", json={"name": "Admin A", "permission_keys": ["staff"]})
    assert resp.status_code == 200, resp.text


def test_update_unknown_role_returns_404(admin_client, db_session):
    resp = admin_client.put("/roles/999999", json={"name": "X", "permission_keys": []})
    assert resp.status_code == 404
