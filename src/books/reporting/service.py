"""Reporting application API (ADR-0016) — the read model.

Reports are computed on demand by joining the owning contexts' query APIs
(Reporting is the sanctioned cross-context reader, ADR-0013); there is no
materialized projection. "Cleared" is derived: a bank posting is cleared iff
a Match references it (ADR-0010), so confirmed cash (invariant 3) and the
tie-out (invariant 4) are both joins, never stored reads.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date

from books.bank_reconciliation.service import BankReconciliationService
from books.general_ledger.service import LedgerService
from books.platform.money import Money

TIMING_DIFFERENCE = "timing_difference"
STALE_EXCEPTION = "stale_exception"


@dataclass(frozen=True, slots=True)
class ReconcilingItem:
    """An uncleared bank posting, classified for review (increment 1).

    A timing difference is expected to clear soon; a stale exception is
    overdue against the owner-configured threshold and needs attention.
    """

    ref: int
    amount: Money
    age_days: int
    classification: str


@dataclass(frozen=True, slots=True)
class ReconciliationReport:
    statement_closing: Money
    ledger_bank_balance: Money
    confirmed_cash: Money
    difference: Money
    reconciling_items: list[ReconcilingItem]  # uncleared bank postings
    unexplained_lines: list[int]  # statement line refs with no match


def _period_end(period: str) -> date:
    """Last calendar day of a ``YYYY-MM`` period."""
    year, month = (int(part) for part in period.split("-"))
    return date(year, month, calendar.monthrange(year, month)[1])


class ReportingService:
    def __init__(
        self,
        ledger: LedgerService,
        recon: BankReconciliationService,
        stale_after_days: int = 30,
    ) -> None:
        self._ledger = ledger
        self._recon = recon
        self._stale_after_days = stale_after_days

    def reconciliation_report(self, account: str, period: str) -> ReconciliationReport:
        ledger_balance = self._ledger.account_balance(code=account)
        statement_closing = self._recon.statement_closing(account, period)
        matched_postings = self._recon.matched_posting_refs()

        postings = self._ledger.postings_for(code=account)
        confirmed_cash = Money.myr(
            sum(p.amount.minor_units for p in postings if p.ref in matched_postings)
        )
        period_end = _period_end(period)
        reconciling_items = [
            ReconcilingItem(
                ref=p.ref,
                amount=p.amount,
                age_days=(age := (period_end - p.date).days),
                classification=(
                    STALE_EXCEPTION
                    if age > self._stale_after_days
                    else TIMING_DIFFERENCE
                ),
            )
            for p in postings
            if p.ref not in matched_postings
        ]

        matched_lines = self._recon.matched_line_refs()
        unexplained_lines = [
            ln.ref
            for ln in self._recon.statement_lines(account, period)
            if ln.ref not in matched_lines
        ]

        difference = statement_closing - confirmed_cash
        return ReconciliationReport(
            statement_closing=statement_closing,
            ledger_bank_balance=ledger_balance,
            confirmed_cash=confirmed_cash,
            difference=difference,
            reconciling_items=reconciling_items,
            unexplained_lines=unexplained_lines,
        )

    def year_end_blockers(self, year: int) -> list[ReconcilingItem]:
        """Every uncleared bank posting standing in the way of the annual hard
        close (ADR-0009, amended): any posting neither matched to a statement
        nor written off blocks, regardless of age. Each carries a timing/stale
        classification by age purely as owner-facing triage — the
        classification no longer gates."""
        year_end = date(year, 12, 31)
        matched = self._recon.matched_posting_refs()
        written_off = self._ledger.written_off_refs()
        blockers: list[ReconcilingItem] = []
        for p in self._ledger.postings_for(code=self._ledger.role_code("bank")):
            if p.ref in matched or p.ref in written_off:
                continue
            age = (year_end - p.date).days
            classification = (
                STALE_EXCEPTION if age > self._stale_after_days else TIMING_DIFFERENCE
            )
            blockers.append(
                ReconcilingItem(
                    ref=p.ref,
                    amount=p.amount,
                    age_days=age,
                    classification=classification,
                )
            )
        return blockers
