"""General Ledger repository (ADR-0013, amended 2026-05-20).

The single persistence touchpoint for ``LedgerService``. Methods are
intent-named (``append_entry``, ``role_code``, ``lock_period``, …) and
take an open ``Session`` as the first argument so the service can compose
multiple operations within one ``unit_of_work()`` block — one transaction
per use-case command (ADR-0011).

Inherits ``unit_of_work()`` from :class:`books.platform.repository.Repository`;
``Database`` (platform) is just an engine container.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from books.general_ledger.period_lifecycle import PeriodState, may_post
from books.general_ledger.persistence.tables import (
    _Account,
    _AccountRole,
    _Entry,
    _PeriodClose,
    _Posting,
    _PostingDimension,
    period_of,
)
from books.platform.repository import Repository

_PNL_TYPES = ("income", "expense")

# (account_code, amount_minor, dimensions). ``dimensions`` is ``None`` for
# an undimensioned leg, else a mapping of ADR-0007 dimension types to
# (value_id, value_name) cached pairs.
Leg = tuple[str, int, dict[str, tuple[str, str]] | None]


@dataclass(frozen=True, slots=True)
class PostingRow:
    """Repository-side projection of a posting + its dimensions. The service
    maps this to its public ``PostingView`` (with ``Money`` + typed
    dimension values)."""

    id: int
    account_code: str
    amount_minor: int
    date: date
    dimensions: dict[str, tuple[str, str]]  # type → (value_id, value_name)


@dataclass(frozen=True, slots=True)
class AccountRow:
    code: str
    name: str
    type: str
    control: bool


class LedgerRepository(Repository):
    # --- commands -------------------------------------------------------

    def add_account(
        self,
        session: Session,
        *,
        code: str,
        name: str,
        type: str,
        control: bool = False,
    ) -> None:
        session.add(_Account(code=code, name=name, type=type, control=control))

    def ensure_role(self, session: Session, role: str, code: str) -> None:
        """Insert the role→code row only if absent (idempotent seed)."""
        if self.find_role(session, role) is None:
            session.add(_AccountRole(role=role, code=code))

    def upsert_role(self, session: Session, role: str, code: str) -> None:
        """Set the role→code mapping; insert or update."""
        row = session.execute(
            select(_AccountRole).where(_AccountRole.role == role)
        ).scalar_one_or_none()
        if row is None:
            session.add(_AccountRole(role=role, code=code))
        else:
            row.code = code

    def lock_period(self, session: Session, period: str, *, kind: str) -> None:
        """Record or upgrade a period lock (ADR-0009). Inserts a new lock, or
        upgrades an existing soft lock to hard; never downgrades, idempotent on
        a repeat of the same kind."""
        row = session.execute(
            select(_PeriodClose).where(_PeriodClose.period == period)
        ).scalar_one_or_none()
        if row is None:
            session.add(_PeriodClose(period=period, kind=kind))
        elif row.kind == "soft" and kind == "hard":
            row.kind = "hard"

    def append_entry(
        self,
        session: Session,
        *,
        on: date,
        narrative: str,
        source_kind: str,
        source_id: str,
        legs: list[Leg],
    ) -> None:
        """Insert one balanced entry with its postings + dimensions. Raises
        ``ValueError`` if the target period is closed (ADR-0009 invariant
        lives with the write that violates it)."""
        period = period_of(on)
        state = self.period_state(session, period)
        if not may_post(state, source_kind):
            raise ValueError(
                f"period {period} is {state.value}-closed: "
                f"cannot post {source_kind} on {on}"
            )
        entry = _Entry(
            date=on,
            narrative=narrative,
            source_kind=source_kind,
            source_id=source_id,
        )
        session.add(entry)
        session.flush()
        for account_code, amount_minor, dimensions in legs:
            posting = _Posting(
                entry_id=entry.id,
                account_code=account_code,
                amount_minor=amount_minor,
                date=on,
            )
            session.add(posting)
            if dimensions:
                session.flush()
                for dim_type, (value_id, value_name) in dimensions.items():
                    session.add(
                        _PostingDimension(
                            posting_id=posting.id,
                            type=dim_type,
                            value_id=str(value_id),
                            value_name=value_name,
                        )
                    )

    # --- queries --------------------------------------------------------

    def period_state(self, session: Session, period: str) -> PeriodState:
        """The close state of a period: OPEN (no lock), SOFT, or HARD."""
        row = session.execute(
            select(_PeriodClose).where(_PeriodClose.period == period)
        ).scalar_one_or_none()
        if row is None:
            return PeriodState.OPEN
        return PeriodState.SOFT if row.kind == "soft" else PeriodState.HARD

    def list_period_locks(self, session: Session) -> list[tuple[str, str]]:
        """Every locked period and its kind (soft/hard), period-ordered."""
        return [
            (row.period, row.kind)
            for row in session.execute(
                select(_PeriodClose).order_by(_PeriodClose.period)
            ).scalars()
        ]

    def find_role(self, session: Session, role: str) -> str | None:
        return session.execute(
            select(_AccountRole.code).where(_AccountRole.role == role)
        ).scalar_one_or_none()

    def role_code(self, session: Session, role: str) -> str:
        """Resolve a role to its current code; raise if the role is unknown."""
        code = self.find_role(session, role)
        if code is None:
            raise ValueError(f"unknown role {role!r}")
        return code

    def ar_party_name(
        self, session: Session, ar_code: str, party_id: int
    ) -> str | None:
        """The display name already cached on this party's AR postings
        (CONTEXT: Party is referenced by id + cached name)."""
        return session.execute(
            select(_PostingDimension.value_name)
            .join(_Posting, _Posting.id == _PostingDimension.posting_id)
            .where(_Posting.account_code == ar_code)
            .where(_PostingDimension.type == "party")
            .where(_PostingDimension.value_id == str(party_id))
            .limit(1)
        ).scalar_one_or_none()

    def account_balance_minor(self, session: Session, code: str) -> int:
        rows = (
            session.execute(
                select(_Posting.amount_minor).where(_Posting.account_code == code)
            )
            .scalars()
            .all()
        )
        return sum(rows)

    def list_accounts(self, session: Session) -> list[AccountRow]:
        """Every account on the Chart, ordered alphabetically by code for
        a deterministic projection. Used by LedgerService.accounts() which
        backs the MCP accounts:// resource."""
        rows = session.execute(select(_Account).order_by(_Account.code)).scalars().all()
        return [
            AccountRow(code=r.code, name=r.name, type=r.type, control=r.control)
            for r in rows
        ]

    def postings_for(self, session: Session, code: str) -> list[PostingRow]:
        rows = (
            session.execute(
                select(_Posting)
                .where(_Posting.account_code == code)
                .order_by(_Posting.id)
            )
            .scalars()
            .all()
        )
        ids = [r.id for r in rows]
        dim_rows = (
            session.execute(
                select(_PostingDimension).where(_PostingDimension.posting_id.in_(ids))
            )
            .scalars()
            .all()
            if ids
            else []
        )
        by_posting: dict[int, dict[str, tuple[str, str]]] = {i: {} for i in ids}
        for d in dim_rows:
            by_posting[d.posting_id][d.type] = (d.value_id, d.value_name)
        return [
            PostingRow(
                id=r.id,
                account_code=r.account_code,
                amount_minor=r.amount_minor,
                date=r.date,
                dimensions=by_posting[r.id],
            )
            for r in rows
        ]

    def get_posting(self, session: Session, posting_ref: int) -> PostingRow | None:
        row = session.get(_Posting, posting_ref)
        if row is None:
            return None
        # Dimensions are not needed for the current callers (write_off) — keep
        # the shape consistent and load them anyway.
        dim_rows = (
            session.execute(
                select(_PostingDimension).where(
                    _PostingDimension.posting_id == posting_ref
                )
            )
            .scalars()
            .all()
        )
        dims: dict[str, tuple[str, str]] = {
            d.type: (d.value_id, d.value_name) for d in dim_rows
        }
        return PostingRow(
            id=row.id,
            account_code=row.account_code,
            amount_minor=row.amount_minor,
            date=row.date,
            dimensions=dims,
        )

    def written_off_refs(self, session: Session) -> set[int]:
        """Bank-posting refs resolved by a guided-journal write-off.

        Returns the refs of (a) the original bank postings that were written
        off (parsed from the ``writeoff:<ref>`` source_id) *and* (b) every
        bank posting that belongs to a write-off guided-journal entry itself
        (the Cr Bank counterpart leg).  Both sets must be excluded from
        ``year_end_blockers`` because neither represents an open reconciling
        item: the first was the phantom and the second is its accounting
        reversal."""
        write_off_entries: list[_Entry] = (
            session.execute(
                select(_Entry).where(
                    _Entry.source_kind == "GuidedJournal",
                    _Entry.source_id.like("writeoff:%"),
                )
            )
            .scalars()
            .all()
        )
        if not write_off_entries:
            return set()

        # (a) original written-off posting refs (from the source_id tag)
        original_refs: set[int] = {
            int(e.source_id.split(":", 1)[1]) for e in write_off_entries
        }

        # (b) bank postings that are the Cr leg inside write-off entries
        entry_ids = [e.id for e in write_off_entries]
        bank_role = self.find_role(session, "bank")
        counterpart_refs: set[int] = set()
        if bank_role is not None:
            counterpart_refs = set(
                session.execute(
                    select(_Posting.id).where(
                        _Posting.entry_id.in_(entry_ids),
                        _Posting.account_code == bank_role,
                    )
                )
                .scalars()
                .all()
            )

        return original_refs | counterpart_refs

    def pnl_balances(self, session: Session) -> dict[str, int]:
        """Signed minor-unit balance per income/expense account that has any
        posting. Used by the year-end P&L → Owner's Equity sweep."""
        codes = (
            session.execute(
                select(_Posting.account_code)
                .join(_Account, _Account.code == _Posting.account_code)
                .where(_Account.type.in_(_PNL_TYPES))
                .distinct()
            )
            .scalars()
            .all()
        )
        return {code: self.account_balance_minor(session, code) for code in codes}
