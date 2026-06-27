"""Tests for the security hardening pass: every router now requires a
logged-in user, registration is gated by an env-var invite code,
forgot/reset-password use an emailed single-use token, and change-password
requires the current password."""
import hashlib
from datetime import datetime, timedelta
from unittest.mock import patch

from models import PasswordResetToken, User
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


def test_register_sends_welcome_email(anon_client, db_session):
    with patch("routers.auth.send_welcome_email") as mock_send:
        resp = anon_client.post("/auth/register", json={
            "email": "newuser3@example.com", "password": "secret123", "invite_code": "test-invite-code",
        })
        assert resp.status_code == 201
        assert mock_send.call_count == 1
        assert mock_send.call_args[0][0] == "newuser3@example.com"


def test_register_succeeds_even_if_welcome_email_fails(anon_client, db_session):
    with patch("routers.auth.send_welcome_email", side_effect=RuntimeError("send failed")):
        resp = anon_client.post("/auth/register", json={
            "email": "newuser4@example.com", "password": "secret123", "invite_code": "test-invite-code",
        })
        assert resp.status_code == 201, resp.text


def test_forgot_password_gives_same_response_whether_or_not_email_exists(anon_client, db_session):
    # Must not be usable to enumerate which emails have accounts.
    user = User(email="exists3@example.com", hashed_password=hash_password("oldpass123"), is_active=True)
    db_session.add(user)
    db_session.commit()

    with patch("routers.auth.send_password_reset_email"):
        resp_known = anon_client.post("/auth/forgot-password", json={"email": "exists3@example.com"})
        resp_unknown = anon_client.post("/auth/forgot-password", json={"email": "doesnotexist@example.com"})

    assert resp_known.status_code == resp_unknown.status_code == 200
    assert resp_known.json() == resp_unknown.json()


def test_forgot_password_creates_token_and_emails_it_only_for_known_email(anon_client, db_session):
    user = User(email="exists4@example.com", hashed_password=hash_password("oldpass123"), is_active=True)
    db_session.add(user)
    db_session.commit()

    with patch("routers.auth.send_password_reset_email") as mock_send:
        anon_client.post("/auth/forgot-password", json={"email": "exists4@example.com"})
        assert mock_send.call_count == 1
        assert mock_send.call_args[0][0] == "exists4@example.com"

    tokens = db_session.query(PasswordResetToken).filter(PasswordResetToken.user_id == user.id).all()
    assert len(tokens) == 1
    assert tokens[0].used is False

    with patch("routers.auth.send_password_reset_email") as mock_send:
        anon_client.post("/auth/forgot-password", json={"email": "doesnotexist@example.com"})
        assert mock_send.call_count == 0


def test_reset_password_succeeds_with_valid_token(anon_client, db_session):
    user = User(email="exists5@example.com", hashed_password=hash_password("oldpass123"), is_active=True)
    db_session.add(user)
    db_session.commit()

    raw_token = "a-valid-raw-token"
    reset_token = PasswordResetToken(
        user_id=user.id,
        token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
        expires_at=datetime.utcnow() + timedelta(minutes=30),
    )
    db_session.add(reset_token)
    db_session.commit()

    resp = anon_client.post("/auth/reset-password", json={"token": raw_token, "new_password": "brandnewpass123"})
    assert resp.status_code == 200, resp.text

    # Old password no longer works, new one does.
    assert anon_client.post("/auth/login", json={"email": "exists5@example.com", "password": "oldpass123"}).status_code == 401
    assert anon_client.post("/auth/login", json={"email": "exists5@example.com", "password": "brandnewpass123"}).status_code == 200

    # Token is single-use.
    resp2 = anon_client.post("/auth/reset-password", json={"token": raw_token, "new_password": "anotherpass123"})
    assert resp2.status_code == 400


def test_reset_password_sends_confirmation_email(anon_client, db_session):
    user = User(email="exists7@example.com", hashed_password=hash_password("oldpass123"), is_active=True)
    db_session.add(user)
    db_session.commit()

    raw_token = "another-valid-token"
    reset_token = PasswordResetToken(
        user_id=user.id,
        token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
        expires_at=datetime.utcnow() + timedelta(minutes=30),
    )
    db_session.add(reset_token)
    db_session.commit()

    with patch("routers.auth.send_password_changed_email") as mock_send:
        resp = anon_client.post("/auth/reset-password", json={"token": raw_token, "new_password": "brandnewpass123"})
        assert resp.status_code == 200
        assert mock_send.call_count == 1
        assert mock_send.call_args[0][0] == "exists7@example.com"


def test_reset_password_rejects_unknown_or_expired_token(anon_client, db_session):
    resp = anon_client.post("/auth/reset-password", json={"token": "never-issued", "new_password": "newpass123"})
    assert resp.status_code == 400

    user = User(email="exists6@example.com", hashed_password=hash_password("oldpass123"), is_active=True)
    db_session.add(user)
    db_session.commit()
    raw_token = "an-expired-token"
    expired = PasswordResetToken(
        user_id=user.id,
        token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
        expires_at=datetime.utcnow() - timedelta(minutes=1),
    )
    db_session.add(expired)
    db_session.commit()

    resp = anon_client.post("/auth/reset-password", json={"token": raw_token, "new_password": "newpass123"})
    assert resp.status_code == 400


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


def test_change_password_sends_confirmation_email(client):
    with patch("routers.auth.send_password_changed_email") as mock_send:
        resp = client.post("/auth/change-password", json={
            "current_password": "test-password-123", "new_password": "newpass456",
        })
        assert resp.status_code == 200
        assert mock_send.call_count == 1
        assert mock_send.call_args[0][0] == "test@example.com"
