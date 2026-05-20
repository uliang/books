"""General Ledger ORM tables (ADR-0013). Private to the GL context — only
``general_ledger.persistence.repository`` may import these; everywhere else
goes through ``LedgerService`` or the repository's intent-named methods."""

from __future__ import annotations

from datetime import date

from sqlalchemy import Date, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from books.platform.db import Base


def period_of(d: date) -> str:
    """Period key for a date — ``YYYY-MM`` (used by the period-lock guard)."""
    return f"{d.year:04d}-{d.month:02d}"


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


class _PeriodClose(Base):
    """A soft- or hard-closed period (ADR-0009). Presence locks new economic
    entries dated into that period; clearance is orthogonal and unaffected."""

    __tablename__ = "gl_period_close"

    period: Mapped[str] = mapped_column(String, primary_key=True)  # YYYY-MM
    kind: Mapped[str] = mapped_column(String)  # "soft" or "hard"


class _AccountRole(Base):
    """Persisted role→code mapping (Chart of Accounts is a GL aggregate per
    CONTEXT). Defaults are seeded idempotently by the service at construction
    so well-known flows work; the owner reassigns via ``assign_role``."""

    __tablename__ = "gl_account_role"

    role: Mapped[str] = mapped_column(String, primary_key=True)
    code: Mapped[str] = mapped_column(String)


class _Posting(Base):
    __tablename__ = "gl_posting"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    entry_id: Mapped[int] = mapped_column(ForeignKey("gl_entry.id"))
    account_code: Mapped[str] = mapped_column(ForeignKey("gl_account.code"))
    amount_minor: Mapped[int] = mapped_column(Integer)  # signed, Dr positive
    date: Mapped[date] = mapped_column(Date)


class _PostingDimension(Base):
    """Generic per-line analytical dimension (ADR-0007). Typed by ``type``
    (only ``"party"`` in v1; Project later is data, not schema)."""

    __tablename__ = "gl_posting_dimension"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    posting_id: Mapped[int] = mapped_column(ForeignKey("gl_posting.id"))
    type: Mapped[str] = mapped_column(String)
    value_id: Mapped[str] = mapped_column(String)
    value_name: Mapped[str] = mapped_column(String)
