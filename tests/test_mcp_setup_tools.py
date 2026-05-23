"""MCP tool surface — setup + health smoke."""

from __future__ import annotations

import json

from _mcp_helpers import mcp_client, run
from books import create_app


def test_health_tool_returns_ok():
    async def scenario():
        async with mcp_client() as client:
            result = await client.call_tool("health", {})
            # FastMCP serializes a dict return as a TextContent JSON payload.
            assert result.isError is False
            assert result.content
            text = result.content[0].text  # TextContent
            assert "ok" in text

    run(scenario())


def test_register_party_creates_a_party_visible_via_the_app():
    app = create_app("sqlite://")

    async def scenario():
        async with mcp_client(app) as client:
            result = await client.call_tool(
                "register_party", {"name": "CloudCo", "role": "supplier"}
            )
            assert result.isError is False
            payload = json.loads(result.content[0].text)
            assert payload["name"] == "CloudCo"
            assert payload["role"] == "supplier"
            assert isinstance(payload["id"], int) and payload["id"] >= 1

    run(scenario())

    # The party is visible on the App the test injected.
    parties = app.party.list()
    assert [p.name for p in parties] == ["CloudCo"]


def test_create_account_creates_an_account_visible_via_the_app():
    app = create_app("sqlite://")

    async def scenario():
        async with mcp_client(app) as client:
            result = await client.call_tool(
                "create_account",
                {"code": "5100", "name": "Office Supplies", "type": "expense"},
            )
            assert result.isError is False

    run(scenario())

    codes = [a.code for a in app.ledger.accounts()]
    assert "5100" in codes
