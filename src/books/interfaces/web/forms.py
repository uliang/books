"""Request -> domain parsing. Kept tiny and explicit (no WTForms).

First used by the invoicing/reconciliation routes (Task 4 onward).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from books.platform.money import Currency, Money


def money_from(amount: str, currency: str = "MYR") -> Money:
    minor = int((Decimal(amount) * 100).to_integral_value())
    return Money(minor, Currency(currency))


def date_from(value: str) -> date:
    return date.fromisoformat(value)


def decimal_from(value: str) -> Decimal:
    return Decimal(value)
