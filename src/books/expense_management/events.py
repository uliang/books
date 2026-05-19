"""Expense Management's published events — the contract the Ledger consumes
(ADR-0006/0011). The owner pays business expenses personally; the business
owes the owner (ADR-0003, amended). Other contexts may import these event
types but never Expense Management's tables.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from books.platform.money import Money


@dataclass(frozen=True)
class OwnerPaidExpenseRecorded:
    """A business expense the owner paid personally. Recognized at the
    charge against the Due-to-Owner payable (ADR-0003, amended). A supplier
    Party is mandatory provenance; the personal card never enters."""

    party_id: int
    party_name: str
    amount: Money
    category_account: str
    on: date


@dataclass(frozen=True)
class OwnerReimbursed:
    """The business paid the owner back from the bank — any amount, partial
    allowed. Draws down the fungible Due-to-Owner balance."""

    amount: Money
    on: date
