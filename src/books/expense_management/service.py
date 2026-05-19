"""Expense Management application API (ADR-0013).

Buy-side outflow capture. The owner pays business expenses personally; the
business owes the owner (ADR-0003, amended — the single accrued payable is
Due to Owner, not a card-clearing account; the card is personal and off the
business books). It references a Party by id and caches the display name
onto the event (CONTEXT) via an injected resolver — no shared kernel, no
cross-context import. It publishes events; the Ledger consumes them and
produces postings (ADR-0006). A supplier Party is mandatory provenance.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from sqlalchemy import Date, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from books.expense_management.events import (
    ContractorPaid,
    OwnerPaidExpenseRecorded,
    OwnerReimbursed,
)
from books.platform.db import Base, Database
from books.platform.events import EventBus
from books.platform.money import Money


class _OwnerPaidExpense(Base):
    __tablename__ = "owner_paid_expense"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    party_id: Mapped[int] = mapped_column(Integer)
    party_name: Mapped[str] = mapped_column(String)
    amount_minor: Mapped[int] = mapped_column(Integer)
    category_account: Mapped[str] = mapped_column(String)
    on: Mapped[date] = mapped_column(Date)


class _OwnerReimbursement(Base):
    __tablename__ = "owner_reimbursement"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    amount_minor: Mapped[int] = mapped_column(Integer)
    on: Mapped[date] = mapped_column(Date)


class _ContractorPayment(Base):
    __tablename__ = "contractor_payment"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    party_id: Mapped[int] = mapped_column(Integer)
    party_name: Mapped[str] = mapped_column(String)
    amount_minor: Mapped[int] = mapped_column(Integer)
    category_account: Mapped[str] = mapped_column(String)
    on: Mapped[date] = mapped_column(Date)


class ExpenseManagementService:
    def __init__(
        self,
        db: Database,
        bus: EventBus,
        party_name: Callable[[int], str],
    ) -> None:
        self._db = db
        self._bus = bus
        self._party_name = party_name

    def record_owner_paid_expense(
        self,
        party_id: int,
        amount: Money,
        category_account: str,
        on: date,
    ) -> None:
        """A business expense the owner paid personally — recognized now
        against Due to Owner. ``party_id`` (the supplier) is required."""
        with self._db.unit_of_work() as session:
            name = self._party_name(party_id)
            session.add(
                _OwnerPaidExpense(
                    party_id=party_id,
                    party_name=name,
                    amount_minor=amount.minor_units,
                    category_account=category_account,
                    on=on,
                )
            )
            self._bus.publish(
                OwnerPaidExpenseRecorded(
                    party_id=party_id,
                    party_name=name,
                    amount=amount,
                    category_account=category_account,
                    on=on,
                )
            )

    def reimburse_owner(self, amount: Money, on: date) -> None:
        """The business pays the owner back — any amount, partial allowed."""
        with self._db.unit_of_work() as session:
            session.add(_OwnerReimbursement(amount_minor=amount.minor_units, on=on))
            self._bus.publish(OwnerReimbursed(amount=amount, on=on))

    def pay_contractor(
        self,
        party_id: int,
        amount: Money,
        category_account: str,
        on: date,
    ) -> None:
        """A categorized direct-bank outflow to a contractor (CONTEXT). Pure
        cash basis (ADR-0003): the expense is recognized as cash leaves."""
        with self._db.unit_of_work() as session:
            name = self._party_name(party_id)
            session.add(
                _ContractorPayment(
                    party_id=party_id,
                    party_name=name,
                    amount_minor=amount.minor_units,
                    category_account=category_account,
                    on=on,
                )
            )
            self._bus.publish(
                ContractorPaid(
                    party_id=party_id,
                    party_name=name,
                    amount=amount,
                    category_account=category_account,
                    on=on,
                )
            )
