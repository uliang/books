"""MCP invoicing tools — per-tool acceptance, driven through the adapter.

Parallels test_mcp_expense_tools.py: each sell-side verb exercised over
the in-memory MCP client against a fresh in-memory App.
"""

from __future__ import annotations

import json
from decimal import Decimal

from _mcp_helpers import mcp_client, run
from books import create_app
from books.platform.money import Money


def _chart(app) -> None:
    """The accounts the invoicing rail posts to (role codes are pre-seeded;
    the account rows must exist or postings fail the FK)."""
    app.ledger.create_account(
        code="AR", name="Accounts Receivable", type="asset", control=True
    )
    app.ledger.create_account(code="Revenue", name="Revenue", type="income")
    app.ledger.create_account(code="Bank", name="Bank", type="asset")


def test_rate_from_bp_converts_basis_points_to_decimal():
    from books.interfaces.mcp.forms import rate_from_bp

    assert rate_from_bp(10000) == Decimal("1")
    assert rate_from_bp(32000) == Decimal("3.2")


def test_issue_invoice_tool_returns_id_and_books_ar():
    app = create_app("sqlite://")
    _chart(app)
    customer = app.party.register_party(name="Acme Sdn Bhd", role="customer")

    async def scenario():
        async with mcp_client(app) as client:
            result = await client.call_tool(
                "issue_invoice",
                {
                    "number": 1001,
                    "party_id": customer.id,
                    "amount_minor": 500_000,  # MYR 5,000.00
                    "currency": "MYR",
                    "issued_on": "2026-02-01",
                },
            )
            assert result.isError is False
            payload = json.loads(result.content[0].text)
            assert payload["number"] == 1001
            assert payload["invoice_id"] >= 1

    run(scenario())
    assert app.ledger.account_balance(code="AR") == Money.myr(500_000)
    assert app.ledger.account_balance(code="Revenue") == Money.myr(-500_000)
