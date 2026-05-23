"""MCP resource surface — parties:// and accounts://."""

from __future__ import annotations

import json

from _mcp_helpers import mcp_client, run
from books import create_app


def test_parties_resource_lists_all_registered_parties():
    app = create_app("sqlite://")
    app.party.register_party(name="Acme", role="customer")
    app.party.register_party(name="CloudCo", role="supplier")

    async def scenario():
        async with mcp_client(app) as client:
            result = await client.read_resource("parties://")
            # ReadResourceResult.contents is a list; the first content's
            # `.text` is the JSON-encoded payload from our handler.
            payload = json.loads(result.contents[0].text)
            assert [p["name"] for p in payload] == ["Acme", "CloudCo"]
            assert [p["role"] for p in payload] == ["customer", "supplier"]

    run(scenario())


def test_accounts_resource_lists_all_created_accounts():
    app = create_app("sqlite://")
    app.ledger.create_account(code="Bank", name="Bank", type="asset")
    app.ledger.create_account(code="5100", name="Office Supplies", type="expense")

    async def scenario():
        async with mcp_client(app) as client:
            result = await client.read_resource("accounts://")
            payload = json.loads(result.contents[0].text)
            codes = [a["code"] for a in payload]
            assert "Bank" in codes and "5100" in codes
            # Defaults from LedgerService._seed_default_roles do NOT create
            # accounts — only role mappings — so we don't expect AR, Revenue
            # etc. to be present unless explicitly created.

    run(scenario())
