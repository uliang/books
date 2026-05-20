"""MCP error translation — domain errors surface as isError: true tool
results, not as server crashes. FastMCP's tool wrapper catches the
exception and returns an error content payload.
"""

from __future__ import annotations

from _mcp_helpers import mcp_client, run
from books import create_app


def test_unknown_party_id_surfaces_as_tool_error():
    app = create_app("sqlite://")
    app.ledger.create_account(code="Software", name="Software", type="expense")
    app.ledger.create_account(
        code="Due to Owner", name="Due to Owner", type="liability"
    )

    async def scenario():
        async with mcp_client(app) as client:
            result = await client.call_tool(
                "record_owner_paid_expense",
                {
                    "party_id": 999,  # nonexistent
                    "amount_minor": 100_00,
                    "currency": "MYR",
                    "category_account": "Software",
                    "on": "2026-01-05",
                },
            )
            assert result.isError is True
            # The LookupError message ("no party 999") should appear in the
            # error content; we check substring rather than exact match so
            # the test isn't brittle to FastMCP wrapping.
            text = result.content[0].text
            assert "999" in text

    run(scenario())


def test_closed_period_surfaces_as_tool_error():
    app = create_app("sqlite://")
    supplier = app.party.register_party(name="CloudCo", role="supplier")
    app.ledger.create_account(code="Software", name="Software", type="expense")
    app.ledger.create_account(
        code="Due to Owner", name="Due to Owner", type="liability"
    )
    # Soft-close January then try to post into it.
    app.ledger.soft_close("2026-01")

    async def scenario():
        async with mcp_client(app) as client:
            result = await client.call_tool(
                "record_owner_paid_expense",
                {
                    "party_id": supplier.id,
                    "amount_minor": 100_00,
                    "currency": "MYR",
                    "category_account": "Software",
                    "on": "2026-01-05",
                },
            )
            assert result.isError is True
            text = result.content[0].text
            assert "2026-01" in text or "closed" in text.lower()

    run(scenario())
