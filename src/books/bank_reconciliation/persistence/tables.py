"""Bank Reconciliation ORM tables (ADR-0013). Private to the context."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from books.platform.db import Base


class _Statement(Base):
    __tablename__ = "br_statement"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    account: Mapped[str] = mapped_column(String)
    period: Mapped[str] = mapped_column(String)
    opening_minor: Mapped[int] = mapped_column(Integer)
    closing_minor: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String, unique=True)


class _Line(Base):
    __tablename__ = "br_line"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    statement_id: Mapped[int] = mapped_column(Integer)
    account: Mapped[str] = mapped_column(String)
    period: Mapped[str] = mapped_column(String)
    date: Mapped[date] = mapped_column(Date)
    amount_minor: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(String)


class _Match(Base):
    """A confirmed line↔posting match. Uniqueness invariants from ADR-0014:
    a line is matched at most once; a posting is matched at most once."""

    __tablename__ = "br_match"
    __table_args__ = (
        UniqueConstraint("statement_line_ref"),
        UniqueConstraint("ledger_posting_ref"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    statement_line_ref: Mapped[int] = mapped_column(Integer)
    ledger_posting_ref: Mapped[int] = mapped_column(Integer)
    confirmed_at: Mapped[datetime] = mapped_column(DateTime)
