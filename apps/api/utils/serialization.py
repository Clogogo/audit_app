"""
JSON Parsing Utilities
Safe JSON parsing with error handling
"""
import json
from typing import Any


def safe_json_loads(json_str: str | dict | None, default: Any = None) -> Any:
    """
    Parse JSON string safely, without raising on malformed input.

    Args:
        json_str: JSON string, dict, or None
        default: Value to return when json_str is empty/None

    Returns:
        The parsed JSON object; the original string unchanged if it isn't
        valid JSON (so a legacy or corrupted value is preserved rather than
        silently discarded, which matters for audit log fields); or
        `default` when json_str is empty/None.

    Example:
        data = safe_json_loads(audit_log.old_values)
    """
    if isinstance(json_str, dict):
        return json_str
    if not json_str:
        return default
    try:
        return json.loads(json_str)
    except (json.JSONDecodeError, TypeError):
        return json_str
