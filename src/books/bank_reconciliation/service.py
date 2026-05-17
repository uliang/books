"""Bank Reconciliation application API — the core domain.

- Import is an anti-corruption layer (ADR-0018): the raw artifact is
  content-hashed (idempotency key) and a format adapter normalizes it into
  the canonical statement; footing is checked at the boundary (ADR-0014).
- ``propose_matches`` is read-only (ADR-0015).
- ``confirm_match`` is the sole reconciliation write and enforces the
  uniqueness invariants (a line matched at most once, a posting matched at
  most once, ADR-0014); it is idempotent on an identical resubmit.

Clearance is *not* stored on the Ledger posting; a posting is cleared iff a
Match references it (ADR-0010).
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Date,
    DateTime,
    Integer,
    String,
    UniqueConstraint,
    select,
)
from sqlalchemy.orm import Mapped, mapped_column

from books.general_ledger.service import PostingView
from books.platform.db import Base, Database
from books.platform.money import Money


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
    __tablename__ = "br_match"
    __table_args__ = (
        UniqueConstraint("statement_line_ref"),
        UniqueConstraint("ledger_posting_ref"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    statement_line_ref: Mapped[int] = mapped_column(Integer)
    ledger_posting_ref: Mapped[int] = mapped_column(Integer)
    confirmed_at: Mapped[datetime] = mapped_column(DateTime)


@dataclass(frozen=True, slots=True)
class Statement:
    id: int
    foots: bool


@dataclass(frozen=True, slots=True)
class StatementLineView:
    ref: int
    date: date
    amount: Money
    description: str


@dataclass(frozen=True, slots=True)
class Proposal:
    statement_line_ref: int
    ledger_posting_ref: int


def _parse_csv(raw: str) -> list[tuple[date, int, str]]:
    lines = [ln for ln in raw.splitlines() if ln.strip()]
    out: list[tuple[date, int, str]] = []
    for row in lines[1:]:  # skip header
        d, amount, description = (c.strip() for c in row.split(",", 2))
        minor = int((Decimal(amount) * 100).to_integral_value())
        out.append((date.fromisoformat(d), minor, description))
    return out


_ADAPTERS: dict[str, Callable[[str], list[tuple[date, int, str]]]] = {
    "csv": _parse_csv,
}


class BankReconciliationService:
    def __init__(
        self,
        db: Database,
        bank_postings: Callable[[str], list[PostingView]],
    ) -> None:
        self._db = db
        self._bank_postings = bank_postings

    # --- import ACL (ADR-0018) -----------------------------------------

    def import_statement(
        self,
        account: str,
        period: str,
        opening: Money,
        closing: Money,
        raw: str,
        fmt: str = "csv",
    ) -> Statement:
        content_hash = hashlib.sha256(raw.encode()).hexdigest()
        with self._db.unit_of_work() as session:
            existing = session.execute(
                select(_Statement).where(_Statement.content_hash == content_hash)
            ).scalar_one_or_none()
            if existing is not None:
                return Statement(id=existing.id, foots=True)

            parsed = _ADAPTERS[fmt](raw)
            total = sum(minor for _, minor, _ in parsed)
            if opening.minor_units + total != closing.minor_units:
                raise ValueError(
                    "statement does not foot: "
                    f"{opening.minor_units} + {total} != "
                    f"{closing.minor_units}"
                )

            stmt = _Statement(
                account=account,
                period=period,
                opening_minor=opening.minor_units,
                closing_minor=closing.minor_units,
                content_hash=content_hash,
            )
            session.add(stmt)
            session.flush()
            for d, minor, description in parsed:
                session.add(
                    _Line(
                        statement_id=stmt.id,
                        account=account,
                        period=period,
                        date=d,
                        amount_minor=minor,
                        description=description,
                    )
                )
            return Statement(id=stmt.id, foots=True)

    # --- query side -----------------------------------------------------

    def statement_lines(self, account: str, period: str) -> list[StatementLineView]:
        with self._db.unit_of_work() as session:
            rows = (
                session.execute(
                    select(_Line)
                    .where(_Line.account == account)
                    .where(_Line.period == period)
                    .order_by(_Line.id)
                )
                .scalars()
                .all()
            )
            return [
                StatementLineView(
                    ref=r.id,
                    date=r.date,
                    amount=Money.myr(r.amount_minor),
                    description=r.description,
                )
                for r in rows
            ]

    def statement_closing(self, account: str, period: str) -> Money:
        with self._db.unit_of_work() as session:
            row = (
                session.execute(
                    select(_Statement)
                    .where(_Statement.account == account)
                    .where(_Statement.period == period)
                    .order_by(_Statement.id.desc())
                )
                .scalars()
                .first()
            )
            return Money.myr(row.closing_minor if row else 0)

    def matched_posting_refs(self) -> set[int]:
        with self._db.unit_of_work() as session:
            return set(
                session.execute(select(_Match.ledger_posting_ref)).scalars().all()
            )

    def matched_line_refs(self) -> set[int]:
        with self._db.unit_of_work() as session:
            return set(
                session.execute(select(_Match.statement_line_ref)).scalars().all()
            )

    # --- propose (read-only, ADR-0015) ---------------------------------

    def propose_matches(self, account: str, period: str) -> list[Proposal]:
        with self._db.unit_of_work() as session:
            matched_lines = set(
                session.execute(select(_Match.statement_line_ref)).scalars().all()
            )
            matched_postings = set(
                session.execute(select(_Match.ledger_posting_ref)).scalars().all()
            )
        lines = [
            ln
            for ln in self.statement_lines(account, period)
            if ln.ref not in matched_lines
        ]
        postings = [
            p for p in self._bank_postings(account) if p.ref not in matched_postings
        ]
        proposals: list[Proposal] = []
        for ln in lines:
            for p in postings:
                if p.amount == ln.amount and p.date == ln.date:
                    proposals.append(
                        Proposal(
                            statement_line_ref=ln.ref,
                            ledger_posting_ref=p.ref,
                        )
                    )
                    break
        return proposals

    # --- confirm (sole write, ADR-0015) --------------------------------

    def confirm_match(self, statement_line_ref: int, ledger_posting_ref: int) -> None:
        with self._db.unit_of_work() as session:
            existing = session.execute(
                select(_Match)
                .where(_Match.statement_line_ref == statement_line_ref)
                .where(_Match.ledger_posting_ref == ledger_posting_ref)
            ).scalar_one_or_none()
            if existing is not None:
                return  # idempotent on identical resubmit

            clash = session.execute(
                select(_Match).where(
                    (_Match.statement_line_ref == statement_line_ref)
                    | (_Match.ledger_posting_ref == ledger_posting_ref)
                )
            ).scalar_one_or_none()
            if clash is not None:
                raise ValueError(
                    "already matched: line "
                    f"{statement_line_ref} / posting "
                    f"{ledger_posting_ref}"
                )

            session.add(
                _Match(
                    statement_line_ref=statement_line_ref,
                    ledger_posting_ref=ledger_posting_ref,
                    confirmed_at=datetime.now(),
                )
            )
