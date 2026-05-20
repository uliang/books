"""Expense Management ORM tables (ADR-0013). Private to the context."""

from __future__ import annotations

from datetime import date

from sqlalchemy import Date, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from books.platform.db import Base


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
