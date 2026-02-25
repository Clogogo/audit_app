"""
Dynamic Bank Statement Parsers

Auto-detects bank and applies appropriate parsing rules.
Supports: Moniepoint, OPay, Access Bank, GTBank, UBA, Zenith, and more.
"""
from .parser_factory import parse_bank_statement

__all__ = ["parse_bank_statement"]
