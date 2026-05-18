"""Thickening increment 1 — no-match + reconciling-item classification.

Same spine as test_tracer_thread_1, one new test. The core domain's real
job is *raising discrepancies for review*, not the happy path:

- An uncleared bank posting is a reconciling item, classified
  *timing_difference* (age within the owner-configured threshold) vs
  *stale_exception* (older — needs attention).
- A statement line with no posting (a bank fee) stays explicitly
  unexplained — a guided-journal candidate.

Threshold is owner-configured once at the composition root
(create_app(stale_after_days=...)). See
docs/PLAN-tracer-bullet-bank-reconciliation.md.
"""

from datetime import date

from books import create_app
from books.platform.money import Money


def test_uncleared_postings_are_classified_and_fee_line_is_unexplained():
    app = create_app(stale_after_days=30)

    # --- Given ----------------------------------------------------------
    acme = app.party.register_party(name="Acme", role="customer")

    app.ledger.create_account(code="Bank", name="Bank", type="asset")
    app.ledger.create_account(
        code="AR", name="Accounts Receivable", type="asset", control=True
    )
    app.ledger.create_account(code="Revenue", name="Revenue", type="income")

    # A recent payment: banked 3 days before the 2026-01 period end.
    recent = app.invoicing.issue_invoice(
        number=1,
        party_id=acme.id,
        amount=Money.myr(1000_00),
        issued_on=date(2026, 1, 10),
    )
    app.invoicing.mark_paid(invoice_id=recent.id, paid_on=date(2026, 1, 28))

    # A long-stale payment: banked 2025-10-05, well past the threshold.
    stale = app.invoicing.issue_invoice(
        number=2,
        party_id=acme.id,
        amount=Money.myr(1000_00),
        issued_on=date(2025, 9, 1),
    )
    app.invoicing.mark_paid(invoice_id=stale.id, paid_on=date(2025, 10, 5))

    assert app.ledger.account_balance(code="Bank") == Money.myr(2000_00)

    # --- When -----------------------------------------------------------
    # Statement carries only a bank fee — no ledger posting explains it,
    # and neither uncleared Bank posting appears on the statement.
    app.bank_reconciliation.import_statement(
        account="Bank",
        period="2026-01",
        opening=Money.myr(0),
        closing=Money.myr(-25_00),
        raw="date,amount,description\n2026-01-31,-25.00,BANK FEE\n",
        fmt="csv",
    )

    assert (
        app.bank_reconciliation.propose_matches(account="Bank", period="2026-01") == []
    )  # fee matches nothing; nothing gets confirmed

    # --- Then -----------------------------------------------------------
    report = app.reporting.reconciliation_report(account="Bank", period="2026-01")

    assert report.confirmed_cash == Money.myr(0)  # nothing cleared

    by_class = {ri.classification: ri for ri in report.reconciling_items}
    assert set(by_class) == {"timing_difference", "stale_exception"}

    timing = by_class["timing_difference"]
    assert timing.amount == Money.myr(1000_00)
    assert timing.age_days == 3  # 2026-01-31 minus 2026-01-28

    stale_item = by_class["stale_exception"]
    assert stale_item.amount == Money.myr(1000_00)
    assert stale_item.age_days == 118  # 2026-01-31 minus 2025-10-05

    # The fee line has no posting: explicitly unexplained.
    assert len(report.unexplained_lines) == 1
