"""MCP tracer — the agent's expense-submission spine, end-to-end.

The MCP-side parallel of tests/test_web_tracer.py (which is the
web-side parallel of tests/test_tracer_thread_1.py). Drives the
slice exclusively through the MCP adapter — no direct App calls
between the setup and the final assertions, so the test exercises
the actual MCP surface the agent will use.
"""

from __future__ import annotations

import json

from _mcp_helpers import mcp_client, run
from books import create_app
from books.platform.money import Money


def test_agent_submits_owner_paid_expense_end_to_end_via_mcp():
    app = create_app("sqlite://")
    # Re-point the due_to_owner role from the default "Due to Owner" code
    # (which has spaces — awkward in URI templates) to "2100", so the
    # expense handler posts to an account whose code is URI-safe. This is
    # not part of the agent's flow; it's test setup. Production callers
    # can keep the default code or override via assign_role at install.
    app.ledger.assign_role("due_to_owner", "2100")

    async def scenario():
        async with mcp_client(app) as client:
            # 1. Agent inspects parties://; finds it empty.
            parties = json.loads(
                (await client.read_resource("parties://")).contents[0].text
            )
            assert parties == []

            # 2. Agent registers the supplier.
            supplier = json.loads(
                (
                    await client.call_tool(
                        "register_party",
                        {"name": "Stationery Co", "role": "supplier"},
                    )
                )
                .content[0]
                .text
            )
            supplier_id = supplier["id"]

            # 3. Agent inspects accounts://; the chart is empty (defaults
            #    are role mappings, not account rows).
            accounts = json.loads(
                (await client.read_resource("accounts://")).contents[0].text
            )
            assert accounts == []

            # 4. Agent creates the two GL accounts the rail needs.
            #    We use numeric codes (no spaces) so postings:// reads later
            #    don't have to URL-encode path segments. The role mapping
            #    is re-pointed from the default "Due to Owner" code to
            #    "2100" so the expense handler posts to the right account.
            await client.call_tool(
                "create_account",
                {
                    "code": "2100",
                    "name": "Due to Owner",
                    "type": "liability",
                },
            )
            await client.call_tool(
                "create_account",
                {
                    "code": "5100",
                    "name": "Office Supplies",
                    "type": "expense",
                },
            )

            # 5. Agent submits the expense it parsed from the invoice image.
            result = await client.call_tool(
                "record_owner_paid_expense",
                {
                    "party_id": supplier_id,
                    "amount_minor": 12345,  # MYR 123.45
                    "currency": "MYR",
                    "category_account": "5100",
                    "on": "2026-01-15",
                },
            )
            assert result.isError is False

            # 6. Agent reads postings://5100 to confirm provenance.
            expense_postings = json.loads(
                (await client.read_resource("postings://5100")).contents[0].text
            )
            assert len(expense_postings) == 1
            (p,) = expense_postings
            assert p["amount_minor"] == 12345
            assert p["currency"] == "MYR"
            assert p["date"] == "2026-01-15"
            assert p["party_name"] == "Stationery Co"
            assert p["dimensions"]["party"]["id"] == str(supplier_id)

            # 7. Agent reads postings://2100 to confirm the other leg.
            liability_postings = json.loads(
                (await client.read_resource("postings://2100")).contents[0].text
            )
            assert len(liability_postings) == 1
            assert liability_postings[0]["amount_minor"] == -12345

    run(scenario())

    # Cross-check the books directly: balances reflect the expense rail.
    assert app.ledger.account_balance(code="5100") == Money.myr(12345)
    assert app.ledger.account_balance(code="2100") == Money.myr(-12345)
