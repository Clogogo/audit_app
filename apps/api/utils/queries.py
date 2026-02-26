"""
Query Building Utilities
Chainable query builders for common database operations
"""
from datetime import date
from sqlalchemy.orm import Session, Query
from models import Transaction


class TransactionQueryBuilder:
    """Build Transaction queries with common filters (chainable)."""

    def __init__(self, db: Session):
        """
        Initialize query builder.

        Args:
            db: Database session
        """
        self.query: Query = db.query(Transaction)

    def filter_date_range(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
    ):
        """
        Apply date range filters.

        Args:
            start_date: Minimum date (inclusive)
            end_date: Maximum date (inclusive)

        Returns:
            Self for chaining

        Example:
            builder.filter_date_range(start_date, end_date)
        """
        if start_date:
            self.query = self.query.filter(Transaction.date >= start_date)
        if end_date:
            self.query = self.query.filter(Transaction.date <= end_date)
        return self

    def filter_type(self, tx_type: str | None = None):
        """
        Filter by transaction type.

        Args:
            tx_type: Transaction type (income/expense/transfer)

        Returns:
            Self for chaining

        Example:
            builder.filter_type("income")
        """
        if tx_type:
            self.query = self.query.filter(Transaction.type == tx_type)
        return self

    def filter_category(self, category: str | None = None):
        """
        Filter by category (case-insensitive substring match).

        Args:
            category: Category substring to search for

        Returns:
            Self for chaining

        Example:
            builder.filter_category("food")
        """
        if category:
            self.query = self.query.filter(
                Transaction.category.ilike(f"%{category}%")
            )
        return self

    def filter_bank_account(self, account_id: int | None = None):
        """
        Filter by bank account.

        Args:
            account_id: Bank account ID

        Returns:
            Self for chaining

        Example:
            builder.filter_bank_account(account_id)
        """
        if account_id:
            self.query = self.query.filter(
                Transaction.bank_account_id == account_id
            )
        return self

    def filter_vendor(self, vendor: str | None = None):
        """
        Filter by vendor (case-insensitive substring match).

        Args:
            vendor: Vendor substring to search for

        Returns:
            Self for chaining

        Example:
            builder.filter_vendor("amazon")
        """
        if vendor:
            self.query = self.query.filter(Transaction.vendor.ilike(f"%{vendor}%"))
        return self

    def build(self) -> Query:
        """
        Return the built query.

        Returns:
            SQLAlchemy Query object

        Example:
            query = builder.filter_type("income").build()
            results = query.all()
        """
        return self.query
