"""Tests that every auth/account event writes an AuditLog row: register,
login (success, bad credentials, blocked-inactive), forgot/reset password,
and change-password (success and failure)."""
import hashlib
from datetime import datetime, timedelta

from models import AuditLog, PasswordResetToken, User
from utils.auth import hash_password


def _logs_for(db_session, action: str) -> list[AuditLog]:
    return db_session.query(AuditLog).filter(AuditLog.entity_type == "user", AuditLog.action == action).all()


def test_register_writes_an_audit_log_entry(anon_client, db_session):
    resp = anon_client.post("/auth/register", json={
        "email": "audited-register@example.com", "password": "secret123",
    })
    assert resp.status_code == 201, resp.text
    user_id = resp.json()["id"]

    logs = _logs_for(db_session, "register")
    assert len(logs) == 1
    assert logs[0].entity_id == user_id


def test_successful_login_writes_an_audit_log_entry(anon_client, db_session):
    user = User(email="audited-login@example.com", hashed_password=hash_password("secret123"), is_active=True)
    db_session.add(user)
    db_session.commit()

    resp = anon_client.post("/auth/login", json={"email": "audited-login@example.com", "password": "secret123"})
    assert resp.status_code == 200, resp.text

    logs = _logs_for(db_session, "login")
    assert len(logs) == 1
    assert logs[0].entity_id == user.id


def test_failed_login_writes_an_audit_log_entry_with_attempted_email(anon_client, db_session):
    resp = anon_client.post("/auth/login", json={"email": "nobody-audited@example.com", "password": "wrong"})
    assert resp.status_code == 401

    logs = _logs_for(db_session, "login_failed")
    assert len(logs) == 1
    assert logs[0].entity_id == 0
    assert "nobody-audited@example.com" in logs[0].new_values


def test_blocked_login_for_inactive_account_writes_an_audit_log_entry(anon_client, db_session):
    user = User(email="inactive-audited@example.com", hashed_password=hash_password("secret123"), is_active=False)
    db_session.add(user)
    db_session.commit()

    resp = anon_client.post("/auth/login", json={"email": "inactive-audited@example.com", "password": "secret123"})
    assert resp.status_code == 403

    logs = _logs_for(db_session, "login_blocked_inactive")
    assert len(logs) == 1
    assert logs[0].entity_id == user.id


def test_forgot_password_request_writes_an_audit_log_entry(anon_client, db_session):
    user = User(email="forgot-audited@example.com", hashed_password=hash_password("secret123"), is_active=True)
    db_session.add(user)
    db_session.commit()

    resp = anon_client.post("/auth/forgot-password", json={"email": "forgot-audited@example.com"})
    assert resp.status_code == 200

    logs = _logs_for(db_session, "forgot_password_requested")
    assert len(logs) == 1
    assert logs[0].entity_id == user.id


def test_forgot_password_for_an_unregistered_email_still_writes_an_audit_log_entry(anon_client, db_session):
    # Anti-enumeration means the HTTP response can't reveal this, but the
    # attempt itself must still be audited (entity_id=0 sentinel, same
    # pattern as login_failed).
    resp = anon_client.post("/auth/forgot-password", json={"email": "unregistered-audited@example.com"})
    assert resp.status_code == 200

    logs = _logs_for(db_session, "forgot_password_requested")
    assert len(logs) == 1
    assert logs[0].entity_id == 0
    assert "unregistered-audited@example.com" in logs[0].new_values


def test_forgot_password_writes_an_audit_log_entry_even_when_mail_is_unconfigured(anon_client, db_session, monkeypatch):
    monkeypatch.delenv("MAILEROO_API_KEY", raising=False)
    monkeypatch.delenv("MAILEROO_FROM_EMAIL", raising=False)

    resp = anon_client.post("/auth/forgot-password", json={"email": "mail-unconfigured@example.com"})
    assert resp.status_code == 200

    logs = _logs_for(db_session, "forgot_password_requested")
    assert len(logs) == 1


def test_reset_password_writes_an_audit_log_entry(anon_client, db_session):
    user = User(email="reset-audited@example.com", hashed_password=hash_password("oldpass123"), is_active=True)
    db_session.add(user)
    db_session.commit()

    raw_token = "audit-test-token"
    reset_token = PasswordResetToken(
        user_id=user.id,
        token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
        expires_at=datetime.utcnow() + timedelta(minutes=30),
    )
    db_session.add(reset_token)
    db_session.commit()

    resp = anon_client.post("/auth/reset-password", json={"token": raw_token, "new_password": "brandnewpass123"})
    assert resp.status_code == 200, resp.text

    logs = _logs_for(db_session, "reset_password")
    assert len(logs) == 1
    assert logs[0].entity_id == user.id


def test_change_password_failure_writes_an_audit_log_entry(client, db_session):
    resp = client.post("/auth/change-password", json={
        "current_password": "wrong-password", "new_password": "newpass123",
    })
    assert resp.status_code == 401

    logs = _logs_for(db_session, "change_password_failed")
    assert len(logs) == 1
    assert logs[0].entity_id == 1  # the client fixture's fake user id


def test_change_password_success_writes_an_audit_log_entry(client, db_session):
    resp = client.post("/auth/change-password", json={
        "current_password": "test-password-123", "new_password": "newpass456",
    })
    assert resp.status_code == 200, resp.text

    logs = _logs_for(db_session, "change_password")
    assert len(logs) == 1
    assert logs[0].entity_id == 1
