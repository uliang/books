"""Tracer bullet — thread 1, the executable definition of "bullet hit".

One MYR invoice: issued, paid, banked, statement imported, line matched,
posting cleared, tied out, reported. Crosses every non-generic context plus
Party-by-id. See docs/PLAN-tracer-bullet-bank-reconciliation.md.

Green ⇒ Invoicing→Ledger event translation, bank-posting representation,
clearance-state ownership, the match operation, cash invariants 3 & 4, and
the Reporting projection are all proven in one shot.
"""

from datetime import date

from books import create_app
from books.platform.money import Money


def test_myr_invoice_is_reconciled_and_ties_out():
    app = create_app()

    # --- Given ----------------------------------------------------------
    acme = app.party.register_party(name="Acme", role="customer")

    app.ledger.create_account(code="Bank", name="Bank", type="asset")
    app.ledger.create_account(
        code="AR", name="Accounts Receivable", type="asset", control=True
    )
    app.ledger.create_account(code="Revenue", name="Revenue", type="income")

    invoice = app.invoicing.issue_invoice(
        number=1,
        party_id=acme.id,
        amount=Money.myr(1000_00),
        issued_on=date(2026, 1, 10),
    )
    # InvoiceIssued -> Ledger posts Dr AR 1,000 / Cr Revenue 1,000,
    # AR line carries dimension Party=Acme.
    ar = app.ledger.account_balance(code="AR")
    assert ar == Money.myr(1000_00)

    app.invoicing.mark_paid(invoice_id=invoice.id, paid_on=date(2026, 1, 15))
    # PaymentRecorded -> Ledger posts Dr Bank 1,000 / Cr AR 1,000.
    # The Bank posting is uncleared: no Match references it yet.
    assert app.ledger.account_balance(code="AR") == Money.myr(0)
    assert app.ledger.account_balance(code="Bank") == Money.myr(1000_00)

    # --- When -----------------------------------------------------------
    statement = app.bank_reconciliation.import_statement(
        account="Bank",
        period="2026-01",
        opening=Money.myr(0),
        closing=Money.myr(1000_00),
        raw="date,amount,description\n2026-01-15,1000.00,ACME TRANSFER\n",
        fmt="csv",
    )
    assert statement.foots is True

    proposals = app.bank_reconciliation.propose_matches(
        account="Bank", period="2026-01"
    )
    assert len(proposals) == 1
    proposal = proposals[0]

    app.bank_reconciliation.confirm_match(
        statement_line_ref=proposal.statement_line_ref,
        ledger_posting_ref=proposal.ledger_posting_ref,
    )

    # --- Then -----------------------------------------------------------
    report = app.reporting.reconciliation_report(account="Bank", period="2026-01")

    assert report.statement_closing == Money.myr(1000_00)
    assert report.ledger_bank_balance == Money.myr(1000_00)
    assert report.confirmed_cash == Money.myr(1000_00)  # invariant 3
    assert report.difference == Money.myr(0)  # invariant 4
    assert report.reconciling_items == []
    assert report.unexplained_lines == []
