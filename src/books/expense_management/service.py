"""Expense Management application API (ADR-0013).

Buy-side outflow capture on the card rail. It references a Party by id and
caches the display name onto the event (CONTEXT) via an injected resolver —
no shared kernel, no cross-context import. It publishes events; the Ledger
consumes them and produces postings (ADR-0006). Purchases are cash basis;
the one accrual is the card clearing account, settled monthly (ADR-0003).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from sqlalchemy import Date, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from books.expense_management.events import (
    CardChargeCaptured,
    CardStatementSettled,
)
from books.platform.db import Base, Database
from books.platform.events import EventBus
from books.platform.money import Money


class _CardCharge(Base):
    __tablename__ = "expense_card_charge"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    party_id: Mapped[int] = mapped_column(Integer)
    party_name: Mapped[str] = mapped_column(String)
    amount_minor: Mapped[int] = mapped_column(Integer)
    category_account: Mapped[str] = mapped_column(String)
    on: Mapped[date] = mapped_column(Date)


class _CardSettlement(Base):
    __tablename__ = "expense_card_settlement"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    amount_minor: Mapped[int] = mapped_column(Integer)
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

    def capture_card_charge(
        self,
        party_id: int,
        amount: Money,
        category_account: str,
        on: date,
    ) -> None:
        with self._db.unit_of_work() as session:
            name = self._party_name(party_id)
            session.add(
                _CardCharge(
                    party_id=party_id,
                    party_name=name,
                    amount_minor=amount.minor_units,
                    category_account=category_account,
                    on=on,
                )
            )
            self._bus.publish(
                CardChargeCaptured(
                    party_id=party_id,
                    party_name=name,
                    amount=amount,
                    category_account=category_account,
                    on=on,
                )
            )

    def settle_card_statement(self, amount: Money, on: date) -> None:
        with self._db.unit_of_work() as session:
            session.add(_CardSettlement(amount_minor=amount.minor_units, on=on))
            self._bus.publish(CardStatementSettled(amount=amount, on=on))
