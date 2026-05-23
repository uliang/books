"""Reconciliation is forbidden on a hard-closed period (ADR-0009 amended): a
late statement cannot retroactively clear a posting in a closed year."""

from __future__ import annotations

from datetime import date

import pytest

from books import create_app
from books.bank_reconciliation.service import BankReconciliationService
from books.platform.db import Database
from books.platform.money import Money


def _chart(app):
    app.ledger.create_account(
        code="AR", name="Accounts Receivable", type="asset", control=True
    )
    app.ledger.create_account(code="Revenue", name="Revenue", type="income")
    app.ledger.create_account(code="Bank", name="Bank", type="asset")
    app.ledger.create_account(code="Write-off", name="Write-off", type="expense")
    app.ledger.create_account(
        code="Owner's Equity", name="Owner's Equity", type="equity"
    )


def test_confirm_match_guard_rejects_unreconcilable_posting():
    # Unit-level: the injected reader says no -> confirm_match raises.
    svc = BankReconciliationService(
        Database(),
        bank_postings=lambda account: [],
        posting_is_reconcilable=lambda _ref: False,
    )
    with pytest.raises(ValueError, match="hard-closed"):
        svc.confirm_match(statement_line_ref=1, ledger_posting_ref=1)


def test_posting_is_reconcilable_flips_with_period_state():
    app = create_app("sqlite://")
    _chart(app)
    acme = app.party.register_party(name="Acme", role="customer")
    inv = app.invoicing.issue_invoice(
        number=1,
        party_id=acme.id,
        amount=Money.myr(1000_00),
        issued_on=date(2026, 1, 10),
    )
    app.invoicing.mark_paid(invoice_id=inv.id, paid_on=date(2026, 3, 1))
    (bank_posting,) = app.ledger.postings_for(code="Bank")

    assert app.ledger.posting_is_reconcilable(bank_posting.ref) is True  # OPEN

    # Resolve the phantom so the year can hard-close, then close it.
    app.ledger.write_off(posting_ref=bank_posting.ref, on=date(2026, 12, 31))
    app.ledger.hard_close(2026)

    assert app.ledger.posting_is_reconcilable(bank_posting.ref) is False  # HARD


def test_confirm_match_rejected_end_to_end_after_hard_close():
    app = create_app("sqlite://")
    _chart(app)
    acme = app.party.register_party(name="Acme", role="customer")
    inv = app.invoicing.issue_invoice(
        number=1,
        party_id=acme.id,
        amount=Money.myr(1000_00),
        issued_on=date(2026, 1, 10),
    )
    app.invoicing.mark_paid(invoice_id=inv.id, paid_on=date(2026, 3, 1))
    (bank_posting,) = app.ledger.postings_for(code="Bank")
    app.ledger.write_off(posting_ref=bank_posting.ref, on=date(2026, 12, 31))
    app.ledger.hard_close(2026)

    # A late statement shows the March transaction; matching it post-close fails.
    app.bank_reconciliation.import_statement(
        account="Bank",
        period="2026-03",
        opening=Money.myr(0),
        closing=Money.myr(1000_00),
        raw="date,amount,description\n2026-03-01,1000.00,ACME TRANSFER\n",
        fmt="csv",
    )
    (line,) = app.bank_reconciliation.statement_lines(account="Bank", period="2026-03")
    with pytest.raises(ValueError, match="hard-closed"):
        app.bank_reconciliation.confirm_match(
            statement_line_ref=line.ref, ledger_posting_ref=bank_posting.ref
        )
