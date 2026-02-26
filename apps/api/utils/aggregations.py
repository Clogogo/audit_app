"""
Transaction Aggregation Utilities
Calculate sums, counts, and groupings for transaction data
"""
from collections import defaultdict
from typing import Callable
from models import Transaction


class TransactionAggregator:
    """Aggregate transaction data for reports and summaries."""

    def __init__(self, transactions: list[Transaction]):
        """
        Initialize aggregator with transaction list.

        Args:
            transactions: List of Transaction objects
        """
        self.transactions = transactions

    def sum_by_type(
        self,
        tx_type: str,
        filter_fn: Callable[[Transaction], bool] | None = None,
    ) -> float:
        """
        Sum amounts for transactions of a given type.

        Args:
            tx_type: Transaction type (income/expense/transfer)
            filter_fn: Optional filter function to apply

        Returns:
            Total amount

        Example:
            agg.sum_by_type("income", filter_fn=lambda t: not is_internal(t))
        """
        return sum(
            t.amount
            for t in self.transactions
            if t.type == tx_type and (filter_fn is None or filter_fn(t))
        )

    def count_by_type(
        self,
        tx_type: str,
        filter_fn: Callable[[Transaction], bool] | None = None,
    ) -> int:
        """
        Count transactions of a given type.

        Args:
            tx_type: Transaction type (income/expense/transfer)
            filter_fn: Optional filter function to apply

        Returns:
            Count of transactions

        Example:
            agg.count_by_type("expense")
        """
        return sum(
            1
            for t in self.transactions
            if t.type == tx_type and (filter_fn is None or filter_fn(t))
        )

    def group_by_category(
        self,
        filter_fn: Callable[[Transaction], bool] | None = None,
    ) -> dict[str, float]:
        """
        Group amounts by category.

        Args:
            filter_fn: Optional filter function to apply

        Returns:
            Dictionary mapping category name to total amount

        Example:
            agg.group_by_category(filter_fn=lambda t: t.type == "expense")
        """
        result = defaultdict(float)
        for t in self.transactions:
            if filter_fn is None or filter_fn(t):
                category = t.category or "Uncategorized"
                result[category] += t.amount
        return dict(result)

    def group_by_type(
        self,
        filter_fn: Callable[[Transaction], bool] | None = None,
    ) -> dict[str, float]:
        """
        Group amounts by transaction type.

        Args:
            filter_fn: Optional filter function to apply

        Returns:
            Dictionary mapping type to total amount

        Example:
            agg.group_by_type()
        """
        result = defaultdict(float)
        for t in self.transactions:
            if filter_fn is None or filter_fn(t):
                result[t.type] += t.amount
        return dict(result)

    def get_monthly_breakdown(
        self,
        filter_fn: Callable[[Transaction], bool] | None = None,
    ) -> dict[str, dict[str, float]]:
        """
        Group amounts by month and type.

        Args:
            filter_fn: Optional filter function to apply

        Returns:
            Dictionary mapping month (YYYY-MM) to type breakdown

        Example:
            agg.get_monthly_breakdown()
            # Returns: {"2025-01": {"income": 1000, "expense": 500}, ...}
        """
        result: dict[str, dict[str, float]] = {}
        for t in self.transactions:
            if filter_fn is None or filter_fn(t):
                month_key = t.date.strftime("%Y-%m")
                if month_key not in result:
                    result[month_key] = {"income": 0.0, "expense": 0.0, "transfer": 0.0}
                result[month_key][t.type] += t.amount
        return result

    def get_totals(
        self,
        filter_fn: Callable[[Transaction], bool] | None = None,
    ) -> dict[str, float]:
        """
        Get total amounts by type (income, expense, transfer).

        Args:
            filter_fn: Optional filter function to apply

        Returns:
            Dictionary with income, expense, and transfer totals

        Example:
            totals = agg.get_totals()
            # Returns: {"income": 1000.0, "expense": 500.0, "transfer": 200.0}
        """
        return {
            "income": self.sum_by_type("income", filter_fn),
            "expense": self.sum_by_type("expense", filter_fn),
            "transfer": self.sum_by_type("transfer", filter_fn),
        }
