"""
Parser Factory - Main entry point for bank statement parsing
Auto-detects bank and applies appropriate parser
"""
import logging
from typing import Optional
import pandas as pd

from .bank_detector import BankDetector
from .moniepoint_parser import MoniepointParser
from .opay_parser import OPayParser
from .generic_parser import GenericParser
from .base_parser import BaseBankParser

logger = logging.getLogger(__name__)


class ParserFactory:
    """Factory to get the right parser for a bank statement."""

    @staticmethod
    def get_parser(
        dataframe: Optional[pd.DataFrame] = None,
        bank_name: Optional[str] = None,
        file_text: Optional[str] = None
    ) -> BaseBankParser:
        """
        Get appropriate parser based on bank detection.

        Args:
            dataframe: DataFrame from CSV/Excel (optional)
            bank_name: User-provided bank name (optional)
            file_text: Raw text from PDF (optional)

        Returns:
            Bank-specific parser instance
        """
        detected_bank = None

        # Try detection from user-provided bank name first
        if bank_name:
            detected_bank = BankDetector.detect_from_bank_name(bank_name)
            if detected_bank:
                logger.info(f"Bank detected from name: {detected_bank}")

        # Try detection from DataFrame
        if not detected_bank and dataframe is not None:
            detected_bank = BankDetector.detect_from_dataframe(dataframe)
            if detected_bank:
                logger.info(f"Bank detected from DataFrame: {detected_bank}")

        # Try detection from text
        if not detected_bank and file_text:
            detected_bank = BankDetector.detect_from_text(file_text)
            if detected_bank:
                logger.info(f"Bank detected from text: {detected_bank}")

        # Return appropriate parser
        if detected_bank == "moniepoint":
            logger.info("Using Moniepoint parser")
            return MoniepointParser()
        elif detected_bank == "opay":
            logger.info("Using OPay parser")
            return OPayParser()
        else:
            # Use generic parser for all other banks
            bank_display_name = bank_name or detected_bank or "Unknown"
            logger.info(f"Using generic parser for: {bank_display_name}")
            return GenericParser(bank_display_name)


def parse_bank_statement(
    dataframe: Optional[pd.DataFrame] = None,
    bank_name: Optional[str] = None,
    file_text: Optional[str] = None
) -> BaseBankParser:
    """
    Convenience function to get parser.

    Usage:
        parser = parse_bank_statement(dataframe=df, bank_name="Moniepoint")
        col_mappings = parser.get_column_mappings()
        vendor = parser.extract_vendor(description, reference)
    """
    return ParserFactory.get_parser(
        dataframe=dataframe,
        bank_name=bank_name,
        file_text=file_text
    )
