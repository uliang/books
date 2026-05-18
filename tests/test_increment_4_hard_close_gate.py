"""Thickening increment 4 — annual hard-close gate (ADR-0009).

The final increment, same spine, one new test, no rework. Hard close:

- BLOCKS while any uncleared bank posting is a stale exception (the real
  control signal) — no silent stale item is frozen into an immutable
  fiscal year. A timing difference would be a legitimate year-end
  reconciling item and would NOT block (reuses increment-1 classification).
- is unblocked by adjudicating the item via the guided-journal path — here
  a write-off of a phantom bank posting (Dr Write-off / Cr Bank).
- once unblocked, posts the year-end closing entry netting P&L → Owner's
  Equity via the guided-journal path, after which the fiscal year is
  immutable (every month locked; new economic entries rejected).

The gate logic lives in the Ledger; the composition root only wires a
year_end_blockers callable (delegating to Reporting, the sanctioned
cross-context reader — GL never imports bank_reconciliation/reporting).

See docs/adr/0009-close-clearance-contract.md and the plan.
"""

from datetime import date

import pytest

from books import create_app
from books.platform.money import Money


def test_hard_close_blocks_on_stale_then_closes_via_guided_journal():
    app = create_app(stale_after_days=30)

    # --- Given ----------------------------------------------------------
    acme = app.party.register_party(name="Acme", role="customer")
    app.ledger.create_account(code="Bank", name="Bank", type="asset")
    app.ledger.create_account(
        code="AR", name="Accounts Receivable", type="asset", control=True
    )
    app.ledger.create_account(code="Revenue", name="Revenue", type="income")
    app.ledger.create_account(code="Write-off", name="Write-off", type="expense")
    app.ledger.create_account(
        code="Owner's Equity", name="Owner's Equity", type="equity"
    )

    # A phantom payment: marked paid, banked, but never appears on a
    # statement — an uncleared Bank posting that is stale by year-end.
    phantom = app.invoicing.issue_invoice(
        number=1,
        party_id=acme.id,
        amount=Money.myr(1000_00),
        issued_on=date(2026, 1, 10),
    )
    app.invoicing.mark_paid(invoice_id=phantom.id, paid_on=date(2026, 3, 1))

    # A second, unpaid invoice: real accrued revenue, no bank posting, so
    # it neither clears nor blocks — it just makes net P&L non-trivial.
    app.invoicing.issue_invoice(
        number=2,
        party_id=acme.id,
        amount=Money.myr(1500_00),
        issued_on=date(2026, 2, 1),
    )

    # --- Then: hard close is blocked -----------------------------------
    with pytest.raises(ValueError, match="blocked"):
        app.ledger.hard_close(2026)

    # --- When: resolve the phantom via the guided-journal path ---------
    (bank_posting,) = app.ledger.postings_for(code="Bank")
    app.ledger.write_off(posting_ref=bank_posting.ref, on=date(2026, 12, 31))

    # --- Then: hard close proceeds and the year becomes immutable ------
    app.ledger.hard_close(2026)

    # P&L accounts are swept to Owner's Equity (net profit:
    # Revenue 1,000 + 1,500 booked, Write-off 1,000 → equity credit 1,500).
    assert app.ledger.account_balance(code="Revenue") == Money.myr(0)
    assert app.ledger.account_balance(code="Write-off") == Money.myr(0)
    assert app.ledger.account_balance(code="Owner's Equity") == Money.myr(-1500_00)

    # The fiscal year is immutable: a new economic entry dated into 2026
    # is rejected (command fails atomically, ADR-0011).
    with pytest.raises(ValueError, match="closed"):
        app.invoicing.issue_invoice(
            number=3,
            party_id=acme.id,
            amount=Money.myr(200_00),
            issued_on=date(2026, 6, 1),
        )
