"""General Ledger application API (ADR-0013).

System-of-record for double-entry postings, measured in functional MYR
(ADR-0017). Mostly event-fed: it subscribes to Invoicing's published events
and translates them into balanced journal entries, each tagged with its
provenance (ADR-0012). Posting amounts are signed minor units, debit
positive; an account balance is their sum.

Well-known account codes (AR / Revenue / Bank) are hardwired for the tracer
thread; configurable account mapping is a thickening concern.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import Date, ForeignKey, Integer, String, select
from sqlalchemy.orm import Mapped, mapped_column

from books.invoicing.events import InvoiceIssued, PaymentRecorded
from books.platform.db import Base, Database
from books.platform.events import EventBus
from books.platform.money import Money

AR = "AR"
REVENUE = "Revenue"
BANK = "Bank"


class _Account(Base):
    __tablename__ = "gl_account"

    code: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    type: Mapped[str] = mapped_column(String)
    control: Mapped[bool] = mapped_column(default=False)


class _Entry(Base):
    __tablename__ = "gl_entry"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column(Date)
    narrative: Mapped[str] = mapped_column(String)
    # Provenance (ADR-0012): what caused this entry.
    source_kind: Mapped[str] = mapped_column(String)
    source_id: Mapped[str] = mapped_column(String)


class _Posting(Base):
    __tablename__ = "gl_posting"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    entry_id: Mapped[int] = mapped_column(ForeignKey("gl_entry.id"))
    account_code: Mapped[str] = mapped_column(ForeignKey("gl_account.code"))
    amount_minor: Mapped[int] = mapped_column(Integer)  # signed, Dr positive
    date: Mapped[date] = mapped_column(Date)
    party_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    party_name: Mapped[str | None] = mapped_column(String, nullable=True)


@dataclass(frozen=True, slots=True)
class PostingView:
    ref: int
    account_code: str
    amount: Money
    date: date
    party_name: str | None


class LedgerService:
    def __init__(self, db: Database, bus: EventBus) -> None:
        self._db = db
        bus.subscribe(InvoiceIssued, self._on_invoice_issued)
        bus.subscribe(PaymentRecorded, self._on_payment_recorded)

    # --- write side -----------------------------------------------------

    def create_account(
        self,
        code: str,
        name: str,
        type: str,
        control: bool = False,
    ) -> None:
        with self._db.unit_of_work() as session:
            session.add(_Account(code=code, name=name, type=type, control=control))

    def _post(
        self,
        session,
        *,
        on: date,
        narrative: str,
        source_kind: str,
        source_id: str,
        legs: list[tuple[str, int, int | None, str | None]],
    ) -> None:
        entry = _Entry(
            date=on,
            narrative=narrative,
            source_kind=source_kind,
            source_id=source_id,
        )
        session.add(entry)
        session.flush()
        for account_code, amount_minor, party_id, party_name in legs:
            session.add(
                _Posting(
                    entry_id=entry.id,
                    account_code=account_code,
                    amount_minor=amount_minor,
                    date=on,
                    party_id=party_id,
                    party_name=party_name,
                )
            )

    def _on_invoice_issued(self, e: InvoiceIssued) -> None:
        amt = e.amount.minor_units
        with self._db.unit_of_work() as session:
            self._post(
                session,
                on=e.issued_on,
                narrative=f"Invoice #{e.invoice_number} to {e.party_name}",
                source_kind="InvoiceIssued",
                source_id=str(e.invoice_number),
                legs=[
                    (AR, amt, e.party_id, e.party_name),
                    (REVENUE, -amt, None, None),
                ],
            )

    def _on_payment_recorded(self, e: PaymentRecorded) -> None:
        amt = e.amount.minor_units
        with self._db.unit_of_work() as session:
            party_name = session.execute(
                select(_Posting.party_name)
                .where(_Posting.account_code == AR)
                .where(_Posting.party_id == e.party_id)
                .limit(1)
            ).scalar_one_or_none()
            self._post(
                session,
                on=e.paid_on,
                narrative=f"Payment for invoice #{e.invoice_number}",
                source_kind="PaymentRecorded",
                source_id=str(e.invoice_number),
                legs=[
                    (BANK, amt, None, None),
                    (AR, -amt, e.party_id, party_name),
                ],
            )

    # --- query side (a context query API, ADR-0013) ---------------------

    def account_balance(self, code: str) -> Money:
        with self._db.unit_of_work() as session:
            total = (
                session.execute(
                    select(_Posting.amount_minor).where(_Posting.account_code == code)
                )
                .scalars()
                .all()
            )
            return Money.myr(sum(total))

    def postings_for(self, code: str) -> list[PostingView]:
        with self._db.unit_of_work() as session:
            rows = (
                session.execute(
                    select(_Posting)
                    .where(_Posting.account_code == code)
                    .order_by(_Posting.id)
                )
                .scalars()
                .all()
            )
            return [
                PostingView(
                    ref=r.id,
                    account_code=r.account_code,
                    amount=Money.myr(r.amount_minor),
                    date=r.date,
                    party_name=r.party_name,
                )
                for r in rows
            ]
