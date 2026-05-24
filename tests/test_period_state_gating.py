"""append_entry gates by (period state, source_kind): a soft-closed month
admits a guarded guided-journal correction but rejects casual economic
entries; the year-end sweep into a soft-closed December therefore works."""

from __future__ import annotations

from datetime import date

import pytest

from books import create_app
from books.general_ledger import PeriodClosedError
from books.general_ledger.period_lifecycle import PeriodState
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


def test_guided_journal_correction_allowed_into_soft_month():
    app = create_app("sqlite://")
    _chart(app)
    acme = app.party.register_party(name="Acme", role="customer")
    inv = app.invoicing.issue_invoice(
        number=1,
        party_id=acme.id,
        amount=Money.myr(1000_00),
        issued_on=date(2026, 1, 10),
    )
    app.invoicing.mark_paid(invoice_id=inv.id, paid_on=date(2026, 1, 28))
    (bank_posting,) = app.ledger.postings_for(code="Bank")

    app.ledger.soft_close("2026-01")

    # A casual economic entry into soft January is rejected...
    with pytest.raises(ValueError, match="2026-01"):
        app.invoicing.issue_invoice(
            number=2,
            party_id=acme.id,
            amount=Money.myr(500_00),
            issued_on=date(2026, 1, 15),
        )
    # ...but a guarded guided-journal write-off into soft January is allowed.
    app.ledger.write_off(posting_ref=bank_posting.ref, on=date(2026, 1, 31))
    assert app.ledger.account_balance(code="Write-off") == Money.myr(1000_00)
    assert app.ledger.account_balance(code="Bank") == Money.myr(0)


def test_soft_closing_december_then_hard_close_succeeds():
    app = create_app("sqlite://")
    _chart(app)
    acme = app.party.register_party(name="Acme", role="customer")
    # Accrued revenue only — no bank posting, so nothing blocks the close.
    app.invoicing.issue_invoice(
        number=1,
        party_id=acme.id,
        amount=Money.myr(1500_00),
        issued_on=date(2026, 2, 1),
    )

    app.ledger.soft_close("2026-12")  # the LAST month, soft-closed first

    # The Dec-31 P&L sweep is a guided journal; soft December must admit it.
    app.ledger.hard_close(2026)
    assert app.ledger.account_balance(code="Owner's Equity") == Money.myr(-1500_00)


def test_append_into_soft_month_raises_typed_period_closed_error():
    app = create_app("sqlite://")
    _chart(app)
    acme = app.party.register_party(name="Acme", role="customer")
    app.ledger.soft_close("2026-01")

    with pytest.raises(PeriodClosedError) as exc:
        app.invoicing.issue_invoice(
            number=1,
            party_id=acme.id,
            amount=Money.myr(500_00),
            issued_on=date(2026, 1, 15),
        )
    assert exc.value.period == "2026-01"
    assert exc.value.state is PeriodState.SOFT
    assert exc.value.source_kind == "InvoiceIssued"
