"""MCP tracer — the agent's sell-side spine, end-to-end.

The MCP-side parallel of test_mcp_expense_tracer.py: drives issue → list →
mark paid → verify, exclusively through the MCP adapter.
"""

from __future__ import annotations

import json

from _mcp_helpers import mcp_client, run
from books import create_app
from books.platform.money import Money


def test_agent_issues_and_settles_invoice_end_to_end_via_mcp():
    app = create_app("sqlite://")
    # Role codes are pre-seeded; create the account rows the rail posts to.
    app.ledger.create_account(
        code="AR", name="Accounts Receivable", type="asset", control=True
    )
    app.ledger.create_account(code="Revenue", name="Revenue", type="income")
    app.ledger.create_account(code="Bank", name="Bank", type="asset")

    async def scenario():
        async with mcp_client(app) as client:
            # 1. Agent inspects invoices://; finds it empty.
            invoices = json.loads(
                (await client.read_resource("invoices://")).contents[0].text
            )
            assert invoices == []

            # 2. Agent registers the customer.
            customer = json.loads(
                (
                    await client.call_tool(
                        "register_party",
                        {"name": "Acme Sdn Bhd", "role": "customer"},
                    )
                )
                .content[0]
                .text
            )

            # 3. Agent issues the invoice.
            issued = json.loads(
                (
                    await client.call_tool(
                        "issue_invoice",
                        {
                            "number": 1001,
                            "party_id": customer["id"],
                            "amount_minor": 500_000,  # MYR 5,000.00
                            "currency": "MYR",
                            "issued_on": "2026-02-01",
                        },
                    )
                )
                .content[0]
                .text
            )
            invoice_id = issued["invoice_id"]

            # 4. invoices:// now lists it, status "issued".
            invoices = json.loads(
                (await client.read_resource("invoices://")).contents[0].text
            )
            assert len(invoices) == 1
            assert invoices[0]["status"] == "issued"
            assert invoices[0]["party_name"] == "Acme Sdn Bhd"
            assert invoices[0]["carrying_minor"] == 500_000

            # 5. Owner saw the money; agent marks it paid (full).
            paid = json.loads(
                (
                    await client.call_tool(
                        "mark_paid",
                        {"invoice_id": invoice_id, "paid_on": "2026-02-20"},
                    )
                )
                .content[0]
                .text
            )
            assert paid["status"] == "paid"

            # 6. postings://AR — the issue and payment legs both present.
            ar_postings = json.loads(
                (await client.read_resource("postings://AR")).contents[0].text
            )
            assert len(ar_postings) == 2

    run(scenario())

    # Cross-check the books directly: AR cleared, cash in, revenue booked.
    assert app.ledger.account_balance(code="AR") == Money.myr(0)
    assert app.ledger.account_balance(code="Bank") == Money.myr(500_000)
    assert app.ledger.account_balance(code="Revenue") == Money.myr(-500_000)
