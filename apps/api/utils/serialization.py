"""
JSON Serialization Utilities
Safe JSON parsing and dumping with error handling
"""
import json


class JSONHelper:
    """Handle JSON serialization/deserialization safely."""

    @staticmethod
    def safe_loads(json_str: str | dict | None, default=None):
        """
        Parse JSON string safely, return default if invalid.

        Args:
            json_str: JSON string, dict, or None
            default: Default value to return if parsing fails

        Returns:
            Parsed JSON object or default value

        Example:
            data = JSONHelper.safe_loads(audit_log.old_values)
        """
        if isinstance(json_str, dict):
            return json_str
        if not json_str:
            return default
        try:
            return json.loads(json_str)
        except (json.JSONDecodeError, TypeError):
            return json_str or default

    @staticmethod
    def safe_dumps(obj, default=None) -> str | None:
        """
        Serialize object to JSON safely.

        Args:
            obj: Object to serialize
            default: Default value to return if serialization fails

        Returns:
            JSON string or default value

        Example:
            json_str = JSONHelper.safe_dumps({"key": "value"})
        """
        if obj is None:
            return default
        try:
            return json.dumps(obj)
        except TypeError:
            return str(obj)
