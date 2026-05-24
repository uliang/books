"""A command and its synchronous handler share one transaction: a handler
rejection rolls back the whole command, leaving NO ghost rows in any context
(the bug found in the PR #4 live trial, 2026-05-24)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from books import create_app
from books.general_ledger import PeriodClosedError
from books.platform.money import Currency, Money


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


def test_issue_into_closed_period_rolls_back_both_contexts():
    app = create_app("sqlite://")
    _chart(app)
    acme = app.party.register_party(name="Acme", role="customer")
    app.ledger.soft_close("2026-01")

    with pytest.raises(PeriodClosedError):
        app.invoicing.issue_invoice(
            number=1,
            party_id=acme.id,
            amount=Money.myr(1000_00),
            issued_on=date(2026, 1, 15),
        )

    # invoicing context: no ghost invoice
    assert app.invoicing.list_invoices() == []
    # general-ledger context: no postings leaked
    assert app.ledger.postings_for(code="AR") == []
    assert app.ledger.postings_for(code="Revenue") == []


def test_mark_paid_into_closed_period_rolls_back_both_contexts():
    app = create_app("sqlite://")
    _chart(app)
    acme = app.party.register_party(name="Acme", role="customer")
    inv = app.invoicing.issue_invoice(
        number=1,
        party_id=acme.id,
        amount=Money.myr(1000_00),
        issued_on=date(2026, 2, 10),  # February: open
    )
    app.ledger.soft_close("2026-03")

    with pytest.raises(PeriodClosedError):
        app.invoicing.mark_paid(invoice_id=inv.id, paid_on=date(2026, 3, 5))

    # No Bank posting leaked, and the invoice status stayed "issued".
    assert app.ledger.postings_for(code="Bank") == []
    (row,) = [i for i in app.invoicing.list_invoices() if i.id == inv.id]
    assert row.status == "issued"


def test_adjudicate_into_closed_period_rolls_back_both_contexts():
    # Hard-close is the only state that rejects GuidedJournal (the source_kind
    # used by the FX adjudication handler); soft-close still admits it per
    # ADR-0006.  We get a hard-closed year by writing off the bank posting that
    # would otherwise block hard_close.
    app = create_app("sqlite://")
    _chart(app)
    app.ledger.create_account(code="FX Loss", name="FX Loss", type="expense")
    acme = app.party.register_party(name="Acme", role="customer")
    inv = app.invoicing.issue_invoice(
        number=1,
        party_id=acme.id,
        amount=Money(1000_00, Currency("SGD")),
        issued_on=date(2025, 2, 1),
        rate=Decimal("3.0"),
    )
    app.invoicing.mark_paid(
        invoice_id=inv.id, paid_on=date(2025, 2, 20), banked=Money.myr(2900_00)
    )
    # Clear the bank posting so hard_close(2025) can proceed.
    (bank_posting,) = app.ledger.postings_for(code="Bank")
    app.ledger.write_off(posting_ref=bank_posting.ref, on=date(2025, 12, 31))
    app.ledger.hard_close(2025)

    with pytest.raises(PeriodClosedError):
        app.invoicing.adjudicate_settlement(
            invoice_id=inv.id, outcome="settled_in_full", on=date(2025, 6, 1)
        )

    assert app.ledger.postings_for(code="FX Loss") == []
    (row,) = [i for i in app.invoicing.list_invoices() if i.id == inv.id]
    assert row.status == "awaiting_adjudication"


def test_owner_paid_expense_into_closed_period_rolls_back_both_contexts():
    app = create_app("sqlite://")
    _chart(app)
    app.ledger.create_account(
        code="Due to Owner", name="Due to Owner", type="liability"
    )
    app.ledger.create_account(code="Office", name="Office", type="expense")
    supplier = app.party.register_party(name="Stationers", role="supplier")
    app.ledger.soft_close("2026-01")

    with pytest.raises(PeriodClosedError):
        app.expense.record_owner_paid_expense(
            party_id=supplier.id,
            amount=Money.myr(120_00),
            category_account="Office",
            on=date(2026, 1, 9),
        )

    assert app.ledger.postings_for(code="Office") == []
    assert app.ledger.postings_for(code="Due to Owner") == []
