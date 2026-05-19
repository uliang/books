"""Expense Management — contractor payment (the direct-bank rail).

The second buy-side rail per the context map. Pure cash basis (ADR-0003):
a contractor payment is a categorized direct-bank outflow to a Party in
the **contractor** role. No accrual, no payable — the expense is
recognized as the cash leaves the bank (CONTEXT: "the v1 meaning of
'salary'. No employment, no withholding.").

Posting at payment: Dr <category expense> / Cr Bank, with the contractor
Party on the expense leg as the analytical dimension. The Bank posting
flows through the existing reconciliation spine unchanged.
"""

from datetime import date

from books import create_app
from books.platform.money import Money


def test_contractor_payment_posts_cash_basis_and_reconciles():
    app = create_app()

    # --- Given ----------------------------------------------------------
    aisha = app.party.register_party(name="Aisha", role="contractor")
    app.ledger.create_account(code="Bank", name="Bank", type="asset")
    app.ledger.create_account(
        code="Contractor Fees", name="Contractor Fees", type="expense"
    )

    # --- When: contractor paid directly from the bank ------------------
    # Cash basis: expense is recognized as cash leaves.
    app.expense.pay_contractor(
        party_id=aisha.id,
        amount=Money.myr(1500_00),
        category_account="Contractor Fees",
        on=date(2026, 3, 1),
    )
    assert app.ledger.account_balance(code="Contractor Fees") == Money.myr(1500_00)
    assert app.ledger.account_balance(code="Bank") == Money.myr(-1500_00)

    # The party dimension rides the expense leg (analytical traceability,
    # consistent with invoicing's customer Party on AR).
    (expense_posting,) = app.ledger.postings_for(code="Contractor Fees")
    assert expense_posting.party_name == "Aisha"

    # --- Then: the Bank posting reconciles on the existing spine -------
    app.bank_reconciliation.import_statement(
        account="Bank",
        period="2026-03",
        opening=Money.myr(0),
        closing=Money.myr(-1500_00),
        raw="date,amount,description\n2026-03-01,-1500.00,AISHA PAYMENT\n",
        fmt="csv",
    )
    (line,) = app.bank_reconciliation.statement_lines(account="Bank", period="2026-03")
    (bank_posting,) = app.ledger.postings_for(code="Bank")

    proposals = app.bank_reconciliation.propose_matches(
        account="Bank", period="2026-03"
    )
    assert len(proposals) == 1

    app.bank_reconciliation.confirm_match(
        statement_line_ref=line.ref,
        ledger_posting_ref=bank_posting.ref,
    )
    report = app.reporting.reconciliation_report(account="Bank", period="2026-03")
    assert report.confirmed_cash == Money.myr(-1500_00)
    assert report.reconciling_items == []
