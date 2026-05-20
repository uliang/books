"""Invoicing ORM tables (ADR-0013). Private to the Invoicing context."""

from __future__ import annotations

from datetime import date

from sqlalchemy import Date, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from books.platform.db import Base


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
