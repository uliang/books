"""MCP postings:// resource — agent verifies its write landed."""

from __future__ import annotations

import json
from datetime import date

from _mcp_helpers import mcp_client, run
from books import create_app
from books.platform.money import Money


def test_postings_resource_returns_postings_with_party_dimension():
    app = create_app("sqlite://")
    supplier = app.party.register_party(name="CloudCo", role="supplier")
    app.ledger.create_account(code="Bank", name="Bank", type="asset")
    app.ledger.create_account(
        code="Due to Owner", name="Due to Owner", type="liability"
    )
    app.ledger.create_account(code="Software", name="Software", type="expense")

    app.expense.record_owner_paid_expense(
        party_id=supplier.id,
        amount=Money.myr(300_00),
        category_account="Software",
        on=date(2026, 1, 5),
    )

    async def scenario():
        async with mcp_client(app) as client:
            result = await client.read_resource("postings://Software")
            payload = json.loads(result.contents[0].text)
            assert len(payload) == 1
            (p,) = payload
            assert p["account_code"] == "Software"
            assert p["amount_minor"] == 300_00
            assert p["currency"] == "MYR"
            assert p["date"] == "2026-01-05"
            assert p["party_name"] == "CloudCo"
            # dimensions present, typed
            assert "party" in p["dimensions"]
            assert p["dimensions"]["party"]["name"] == "CloudCo"

    run(scenario())


def test_postings_resource_decodes_percent_encoded_account_code():
    """A code containing a space (e.g. the default "Due to Owner" role —
    the credit leg of every owner-paid expense) must be addressable.
    MCP URIs reject a raw space, so a client sends it percent-encoded;
    the resource must URL-decode the path param before looking it up."""
    app = create_app("sqlite://")
    supplier = app.party.register_party(name="CloudCo", role="supplier")
    app.expense.record_owner_paid_expense(
        party_id=supplier.id,
        amount=Money.myr(300_00),
        category_account="Software",
        on=date(2026, 1, 5),
    )

    async def scenario():
        async with mcp_client(app) as client:
            result = await client.read_resource("postings://Due%20to%20Owner")
            payload = json.loads(result.contents[0].text)
            assert len(payload) == 1
            (p,) = payload
            assert p["account_code"] == "Due to Owner"
            assert p["amount_minor"] == -300_00  # the credit leg

    run(scenario())
