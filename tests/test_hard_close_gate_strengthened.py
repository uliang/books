"""The amended hard-close gate (ADR-0009): ANY uncleared bank posting blocks,
not just stale ones. A recent (timing-difference) uncleared item now blocks
too; its classification survives only as triage."""

from __future__ import annotations

from datetime import date

import pytest

from books import create_app
from books.platform.money import Money


def test_recent_uncleared_posting_blocks_hard_close():
    app = create_app("sqlite://")  # stale_after_days defaults to 30
    acme = app.party.register_party(name="Acme", role="customer")
    app.ledger.create_account(
        code="AR", name="Accounts Receivable", type="asset", control=True
    )
    app.ledger.create_account(code="Revenue", name="Revenue", type="income")
    app.ledger.create_account(code="Bank", name="Bank", type="asset")

    # A RECENT uncleared receipt (Dec 20) — only 11 days old at year-end, so a
    # timing difference under the old rule, which would NOT have blocked.
    inv = app.invoicing.issue_invoice(
        number=1,
        party_id=acme.id,
        amount=Money.myr(1000_00),
        issued_on=date(2026, 12, 15),
    )
    app.invoicing.mark_paid(invoice_id=inv.id, paid_on=date(2026, 12, 20))

    with pytest.raises(ValueError, match="blocked"):
        app.ledger.hard_close(2026)

    (blocker,) = app.reporting.year_end_blockers(2026)
    assert blocker.classification == "timing_difference"  # triage label, still blocks
    assert blocker.age_days == 11
