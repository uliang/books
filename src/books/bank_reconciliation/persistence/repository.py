"""Bank Reconciliation repository (ADR-0013 amended 2026-05-20)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from books.bank_reconciliation.persistence.tables import _Line, _Match, _Statement
from books.platform.repository import Repository


@dataclass(frozen=True, slots=True)
class StatementRow:
    id: int
    closing_minor: int


@dataclass(frozen=True, slots=True)
class LineRow:
    id: int
    date: date
    amount_minor: int
    description: str


class BankReconciliationRepository(Repository):
    # --- statement import ----------------------------------------------

    def find_statement_by_hash(
        self, session: Session, content_hash: str
    ) -> StatementRow | None:
        row = session.execute(
            select(_Statement).where(_Statement.content_hash == content_hash)
        ).scalar_one_or_none()
        if row is None:
            return None
        return StatementRow(id=row.id, closing_minor=row.closing_minor)

    def add_statement(
        self,
        session: Session,
        *,
        account: str,
        period: str,
        opening_minor: int,
        closing_minor: int,
        content_hash: str,
        lines: list[tuple[date, int, str]],
    ) -> StatementRow:
        stmt = _Statement(
            account=account,
            period=period,
            opening_minor=opening_minor,
            closing_minor=closing_minor,
            content_hash=content_hash,
        )
        session.add(stmt)
        session.flush()
        for d, minor, description in lines:
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
        return StatementRow(id=stmt.id, closing_minor=stmt.closing_minor)

    # --- queries --------------------------------------------------------

    def lines_for(self, session: Session, account: str, period: str) -> list[LineRow]:
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
            LineRow(
                id=r.id,
                date=r.date,
                amount_minor=r.amount_minor,
                description=r.description,
            )
            for r in rows
        ]

    def latest_closing_minor(self, session: Session, account: str, period: str) -> int:
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
        return row.closing_minor if row else 0

    def matched_line_refs(self, session: Session) -> set[int]:
        return set(session.execute(select(_Match.statement_line_ref)).scalars().all())

    def matched_posting_refs(self, session: Session) -> set[int]:
        return set(session.execute(select(_Match.ledger_posting_ref)).scalars().all())

    # --- confirm match (sole write, ADR-0015) --------------------------

    def find_match(
        self, session: Session, *, line_ref: int, posting_ref: int
    ) -> int | None:
        row = session.execute(
            select(_Match)
            .where(_Match.statement_line_ref == line_ref)
            .where(_Match.ledger_posting_ref == posting_ref)
        ).scalar_one_or_none()
        return None if row is None else row.id

    def find_clash(
        self, session: Session, *, line_ref: int, posting_ref: int
    ) -> int | None:
        """Any existing Match touching either side of the proposed pair."""
        row = session.execute(
            select(_Match).where(
                (_Match.statement_line_ref == line_ref)
                | (_Match.ledger_posting_ref == posting_ref)
            )
        ).scalar_one_or_none()
        return None if row is None else row.id

    def record_match(
        self, session: Session, *, line_ref: int, posting_ref: int, at: datetime
    ) -> None:
        session.add(
            _Match(
                statement_line_ref=line_ref,
                ledger_posting_ref=posting_ref,
                confirmed_at=at,
            )
        )
