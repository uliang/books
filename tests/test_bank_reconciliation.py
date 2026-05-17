"""Bank Reconciliation (CORE) — ADR-0014/0015/0018.

Import is an ACL (CSV adapter, footing check, content-hash idempotency).
propose_matches is read-only; confirm_match is the sole write and enforces
the uniqueness invariants.
"""

from datetime import date

import pytest

from books.bank_reconciliation.service import BankReconciliationService
from books.general_ledger.service import PostingView
from books.platform.db import Database
from books.platform.money import Money

JAN_CSV = "date,amount,description\n2026-01-15,1000.00,ACME TRANSFER\n"


def _bank_posting() -> PostingView:
    return PostingView(
        ref=99,
        account_code="Bank",
        amount=Money.myr(1000_00),
        date=date(2026, 1, 15),
        party_name=None,
    )


def _service(postings: list[PostingView]) -> BankReconciliationService:
    return BankReconciliationService(Database(), bank_postings=lambda account: postings)


def test_import_rejects_a_statement_that_does_not_foot():
    svc = _service([])
    with pytest.raises(ValueError, match="foot"):
        svc.import_statement(
            account="Bank",
            period="2026-01",
            opening=Money.myr(0),
            closing=Money.myr(999_00),  # != opening + Σ lines
            raw=JAN_CSV,
            fmt="csv",
        )


def test_reimporting_the_same_file_is_idempotent_by_content_hash():
    svc = _service([])
    kw = dict(
        account="Bank",
        period="2026-01",
        opening=Money.myr(0),
        closing=Money.myr(1000_00),
        raw=JAN_CSV,
        fmt="csv",
    )
    first = svc.import_statement(**kw)
    again = svc.import_statement(**kw)
    assert first.id == again.id
    assert (
        svc.statement_lines(account="Bank", period="2026-01")
        and len(svc.statement_lines(account="Bank", period="2026-01")) == 1
    )


def test_propose_is_read_only_and_finds_the_exact_match():
    svc = _service([_bank_posting()])
    svc.import_statement(
        account="Bank",
        period="2026-01",
        opening=Money.myr(0),
        closing=Money.myr(1000_00),
        raw=JAN_CSV,
        fmt="csv",
    )

    proposals = svc.propose_matches(account="Bank", period="2026-01")

    assert len(proposals) == 1
    assert proposals[0].ledger_posting_ref == 99
    # read-only: proposing again still yields the candidate (no state change)
    assert len(svc.propose_matches(account="Bank", period="2026-01")) == 1


def test_confirm_creates_match_and_rejects_double_matching():
    svc = _service([_bank_posting()])
    svc.import_statement(
        account="Bank",
        period="2026-01",
        opening=Money.myr(0),
        closing=Money.myr(1000_00),
        raw=JAN_CSV,
        fmt="csv",
    )
    p = svc.propose_matches(account="Bank", period="2026-01")[0]

    svc.confirm_match(p.statement_line_ref, p.ledger_posting_ref)

    # idempotent on identical resubmit
    svc.confirm_match(p.statement_line_ref, p.ledger_posting_ref)
    # the matched line is no longer proposed
    assert svc.propose_matches(account="Bank", period="2026-01") == []
    # the posting is already matched -> rejected against a different line
    with pytest.raises(ValueError, match="already matched"):
        svc.confirm_match(p.statement_line_ref + 1, p.ledger_posting_ref)

    assert svc.matched_posting_refs() == {99}
