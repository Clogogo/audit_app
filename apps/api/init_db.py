#!/usr/bin/env python
"""
Database initialization script for SQLite.
Run this once to create all tables.

Usage:
    python init_db.py
"""

import sys
import os
from pathlib import Path

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import engine, Base
from models import (
    User,
    UploadedFile,
    Transaction,
    BankStatement,
    BankTransaction,
    BankAccount,
    AuditLog,
)


def init_db():
    """Initialize the database by creating all tables."""
    print("🔧 Initializing SQLite database...")
    print(f"📁 Database location: {os.getenv('DB_PATH', 'PROJECT_ROOT')}/finance.db")

    try:
        Base.metadata.create_all(bind=engine)
        print("✅ Database initialized successfully!")
        print("\n📊 Created tables:")
        for table_name in Base.metadata.tables.keys():
            print(f"   - {table_name}")

        print("\n💡 Next steps:")
        print("   1. Create a superuser: python create_user.py")
        print("   2. Start the API: uvicorn main:app --reload")
        print("   3. Access API docs: http://localhost:8000/docs")

    except Exception as e:
        print(f"❌ Error initializing database: {e}")
        sys.exit(1)


def verify_db():
    """Verify database connection and tables."""
    print("\n🔍 Verifying database...")
    try:
        from sqlalchemy import inspect

        inspector = inspect(engine)
        tables = inspector.get_table_names()

        if tables:
            print(f"✅ Database connection OK. Found {len(tables)} tables")
            for table in tables:
                columns = len(inspector.get_columns(table))
                print(f"   - {table} ({columns} columns)")
        else:
            print("⚠️  Database exists but is empty. Run init_db() to create tables.")

    except Exception as e:
        print(f"❌ Database verification failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    init_db()
    verify_db()
