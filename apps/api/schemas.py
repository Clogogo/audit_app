from datetime import date, datetime
from typing import Optional, Any
from pydantic import BaseModel


# ── Transactions ──────────────────────────────────────────────────────────────

class TransactionCreate(BaseModel):
    type: str
    amount: float
    currency: str = "USD"
    category: str
    description: str
    date: date
    vendor: Optional[str] = None
    bank: Optional[str] = None
    file_id: Optional[int] = None


class TransactionUpdate(BaseModel):
    type: Optional[str] = None
    amount: Optional[float] = None
    currency: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    date: Optional[date] = None
    vendor: Optional[str] = None
    bank: Optional[str] = None


class TransactionOut(BaseModel):
    id: int
    type: str
    amount: float
    currency: str
    category: str
    description: str
    date: date
    vendor: Optional[str]
    bank: Optional[str]
    file_id: Optional[int]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MonthlySummary(BaseModel):
    month: str
    income: float
    expenses: float


class TransactionSummary(BaseModel):
    total_income: float
    total_expenses: float
    balance: float
    by_category: dict[str, float]
    monthly: list[MonthlySummary]


# ── Uploaded Files ────────────────────────────────────────────────────────────

class AIResult(BaseModel):
    amount: Optional[float] = None
    currency: Optional[str] = None
    date: Optional[str] = None
    vendor: Optional[str] = None
    category: Optional[str] = None
    type: Optional[str] = None
    description: Optional[str] = None


class UploadedFileOut(BaseModel):
    id: int
    original_name: str
    stored_path: str
    mime_type: str
    ocr_text: Optional[str]
    ai_result: Optional[AIResult]
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Batch extraction ───────────────────────────────────────────────────────────

class BatchItem(BaseModel):
    amount: Optional[float] = None
    currency: Optional[str] = "USD"
    date: Optional[str] = None
    vendor: Optional[str] = None
    category: Optional[str] = None
    type: Optional[str] = "expense"
    description: Optional[str] = None
    reference: Optional[str] = None


class BatchUploadResult(BaseModel):
    file_id: int
    original_name: str
    mime_type: str
    item_count: int
    items: list[BatchItem]


class BatchConfirmItem(BaseModel):
    amount: float
    currency: str = "USD"
    category: str
    description: str
    date: date
    vendor: Optional[str] = None
    bank: Optional[str] = None
    type: str = "expense"
    file_id: Optional[int] = None


class BatchConfirmRequest(BaseModel):
    items: list[BatchConfirmItem]


# ── Statement Import ───────────────────────────────────────────────────────────

class StatementImportItem(BaseModel):
    bank_transaction_id: int
    amount: float
    currency: str = "USD"
    category: str
    description: str
    date: date
    vendor: Optional[str] = None
    type: str = "expense"


class StatementImportRequest(BaseModel):
    items: list[StatementImportItem]


# ── Bank Statements ───────────────────────────────────────────────────────────

class BankStatementOut(BaseModel):
    id: int
    bank_name: str
    account_last4: Optional[str]
    statement_period_start: Optional[date]
    statement_period_end: Optional[date]
    file_path: str
    file_type: str
    status: str
    created_at: datetime
    transaction_count: Optional[int] = None
    matched_count: Optional[int] = None

    model_config = {"from_attributes": True}


class BankTransactionOut(BaseModel):
    id: int
    statement_id: int
    date: date
    description: str
    amount: float
    transaction_type: str
    reference: Optional[str]
    matched_transaction_id: Optional[int]
    match_status: str
    match_confidence: Optional[float]
    created_at: datetime

    model_config = {"from_attributes": True}


class ReconciliationStatus(BaseModel):
    statement_id: int
    total: int
    matched: int
    unmatched: int
    discrepancies: int


class ManualMatchRequest(BaseModel):
    bank_transaction_id: int
    transaction_id: int


# ── Audit Log ─────────────────────────────────────────────────────────────────

class AuditLogOut(BaseModel):
    id: int
    entity_type: str
    entity_id: int
    action: str
    old_values: Optional[Any]
    new_values: Optional[Any]
    timestamp: datetime

    model_config = {"from_attributes": True}
