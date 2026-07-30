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
            "opening_balance_date DATE",
            "current_balance REAL",
        ],
        "advance_payments": [
            "remaining_amount REAL DEFAULT 0.0",
        ],
        "teacher_bonuses": [
            "frequency VARCHAR(20) DEFAULT 'onetime'",
            "end_year INTEGER",
            "end_month INTEGER",
        ],
        "school_loans": [
            "total_interest_due REAL NOT NULL DEFAULT 0.0",
            "transaction_id INTEGER REFERENCES transactions(id) ON DELETE SET NULL",
        ],
        "users": [
            "is_admin BOOLEAN NOT NULL DEFAULT FALSE",
            "role_id INTEGER REFERENCES roles(id) ON DELETE SET NULL",
        ],
        "stock_movements": [
            "unit_cost FLOAT",
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

    _seed_roles_and_permissions()
    _seed_bonus_types()


# One (key, label) per app section — a fixed set defined by the app's own
# nav structure, not admin-creatable, unlike Role which is fully editable.
_PERMISSION_SEEDS = [
    ("transactions", "Transactions"),
    ("banking", "Banking"),
    ("tax", "Tax & Compliance"),
    ("staff", "Staff & Payroll"),
    ("inventory", "Inventory"),
    ("audit_log", "Audit Log"),
    ("user_management", "User Management"),
]


def _seed_roles_and_permissions() -> None:
    """Idempotent permission/role seed, plus a one-time migration of any
    user that doesn't have a role yet. Uses the ORM (not raw connection.text)
    since a role's permission set is a real object graph, not a flat
    column — imported lazily, same reason as the `from models import Base`
    import above: model registration must already be complete.
    """
    from models import Permission, Role, User

    with SessionLocal() as session:
        existing_perm_keys = {p.key for p in session.query(Permission).all()}
        for key, label in _PERMISSION_SEEDS:
            if key not in existing_perm_keys:
                session.add(Permission(key=key, label=label))
        session.commit()

        permissions_by_key = {p.key: p for p in session.query(Permission).all()}

        existing_role_names = {r.name for r in session.query(Role).all()}
        # The Role table itself didn't exist before this feature — an empty
        # table means this is the very first time this code has ever run
        # against this database. Only THAT run is allowed to cut legacy
        # is_admin users over automatically (see below); every later restart
        # must leave a fresh registration's role_id alone.
        is_first_ever_run = not existing_role_names

        role_seeds = [
            ("Admin", "Full access to every section, including User Management.", True, list(permissions_by_key)),
            ("Accountant", "Full access to financial data; cannot manage users or roles.",
             False, [k for k in permissions_by_key if k != "user_management"]),
            ("Staff", "Dashboard only by default — grant sections as needed.", False, []),
        ]
        for name, description, is_system, perm_keys in role_seeds:
            if name not in existing_role_names:
                role = Role(name=name, description=description, is_system=is_system)
                role.permissions = [permissions_by_key[k] for k in perm_keys]
                session.add(role)
        session.commit()

        admin_role = session.query(Role).filter(Role.name == "Admin").first()
        accountant_role = session.query(Role).filter(Role.name == "Accountant").first()

        # Reconcile permission grants for Admin/Accountant every startup —
        # the role_seeds loop above only fires once per role name, so a
        # permission key added to _PERMISSION_SEEDS after those roles
        # already exist (e.g. "inventory") would otherwise never reach
        # them. Additive-only and idempotent; Staff is deliberately left
        # alone — it should not auto-gain new section access.
        if admin_role:
            for perm in permissions_by_key.values():
                if perm not in admin_role.permissions:
                    admin_role.permissions.append(perm)
        if accountant_role:
            for key, perm in permissions_by_key.items():
                if key != "user_management" and perm not in accountant_role.permissions:
                    accountant_role.permissions.append(perm)
        session.commit()

        # One-time legacy cutover, first run only: any user that predates the
        # Role table gets Admin (if is_admin was already set) or Accountant
        # (everyone else — matches their current defacto full financial
        # access, since is_admin was the only thing previously gating
        # anything). A user who registers on any LATER run must keep
        # role_id = NULL until an admin explicitly assigns one — they must
        # never be silently upgraded to Accountant just because the server
        # restarted.
        if is_first_ever_run:
            legacy_users = session.query(User).filter(User.role_id.is_(None)).all()
            for user in legacy_users:
                user.role_id = admin_role.id if user.is_admin else accountant_role.id
            if legacy_users:
                session.commit()

        # BOOTSTRAP_ADMIN_EMAIL: only fires while nobody holds the Admin role
        # yet — permanently inert afterward, admins can freely reassign
        # roles (including their own) via the Role/User Management UI
        # without this migration fighting them.
        bootstrap_admin_email = os.getenv("BOOTSTRAP_ADMIN_EMAIL")
        if bootstrap_admin_email:
            admin_holder_count = session.query(User).filter(User.role_id == admin_role.id).count()
            if admin_holder_count == 0:
                target = session.query(User).filter(User.email == bootstrap_admin_email).first()
                if target:
                    target.role_id = admin_role.id
                    session.commit()


# The original six bonus schemes, now seeded as real admin-editable rows
# instead of a hardcoded list (see routers/teacher_bonuses.py) — key,
# label, basis_is_salary, default_percentage. All use calculation_method
# "percentage"; a brand new "flat_amount" type is only ever created
# through the UI, never seeded.
_BONUS_TYPE_SEEDS = [
    ("performance", "Performance Bonus", True, 10.0,
     "Class average 80%+ — reviewed termly"),
    ("punctuality", "Punctuality & Classroom Management Bonus", True, 5.0,
     "Rated EXCELLENT for punctuality and classroom conduct"),
    ("student_referral", "Student Referral Bonus", False, 10.0,
     "% of the referred student's fee — paid after their first full term"),
    ("teacher_referral", "Teacher Referral Bonus", True, 20.0,
     "One-time — the referred teacher was hired and stayed"),
    ("loyalty", "Loyalty Bonus", True, 10.0,
     "End of session — full attendance and consistent performance, any staff member"),
    ("annual_high_performance", "Annual High Performance Bonus", True, 0.0,
     "Dynamic 0-100%, set by management at end of session"),
]


def _seed_bonus_types() -> None:
    """Idempotent — only inserts keys that don't exist yet, same shape as
    _seed_roles_and_permissions(). Safe to run on every startup; never
    touches a row an admin has since edited or retired."""
    from models import BonusType

    with SessionLocal() as session:
        existing_keys = {b.key for b in session.query(BonusType).all()}
        for key, label, basis_is_salary, default_percentage, description in _BONUS_TYPE_SEEDS:
            if key not in existing_keys:
                session.add(BonusType(
                    key=key, label=label, description=description,
                    calculation_method="percentage",
                    basis_is_salary=basis_is_salary,
                    default_percentage=default_percentage,
                ))
        session.commit()
