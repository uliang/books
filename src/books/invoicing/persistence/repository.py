"""Invoicing repository (ADR-0013 amended 2026-05-20)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from books.invoicing.persistence.tables import _Invoice
from books.platform.repository import Repository


@dataclass(frozen=True, slots=True)
class InvoiceRow:
    id: int
    number: int
    party_id: int
    amount_minor: int  # transaction currency
    currency: str  # transaction currency code
    rate: str
    carrying_minor: int  # functional MYR
    banked_minor: int | None
    issued_on: date
    status: str


def _row_to_snapshot(row: _Invoice) -> InvoiceRow:
    return InvoiceRow(
        id=row.id,
        number=row.number,
        party_id=row.party_id,
        amount_minor=row.amount_minor,
        currency=row.currency,
        rate=row.rate,
        carrying_minor=row.carrying_minor,
        banked_minor=row.banked_minor,
        issued_on=row.issued_on,
        status=row.status,
    )


class InvoiceRepository(Repository):
    def add(
        self,
        session: Session,
        *,
        number: int,
        party_id: int,
        amount_minor: int,
        currency: str,
        rate: str,
        carrying_minor: int,
        issued_on: date,
    ) -> InvoiceRow:
        row = _Invoice(
            number=number,
            party_id=party_id,
            amount_minor=amount_minor,
            currency=currency,
            rate=rate,
            carrying_minor=carrying_minor,
            issued_on=issued_on,
        )
        session.add(row)
        session.flush()
        return _row_to_snapshot(row)

    def get(self, session: Session, invoice_id: int) -> InvoiceRow | None:
        row = session.get(_Invoice, invoice_id)
        return None if row is None else _row_to_snapshot(row)

    def record_payment(
        self,
        session: Session,
        invoice_id: int,
        *,
        banked_minor: int,
        status: str,
    ) -> None:
        row = session.get(_Invoice, invoice_id)
        if row is None:
            raise LookupError(f"no invoice {invoice_id}")
        row.banked_minor = banked_minor
        row.status = status

    def set_status(self, session: Session, invoice_id: int, status: str) -> None:
        row = session.get(_Invoice, invoice_id)
        if row is None:
            raise LookupError(f"no invoice {invoice_id}")
        row.status = status
