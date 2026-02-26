"""
Backend Utility Modules
Shared utilities for reducing code duplication across routers
"""
from .errors import get_or_404
from .audit import AuditLogger
from .queries import TransactionQueryBuilder
from .aggregations import TransactionAggregator
from .serialization import JSONHelper
from .auth import get_current_user, hash_password, verify_password

__all__ = [
    "get_or_404",
    "AuditLogger",
    "TransactionQueryBuilder",
    "TransactionAggregator",
    "JSONHelper",
    "get_current_user",
    "hash_password",
    "verify_password",
]
