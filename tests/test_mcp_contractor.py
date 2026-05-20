"""MCP contractor rail acceptance — parallels tests/test_contractor_payment.py.

Agent registers a contractor party, creates a category, calls pay_contractor;
then reads postings:// to verify both legs landed with provenance.
"""

from __future__ import annotations

import json

from _mcp_helpers import mcp_client, run
from books import create_app
from books.platform.money import Money


def test_agent_pays_contractor_end_to_end_via_mcp():
    app = create_app("sqlite://")
    # We pre-create the Bank account because LedgerService only seeds
    # role->code mappings (not the Chart entries themselves).
    app.ledger.create_account(code="Bank", name="Bank", type="asset")

    async def scenario():
        async with mcp_client(app) as client:
            # Agent registers the contractor.
            party_result = await client.call_tool(
                "register_party",
                {"name": "Freelance Dev", "role": "supplier"},
            )
            assert party_result.isError is False
            party = json.loads(party_result.content[0].text)

            # Agent creates the category (would normally check accounts://
            # first; for the test we assert it ends up listed afterwards).
            await client.call_tool(
                "create_account",
                {"code": "Contracting", "name": "Contracting", "type": "expense"},
            )

            # Verify discoverability via the resource.
            accounts = json.loads(
                (await client.read_resource("accounts://")).contents[0].text
            )
            assert any(a["code"] == "Contracting" for a in accounts)

            # Submit the contractor payment.
            await client.call_tool(
                "pay_contractor",
                {
                    "party_id": party["id"],
                    "amount_minor": 1500_00,
                    "currency": "MYR",
                    "category_account": "Contracting",
                    "on": "2026-01-12",
                },
            )

            # Agent confirms its write by reading the expense leg.
            postings = json.loads(
                (await client.read_resource("postings://Contracting")).contents[0].text
            )
            assert len(postings) == 1
            (p,) = postings
            assert p["amount_minor"] == 1500_00
            assert p["party_name"] == "Freelance Dev"

    run(scenario())

    # Cash basis (ADR-0003): bank moves at once; no payable.
    assert app.ledger.account_balance(code="Contracting") == Money.myr(1500_00)
    assert app.ledger.account_balance(code="Bank") == Money.myr(-1500_00)
