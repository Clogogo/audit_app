"""Shared pytest fixtures.

Sets DATABASE_URL/SECRET_KEY before any application module is imported,
since database.py (and code that imports it) reads these env vars exactly
once at import time. Locally this defaults to a throwaway SQLite file so
running pytest never touches the real finance.db; in CI, DATABASE_URL is
already set to point at a Postgres service container before pytest runs,
and os.environ.setdefault below leaves that untouched.
"""
import os
import sys
from pathlib import Path

API_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_DIR))

TEST_DB_PATH = Path(__file__).resolve().parent / "test.db"
os.environ.setdefault("DATABASE_URL", f"sqlite:///{TEST_DB_PATH}")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("OPENROUTER_API_KEY", "test-key-not-real")
os.environ.setdefault("REGISTRATION_INVITE_CODE", "test-invite-code")
os.environ.setdefault("RESEND_API_KEY", "test-key-not-real")

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

from database import Base, SessionLocal, engine, initialize_database
from main import app
from models import User
from utils.auth import get_current_user, hash_password


@pytest.fixture(autouse=True)
def _mock_email_sending():
    """No test should make a real Resend API call — patch all three
    send_* functions at their point of use (routers.auth) by default.
    Tests that want to assert on send behavior re-patch locally, which
    just shadows this one for that `with` block."""
    with (
        patch("routers.auth.send_password_reset_email"),
        patch("routers.auth.send_welcome_email"),
        patch("routers.auth.send_password_changed_email"),
    ):
        yield


@pytest.fixture(scope="session", autouse=True)
def _setup_database():
    initialize_database()
    yield
    Base.metadata.drop_all(bind=engine)
    if engine.dialect.name == "sqlite" and TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()


@pytest.fixture(autouse=True)
def _clean_tables():
    """Truncate every table between tests so they don't see each other's data."""
    yield
    with engine.begin() as connection:
        for table in reversed(Base.metadata.sorted_tables):
            connection.execute(table.delete())


@pytest.fixture
def db_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _fake_current_user() -> User:
    """Stand-in for get_current_user — every router except auth.py now
    requires a logged-in user, so the `client` fixture authenticates as this
    fake user by default rather than every existing test needing real login."""
    return User(
        id=1,
        email="test@example.com",
        hashed_password=hash_password("test-password-123"),
        full_name="Test User",
        is_active=True,
    )


@pytest.fixture
def client():
    app.dependency_overrides[get_current_user] = _fake_current_user
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def anon_client():
    """A client with no auth override — for tests that specifically verify
    unauthenticated requests are rejected."""
    return TestClient(app)
