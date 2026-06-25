from datetime import date, datetime
from typing import Optional, Any
from pydantic import BaseModel, EmailStr


# ── Authentication ────────────────────────────────────────────────────────────

class UserRegister(BaseModel):
    """Schema for user registration."""
    email: EmailStr
    password: str
    full_name: Optional[str] = None


class UserLogin(BaseModel):
    """Schema for user login."""
    email: EmailStr
    password: str


class ForgotPasswordRequest(BaseModel):
    """Schema for resetting a forgotten password directly by email."""
    email: EmailStr
    new_password: str


class Token(BaseModel):
    """Schema for JWT token response."""
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    """Schema for user information response."""
    id: int
    email: str
    full_name: Optional[str]
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Transactions ──────────────────────────────────────────────────────────────

class TransactionCreate(BaseModel):
    type: str
    amount: float
    currency: str = "NGN"
    category: str
    description: str
    date: date
    vendor: Optional[str] = None
    bank: Optional[str] = None
    bank_account_id: Optional[int] = None
    file_id: Optional[int] = None


class TransactionUpdate(BaseModel):
    type: Optional[str] = None
    amount: Optional[float] = None
    currency: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    date: Optional[str] = None  # accept ISO string; parsed to date in the handler
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
    bank_account_id: Optional[int]
    file_id: Optional[int]
    created_at: datetime
    updated_at: datetime
    # Duplicate detection fields
    is_potential_duplicate: bool = False
    duplicate_of_id: Optional[int] = None
    duplicate_reviewed: bool = False
    duplicate_confidence: Optional[float] = None

    model_config = {"from_attributes": True}


class TransactionPage(BaseModel):
    items: list["TransactionOut"]
    total: int
    limit: int
    offset: int


class MonthlySummary(BaseModel):
    month: str
    income: float
    expenses: float


class TransactionSummary(BaseModel):
    total_income: float
    total_expenses: float
    balance: float
    by_category: dict[str, float]          # kept for compat (all categories)
    expense_by_category: dict[str, float]  # expenses only
    income_by_category: dict[str, float]   # income only
    monthly: list[MonthlySummary]


class TransactionAISummary(BaseModel):
    narrative: Optional[str] = None
    available: bool


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
    currency: str = "NGN"
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
    currency: str = "NGN"
    category: str
    description: str
    date: date
    vendor: Optional[str] = None
    type: str = "expense"


class StatementImportRequest(BaseModel):
    items: list[StatementImportItem]
    bank_account_id: Optional[int] = None  # link all saved transactions to this account
    resolution_mode: str = "manual"  # "manual" or "auto" - how to handle duplicates


class StatementImportResult(BaseModel):
    saved: int                   # new transactions created
    reconciled: int              # duplicates linked to existing transactions
    duplicates_flagged: int = 0  # duplicates flagged for manual review
    duplicates_resolved: int = 0 # duplicates auto-resolved
    statement_id: int


# ── LLM Bank Statement Extraction ────────────────────────────────────────────

class LLMBankTransactionItem(BaseModel):
    """Transaction extracted by LLM from bank statement."""
    date: str  # ISO format YYYY-MM-DD
    description: str
    amount: float
    transaction_type: str  # debit | credit
    balance_after: Optional[float] = None
    reference: Optional[str] = None
    vendor: Optional[str] = None
    category_suggested: Optional[str] = None
    confidence: float = 1.0


class LLMBankStatementMetadata(BaseModel):
    """Metadata extracted by LLM."""
    bank_name: str
    account_number: Optional[str] = None
    account_holder: Optional[str] = None
    statement_period_start: Optional[str] = None
    statement_period_end: Optional[str] = None
    opening_balance: Optional[float] = None
    closing_balance: Optional[float] = None
    currency: str = "NGN"
    statement_date: Optional[str] = None


class LLMStatementParseResult(BaseModel):
    """Result of LLM parsing a bank statement."""
    metadata: LLMBankStatementMetadata
    transactions: list[LLMBankTransactionItem]
    extraction_quality: str  # high | medium | low
    validation_issues: list[str] = []


class LLMStatementUploadResult(BaseModel):
    """Response when uploading a bank statement for LLM parsing."""
    statement_id: int
    file_name: str
    bank_name: str
    statement_period_start: Optional[str] = None
    statement_period_end: Optional[str] = None
    transaction_count: int
    extraction_quality: str
    validation_issues: list[str] = []
    metadata: LLMBankStatementMetadata


class LLMStatementImportItem(BaseModel):
    """Item to import from LLM-extracted statement."""
    transaction_index: int  # Index in extracted transactions
    amount: float
    currency: str = "NGN"
    category: str  # Must be valid category
    description: str
    date: date
    vendor: Optional[str] = None
    type: str = "expense"


class LLMStatementImportRequest(BaseModel):
    """Request to import transactions from LLM-extracted statement."""
    statement_id: int
    items: list[LLMStatementImportItem]
    bank_account_id: Optional[int] = None


class LLMStatementImportResult(BaseModel):
    """Result of importing transactions from LLM-extracted statement."""
    saved: int  # New transactions created
    reconciled: int  # Matched with existing transactions
    statement_id: int


# ── Bank Accounts ─────────────────────────────────────────────────────────────


class BankAccountCreate(BaseModel):
    """Create or update a bank account."""
    bank_name: str
    account_holder_name: Optional[str] = None
    account_number: Optional[str] = None
    opening_balance: Optional[float] = None
    current_balance: Optional[float] = None


class BankAccountOut(BaseModel):
    """Bank account for management/CRUD operations."""
    id: int
    bank_name: str
    account_holder_name: Optional[str]
    account_number: Optional[str]
    opening_balance: Optional[float]
    current_balance: Optional[float]
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Bank Statements ───────────────────────────────────────────────────────────

class BankStatementOut(BaseModel):
    id: int
    bank_name: str
    bank_account_id: Optional[int]
    account_last4: Optional[str]
    statement_period_start: Optional[date]
    statement_period_end: Optional[date]
    file_path: Optional[str]  # None for CSV/Excel (parsed from memory)
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
    vendor: Optional[str] = None  # Extracted recipient/merchant name
    matched_transaction_id: Optional[int]
    match_status: str
    match_confidence: Optional[float]
    suggested_category: Optional[str] = None
    suggested_type: Optional[str] = None
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


# ── Bank Account Reports ──────────────────────────────────────────────────────

class BankAccountReportSummary(BaseModel):
    """Summary report for a bank account - income and expense totals."""
    bank_account_id: int
    bank_name: str
    account_holder_name: Optional[str]
    account_number: Optional[str]
    opening_balance: float  # Balance at start of period (e.g. Dec 31 prior year)
    total_income: float
    total_expense: float
    total_transfer: float  # Inter-account transfers shown separately for reference
    net_amount: float  # opening_balance + income - expense
    income_count: int
    expense_count: int  # Includes transfer count
    transfer_count: int  # Subset of expense_count - for reference only
    total_transactions: int
    first_transaction_date: Optional[date]
    last_transaction_date: Optional[date]
    currency: str


class BankAccountReport(BaseModel):
    """Detailed report for a bank account with category breakdown and monthly trends."""
    bank_account_id: int
    bank_name: str
    account_holder_name: Optional[str]
    account_number: Optional[str]
    opening_balance: float
    total_income: float
    total_expense: float
    total_transfer: float
    net_amount: float  # opening_balance + income - expense
    income_count: int
    expense_count: int
    transfer_count: int
    total_transactions: int
    expense_by_category: dict[str, float]  # category name -> total amount
    income_by_category: dict[str, float]   # category name -> total amount
    transfer_by_category: dict[str, float]  # category name -> total amount
    monthly_breakdown: dict[str, dict[str, float]]  # YYYY-MM -> {income, expense, transfer}
    first_transaction_date: Optional[date]
    last_transaction_date: Optional[date]
    currency: str
