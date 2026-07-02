import logging
import os
from pathlib import Path

from sqlalchemy import create_engine, inspect, text, Boolean
from sqlalchemy.orm import DeclarativeBase, sessionmaker

logger = logging.getLogger(__name__)

# Production: set DATABASE_URL (e.g. Render managed Postgres) for a real,
# persistent database. Local/dev default: SQLite file on disk, no external
# database needed. SQLAlchemy abstracts the engine, so the rest of the app
# (models, queries, routers) is identical either way.
_database_url = os.getenv("DATABASE_URL")

if _database_url:
    # Render/Heroku-style URLs use the legacy "postgres://" scheme;
    # SQLAlchemy 1.4+ requires "postgresql://".
    if _database_url.startswith("postgres://"):
        _database_url = _database_url.replace("postgres://", "postgresql://", 1)
    DATABASE_URL = _database_url
    connect_args = {}
else:
    BASE_DIR = Path(__file__).resolve().parents[2]
    DB_DIRECTORY = Path(os.getenv("DB_PATH", str(BASE_DIR)))
    if not DB_DIRECTORY.exists() or not os.access(DB_DIRECTORY, os.W_OK):
        DB_DIRECTORY = Path("/tmp")
    DB_DIRECTORY.mkdir(parents=True, exist_ok=True)
    DATABASE_URL = f"sqlite:///{DB_DIRECTORY / 'finance.db'}"
    connect_args = {"check_same_thread": False, "timeout": 30}

logger.info(f"Using database engine: {DATABASE_URL.split('://')[0]}")  # never log credentials

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    echo=os.getenv("SQL_ECHO", "False") == "True",
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def initialize_database() -> None:
    """Create tables and add missing columns. Works against SQLite or Postgres —
    every statement here is standard SQL supported by both engines."""

    from models import Base  # Imported lazily so model registration is complete.

    Base.metadata.create_all(bind=engine)

    schema_updates = {
        "transactions": [
            "bank VARCHAR(200)",
            "bank_account_id INTEGER REFERENCES bank_accounts(id) ON DELETE SET NULL",
            "is_potential_duplicate INTEGER DEFAULT 0",
            "duplicate_of_id INTEGER REFERENCES transactions(id) ON DELETE SET NULL",
            "duplicate_reviewed INTEGER DEFAULT 0",
            "duplicate_confidence FLOAT",
        ],
        "bank_transactions": [
            "suggested_category VARCHAR(100)",
            "suggested_type VARCHAR(20)",
            "vendor VARCHAR(200)",
        ],
        "staff_loans": [
            "deduction_rate REAL DEFAULT 0.5",
            "staff_id INTEGER REFERENCES staff(id) ON DELETE SET NULL",
        ],
        "staff": [
            "start_date DATE",
            "end_date DATE",
        ],
        "payroll_entries": [
            "bonus REAL DEFAULT 0.0",
            "advance_deduction REAL DEFAULT 0.0",
        ],
        "staff_loan_payments": [
            "transaction_id INTEGER REFERENCES transactions(id) ON DELETE SET NULL",
        ],
        "bank_accounts": [
            "opening_balance REAL",
            "current_balance REAL",
        ],
        "advance_payments": [
            "remaining_amount REAL DEFAULT 0.0",
        ],
    }

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.connect() as connection:
        # NOTE: table/column identifiers interpolated into raw SQL below come
        # only from the hardcoded literals above (schema_updates, bool_columns)
        # or from existing_tables/inspector.get_columns() — never from request
        # input. SQL identifiers can't be parameterized via bind params, so
        # this f-string pattern is the normal way to build DDL; just never
        # feed it a value that traces back to a user-supplied string.

        # Migrate staff_loans: drop legacy monthly_deduction (NOT NULL) → use deduction_rate
        if "staff_loans" in existing_tables:
            sl_cols = {col["name"] for col in inspector.get_columns("staff_loans")}
            if "monthly_deduction" in sl_cols:
                connection.execute(text("""
                    CREATE TABLE IF NOT EXISTS staff_loans_new (
                        id INTEGER NOT NULL,
                        employee_name VARCHAR(200) NOT NULL,
                        loan_amount FLOAT NOT NULL,
                        deduction_rate REAL DEFAULT 0.5,
                        deduction_start DATE NOT NULL,
                        notes TEXT,
                        is_active INTEGER NOT NULL DEFAULT 1,
                        created_at DATETIME NOT NULL,
                        updated_at DATETIME NOT NULL,
                        PRIMARY KEY (id)
                    )
                """))
                connection.execute(text("""
                    INSERT INTO staff_loans_new
                    SELECT id, employee_name, loan_amount,
                           COALESCE(deduction_rate, 0.5),
                           deduction_start, notes, is_active, created_at, updated_at
                    FROM staff_loans
                """))
                connection.execute(text("DROP TABLE staff_loans"))
                connection.execute(text("ALTER TABLE staff_loans_new RENAME TO staff_loans"))
                connection.execute(text(
                    "CREATE INDEX IF NOT EXISTS ix_staff_loans_id ON staff_loans (id)"
                ))
                connection.commit()

        for table_name, column_definitions in schema_updates.items():
            if table_name not in existing_tables:
                continue
            existing_columns = {column["name"] for column in inspector.get_columns(table_name)}

            for column_definition in column_definitions:
                column_name = column_definition.split()[0]
                if column_name in existing_columns:
                    continue

                connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_definition}"))

        connection.execute(
            text("UPDATE transactions SET currency = 'NGN' WHERE currency = 'USD' OR currency IS NULL")
        )
        # Backfill remaining_amount = amount for any advance rows that existed
        # before the remaining_amount column was added (they'd have the column
        # default of 0.0, making them invisible to _advance_deduction_for_month).
        # Use :val so SQLAlchemy adapts the bool correctly for both Postgres
        # (boolean column) and SQLite (integer 0/1).
        connection.execute(text(
            "UPDATE advance_payments SET remaining_amount = amount "
            "WHERE remaining_amount = 0 AND is_recovered = :val"
        ), {"val": False})
        connection.commit()

        # Postgres only: columns that were created as INTEGER (back when the
        # models declared Integer for booleans) need converting to a real
        # boolean type, otherwise psycopg2 sends `true`/`false` literals for
        # Python bool assignments and Postgres rejects them against an
        # integer column. SQLite has no real column types to fix — it already
        # stores these as 0/1 either way, so this is a no-op there.
        if engine.dialect.name == "postgresql":
            bool_columns = [
                ("users", "is_active"),
                ("transactions", "is_potential_duplicate"),
                ("transactions", "duplicate_reviewed"),
                ("staff", "is_active"),
                ("staff_loans", "is_active"),
                ("school_loans", "is_active"),
                ("payroll_entries", "is_paid"),
            ]
            for table_name, column_name in bool_columns:
                if table_name not in existing_tables:
                    continue
                col_info = next(
                    (c for c in inspector.get_columns(table_name) if c["name"] == column_name),
                    None,
                )
                if col_info is None or isinstance(col_info["type"], Boolean):
                    continue
                connection.execute(text(
                    f"ALTER TABLE {table_name} ALTER COLUMN {column_name} "
                    f"TYPE boolean USING ({column_name} <> 0)"
                ))
            connection.commit()
