"""Close-state transitions: hard_close upgrades a soft month to hard (fixing
the January-stays-soft bug); soft_close rejects a hard month; hard_close
rejects a re-run (no double P&L sweep)."""

from __future__ import annotations

from datetime import date

import pytest

from books import create_app
from books.platform.money import Money


def _chart(app):
    app.ledger.create_account(
        code="AR", name="Accounts Receivable", type="asset", control=True
    )
    app.ledger.create_account(code="Revenue", name="Revenue", type="income")
    app.ledger.create_account(
        code="Owner's Equity", name="Owner's Equity", type="equity"
    )


def test_hard_close_upgrades_soft_month_to_hard():
    app = create_app("sqlite://")
    _chart(app)
    acme = app.party.register_party(name="Acme", role="customer")
    app.invoicing.issue_invoice(
        number=1,
        party_id=acme.id,
        amount=Money.myr(1500_00),
        issued_on=date(2026, 2, 1),
    )
    app.ledger.soft_close("2026-01")

    app.ledger.hard_close(2026)

    kinds = {lk.period: lk.kind for lk in app.ledger.locked_periods()}
    assert len(kinds) == 12
    assert all(kind == "hard" for kind in kinds.values())  # January upgraded


def test_soft_close_on_hard_closed_period_is_rejected():
    app = create_app("sqlite://")
    _chart(app)
    app.ledger.hard_close(2026)  # clean books, no blockers
    with pytest.raises(ValueError, match="hard-closed"):
        app.ledger.soft_close("2026-06")


def test_hard_close_twice_is_rejected():
    app = create_app("sqlite://")
    _chart(app)
    acme = app.party.register_party(name="Acme", role="customer")
    app.invoicing.issue_invoice(
        number=1,
        party_id=acme.id,
        amount=Money.myr(1500_00),
        issued_on=date(2026, 2, 1),
    )
    app.ledger.hard_close(2026)
    with pytest.raises(ValueError, match="already"):
        app.ledger.hard_close(2026)
    # P&L was swept exactly once.
    assert app.ledger.account_balance(code="Owner's Equity") == Money.myr(-1500_00)
