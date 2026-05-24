"""Pure unit tests for the period-close lifecycle policy (ADR-0008/0009)."""

from __future__ import annotations

from datetime import date

import pytest

from books.general_ledger import PeriodClosedError as ReexportedPeriodClosedError
from books.general_ledger.period_lifecycle import (
    PeriodClosedError,
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


def test_period_closed_error_is_a_value_error_carrying_fields():
    err = PeriodClosedError(
        period="2026-01",
        state=PeriodState.SOFT,
        source_kind="InvoiceIssued",
        on=date(2026, 1, 15),
    )
    assert isinstance(err, ValueError)
    assert err.period == "2026-01"
    assert err.state is PeriodState.SOFT
    assert err.source_kind == "InvoiceIssued"
    assert err.on == date(2026, 1, 15)
    assert str(err) == (
        "period 2026-01 is soft-closed: cannot post InvoiceIssued on 2026-01-15"
    )


def test_period_closed_error_is_re_exported_from_the_context():
    assert ReexportedPeriodClosedError is PeriodClosedError
