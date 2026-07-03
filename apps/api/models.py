from datetime import datetime, date
from typing import Optional
from sqlalchemy import (
    Integer, String, Float, Date, DateTime, ForeignKey, Text, Enum, Index, Boolean
)
from sqlalchemy.sql import func
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
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)  # SQLite uses INTEGER for bool
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PasswordResetToken(Base):
    """Single-use, time-limited token emailed to a user for password
    recovery. Only token_hash (sha256 of the random token) is stored —
    never the raw token — so a DB read alone can't be used to reset an
    account."""
    __tablename__ = "password_reset_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


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
    __table_args__ = (
        Index("ix_transactions_date_amount_type", "date", "amount", "type"),
        Index("ix_transactions_bank_account_id", "bank_account_id"),
        Index("ix_transactions_duplicate_flags", "duplicate_reviewed", "is_potential_duplicate"),
    )

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
    is_potential_duplicate: Mapped[bool] = mapped_column(Boolean, default=False)  # SQLite uses 0/1 for boolean
    duplicate_of_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("transactions.id", ondelete="SET NULL"), nullable=True)
    duplicate_reviewed: Mapped[bool] = mapped_column(Boolean, default=False)
    duplicate_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    file: Mapped[Optional[UploadedFile]] = relationship("UploadedFile", back_populates="transaction")
    bank_account: Mapped[Optional["BankAccount"]] = relationship("BankAccount", back_populates="transactions")
    audit_logs: Mapped[list["AuditLog"]] = relationship("AuditLog", back_populates="transaction", foreign_keys="AuditLog.entity_id", primaryjoin="and_(AuditLog.entity_id == Transaction.id, AuditLog.entity_type == 'transaction')", passive_deletes=True)
    bank_match: Mapped[Optional["BankTransaction"]] = relationship("BankTransaction", back_populates="matched_transaction", uselist=False)

    # Self-referential relationship for duplicates
    potential_duplicate: Mapped[Optional["Transaction"]] = relationship("Transaction", remote_side="Transaction.id", foreign_keys=[duplicate_of_id])


class BankStatement(Base):
    __tablename__ = "bank_statements"
    __table_args__ = (
        Index("ix_bank_statements_bank_account_id", "bank_account_id"),
        Index("ix_bank_statements_status_created_at", "status", "created_at"),
    )

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
    __table_args__ = (
        Index("ix_bank_transactions_statement_status_date", "statement_id", "match_status", "date"),
        Index("ix_bank_transactions_statement_amount_date", "statement_id", "amount", "date"),
        Index("ix_bank_transactions_matched_transaction_id", "matched_transaction_id"),
    )

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
    opening_balance: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    current_balance: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    __table_args__ = (
        Index("ix_bank_accounts_account_number", "account_number"),
        Index("ix_bank_accounts_bank_name_account_number", "bank_name", "account_number"),
        Index("ix_bank_accounts_lower_bank_name_account_number", func.lower(bank_name), account_number),
    )

    transactions: Mapped[list["Transaction"]] = relationship("Transaction", back_populates="bank_account")
    statements: Mapped[list["BankStatement"]] = relationship("BankStatement", back_populates="bank_account")


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(100))
    purchase_date: Mapped[date] = mapped_column(Date)
    purchase_cost: Mapped[float] = mapped_column(Float)
    useful_life_years: Mapped[float] = mapped_column(Float, default=5.0)
    depreciation_method: Mapped[str] = mapped_column(String(20), default="straight_line")
    residual_value: Mapped[float] = mapped_column(Float, default=0.0)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Staff(Base):
    __tablename__ = "staff"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    full_name: Mapped[str] = mapped_column(String(200))
    role: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    bank_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    account_number: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    monthly_gross: Mapped[float] = mapped_column(Float, default=0.0)
    start_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    loans: Mapped[list["StaffLoan"]] = relationship("StaffLoan", back_populates="staff_member")
    payroll_entries: Mapped[list["PayrollEntry"]] = relationship("PayrollEntry", back_populates="staff_member")


class StaffLoan(Base):
    __tablename__ = "staff_loans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    staff_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("staff.id", ondelete="SET NULL"), nullable=True)
    employee_name: Mapped[str] = mapped_column(String(200))
    loan_amount: Mapped[float] = mapped_column(Float)
    deduction_rate: Mapped[float] = mapped_column(Float, default=0.5)
    deduction_start: Mapped[date] = mapped_column(Date)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    staff_member: Mapped[Optional["Staff"]] = relationship("Staff", back_populates="loans")
    payments: Mapped[list["StaffLoanPayment"]] = relationship(
        "StaffLoanPayment", back_populates="loan", cascade="all, delete-orphan", order_by="StaffLoanPayment.paid_date"
    )


class StaffLoanPayment(Base):
    __tablename__ = "staff_loan_payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    loan_id: Mapped[int] = mapped_column(Integer, ForeignKey("staff_loans.id", ondelete="CASCADE"))
    transaction_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("transactions.id", ondelete="SET NULL"), nullable=True)
    amount_paid: Mapped[float] = mapped_column(Float)
    paid_date: Mapped[date] = mapped_column(Date)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    loan: Mapped["StaffLoan"] = relationship("StaffLoan", back_populates="payments")
    transaction: Mapped[Optional["Transaction"]] = relationship("Transaction")


class AdvancePayment(Base):
    """A one-off salary advance/IOU given to a staff member — recovered in
    full from the next payroll run processed after it's recorded, not
    repaid in installments like StaffLoan. One row per advance; no separate
    payments sub-table since recovery is a single event."""
    __tablename__ = "advance_payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    staff_id: Mapped[int] = mapped_column(Integer, ForeignKey("staff.id", ondelete="CASCADE"), nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    remaining_amount: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    date_issued: Mapped[date] = mapped_column(Date, nullable=False)
    transaction_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("transactions.id", ondelete="SET NULL"), nullable=True)
    is_recovered: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    recovered_period_year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    recovered_period_month: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    staff_member: Mapped["Staff"] = relationship("Staff")
    transaction: Mapped[Optional["Transaction"]] = relationship("Transaction")


class SchoolLoan(Base):
    """A loan the school has borrowed (collected) from a lender, e.g. a bank or cooperative."""
    __tablename__ = "school_loans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    lender_name: Mapped[str] = mapped_column(String(200))
    loan_amount: Mapped[float] = mapped_column(Float)
    interest_rate: Mapped[float] = mapped_column(Float, default=0.0)  # annual %, reference/display only
    total_interest_due: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)  # agreed total interest, not auto-computed from interest_rate
    collected_date: Mapped[date] = mapped_column(Date)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    payments: Mapped[list["SchoolLoanPayment"]] = relationship(
        "SchoolLoanPayment", back_populates="loan", cascade="all, delete-orphan", order_by="SchoolLoanPayment.paid_date"
    )


class SchoolLoanPayment(Base):
    """A repayment installment on a SchoolLoan, split into principal / interest / misc charges."""
    __tablename__ = "school_loan_payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    loan_id: Mapped[int] = mapped_column(Integer, ForeignKey("school_loans.id", ondelete="CASCADE"))
    transaction_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("transactions.id", ondelete="SET NULL"), nullable=True)
    amount_paid: Mapped[float] = mapped_column(Float)       # total cash paid this installment
    interest_amount: Mapped[float] = mapped_column(Float, default=0.0)  # portion that is interest
    misc_amount: Mapped[float] = mapped_column(Float, default=0.0)      # portion that is misc fees/charges
    paid_date: Mapped[date] = mapped_column(Date)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    loan: Mapped["SchoolLoan"] = relationship("SchoolLoan", back_populates="payments")
    transaction: Mapped[Optional["Transaction"]] = relationship("Transaction")


class PayrollEntry(Base):
    __tablename__ = "payroll_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    staff_id: Mapped[int] = mapped_column(Integer, ForeignKey("staff.id", ondelete="CASCADE"))
    period_year: Mapped[int] = mapped_column(Integer)
    period_month: Mapped[int] = mapped_column(Integer)
    gross_salary: Mapped[float] = mapped_column(Float)
    bonus: Mapped[float] = mapped_column(Float, default=0.0)
    loan_deduction: Mapped[float] = mapped_column(Float, default=0.0)
    advance_deduction: Mapped[float] = mapped_column(Float, default=0.0)
    other_deductions: Mapped[float] = mapped_column(Float, default=0.0)
    net_salary: Mapped[float] = mapped_column(Float)
    is_paid: Mapped[bool] = mapped_column(Boolean, default=False)
    paid_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    transaction_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("transactions.id", ondelete="SET NULL"), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    staff_member: Mapped["Staff"] = relationship("Staff", back_populates="payroll_entries")


class Term(Base):
    __tablename__ = "terms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(100))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_entity_type_entity_id_timestamp", "entity_type", "entity_id", "timestamp"),
    )

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
