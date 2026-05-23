"""Period-close lifecycle (ADR-0008 / ADR-0009, amended 2026-05-23).

A period (YYYY-MM) moves Open → Soft → Hard, monotonically; Hard is terminal.
This pure module is the single home for what each state permits — no I/O, so
the rules are unit-testable in isolation. The Ledger's append_entry and the
Bank Reconciliation clearance write both consult it.
"""

from __future__ import annotations

from enum import Enum

GUIDED_JOURNAL = "GuidedJournal"


class PeriodState(Enum):
    OPEN = "open"
    SOFT = "soft"
    HARD = "hard"


def may_post(state: PeriodState, source_kind: str) -> bool:
    """May an entry with this source_kind post into a period in `state`?

    Open accepts anything; Soft accepts only the guarded guided-journal
    correction channel (ADR-0006); Hard accepts nothing (immutable).
    """
    if state is PeriodState.OPEN:
        return True
    if state is PeriodState.SOFT:
        return source_kind == GUIDED_JOURNAL
    return False


def may_reconcile(state: PeriodState) -> bool:
    """May a clearance match be confirmed against a posting in `state`?
    Forbidden once the period is hard-closed — the year is then immutable."""
    return state is not PeriodState.HARD


def on_soft_close(state: PeriodState) -> PeriodState:
    """Transition for soft_close. Open/Soft → Soft (idempotent); Hard rejects."""
    if state is PeriodState.HARD:
        raise ValueError("cannot soft-close a hard-closed period")
    return PeriodState.SOFT


def on_hard_close(state: PeriodState) -> PeriodState:
    """Transition for hard_close. Open/Soft → Hard (soft-close is not a
    prerequisite — Open may go straight to Hard); Hard rejects (already closed)."""
    if state is PeriodState.HARD:
        raise ValueError("period already hard-closed")
    return PeriodState.HARD
