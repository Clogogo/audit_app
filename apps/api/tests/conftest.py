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

import pytest
from fastapi.testclient import TestClient

from database import Base, SessionLocal, engine, initialize_database
from main import app


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


@pytest.fixture
def client():
    return TestClient(app)
