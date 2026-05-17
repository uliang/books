"""Invoicing application API (ADR-0013).

Holds the Invoice aggregate; publishes InvoiceIssued / PaymentRecorded. It
references a Party by id and caches the display name onto the event (CONTEXT)
via an injected resolver — no shared kernel, no cross-context import.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from sqlalchemy import Date, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from books.invoicing.events import InvoiceIssued, PaymentRecorded
from books.platform.db import Base, Database
from books.platform.events import EventBus
from books.platform.money import Currency, Money


class _Invoice(Base):
    __tablename__ = "invoice"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    number: Mapped[int] = mapped_column(Integer, unique=True)
    party_id: Mapped[int] = mapped_column(Integer)
    amount_minor: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String)
    issued_on: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String, default="issued")


@dataclass(frozen=True, slots=True)
class Invoice:
    id: int
    number: int


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
    ) -> Invoice:
        with self._db.unit_of_work() as session:
            row = _Invoice(
                number=number,
                party_id=party_id,
                amount_minor=amount.minor_units,
                currency=amount.currency.value,
                issued_on=issued_on,
            )
            session.add(row)
            session.flush()
            invoice = Invoice(id=row.id, number=row.number)
            self._bus.publish(
                InvoiceIssued(
                    invoice_number=number,
                    party_id=party_id,
                    party_name=self._party_name(party_id),
                    amount=amount,
                    issued_on=issued_on,
                )
            )
            return invoice

    def mark_paid(self, invoice_id: int, paid_on: date) -> None:
        with self._db.unit_of_work() as session:
            row = session.get(_Invoice, invoice_id)
            if row is None:
                raise LookupError(f"no invoice {invoice_id}")
            row.status = "paid"
            event = PaymentRecorded(
                invoice_number=row.number,
                party_id=row.party_id,
                amount=Money(row.amount_minor, Currency(row.currency)),
                paid_on=paid_on,
            )
            self._bus.publish(event)
