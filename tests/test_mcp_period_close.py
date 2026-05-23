"""MCP period-close tracer (ADR-0008 / ADR-0009), end-to-end through the
in-memory client. Mirrors test_increment_4_hard_close_gate.py via the MCP
adapter: soft close, write-off, and the two-tier hard-close gate.
"""

from __future__ import annotations

import json

from _mcp_helpers import mcp_client, run
from books import create_app


def test_closings_resource_lists_soft_closed_period_via_mcp():
    app = create_app("sqlite://")
    app.ledger.soft_close("2026-03")

    async def scenario():
        async with mcp_client(app) as client:
            rows = json.loads(
                (await client.read_resource("closings://")).contents[0].text
            )
            assert rows == [{"period": "2026-03", "kind": "soft"}]

    run(scenario())


def test_year_end_blockers_resource_shows_stale_bank_posting_via_mcp():
    app = create_app("sqlite://")
    app.ledger.create_account(
        code="AR", name="Accounts Receivable", type="asset", control=True
    )
    app.ledger.create_account(code="Revenue", name="Revenue", type="income")
    app.ledger.create_account(code="Bank", name="Bank", type="asset")
    customer = app.party.register_party(name="Acme", role="customer")

    async def scenario():
        async with mcp_client(app) as client:
            issued = json.loads(
                (
                    await client.call_tool(
                        "issue_invoice",
                        {
                            "number": 1,
                            "party_id": customer.id,
                            "amount_minor": 1000_00,
                            "currency": "MYR",
                            "issued_on": "2026-01-10",
                        },
                    )
                )
                .content[0]
                .text
            )
            # mark_paid posts Dr Bank / Cr AR — an uncleared, soon-stale
            # bank posting that blocks the year-end hard close.
            await client.call_tool(
                "mark_paid",
                {"invoice_id": issued["invoice_id"], "paid_on": "2026-03-01"},
            )

            blockers = json.loads(
                (await client.read_resource("year-end-blockers://2026"))
                .contents[0]
                .text
            )
            assert len(blockers) == 1
            assert blockers[0]["amount_minor"] == 1000_00
            assert blockers[0]["currency"] == "MYR"

    run(scenario())
