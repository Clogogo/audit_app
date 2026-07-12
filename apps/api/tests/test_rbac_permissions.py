"""End-to-end proof that require_permission is actually wired into routers
(not just defined) — a role missing a section's permission gets 403 from
that section's endpoints, and a role with it gets through."""
import pytest
from fastapi.testclient import TestClient

from main import app
from models import Permission, Role, User
from utils.auth import get_current_user, hash_password


def _user_with_permissions(permission_keys: list[str]) -> User:
    user = User(
        id=1, email="scoped@example.com",
        hashed_password=hash_password("password123"),
        full_name="Scoped User", is_active=True,
    )
    role = Role(id=1, name="Scoped", is_system=False)
    role.permissions = [Permission(key=k, label=k) for k in permission_keys]
    user.role = role
    return user


@pytest.fixture
def scoped_client():
    """Yields a function that builds a TestClient authenticated as a fake
    user holding exactly the given permissions."""
    def _make(permission_keys: list[str]) -> TestClient:
        app.dependency_overrides[get_current_user] = lambda: _user_with_permissions(permission_keys)
        return TestClient(app)
    yield _make
    app.dependency_overrides.pop(get_current_user, None)


def test_role_without_staff_permission_is_rejected_from_staff_directory(scoped_client):
    client = scoped_client(["transactions", "banking"])
    resp = client.get("/staff-directory")
    assert resp.status_code == 403


def test_role_with_staff_permission_can_reach_staff_directory(scoped_client):
    client = scoped_client(["staff"])
    resp = client.get("/staff-directory")
    assert resp.status_code == 200


def test_role_without_transactions_permission_is_rejected_from_transactions(scoped_client):
    client = scoped_client(["staff"])
    resp = client.get("/transactions/summary")
    assert resp.status_code == 403


def test_role_with_transactions_permission_can_reach_transactions(scoped_client):
    client = scoped_client(["transactions"])
    resp = client.get("/transactions/summary")
    assert resp.status_code == 200


def test_role_without_inventory_permission_is_rejected_from_inventory(scoped_client):
    client = scoped_client(["staff"])
    resp = client.get("/inventory/items")
    assert resp.status_code == 403


def test_role_with_inventory_permission_can_reach_inventory(scoped_client):
    client = scoped_client(["inventory"])
    resp = client.get("/inventory/items")
    assert resp.status_code == 200


def test_role_with_no_permissions_at_all_is_rejected_everywhere(scoped_client):
    client = scoped_client([])
    assert client.get("/staff-directory").status_code == 403
    assert client.get("/transactions/summary").status_code == 403
    assert client.get("/audit-log").status_code == 403
    assert client.get("/users").status_code == 403
    assert client.get("/inventory/items").status_code == 403


def test_user_with_no_role_at_all_is_rejected_everywhere(scoped_client):
    # Newly registered users have role_id = NULL until an admin assigns one.
    app.dependency_overrides[get_current_user] = lambda: User(
        id=1, email="norole@example.com", hashed_password=hash_password("password123"),
        full_name="No Role", is_active=True,
    )
    client = TestClient(app)
    assert client.get("/staff-directory").status_code == 403
    assert client.get("/transactions/summary").status_code == 403
    assert client.get("/inventory/items").status_code == 403
