"""
Bank Detector - Auto-detect bank from statement content
"""
import re
from typing import Optional
import pandas as pd


class BankDetector:
    """Detect which Nigerian bank a statement is from."""

    # Bank identification patterns (case-insensitive)
    BANK_PATTERNS = {
        "moniepoint": [
            r"moniepoint",
            r"teamapt",
            r"_CREDIT_\d+",  # Moniepoint reference suffix
            r"_DEBIT_\d+",
        ],
        "opay": [
            r"opay",
            r"opera\s*pay",
            r"owealth",  # OPay savings product
        ],
        "access": [
            r"access\s*bank",
            r"diamond\s*bank",  # Merged with Access
        ],
        "gtbank": [
            r"gt\s*bank",
            r"guaranty\s*trust",
        ],
        "uba": [
            r"uba",
            r"united\s*bank\s*for\s*africa",
        ],
        "zenith": [
            r"zenith\s*bank",
        ],
        "first_bank": [
            r"first\s*bank",
            r"firstbank",
        ],
        "fidelity": [
            r"fidelity\s*bank",
        ],
        "union": [
            r"union\s*bank",
        ],
        "stanbic": [
            r"stanbic",
            r"ibtc",
        ],
    }

    @classmethod
    def detect_from_dataframe(cls, df: pd.DataFrame) -> Optional[str]:
        """
        Detect bank from DataFrame content.
        Returns bank key (e.g., "moniepoint", "opay") or None.
        """
        # Convert first few rows to text for searching
        sample_text = ""
        for idx in range(min(20, len(df))):
            row_text = " ".join(str(v) for v in df.iloc[idx] if pd.notna(v))
            sample_text += row_text.lower() + " "

        # Also check column names
        col_text = " ".join(str(c).lower() for c in df.columns)
        sample_text += col_text

        return cls._detect_from_text(sample_text)

    @classmethod
    def detect_from_text(cls, text: str) -> Optional[str]:
        """Detect bank from raw text content."""
        return cls._detect_from_text(text.lower())

    @classmethod
    def _detect_from_text(cls, text_lower: str) -> Optional[str]:
        """Internal: detect from lowercase text."""
        # Score each bank by pattern matches
        scores = {}
        for bank_key, patterns in cls.BANK_PATTERNS.items():
            score = sum(1 for pattern in patterns if re.search(pattern, text_lower))
            if score > 0:
                scores[bank_key] = score

        if not scores:
            return None

        # Return bank with highest score
        return max(scores.items(), key=lambda x: x[1])[0]

    @classmethod
    def detect_from_bank_name(cls, bank_name: str) -> Optional[str]:
        """
        Detect bank code from provided bank name.
        Used when user explicitly provides bank name during upload.
        """
        if not bank_name:
            return None

        return cls._detect_from_text(bank_name.lower())
