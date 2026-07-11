"""
Backend Utility Modules
Shared utilities for reducing code duplication across routers
"""
from .errors import get_or_404
from .audit import AuditLogger
from .queries import TransactionQueryBuilder
from .serialization import safe_json_loads
from .auth import get_current_user, hash_password, verify_password

__all__ = [
    "get_or_404",
    "AuditLogger",
    "TransactionQueryBuilder",
    "safe_json_loads",
    "get_current_user",
    "hash_password",
    "verify_password",
]
