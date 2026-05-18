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
    amount: Money  # MYR actually banked at settlement
    paid_on: date


@dataclass(frozen=True)
class SettlementAdjudicated:
    """Owner ruled an ambiguous foreign settlement (ADR-0005). When the
    invoice is settled in full, the MYR shortfall is a realized FX loss the
    Ledger recognizes via its guided-journal template (ADR-0006)."""

    invoice_number: int
    party_id: int
    fx_loss: Money  # MYR; positive = realized loss
    on: date
