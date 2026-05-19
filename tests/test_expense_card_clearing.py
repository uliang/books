"""Expense Management tracer slice — card clearing is the only payable.

Beyond-plan bounded context (CONTEXT.md, ADR-0001/0003/0006). Buy-side
outflow capture on the card rail, event-driven into the Ledger:

- A card charge captured at swipe accrues into the **card clearing**
  account — the single liability holding charges between swipe and the
  monthly settlement (the card issuer, not any supplier, is the creditor;
  this is NOT Accounts Payable).
- Monthly settlement pays the clearing account down from the bank,
  producing a Bank posting that then flows through the *existing*
  reconciliation spine (import → propose → confirm → tie-out) unchanged.

Same spine, one new context, one acceptance test.
"""

from datetime import date

from books import create_app
from books.platform.money import Money


def test_card_charge_accrues_to_clearing_then_settlement_reconciles():
    app = create_app()

    # --- Given ----------------------------------------------------------
    supplier = app.party.register_party(name="CloudCo", role="supplier")
    app.ledger.create_account(code="Bank", name="Bank", type="asset")
    app.ledger.create_account(
        code="Card Clearing", name="Card Clearing", type="liability"
    )
    app.ledger.create_account(
        code="Software", name="Software Subscriptions", type="expense"
    )

    # --- When: card charge captured at swipe ---------------------------
    # Accrues the expense; the card clearing account is the only payable.
    app.expense.capture_card_charge(
        party_id=supplier.id,
        amount=Money.myr(300_00),
        category_account="Software",
        on=date(2026, 1, 5),
    )
    assert app.ledger.account_balance(code="Software") == Money.myr(300_00)
    assert app.ledger.account_balance(code="Card Clearing") == Money.myr(-300_00)
    assert app.ledger.account_balance(code="Bank") == Money.myr(0)

    # --- When: monthly card statement settled from the bank ------------
    app.expense.settle_card_statement(amount=Money.myr(300_00), on=date(2026, 2, 1))
    assert app.ledger.account_balance(code="Card Clearing") == Money.myr(0)
    assert app.ledger.account_balance(code="Bank") == Money.myr(-300_00)

    # --- Then: the settlement Bank posting reconciles on the old spine -
    app.bank_reconciliation.import_statement(
        account="Bank",
        period="2026-02",
        opening=Money.myr(0),
        closing=Money.myr(-300_00),
        raw="date,amount,description\n2026-02-01,-300.00,CARD AUTOPAY\n",
        fmt="csv",
    )
    (line,) = app.bank_reconciliation.statement_lines(account="Bank", period="2026-02")
    (posting,) = app.ledger.postings_for(code="Bank")

    proposals = app.bank_reconciliation.propose_matches(
        account="Bank", period="2026-02"
    )
    assert len(proposals) == 1

    app.bank_reconciliation.confirm_match(
        statement_line_ref=line.ref,
        ledger_posting_ref=posting.ref,
    )
    report = app.reporting.reconciliation_report(account="Bank", period="2026-02")
    assert report.confirmed_cash == Money.myr(-300_00)
    assert report.reconciling_items == []
