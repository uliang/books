"""MCP sell-side FX adjudication (ADR-0005 / ADR-0019), end-to-end.

A foreign invoice that banks fewer MYR than carried is ambiguous. The agent
relays the owner's explicit outcome; the system never auto-decides. Mirrors
test_increment_3_fx_adjudication.py through the MCP adapter.
"""

from __future__ import annotations

import json

from _mcp_helpers import mcp_client, run
from books import create_app
from books.platform.money import Money


def _fx_chart(app) -> None:
    app.ledger.create_account(
        code="AR", name="Accounts Receivable", type="asset", control=True
    )
    app.ledger.create_account(code="Revenue", name="Revenue", type="income")
    app.ledger.create_account(code="Bank", name="Bank", type="asset")
    app.ledger.create_account(code="FX Loss", name="Realized FX Loss", type="expense")


def test_foreign_invoice_settled_in_full_recognizes_fx_loss_via_mcp():
    app = create_app("sqlite://")
    _fx_chart(app)
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
                            "rate_bp": 32000,  # 3.20 → carrying MYR 3,200
                        },
                    )
                )
                .content[0]
                .text
            )
            invoice_id = issued["invoice_id"]

            paid = json.loads(
                (
                    await client.call_tool(
                        "mark_paid",
                        {
                            "invoice_id": invoice_id,
                            "paid_on": "2026-01-20",
                            "banked_minor": 318_000,  # MYR 3,180
                        },
                    )
                )
                .content[0]
                .text
            )
            assert paid["status"] == "awaiting_adjudication"

            adj = json.loads(
                (
                    await client.call_tool(
                        "adjudicate_settlement",
                        {
                            "invoice_id": invoice_id,
                            "outcome": "settled_in_full",
                            "on": "2026-01-25",
                        },
                    )
                )
                .content[0]
                .text
            )
            assert adj["status"] == "paid"

    run(scenario())
    assert app.ledger.account_balance(code="AR") == Money.myr(0)
    assert app.ledger.account_balance(code="FX Loss") == Money.myr(20_00)


def test_foreign_invoice_still_owes_leaves_ar_open_via_mcp():
    app = create_app("sqlite://")
    _fx_chart(app)
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
                            "amount_minor": 100_000,
                            "currency": "SGD",
                            "issued_on": "2026-01-10",
                            "rate_bp": 32000,
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
                    "banked_minor": 318_000,
                },
            )
            adj = json.loads(
                (
                    await client.call_tool(
                        "adjudicate_settlement",
                        {
                            "invoice_id": invoice_id,
                            "outcome": "still_owes",
                            "on": "2026-01-25",
                        },
                    )
                )
                .content[0]
                .text
            )
            assert adj["status"] == "partially_paid"

    run(scenario())
    assert app.ledger.account_balance(code="AR") == Money.myr(20_00)
    assert app.ledger.account_balance(code="FX Loss") == Money.myr(0)
