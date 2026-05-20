"""MCP expense tools — owner-paid and contractor rails."""

from __future__ import annotations

from _mcp_helpers import mcp_client, run
from books import create_app


def _seed(app):
    """Common setup: a supplier party, the Due-to-Owner / Bank / category
    accounts. Returns the supplier's id."""
    supplier = app.party.register_party(name="CloudCo", role="supplier")
    app.ledger.create_account(code="Bank", name="Bank", type="asset")
    app.ledger.create_account(
        code="Due to Owner", name="Due to Owner", type="liability"
    )
    app.ledger.create_account(
        code="Software", name="Software Subscriptions", type="expense"
    )
    return supplier.id


def test_record_owner_paid_expense_posts_dr_category_cr_due_to_owner():
    from books.platform.money import Money

    app = create_app("sqlite://")
    supplier_id = _seed(app)

    async def scenario():
        async with mcp_client(app) as client:
            result = await client.call_tool(
                "record_owner_paid_expense",
                {
                    "party_id": supplier_id,
                    "amount_minor": 300_00,
                    "currency": "MYR",
                    "category_account": "Software",
                    "on": "2026-01-05",
                },
            )
            assert result.isError is False

    run(scenario())

    assert app.ledger.account_balance(code="Software") == Money.myr(300_00)
    assert app.ledger.account_balance(code="Due to Owner") == Money.myr(-300_00)
    # The expense leg carries the supplier Party as the ADR-0007 dimension.
    (posting,) = app.ledger.postings_for(code="Software")
    assert posting.party_name == "CloudCo"


def test_pay_contractor_posts_dr_category_cr_bank():
    from books.platform.money import Money

    app = create_app("sqlite://")
    contractor = app.party.register_party(name="Freelance Dev", role="supplier")
    app.ledger.create_account(code="Bank", name="Bank", type="asset")
    app.ledger.create_account(code="Contracting", name="Contracting", type="expense")

    async def scenario():
        async with mcp_client(app) as client:
            result = await client.call_tool(
                "pay_contractor",
                {
                    "party_id": contractor.id,
                    "amount_minor": 1500_00,
                    "currency": "MYR",
                    "category_account": "Contracting",
                    "on": "2026-01-12",
                },
            )
            assert result.isError is False

    run(scenario())

    assert app.ledger.account_balance(code="Contracting") == Money.myr(1500_00)
    assert app.ledger.account_balance(code="Bank") == Money.myr(-1500_00)
    (posting,) = app.ledger.postings_for(code="Contracting")
    assert posting.party_name == "Freelance Dev"
