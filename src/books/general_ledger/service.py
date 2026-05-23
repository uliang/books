"""General Ledger application API (ADR-0013).

System-of-record for double-entry postings, measured in functional MYR
(ADR-0017). Mostly event-fed: subscribes to other contexts' published events
and translates them into balanced journal entries, each tagged with its
provenance (ADR-0012). Posting amounts are signed minor units, debit
positive; an account balance is their sum.

Well-known posting roles (ar / revenue / bank / fx_loss / write_off /
owners_equity / due_to_owner) map to concrete account codes via a persisted
``gl_account_role`` table, seeded with sensible defaults and editable by the
owner through ``assign_role``. The Chart of Accounts is a GL aggregate
(CONTEXT) so the role mapping lives in this context, not at the composition
root.

Persistence is owned by :class:`books.general_ledger.persistence.repository.
LedgerRepository`; the service holds only ``self._repo`` and expresses
business intent against it (ADR-0013 amendment 2026-05-20).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

from books.expense_management.events import (
    ContractorPaid,
    OwnerPaidExpenseRecorded,
    OwnerReimbursed,
)
from books.general_ledger.period_lifecycle import (
    PeriodState,
    may_reconcile,
    on_soft_close,
)
from books.general_ledger.persistence.repository import LedgerRepository
from books.invoicing.events import (
    InvoiceIssued,
    PaymentRecorded,
    SettlementAdjudicated,
)
from books.platform.db import Database
from books.platform.events import EventBus
from books.platform.money import Money

# Default role → code mapping. The Chart of Accounts is an aggregate inside
# General Ledger (CONTEXT); the codes the handlers post to are a *persisted*
# role mapping the owner can override (see ``assign_role``). Defaults match
# the well-known names so first-run flows just work.
_DEFAULT_ROLES: dict[str, str] = {
    "ar": "AR",
    "revenue": "Revenue",
    "bank": "Bank",
    "fx_loss": "FX Loss",  # ADR-0005 dedicated realized-FX P&L account
    "write_off": "Write-off",  # guided-journal write-off contra
    "owners_equity": "Owner's Equity",  # year-end P&L sweep target
    "due_to_owner": "Due to Owner",  # the only payable (ADR-0003, amended)
}


def _party_dim(party_id: int, party_name: str | None) -> dict[str, tuple[str, str]]:
    """Carry a Party as the ADR-0007 dimension on a journal leg (v1's only
    dimension type). Name defaults to the empty string so the schema's
    cached-name invariant holds even if a resolver returned ``None``."""
    return {"party": (str(party_id), party_name or "")}


@dataclass(frozen=True, slots=True)
class DimensionValue:
    """A typed analytical tag's value on a posting (ADR-0007)."""

    id: str
    name: str


@dataclass(frozen=True, slots=True)
class PostingView:
    ref: int
    account_code: str
    amount: Money
    date: date
    dimensions: dict[str, DimensionValue] = field(default_factory=dict)
    # Derived backward-compat convenience: the Party dimension's name (Party
    # is the only v1 dimension type). Prefer ``dimensions["party"]`` in new
    # code so adding Project later doesn't grow the view's shape.
    party_name: str | None = None


@dataclass(frozen=True, slots=True)
class Account:
    code: str
    name: str
    type: str
    control: bool


@dataclass(frozen=True, slots=True)
class PeriodLockView:
    """A closed period and its kind. The kind now carries behaviour (see
    ``period_lifecycle``): soft permits guarded guided-journal corrections and
    reconciliation; hard permits neither."""

    period: str
    kind: str


class LedgerService:
    def __init__(
        self,
        db: Database,
        bus: EventBus,
        year_end_blockers: Callable[[int], list] = lambda _year: [],
    ) -> None:
        # The repository is the service's sole persistence touchpoint
        # (ADR-0013 amended 2026-05-20). ``db`` is threaded into the repo
        # and not retained as an attribute.
        self._repo = LedgerRepository(db)
        # Injected at the composition root (delegates to Reporting, the
        # sanctioned cross-context reader) so the gate logic stays here in
        # the Ledger without GL importing bank_reconciliation/reporting.
        self._year_end_blockers = year_end_blockers
        bus.subscribe(InvoiceIssued, self._on_invoice_issued)
        bus.subscribe(PaymentRecorded, self._on_payment_recorded)
        bus.subscribe(SettlementAdjudicated, self._on_settlement_adjudicated)
        bus.subscribe(OwnerPaidExpenseRecorded, self._on_owner_paid_expense)
        bus.subscribe(OwnerReimbursed, self._on_owner_reimbursed)
        bus.subscribe(ContractorPaid, self._on_contractor_paid)
        self._seed_default_roles()

    def _seed_default_roles(self) -> None:
        """Idempotent first-run seed of the role→code defaults."""
        with self._repo.unit_of_work() as session:
            for role, code in _DEFAULT_ROLES.items():
                self._repo.ensure_role(session, role, code)

    # --- write side -----------------------------------------------------

    def create_account(
        self,
        code: str,
        name: str,
        type: str,
        control: bool = False,
    ) -> None:
        with self._repo.unit_of_work() as session:
            self._repo.add_account(
                session, code=code, name=name, type=type, control=control
            )

    def assign_role(self, role: str, code: str) -> None:
        """Override the code a well-known posting role maps to. The code
        need not exist on the Chart yet, but a posting referencing a missing
        code will fail at post time via the existing _Posting → _Account FK."""
        if role not in _DEFAULT_ROLES:
            raise ValueError(f"unknown role {role!r}; known: {sorted(_DEFAULT_ROLES)}")
        with self._repo.unit_of_work() as session:
            self._repo.upsert_role(session, role, code)

    def soft_close(self, period: str) -> None:
        """Lock ``period`` (YYYY-MM) against casual economic entries; guarded
        guided-journal corrections and reconciliation still pass (ADR-0009,
        amended). Never blocks on uncleared items; idempotent on a soft
        period; rejects a period already hard-closed."""
        with self._repo.unit_of_work() as session:
            on_soft_close(self._repo.period_state(session, period))  # rejects HARD
            self._repo.lock_period(session, period, kind="soft")

    def write_off(self, posting_ref: int, on: date) -> None:
        """Guided-journal write-off of a phantom bank posting (ADR-0006):
        a fixed-shape Dr Write-off / Cr Bank reversal. Removes the posting
        from the uncleared set so it no longer blocks the hard close."""
        with self._repo.unit_of_work() as session:
            target = self._repo.get_posting(session, posting_ref)
            if target is None:
                raise LookupError(f"no posting {posting_ref}")
            write_off = self._repo.role_code(session, "write_off")
            bank = self._repo.role_code(session, "bank")
            self._repo.append_entry(
                session,
                on=on,
                narrative=f"Write-off of phantom bank posting #{posting_ref}",
                source_kind="GuidedJournal",
                source_id=f"writeoff:{posting_ref}",
                legs=[
                    (write_off, target.amount_minor, None),
                    (bank, -target.amount_minor, None),
                ],
            )

    def hard_close(self, year: int) -> None:
        """Annual hard close (ADR-0009, amended). Blocks while ANY bank
        posting is uncleared — matched to a statement or written off are the
        only resolutions, regardless of age; once clear, sweeps net P&L into
        Owner's Equity via the guided-journal path and locks every month of
        the year, after which the fiscal year is immutable."""
        blockers = self._year_end_blockers(year)
        if blockers:
            raise ValueError(
                f"hard close {year} blocked: {len(blockers)} unresolved "
                "uncleared item(s) — reconcile or write off first"
            )
        on = date(year, 12, 31)
        with self._repo.unit_of_work() as session:
            # December HARD ⟺ the whole year is closed: the loop below locks
            # all 12 months atomically, so no partial-hard year can exist.
            if self._repo.period_state(session, f"{year:04d}-12") is PeriodState.HARD:
                raise ValueError(f"hard close {year}: already closed")
            balances = self._repo.pnl_balances(session)
            legs: list[tuple[str, int, dict[str, tuple[str, str]] | None]] = []
            net = 0
            for code in sorted(balances):
                bal = balances[code]
                if bal:
                    legs.append((code, -bal, None))
                    net += bal
            legs.append((self._repo.role_code(session, "owners_equity"), net, None))
            self._repo.append_entry(
                session,
                on=on,
                narrative=f"Year-end close {year}: net P&L to Owner's Equity",
                source_kind="GuidedJournal",
                source_id=f"hardclose:{year}",
                legs=legs,
            )
            for month in range(1, 13):
                self._repo.lock_period(session, f"{year:04d}-{month:02d}", kind="hard")

    def _on_invoice_issued(self, e: InvoiceIssued) -> None:
        amt = e.amount.minor_units
        with self._repo.unit_of_work() as session:
            ar = self._repo.role_code(session, "ar")
            revenue = self._repo.role_code(session, "revenue")
            self._repo.append_entry(
                session,
                on=e.issued_on,
                narrative=f"Invoice #{e.invoice_number} to {e.party_name}",
                source_kind="InvoiceIssued",
                source_id=str(e.invoice_number),
                legs=[
                    (ar, amt, _party_dim(e.party_id, e.party_name)),
                    (revenue, -amt, None),
                ],
            )

    def _on_payment_recorded(self, e: PaymentRecorded) -> None:
        amt = e.amount.minor_units
        with self._repo.unit_of_work() as session:
            ar = self._repo.role_code(session, "ar")
            bank = self._repo.role_code(session, "bank")
            party_name = self._repo.ar_party_name(session, ar, e.party_id)
            self._repo.append_entry(
                session,
                on=e.paid_on,
                narrative=f"Payment for invoice #{e.invoice_number}",
                source_kind="PaymentRecorded",
                source_id=str(e.invoice_number),
                legs=[
                    (bank, amt, None),
                    (ar, -amt, _party_dim(e.party_id, party_name)),
                ],
            )

    def _on_settlement_adjudicated(self, e: SettlementAdjudicated) -> None:
        # The one guarded guided-journal template for realized FX (ADR-0006):
        # a fixed-shape Dr FX Loss / Cr AR entry, not free-hand journaling.
        loss = e.fx_loss.minor_units
        if loss == 0:
            return
        with self._repo.unit_of_work() as session:
            ar = self._repo.role_code(session, "ar")
            fx_loss = self._repo.role_code(session, "fx_loss")
            party_name = self._repo.ar_party_name(session, ar, e.party_id)
            self._repo.append_entry(
                session,
                on=e.on,
                narrative=(
                    f"Realized FX loss on settlement of invoice #{e.invoice_number}"
                ),
                source_kind="GuidedJournal",
                source_id=str(e.invoice_number),
                legs=[
                    (fx_loss, loss, None),
                    (ar, -loss, _party_dim(e.party_id, party_name)),
                ],
            )

    def _on_owner_paid_expense(self, e: OwnerPaidExpenseRecorded) -> None:
        # Recognized at the charge; the business owes the owner (ADR-0003,
        # amended). Supplier Party rides the expense leg as the dimension.
        amt = e.amount.minor_units
        with self._repo.unit_of_work() as session:
            due = self._repo.role_code(session, "due_to_owner")
            self._repo.append_entry(
                session,
                on=e.on,
                narrative=f"Owner-paid expense: {e.party_name}",
                source_kind="OwnerPaidExpenseRecorded",
                source_id=str(e.party_id),
                legs=[
                    (e.category_account, amt, _party_dim(e.party_id, e.party_name)),
                    (due, -amt, None),
                ],
            )

    def _on_contractor_paid(self, e: ContractorPaid) -> None:
        # Pure cash basis (ADR-0003): no payable, the bank moves at once.
        # Contractor Party rides the expense leg as the dimension.
        amt = e.amount.minor_units
        with self._repo.unit_of_work() as session:
            bank = self._repo.role_code(session, "bank")
            self._repo.append_entry(
                session,
                on=e.on,
                narrative=f"Contractor payment: {e.party_name}",
                source_kind="ContractorPaid",
                source_id=str(e.party_id),
                legs=[
                    (e.category_account, amt, _party_dim(e.party_id, e.party_name)),
                    (bank, -amt, None),
                ],
            )

    def _on_owner_reimbursed(self, e: OwnerReimbursed) -> None:
        amt = e.amount.minor_units
        with self._repo.unit_of_work() as session:
            due = self._repo.role_code(session, "due_to_owner")
            bank = self._repo.role_code(session, "bank")
            self._repo.append_entry(
                session,
                on=e.on,
                narrative="Reimbursement to owner",
                source_kind="OwnerReimbursed",
                source_id=e.on.isoformat(),
                legs=[
                    (due, amt, None),
                    (bank, -amt, None),
                ],
            )

    # --- query side (a context query API, ADR-0013) ---------------------

    def role_code(self, role: str) -> str:
        """The code currently mapped to a well-known posting role."""
        with self._repo.unit_of_work() as session:
            return self._repo.role_code(session, role)

    def accounts(self) -> list[Account]:
        with self._repo.unit_of_work() as session:
            return [
                Account(code=r.code, name=r.name, type=r.type, control=r.control)
                for r in self._repo.list_accounts(session)
            ]

    def locked_periods(self) -> list[PeriodLockView]:
        """Every closed period and its kind (soft/hard), period-ordered."""
        with self._repo.unit_of_work() as session:
            return [
                PeriodLockView(period=period, kind=kind)
                for period, kind in self._repo.list_period_locks(session)
            ]

    def account_balance(self, code: str) -> Money:
        with self._repo.unit_of_work() as session:
            return Money.myr(self._repo.account_balance_minor(session, code))

    def postings_for(self, code: str) -> list[PostingView]:
        with self._repo.unit_of_work() as session:
            rows = self._repo.postings_for(session, code)
        return [
            PostingView(
                ref=r.id,
                account_code=r.account_code,
                amount=Money.myr(r.amount_minor),
                date=r.date,
                dimensions={
                    t: DimensionValue(id=v_id, name=v_name)
                    for t, (v_id, v_name) in r.dimensions.items()
                },
                party_name=(
                    r.dimensions["party"][1] if "party" in r.dimensions else None
                ),
            )
            for r in rows
        ]

    def written_off_refs(self) -> set[int]:
        """Bank-posting refs to exclude from year-end blockers: both the
        original postings resolved by a write-off and the write-off entries'
        own Cr Bank reversal legs (see the repository method for detail)."""
        with self._repo.unit_of_work() as session:
            return self._repo.written_off_refs(session)

    def posting_is_reconcilable(self, posting_ref: int) -> bool:
        """Whether a clearance match may still be confirmed against this
        posting: true unless its period is hard-closed (ADR-0009 amended).
        Bank Reconciliation consults this before confirm_match. An unknown
        ref returns True so confirm_match surfaces its own error."""
        with self._repo.unit_of_work() as session:
            state = self._repo.posting_period_state(session, posting_ref)
            return True if state is None else may_reconcile(state)
