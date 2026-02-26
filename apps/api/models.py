from datetime import datetime, date
from typing import Optional
from sqlalchemy import (
    Integer, String, Float, Date, DateTime, ForeignKey, Text, Enum
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from database import Base
import enum


class TransactionType(str, enum.Enum):
    expense = "expense"
    income = "income"
    transfer = "transfer"


class MatchStatus(str, enum.Enum):
    unmatched = "unmatched"
    matched = "matched"
    discrepancy = "discrepancy"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Integer, default=1)  # SQLite uses INTEGER for bool
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class UploadedFile(Base):
    __tablename__ = "uploaded_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    original_name: Mapped[str] = mapped_column(String(255))
    stored_path: Mapped[str] = mapped_column(String(500))
    mime_type: Mapped[str] = mapped_column(String(100))
    ocr_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ai_result: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON string
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    transaction: Mapped[Optional["Transaction"]] = relationship("Transaction", back_populates="file", uselist=False)


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    type: Mapped[str] = mapped_column(String(10))  # expense | income
    amount: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(10), default="USD")
    category: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(String(500))
    date: Mapped[date] = mapped_column(Date)
    vendor: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    bank: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    bank_account_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("bank_accounts.id", ondelete="SET NULL"), nullable=True)
    file_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("uploaded_files.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Duplicate detection fields
    is_potential_duplicate: Mapped[bool] = mapped_column(Integer, default=0)  # SQLite uses 0/1 for boolean
    duplicate_of_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("transactions.id", ondelete="SET NULL"), nullable=True)
    duplicate_reviewed: Mapped[bool] = mapped_column(Integer, default=0)
    duplicate_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    file: Mapped[Optional[UploadedFile]] = relationship("UploadedFile", back_populates="transaction")
    bank_account: Mapped[Optional["BankAccount"]] = relationship("BankAccount", back_populates="transactions")
    audit_logs: Mapped[list["AuditLog"]] = relationship("AuditLog", back_populates="transaction", foreign_keys="AuditLog.entity_id", primaryjoin="and_(AuditLog.entity_id == Transaction.id, AuditLog.entity_type == 'transaction')", passive_deletes=True)
    bank_match: Mapped[Optional["BankTransaction"]] = relationship("BankTransaction", back_populates="matched_transaction", uselist=False)

    # Self-referential relationship for duplicates
    potential_duplicate: Mapped[Optional["Transaction"]] = relationship("Transaction", remote_side="Transaction.id", foreign_keys=[duplicate_of_id])


class BankStatement(Base):
    __tablename__ = "bank_statements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    bank_name: Mapped[str] = mapped_column(String(200))
    bank_account_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("bank_accounts.id", ondelete="SET NULL"), nullable=True)
    account_last4: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    statement_period_start: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    statement_period_end: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    file_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)  # Only PDFs are saved to disk
    file_type: Mapped[str] = mapped_column(String(20))  # csv | excel | pdf
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | reconciled
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    bank_account: Mapped[Optional["BankAccount"]] = relationship("BankAccount", back_populates="statements")
    bank_transactions: Mapped[list["BankTransaction"]] = relationship("BankTransaction", back_populates="statement", cascade="all, delete-orphan")


class BankTransaction(Base):
    __tablename__ = "bank_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    statement_id: Mapped[int] = mapped_column(Integer, ForeignKey("bank_statements.id"))
    date: Mapped[date] = mapped_column(Date)
    description: Mapped[str] = mapped_column(String(500))
    amount: Mapped[float] = mapped_column(Float)
    transaction_type: Mapped[str] = mapped_column(String(10))  # debit | credit
    reference: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    vendor: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)  # Extracted from description
    matched_transaction_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("transactions.id"), nullable=True)
    match_status: Mapped[str] = mapped_column(String(20), default="unmatched")
    match_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # AI / keyword-suggested category and type (pre-fills the import review table)
    suggested_category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    suggested_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    statement: Mapped[BankStatement] = relationship("BankStatement", back_populates="bank_transactions")
    matched_transaction: Mapped[Optional[Transaction]] = relationship("Transaction", back_populates="bank_match")


class BankAccount(Base):
    __tablename__ = "bank_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    bank_name: Mapped[str] = mapped_column(String(200))
    account_holder_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    account_number: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    transactions: Mapped[list["Transaction"]] = relationship("Transaction", back_populates="bank_account")
    statements: Mapped[list["BankStatement"]] = relationship("BankStatement", back_populates="bank_account")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    entity_type: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(50))
    old_values: Mapped[Optional[str]] = mapped_column(Text, nullable=True)   # JSON
    new_values: Mapped[Optional[str]] = mapped_column(Text, nullable=True)   # JSON
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    transaction: Mapped[Optional[Transaction]] = relationship(
        "Transaction",
        back_populates="audit_logs",
        foreign_keys=[entity_id],
        primaryjoin="and_(AuditLog.entity_id == Transaction.id, AuditLog.entity_type == 'transaction')",
        viewonly=True,
    )
