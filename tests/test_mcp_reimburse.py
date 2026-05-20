"""MCP reimburse_owner tool — closes the owner-paid expense rail.

Covers the full lifecycle: owner pays a business expense personally,
Due to Owner accrues, then the business reimburses the owner from
the bank and Due to Owner clears.
"""

from __future__ import annotations

from _mcp_helpers import mcp_client, run
from books import create_app
from books.platform.money import Money


def test_full_owner_paid_then_reimburse_loop_clears_due_to_owner():
    app = create_app("sqlite://")
    supplier = app.party.register_party(name="CloudCo", role="supplier")
    app.ledger.create_account(code="Bank", name="Bank", type="asset")
    app.ledger.create_account(
        code="Due to Owner", name="Due to Owner", type="liability"
    )
    app.ledger.create_account(code="Software", name="Software", type="expense")

    async def scenario():
        async with mcp_client(app) as client:
            # 1. Owner pays
            r1 = await client.call_tool(
                "record_owner_paid_expense",
                {
                    "party_id": supplier.id,
                    "amount_minor": 300_00,
                    "currency": "MYR",
                    "category_account": "Software",
                    "on": "2026-01-05",
                },
            )
            assert r1.isError is False

            # 2. Business reimburses
            r2 = await client.call_tool(
                "reimburse_owner",
                {
                    "amount_minor": 300_00,
                    "currency": "MYR",
                    "on": "2026-02-01",
                },
            )
            assert r2.isError is False

    run(scenario())

    # Due to Owner net to zero; Bank now reflects the outflow.
    assert app.ledger.account_balance(code="Due to Owner") == Money.myr(0)
    assert app.ledger.account_balance(code="Bank") == Money.myr(-300_00)
