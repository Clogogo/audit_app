"""
JSON Serialization Utilities
Safe JSON parsing with error handling
"""
import json
from typing import Any


def safe_json_loads(json_str: str | dict | None, default: Any = None) -> Any:
    """
    Parse JSON string safely, return default if invalid.

    Args:
        json_str: JSON string, dict, or None
        default: Default value to return if parsing fails

    Returns:
        Parsed JSON object or default value

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
        return json_str or default
