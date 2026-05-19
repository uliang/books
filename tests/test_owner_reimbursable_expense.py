"""Expense Management tracer slice — owner-reimbursable expenses.

Beyond-plan bounded context (CONTEXT.md, ADR-0001/0003/0006). The owner
pays business expenses personally (on a personal / mixed-use card); the
business never sees the card statement and never pays the card issuer. The
point is to compute how much the business owes the owner.

Per the amended ADR-0003 the single accrued payable is **Due to Owner**:

- Each individual business expense is recognized at the charge:
  Dr <category> / Cr Due to Owner. A supplier Party is mandatory
  (provenance, mirrors invoicing's customer). Personal spend never enters.
- The business reimburses the owner — any amount, partial allowed —
  Dr Due to Owner / Cr Bank; that Bank posting reconciles on the existing
  spine (import → propose → confirm → tie-out) unchanged.

Same spine, one new context.
"""

from datetime import date

from books import create_app
from books.platform.money import Money


def test_owner_paid_expense_accrues_due_to_owner_then_reimbursement_reconciles():
    app = create_app()

    # --- Given ----------------------------------------------------------
    cloudco = app.party.register_party(name="CloudCo", role="supplier")
    app.ledger.create_account(code="Bank", name="Bank", type="asset")
    app.ledger.create_account(
        code="Due to Owner", name="Due to Owner", type="liability"
    )
    app.ledger.create_account(
        code="Software", name="Software Subscriptions", type="expense"
    )

    # --- When: owner pays a business expense personally ----------------
    # Recognized at the charge; the business owes the owner.
    app.expense.record_owner_paid_expense(
        party_id=cloudco.id,
        amount=Money.myr(300_00),
        category_account="Software",
        on=date(2026, 1, 5),
    )
    assert app.ledger.account_balance(code="Software") == Money.myr(300_00)
    assert app.ledger.account_balance(code="Due to Owner") == Money.myr(-300_00)
    assert app.ledger.account_balance(code="Bank") == Money.myr(0)

    # --- When: the business reimburses the owner from the bank ---------
    app.expense.reimburse_owner(amount=Money.myr(300_00), on=date(2026, 2, 1))
    assert app.ledger.account_balance(code="Due to Owner") == Money.myr(0)
    assert app.ledger.account_balance(code="Bank") == Money.myr(-300_00)

    # --- Then: the reimbursement Bank posting reconciles on the spine --
    app.bank_reconciliation.import_statement(
        account="Bank",
        period="2026-02",
        opening=Money.myr(0),
        closing=Money.myr(-300_00),
        raw="date,amount,description\n2026-02-01,-300.00,REIMBURSE OWNER\n",
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


def test_due_to_owner_is_fungible_partial_reimbursement_draws_the_balance():
    """The other resolved behaviour (ADR-0003 amendment): Due to Owner is a
    single fungible liability. Charges from different suppliers accrue into
    it; a partial reimbursement of any amount draws the balance down — it is
    not linked to specific charges."""
    app = create_app()

    cloudco = app.party.register_party(name="CloudCo", role="supplier")
    grab = app.party.register_party(name="Grab", role="supplier")
    app.ledger.create_account(code="Bank", name="Bank", type="asset")
    app.ledger.create_account(
        code="Due to Owner", name="Due to Owner", type="liability"
    )
    app.ledger.create_account(code="Software", name="Software", type="expense")
    app.ledger.create_account(code="Travel", name="Travel", type="expense")

    app.expense.record_owner_paid_expense(
        party_id=cloudco.id,
        amount=Money.myr(600_00),
        category_account="Software",
        on=date(2026, 1, 5),
    )
    app.expense.record_owner_paid_expense(
        party_id=grab.id,
        amount=Money.myr(300_00),
        category_account="Travel",
        on=date(2026, 1, 9),
    )
    assert app.ledger.account_balance(code="Due to Owner") == Money.myr(-900_00)

    # Partial reimbursement, not tied to either charge.
    app.expense.reimburse_owner(amount=Money.myr(500_00), on=date(2026, 1, 31))
    assert app.ledger.account_balance(code="Due to Owner") == Money.myr(-400_00)
    assert app.ledger.account_balance(code="Bank") == Money.myr(-500_00)
