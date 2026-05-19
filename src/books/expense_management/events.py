"""Expense Management's published events — the contract the Ledger consumes
(ADR-0006/0011). Buy-side outflow capture on the card rail; other contexts
may import these event types but never Expense Management's tables.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from books.platform.money import Money


@dataclass(frozen=True)
class CardChargeCaptured:
    """A card swipe. Accrues the expense against the card clearing account
    (the only payable, ADR-0003) — the issuer, not the supplier, is owed."""

    party_id: int
    party_name: str
    amount: Money
    category_account: str
    on: date


@dataclass(frozen=True)
class CardStatementSettled:
    """The monthly card bill paid from the bank, clearing the liability."""

    amount: Money
    on: date
