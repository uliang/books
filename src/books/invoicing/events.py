"""Invoicing's published events — the contract Ledger consumes (ADR-0011).

These are part of Invoicing's public surface (ADR-0013); other contexts may
import the event types but never Invoicing's aggregates or tables.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from books.platform.money import Money


@dataclass(frozen=True)
class InvoiceIssued:
    invoice_number: int
    party_id: int
    party_name: str
    amount: Money
    issued_on: date


@dataclass(frozen=True)
class PaymentRecorded:
    invoice_number: int
    party_id: int
    amount: Money
    paid_on: date
