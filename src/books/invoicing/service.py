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

from books.invoicing.events import (
    InvoiceIssued,
    PaymentRecorded,
    SettlementAdjudicated,
)
from books.invoicing.persistence.repository import InvoiceRepository
from books.platform.db import Database
from books.platform.events import EventBus
from books.platform.money import Currency, Money
from books.platform.unit_of_work import UnitOfWork


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


@dataclass(frozen=True, slots=True)
class InvoiceView:
    """A row for the invoices:// read surface: the persisted invoice plus the
    resolved (cached-name) Party, so an agent can list and target invoices."""

    id: int
    number: int
    party_id: int
    party_name: str
    currency: str  # transaction currency
    amount_minor: int  # transaction currency
    carrying_minor: int  # functional MYR booked into AR
    banked_minor: int | None
    status: str


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
        unit_of_work: Callable[[], UnitOfWork] | None = None,
    ) -> None:
        self._repo = InvoiceRepository(db)
        self._bus = bus
        self._party_name = party_name
        self._uow = unit_of_work or (lambda: UnitOfWork(db))

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
        # Resolve the party name before opening the UoW: the party resolver
        # opens its own per-context session and commits it.  If that commit
        # runs inside the UoW block it would commit the invoice INSERT too
        # (StaticPool shares one connection), defeating the rollback guarantee.
        party_name = self._party_name(party_id)
        with self._uow() as uow:
            row = self._repo.add(
                uow.session,
                number=number,
                party_id=party_id,
                amount_minor=amount.minor_units,
                currency=amount.currency.value,
                rate=str(rate),
                carrying_minor=carrying_minor,
                issued_on=issued_on,
            )
            # The Ledger is MYR system-of-record: it sees the carrying value.
            self._bus.publish(
                InvoiceIssued(
                    invoice_number=number,
                    party_id=party_id,
                    party_name=party_name,
                    amount=Money.myr(carrying_minor),
                    issued_on=issued_on,
                )
            )
            return Invoice(id=row.id, number=row.number)

    def mark_paid(
        self,
        invoice_id: int,
        paid_on: date,
        banked: Money | None = None,
    ) -> None:
        with self._uow() as uow:
            invoice = self._repo.get(uow.session, invoice_id)
            if invoice is None:
                raise LookupError(f"no invoice {invoice_id}")
            # Default: the full carrying value landed (domestic case).
            banked_minor = (
                invoice.carrying_minor if banked is None else banked.minor_units
            )
            # Record only what moved; an MYR shortfall stays open until the
            # owner adjudicates (ADR-0005) — never auto-resolved.
            status = (
                "paid"
                if banked_minor >= invoice.carrying_minor
                else "awaiting_adjudication"
            )
            self._repo.record_payment(
                uow.session, invoice_id, banked_minor=banked_minor, status=status
            )
            self._bus.publish(
                PaymentRecorded(
                    invoice_number=invoice.number,
                    party_id=invoice.party_id,
                    amount=Money.myr(banked_minor),
                    paid_on=paid_on,
                )
            )

    def settlement_picture(self, invoice_id: int) -> SettlementPicture:
        with self._repo.unit_of_work() as session:
            invoice = self._repo.get(session, invoice_id)
            if invoice is None:
                raise LookupError(f"no invoice {invoice_id}")
            banked_minor = invoice.banked_minor or 0
            return SettlementPicture(
                transaction_amount=Money(
                    invoice.amount_minor, Currency(invoice.currency)
                ),
                carrying=Money.myr(invoice.carrying_minor),
                banked=Money.myr(banked_minor),
                shortfall=Money.myr(invoice.carrying_minor - banked_minor),
            )

    def adjudicate_settlement(
        self,
        invoice_id: int,
        outcome: str,
        on: date,
    ) -> None:
        with self._repo.unit_of_work() as session:
            invoice = self._repo.get(session, invoice_id)
            if invoice is None:
                raise LookupError(f"no invoice {invoice_id}")
            shortfall = invoice.carrying_minor - (invoice.banked_minor or 0)
            if outcome == "settled_in_full":
                self._repo.set_status(session, invoice_id, "paid")
                # Realized FX loss, recognized only at settlement, posted by
                # the Ledger's guided-journal path (ADR-0005/0006).
                self._bus.publish(
                    SettlementAdjudicated(
                        invoice_number=invoice.number,
                        party_id=invoice.party_id,
                        fx_loss=Money.myr(shortfall),
                        on=on,
                    )
                )
            elif outcome == "still_owes":
                # No FX recognition: AR stays open for the shortfall.
                self._repo.set_status(session, invoice_id, "partially_paid")
            else:
                raise ValueError(f"unknown adjudication outcome: {outcome!r}")

    def list_invoices(self) -> list[InvoiceView]:
        with self._repo.unit_of_work() as session:
            rows = self._repo.list_all(session)
        return [
            InvoiceView(
                id=r.id,
                number=r.number,
                party_id=r.party_id,
                party_name=self._party_name(r.party_id),
                currency=r.currency,
                amount_minor=r.amount_minor,
                carrying_minor=r.carrying_minor,
                banked_minor=r.banked_minor,
                status=r.status,
            )
            for r in rows
        ]
