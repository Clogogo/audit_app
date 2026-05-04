from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
import os
import logging

logger = logging.getLogger(__name__)

# SQLite-based configuration for Vercel compatibility
# Works with no external endpoint dependencies
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Try to use a writable directory, fall back to current directory
db_directory = os.getenv("DB_PATH", BASE_DIR)
if not os.access(db_directory, os.W_OK):
    db_directory = "/tmp"

DATABASE_URL = f"sqlite:///{db_directory}/finance.db"
logger.info(f"Using database: {DATABASE_URL}")

# SQLite configuration optimized for serverless/Vercel
engine = create_engine(
    DATABASE_URL,
    connect_args={
        "check_same_thread": False,
        "timeout": 30,  # Timeout for database locks
    },
    echo=os.getenv("SQL_ECHO", "False") == "True",
    pool_size=0,  # Disable pooling for SQLite
    max_overflow=0,  # No overflow connections
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
        db.close()
