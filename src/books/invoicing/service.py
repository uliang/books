"""Invoicing application API (ADR-0013).

Holds the Invoice aggregate; publishes InvoiceIssued / PaymentRecorded /
SettlementAdjudicated. It references a Party by id and caches the display
name onto the event (CONTEXT) via an injected resolver — no shared kernel,
no cross-context import.

An invoice may be denominated in a transaction currency (e.g. SGD) with a
manually-entered booking rate at issue (ADR-0005). The Ledger is the
functional-MYR system-of-record, so the AR carrying value is translated
here at issue and the events Invoicing publishes are already in MYR. A
foreign invoice that banks fewer MYR than its carrying value is *ambiguous*
(adverse FX vs underpayment); the system surfaces both numbers and the
owner adjudicates — it is never auto-resolved.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import Date, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from books.invoicing.events import (
    InvoiceIssued,
    PaymentRecorded,
    SettlementAdjudicated,
)
from books.platform.db import Base, Database
from books.platform.events import EventBus
from books.platform.money import Currency, Money


class _Invoice(Base):
    __tablename__ = "invoice"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    number: Mapped[int] = mapped_column(Integer, unique=True)
    party_id: Mapped[int] = mapped_column(Integer)
    amount_minor: Mapped[int] = mapped_column(Integer)  # transaction currency
    currency: Mapped[str] = mapped_column(String)  # transaction currency
    rate: Mapped[str] = mapped_column(String)  # txn→MYR booking rate
    carrying_minor: Mapped[int] = mapped_column(Integer)  # functional MYR
    banked_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    issued_on: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String, default="issued")


@dataclass(frozen=True, slots=True)
class Invoice:
    id: int
    number: int


@dataclass(frozen=True, slots=True)
class SettlementPicture:
    """Both numbers, surfaced for owner adjudication (ADR-0005). The system
    computes and displays; it never guesses underpayment vs FX."""

    transaction_amount: Money  # what was invoiced (e.g. SGD 1,000)
    carrying: Money  # MYR booked into AR at issue
    banked: Money  # MYR actually received
    shortfall: Money  # MYR carrying − banked (0 if none)


def _to_myr(minor: int, rate: Decimal) -> int:
    """Translate transaction-currency minor units to functional MYR minor
    units at the booking rate, rounding half-up to the minor unit."""
    return int((Decimal(minor) * rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


class InvoicingService:
    def __init__(
        self,
        db: Database,
        bus: EventBus,
        party_name: Callable[[int], str],
    ) -> None:
        self._db = db
        self._bus = bus
        self._party_name = party_name

    def issue_invoice(
        self,
        number: int,
        party_id: int,
        amount: Money,
        issued_on: date,
        rate: Decimal = Decimal(1),
    ) -> Invoice:
        if amount.currency is Currency.MYR:
            rate = Decimal(1)
        carrying_minor = _to_myr(amount.minor_units, rate)
        with self._db.unit_of_work() as session:
            row = _Invoice(
                number=number,
                party_id=party_id,
                amount_minor=amount.minor_units,
                currency=amount.currency.value,
                rate=str(rate),
                carrying_minor=carrying_minor,
                issued_on=issued_on,
            )
            session.add(row)
            session.flush()
            invoice = Invoice(id=row.id, number=row.number)
            # The Ledger is MYR system-of-record: it sees the carrying value.
            self._bus.publish(
                InvoiceIssued(
                    invoice_number=number,
                    party_id=party_id,
                    party_name=self._party_name(party_id),
                    amount=Money.myr(carrying_minor),
                    issued_on=issued_on,
                )
            )
            return invoice

    def mark_paid(
        self,
        invoice_id: int,
        paid_on: date,
        banked: Money | None = None,
    ) -> None:
        with self._db.unit_of_work() as session:
            row = session.get(_Invoice, invoice_id)
            if row is None:
                raise LookupError(f"no invoice {invoice_id}")
            # Default: the full carrying value landed (domestic case).
            banked_minor = row.carrying_minor if banked is None else banked.minor_units
            row.banked_minor = banked_minor
            # Record only what moved; an MYR shortfall stays open until the
            # owner adjudicates (ADR-0005) — never auto-resolved.
            row.status = (
                "paid"
                if banked_minor >= row.carrying_minor
                else "awaiting_adjudication"
            )
            self._bus.publish(
                PaymentRecorded(
                    invoice_number=row.number,
                    party_id=row.party_id,
                    amount=Money.myr(banked_minor),
                    paid_on=paid_on,
                )
            )

    def settlement_picture(self, invoice_id: int) -> SettlementPicture:
        with self._db.unit_of_work() as session:
            row = session.get(_Invoice, invoice_id)
            if row is None:
                raise LookupError(f"no invoice {invoice_id}")
            banked_minor = row.banked_minor or 0
            return SettlementPicture(
                transaction_amount=Money(row.amount_minor, Currency(row.currency)),
                carrying=Money.myr(row.carrying_minor),
                banked=Money.myr(banked_minor),
                shortfall=Money.myr(row.carrying_minor - banked_minor),
            )

    def adjudicate_settlement(
        self,
        invoice_id: int,
        outcome: str,
        on: date,
    ) -> None:
        with self._db.unit_of_work() as session:
            row = session.get(_Invoice, invoice_id)
            if row is None:
                raise LookupError(f"no invoice {invoice_id}")
            shortfall = row.carrying_minor - (row.banked_minor or 0)
            if outcome == "settled_in_full":
                row.status = "paid"
                # Realized FX loss, recognized only at settlement, posted by
                # the Ledger's guided-journal path (ADR-0005/0006).
                self._bus.publish(
                    SettlementAdjudicated(
                        invoice_number=row.number,
                        party_id=row.party_id,
                        fx_loss=Money.myr(shortfall),
                        on=on,
                    )
                )
            elif outcome == "still_owes":
                # No FX recognition: AR stays open for the shortfall.
                row.status = "partially_paid"
            else:
                raise ValueError(f"unknown adjudication outcome: {outcome!r}")
