"""Thickening increment 2 — soft-close carry-forward (ADR-0009).

The close↔clearance contract, the highest-subtlety rule in the domain.
Same spine, one new test, no rework:

- Soft close never blocks on uncleared bank postings — January locks
  even though its Bank posting is still uncleared.
- The period lock has teeth: a *new economic* entry dated into closed
  January is rejected (the command fails atomically, ADR-0011).
- Clearance-state mutation is exempt from the lock: a February statement
  line clears the January posting on a soft-closed January.
- Items age and escalate across the boundary: the January posting, a
  timing_difference within January, is a stale_exception by February.

See docs/adr/0009-close-clearance-contract.md and the plan.
"""

from datetime import date

import pytest

from books import create_app
from books.platform.money import Money


def test_soft_closed_january_carries_forward_and_clears_in_february():
    app = create_app(stale_after_days=30)

    # --- Given ----------------------------------------------------------
    acme = app.party.register_party(name="Acme", role="customer")
    app.ledger.create_account(code="Bank", name="Bank", type="asset")
    app.ledger.create_account(
        code="AR", name="Accounts Receivable", type="asset", control=True
    )
    app.ledger.create_account(code="Revenue", name="Revenue", type="income")

    inv = app.invoicing.issue_invoice(
        number=1,
        party_id=acme.id,
        amount=Money.myr(1000_00),
        issued_on=date(2026, 1, 10),
    )
    app.invoicing.mark_paid(invoice_id=inv.id, paid_on=date(2026, 1, 28))
    # Bank posting 2026-01-28, uncleared (no statement line yet).

    # --- When: soft close January --------------------------------------
    # ADR-0009: soft close never blocks on uncleared items.
    app.ledger.soft_close(period="2026-01")

    # The lock has teeth: a NEW economic entry dated into closed January
    # is rejected, and the command fails atomically (ADR-0011) — invoice
    # #2 must not persist.
    with pytest.raises(ValueError, match="2026-01"):
        app.invoicing.issue_invoice(
            number=2,
            party_id=acme.id,
            amount=Money.myr(500_00),
            issued_on=date(2026, 1, 15),
        )
    assert app.ledger.account_balance(code="Bank") == Money.myr(1000_00)

    # The uncleared January posting ages across the boundary: benign within
    # January, a stale exception once February's threshold applies.
    feb_before = app.reporting.reconciliation_report(account="Bank", period="2026-02")
    (carried,) = feb_before.reconciling_items
    assert carried.classification == "stale_exception"
    assert carried.age_days == 31  # 2026-02-28 minus 2026-01-28

    # --- Then: clear it from a February statement ----------------------
    # Clearance mutation is exempt from the period lock (orthogonal axes):
    # confirming a match against the soft-closed-January posting succeeds.
    app.bank_reconciliation.import_statement(
        account="Bank",
        period="2026-02",
        opening=Money.myr(0),
        closing=Money.myr(1000_00),
        raw="date,amount,description\n2026-02-03,1000.00,ACME TRANSFER\n",
        fmt="csv",
    )
    (line,) = app.bank_reconciliation.statement_lines(account="Bank", period="2026-02")
    (posting,) = app.ledger.postings_for(code="Bank")

    app.bank_reconciliation.confirm_match(
        statement_line_ref=line.ref,
        ledger_posting_ref=posting.ref,
    )

    report = app.reporting.reconciliation_report(account="Bank", period="2026-02")
    assert report.confirmed_cash == Money.myr(1000_00)
    assert report.reconciling_items == []
