"""Tests for the security hardening pass: every router now requires a
logged-in user, registration/forgot-password are gated by env-var codes, and
change-password requires the current password."""
from models import User
from utils.auth import hash_password


def test_anonymous_request_to_protected_route_is_rejected(anon_client):
    # No Authorization header at all — should be rejected, not served.
    resp = anon_client.get("/transactions/summary")
    assert resp.status_code in (401, 403)


def test_anonymous_request_to_payroll_is_rejected(anon_client):
    resp = anon_client.get("/payroll/compute", params={"year": 2026, "month": 1})
    assert resp.status_code in (401, 403)


def test_anonymous_request_to_staff_directory_is_rejected(anon_client):
    resp = anon_client.get("/staff-directory/")
    assert resp.status_code in (401, 403)


def test_auth_me_still_requires_auth_but_other_auth_routes_dont(anon_client):
    # /auth/login, /auth/register, /auth/forgot-password must stay reachable
    # without a token (you can't log in if logging in itself requires login).
    resp = anon_client.post("/auth/login", json={"email": "nobody@example.com", "password": "wrong"})
    assert resp.status_code == 401  # rejected for bad credentials, not for being anonymous

    resp = anon_client.get("/auth/me")
    assert resp.status_code in (401, 403)


def test_register_rejects_missing_or_wrong_invite_code(anon_client):
    resp = anon_client.post("/auth/register", json={
        "email": "newuser@example.com", "password": "secret123", "invite_code": "wrong-code",
    })
    assert resp.status_code == 403

    # invite_code is optional in the schema specifically so omitting it
    # entirely still hits the router's 403 check instead of a 422 validation
    # error (the two should be indistinguishable to an attacker).
    resp = anon_client.post("/auth/register", json={
        "email": "newuser@example.com", "password": "secret123",
    })
    assert resp.status_code == 403


def test_register_succeeds_with_correct_invite_code(anon_client, db_session):
    resp = anon_client.post("/auth/register", json={
        "email": "newuser2@example.com", "password": "secret123", "invite_code": "test-invite-code",
    })
    assert resp.status_code == 201, resp.text


def test_forgot_password_rejects_missing_or_wrong_recovery_code(anon_client, db_session):
    user = User(email="exists@example.com", hashed_password=hash_password("oldpass123"), is_active=True)
    db_session.add(user)
    db_session.commit()

    resp = anon_client.post("/auth/forgot-password", json={
        "email": "exists@example.com", "new_password": "newpass123", "recovery_code": "wrong-code",
    })
    assert resp.status_code == 403

    # recovery_code is optional in the schema specifically so omitting it
    # entirely still hits the router's 403 check instead of a 422.
    resp = anon_client.post("/auth/forgot-password", json={
        "email": "exists@example.com", "new_password": "newpass123",
    })
    assert resp.status_code == 403


def test_forgot_password_succeeds_with_correct_recovery_code(anon_client, db_session):
    user = User(email="exists2@example.com", hashed_password=hash_password("oldpass123"), is_active=True)
    db_session.add(user)
    db_session.commit()

    resp = anon_client.post("/auth/forgot-password", json={
        "email": "exists2@example.com", "new_password": "newpass123", "recovery_code": "test-recovery-code",
    })
    assert resp.status_code == 200, resp.text


def test_change_password_rejects_wrong_current_password(client):
    resp = client.post("/auth/change-password", json={
        "current_password": "not-the-real-password", "new_password": "newpass123",
    })
    assert resp.status_code == 401


def test_change_password_succeeds_with_correct_current_password(client):
    # _fake_current_user in conftest.py sets the password to "test-password-123"
    resp = client.post("/auth/change-password", json={
        "current_password": "test-password-123", "new_password": "newpass456",
    })
    assert resp.status_code == 200, resp.text
