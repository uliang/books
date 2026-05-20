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

Persistence is owned by :class:`BankReconciliationRepository` (ADR-0013
amendment 2026-05-20); the service holds only ``self._repo``.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from books.bank_reconciliation.persistence.repository import (
    BankReconciliationRepository,
)
from books.general_ledger.service import PostingView
from books.platform.db import Database
from books.platform.money import Money


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
        self._repo = BankReconciliationRepository(db)
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
        with self._repo.unit_of_work() as session:
            existing = self._repo.find_statement_by_hash(session, content_hash)
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
            stmt = self._repo.add_statement(
                session,
                account=account,
                period=period,
                opening_minor=opening.minor_units,
                closing_minor=closing.minor_units,
                content_hash=content_hash,
                lines=parsed,
            )
            return Statement(id=stmt.id, foots=True)

    # --- query side -----------------------------------------------------

    def statement_lines(self, account: str, period: str) -> list[StatementLineView]:
        with self._repo.unit_of_work() as session:
            rows = self._repo.lines_for(session, account, period)
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
        with self._repo.unit_of_work() as session:
            return Money.myr(self._repo.latest_closing_minor(session, account, period))

    def matched_posting_refs(self) -> set[int]:
        with self._repo.unit_of_work() as session:
            return self._repo.matched_posting_refs(session)

    def matched_line_refs(self) -> set[int]:
        with self._repo.unit_of_work() as session:
            return self._repo.matched_line_refs(session)

    # --- propose (read-only, ADR-0015) ---------------------------------

    def propose_matches(self, account: str, period: str) -> list[Proposal]:
        with self._repo.unit_of_work() as session:
            matched_lines = self._repo.matched_line_refs(session)
            matched_postings = self._repo.matched_posting_refs(session)
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
        with self._repo.unit_of_work() as session:
            if (
                self._repo.find_match(
                    session,
                    line_ref=statement_line_ref,
                    posting_ref=ledger_posting_ref,
                )
                is not None
            ):
                return  # idempotent on identical resubmit
            if (
                self._repo.find_clash(
                    session,
                    line_ref=statement_line_ref,
                    posting_ref=ledger_posting_ref,
                )
                is not None
            ):
                raise ValueError(
                    "already matched: line "
                    f"{statement_line_ref} / posting "
                    f"{ledger_posting_ref}"
                )
            self._repo.record_match(
                session,
                line_ref=statement_line_ref,
                posting_ref=ledger_posting_ref,
                at=datetime.now(),
            )
