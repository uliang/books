"""JSON-arg -> domain-type helpers for the MCP interface.

Kept tiny and explicit, mirroring the web layer's forms.py. The MCP
caller passes JSON-friendly primitives (int minor units, ISO date
strings); these helpers wrap them in domain types (Money, date).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from books.platform.money import Currency, Money


def money_from_minor(amount_minor: int, currency: str = "MYR") -> Money:
    return Money(amount_minor, Currency(currency))


def date_from(value: str) -> date:
    return date.fromisoformat(value)


def rate_from_bp(rate_bp: int = 10000) -> Decimal:
    """Integer basis points (×10000) → Decimal booking rate. 10000 → 1,
    32000 → 3.2. Mirrors the minor-units convention: no floats on the wire."""
    return Decimal(rate_bp) / Decimal(10000)
