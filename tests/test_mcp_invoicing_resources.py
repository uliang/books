"""MCP invoicing resources: invoices:// list + per-id settlement picture.

Parallels test_mcp_setup_resources.py / test_mcp_postings_resource.py.
"""

from __future__ import annotations

import json

from _mcp_helpers import mcp_client, run
from books import create_app


def _chart(app) -> None:
    app.ledger.create_account(
        code="AR", name="Accounts Receivable", type="asset", control=True
    )
    app.ledger.create_account(code="Revenue", name="Revenue", type="income")
    app.ledger.create_account(code="Bank", name="Bank", type="asset")


def test_invoices_resource_empty_then_lists_issued_invoice():
    app = create_app("sqlite://")
    _chart(app)
    customer = app.party.register_party(name="Acme Sdn Bhd", role="customer")

    async def scenario():
        async with mcp_client(app) as client:
            empty = json.loads(
                (await client.read_resource("invoices://")).contents[0].text
            )
            assert empty == []

            await client.call_tool(
                "issue_invoice",
                {
                    "number": 1001,
                    "party_id": customer.id,
                    "amount_minor": 500_000,
                    "currency": "MYR",
                    "issued_on": "2026-02-01",
                },
            )
            rows = json.loads(
                (await client.read_resource("invoices://")).contents[0].text
            )
            assert len(rows) == 1
            assert rows[0]["number"] == 1001
            assert rows[0]["party_name"] == "Acme Sdn Bhd"
            assert rows[0]["currency"] == "MYR"
            assert rows[0]["carrying_minor"] == 500_000
            assert rows[0]["banked_minor"] is None
            assert rows[0]["status"] == "issued"

    run(scenario())


def test_settlement_resource_shows_both_numbers():
    app = create_app("sqlite://")
    _chart(app)
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
                            "amount_minor": 100_000,  # SGD 1,000.00
                            "currency": "SGD",
                            "issued_on": "2026-01-10",
                            "rate_bp": 32000,  # carrying MYR 3,200
                        },
                    )
                )
                .content[0]
                .text
            )
            invoice_id = issued["invoice_id"]
            await client.call_tool(
                "mark_paid",
                {
                    "invoice_id": invoice_id,
                    "paid_on": "2026-01-20",
                    "banked_minor": 318_000,  # MYR 3,180
                },
            )

            s = json.loads(
                (await client.read_resource(f"invoices://{invoice_id}/settlement"))
                .contents[0]
                .text
            )
            assert s["transaction_currency"] == "SGD"
            assert s["transaction_amount_minor"] == 100_000
            assert s["carrying_minor"] == 320_000
            assert s["banked_minor"] == 318_000
            assert s["shortfall_minor"] == 2_000

    run(scenario())
