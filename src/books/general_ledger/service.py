"""General Ledger application API (ADR-0013).

System-of-record for double-entry postings, measured in functional MYR
(ADR-0017). Mostly event-fed: it subscribes to Invoicing's published events
and translates them into balanced journal entries, each tagged with its
provenance (ADR-0012). Posting amounts are signed minor units, debit
positive; an account balance is their sum.

Well-known account codes (AR / Revenue / Bank) are hardwired for the tracer
thread; configurable account mapping is a thickening concern.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from sqlalchemy import Date, ForeignKey, Integer, String, select
from sqlalchemy.orm import Mapped, mapped_column

from books.expense_management.events import (
    OwnerPaidExpenseRecorded,
    OwnerReimbursed,
)
from books.invoicing.events import (
    InvoiceIssued,
    PaymentRecorded,
    SettlementAdjudicated,
)
from books.platform.db import Base, Database
from books.platform.events import EventBus
from books.platform.money import Money

AR = "AR"
REVENUE = "Revenue"
BANK = "Bank"
FX_LOSS = "FX Loss"  # dedicated realized-FX P&L account (ADR-0005)
WRITE_OFF = "Write-off"  # guided-journal write-off contra
OWNERS_EQUITY = "Owner's Equity"  # year-end P&L sweep target
DUE_TO_OWNER = "Due to Owner"  # the only payable (ADR-0003, amended)
_PNL_TYPES = ("income", "expense")


def _period_of(d: date) -> str:
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
    """A soft-closed period (ADR-0009). Its presence locks new economic
    entries dated into that period; clearance is orthogonal and unaffected."""

    __tablename__ = "gl_period_close"

    period: Mapped[str] = mapped_column(String, primary_key=True)  # YYYY-MM
    kind: Mapped[str] = mapped_column(String)  # "soft"


class _Posting(Base):
    __tablename__ = "gl_posting"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    entry_id: Mapped[int] = mapped_column(ForeignKey("gl_entry.id"))
    account_code: Mapped[str] = mapped_column(ForeignKey("gl_account.code"))
    amount_minor: Mapped[int] = mapped_column(Integer)  # signed, Dr positive
    date: Mapped[date] = mapped_column(Date)
    party_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    party_name: Mapped[str | None] = mapped_column(String, nullable=True)


@dataclass(frozen=True, slots=True)
class PostingView:
    ref: int
    account_code: str
    amount: Money
    date: date
    party_name: str | None


class LedgerService:
    def __init__(
        self,
        db: Database,
        bus: EventBus,
        year_end_blockers: Callable[[int], list] = lambda _year: [],
    ) -> None:
        self._db = db
        # Injected at the composition root (delegates to Reporting, the
        # sanctioned cross-context reader) so the gate logic stays here in
        # the Ledger without GL importing bank_reconciliation/reporting.
        self._year_end_blockers = year_end_blockers
        bus.subscribe(InvoiceIssued, self._on_invoice_issued)
        bus.subscribe(PaymentRecorded, self._on_payment_recorded)
        bus.subscribe(SettlementAdjudicated, self._on_settlement_adjudicated)
        bus.subscribe(OwnerPaidExpenseRecorded, self._on_owner_paid_expense)
        bus.subscribe(OwnerReimbursed, self._on_owner_reimbursed)

    # --- write side -----------------------------------------------------

    def create_account(
        self,
        code: str,
        name: str,
        type: str,
        control: bool = False,
    ) -> None:
        with self._db.unit_of_work() as session:
            session.add(_Account(code=code, name=name, type=type, control=control))

    @staticmethod
    def _period_locked(session, period: str) -> bool:
        return (
            session.execute(
                select(_PeriodClose).where(_PeriodClose.period == period)
            ).scalar_one_or_none()
            is not None
        )

    @classmethod
    def _lock_period(cls, session, period: str, kind: str) -> None:
        """Idempotently record a period lock (ADR-0009)."""
        if not cls._period_locked(session, period):
            session.add(_PeriodClose(period=period, kind=kind))

    def soft_close(self, period: str) -> None:
        """Lock ``period`` (YYYY-MM) against new economic entries (ADR-0009).

        Never blocks on uncleared bank postings — clearance is the
        orthogonal axis and is deliberately not consulted here. Idempotent.
        """
        with self._db.unit_of_work() as session:
            self._lock_period(session, period, kind="soft")

    def write_off(self, posting_ref: int, on: date) -> None:
        """Guided-journal write-off of a phantom bank posting (ADR-0006):
        a fixed-shape Dr Write-off / Cr Bank reversal. Removes the posting
        from the uncleared set so it no longer blocks the hard close."""
        with self._db.unit_of_work() as session:
            target = session.get(_Posting, posting_ref)
            if target is None:
                raise LookupError(f"no posting {posting_ref}")
            amt = target.amount_minor
            self._post(
                session,
                on=on,
                narrative=f"Write-off of phantom bank posting #{posting_ref}",
                source_kind="GuidedJournal",
                source_id=f"writeoff:{posting_ref}",
                legs=[
                    (WRITE_OFF, amt, None, None),
                    (BANK, -amt, None, None),
                ],
            )

    def hard_close(self, year: int) -> None:
        """Annual hard close (ADR-0009). Blocks while any uncleared bank
        posting is unresolved (a stale exception); once clear, sweeps net
        P&L into Owner's Equity via the guided-journal path and locks every
        month of the year, after which the fiscal year is immutable."""
        blockers = self._year_end_blockers(year)
        if blockers:
            raise ValueError(
                f"hard close {year} blocked: {len(blockers)} unresolved "
                "stale uncleared item(s) — classify or adjudicate first"
            )
        on = date(year, 12, 31)
        with self._db.unit_of_work() as session:
            balances = session.execute(
                select(_Posting.account_code, _Account.type)
                .join(_Account, _Account.code == _Posting.account_code)
                .where(_Account.type.in_(_PNL_TYPES))
            ).all()
            pnl_codes = {code for code, _type in balances}
            legs: list[tuple[str, int, int | None, str | None]] = []
            net = 0
            for code in sorted(pnl_codes):
                bal = sum(
                    session.execute(
                        select(_Posting.amount_minor).where(
                            _Posting.account_code == code
                        )
                    )
                    .scalars()
                    .all()
                )
                if bal:
                    legs.append((code, -bal, None, None))
                    net += bal
            legs.append((OWNERS_EQUITY, net, None, None))
            self._post(
                session,
                on=on,
                narrative=f"Year-end close {year}: net P&L to Owner's Equity",
                source_kind="GuidedJournal",
                source_id=f"hardclose:{year}",
                legs=legs,
            )
            for month in range(1, 13):
                self._lock_period(session, f"{year:04d}-{month:02d}", kind="hard")

    def _post(
        self,
        session,
        *,
        on: date,
        narrative: str,
        source_kind: str,
        source_id: str,
        legs: list[tuple[str, int, int | None, str | None]],
    ) -> None:
        period = _period_of(on)
        if self._period_locked(session, period):
            raise ValueError(f"period {period} is closed: cannot post on {on}")
        entry = _Entry(
            date=on,
            narrative=narrative,
            source_kind=source_kind,
            source_id=source_id,
        )
        session.add(entry)
        session.flush()
        for account_code, amount_minor, party_id, party_name in legs:
            session.add(
                _Posting(
                    entry_id=entry.id,
                    account_code=account_code,
                    amount_minor=amount_minor,
                    date=on,
                    party_id=party_id,
                    party_name=party_name,
                )
            )

    def _on_invoice_issued(self, e: InvoiceIssued) -> None:
        amt = e.amount.minor_units
        with self._db.unit_of_work() as session:
            self._post(
                session,
                on=e.issued_on,
                narrative=f"Invoice #{e.invoice_number} to {e.party_name}",
                source_kind="InvoiceIssued",
                source_id=str(e.invoice_number),
                legs=[
                    (AR, amt, e.party_id, e.party_name),
                    (REVENUE, -amt, None, None),
                ],
            )

    def _ar_party_name(self, session, party_id: int) -> str | None:
        """The display name already cached on this party's AR postings
        (CONTEXT: Party is referenced by id + cached name)."""
        return session.execute(
            select(_Posting.party_name)
            .where(_Posting.account_code == AR)
            .where(_Posting.party_id == party_id)
            .limit(1)
        ).scalar_one_or_none()

    def _on_payment_recorded(self, e: PaymentRecorded) -> None:
        amt = e.amount.minor_units
        with self._db.unit_of_work() as session:
            party_name = self._ar_party_name(session, e.party_id)
            self._post(
                session,
                on=e.paid_on,
                narrative=f"Payment for invoice #{e.invoice_number}",
                source_kind="PaymentRecorded",
                source_id=str(e.invoice_number),
                legs=[
                    (BANK, amt, None, None),
                    (AR, -amt, e.party_id, party_name),
                ],
            )

    def _on_settlement_adjudicated(self, e: SettlementAdjudicated) -> None:
        # The one guarded guided-journal template for realized FX (ADR-0006):
        # a fixed-shape Dr FX Loss / Cr AR entry, not free-hand journaling.
        loss = e.fx_loss.minor_units
        if loss == 0:
            return
        with self._db.unit_of_work() as session:
            party_name = self._ar_party_name(session, e.party_id)
            self._post(
                session,
                on=e.on,
                narrative=(
                    f"Realized FX loss on settlement of invoice #{e.invoice_number}"
                ),
                source_kind="GuidedJournal",
                source_id=str(e.invoice_number),
                legs=[
                    (FX_LOSS, loss, None, None),
                    (AR, -loss, e.party_id, party_name),
                ],
            )

    def _on_owner_paid_expense(self, e: OwnerPaidExpenseRecorded) -> None:
        # Recognized at the charge; the business owes the owner (ADR-0003,
        # amended). Supplier Party rides the expense leg as the dimension.
        amt = e.amount.minor_units
        with self._db.unit_of_work() as session:
            self._post(
                session,
                on=e.on,
                narrative=f"Owner-paid expense: {e.party_name}",
                source_kind="OwnerPaidExpenseRecorded",
                source_id=str(e.party_id),
                legs=[
                    (e.category_account, amt, e.party_id, e.party_name),
                    (DUE_TO_OWNER, -amt, None, None),
                ],
            )

    def _on_owner_reimbursed(self, e: OwnerReimbursed) -> None:
        amt = e.amount.minor_units
        with self._db.unit_of_work() as session:
            self._post(
                session,
                on=e.on,
                narrative="Reimbursement to owner",
                source_kind="OwnerReimbursed",
                source_id=e.on.isoformat(),
                legs=[
                    (DUE_TO_OWNER, amt, None, None),
                    (BANK, -amt, None, None),
                ],
            )

    # --- query side (a context query API, ADR-0013) ---------------------

    def account_balance(self, code: str) -> Money:
        with self._db.unit_of_work() as session:
            total = (
                session.execute(
                    select(_Posting.amount_minor).where(_Posting.account_code == code)
                )
                .scalars()
                .all()
            )
            return Money.myr(sum(total))

    def postings_for(self, code: str) -> list[PostingView]:
        with self._db.unit_of_work() as session:
            rows = (
                session.execute(
                    select(_Posting)
                    .where(_Posting.account_code == code)
                    .order_by(_Posting.id)
                )
                .scalars()
                .all()
            )
            return [
                PostingView(
                    ref=r.id,
                    account_code=r.account_code,
                    amount=Money.myr(r.amount_minor),
                    date=r.date,
                    party_name=r.party_name,
                )
                for r in rows
            ]

    def written_off_refs(self) -> set[int]:
        """Bank-posting refs resolved by a guided-journal write-off."""
        with self._db.unit_of_work() as session:
            ids = (
                session.execute(
                    select(_Entry.source_id).where(
                        _Entry.source_kind == "GuidedJournal",
                        _Entry.source_id.like("writeoff:%"),
                    )
                )
                .scalars()
                .all()
            )
            return {int(sid.split(":", 1)[1]) for sid in ids}
