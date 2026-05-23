"""Pure unit tests for the period-close lifecycle policy (ADR-0008/0009)."""

from __future__ import annotations

import pytest

from books.general_ledger.period_lifecycle import (
    PeriodState,
    may_post,
    may_reconcile,
    on_hard_close,
    on_soft_close,
)


def test_open_accepts_any_posting():
    assert may_post(PeriodState.OPEN, "InvoiceIssued")
    assert may_post(PeriodState.OPEN, "GuidedJournal")


def test_soft_accepts_only_guided_journal():
    assert may_post(PeriodState.SOFT, "GuidedJournal")
    assert not may_post(PeriodState.SOFT, "InvoiceIssued")
    assert not may_post(PeriodState.SOFT, "PaymentRecorded")


def test_hard_accepts_nothing():
    assert not may_post(PeriodState.HARD, "GuidedJournal")
    assert not may_post(PeriodState.HARD, "InvoiceIssued")


def test_reconciliation_blocked_only_when_hard():
    assert may_reconcile(PeriodState.OPEN)
    assert may_reconcile(PeriodState.SOFT)
    assert not may_reconcile(PeriodState.HARD)


def test_soft_close_transition():
    assert on_soft_close(PeriodState.OPEN) is PeriodState.SOFT
    assert on_soft_close(PeriodState.SOFT) is PeriodState.SOFT
    with pytest.raises(ValueError, match="hard-closed"):
        on_soft_close(PeriodState.HARD)


def test_hard_close_transition():
    assert on_hard_close(PeriodState.OPEN) is PeriodState.HARD
    assert on_hard_close(PeriodState.SOFT) is PeriodState.HARD
    with pytest.raises(ValueError, match="already hard-closed"):
        on_hard_close(PeriodState.HARD)
