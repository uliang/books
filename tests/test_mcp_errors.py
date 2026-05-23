"""MCP error translation — domain errors surface as isError: true tool
results, not as server crashes. FastMCP's tool wrapper catches the
exception and returns an error content payload.
"""

from __future__ import annotations

from datetime import date

from _mcp_helpers import mcp_client, run
from books import create_app
from books.platform.money import Money


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


def test_unknown_invoice_id_on_mark_paid_surfaces_as_tool_error():
    app = create_app("sqlite://")
    app.ledger.create_account(
        code="AR", name="Accounts Receivable", type="asset", control=True
    )
    app.ledger.create_account(code="Revenue", name="Revenue", type="income")
    app.ledger.create_account(code="Bank", name="Bank", type="asset")

    async def scenario():
        async with mcp_client(app) as client:
            result = await client.call_tool(
                "mark_paid",
                {"invoice_id": 999, "paid_on": "2026-02-20"},
            )
            assert result.isError is True
            assert "999" in result.content[0].text

    run(scenario())


def test_unknown_party_on_issue_invoice_surfaces_as_tool_error():
    app = create_app("sqlite://")
    app.ledger.create_account(
        code="AR", name="Accounts Receivable", type="asset", control=True
    )
    app.ledger.create_account(code="Revenue", name="Revenue", type="income")

    async def scenario():
        async with mcp_client(app) as client:
            result = await client.call_tool(
                "issue_invoice",
                {
                    "number": 1,
                    "party_id": 999,  # nonexistent
                    "amount_minor": 100_00,
                    "currency": "MYR",
                    "issued_on": "2026-02-01",
                },
            )
            assert result.isError is True
            assert "999" in result.content[0].text

    run(scenario())


def test_bad_adjudication_outcome_surfaces_as_tool_error():
    app = create_app("sqlite://")
    app.ledger.create_account(
        code="AR", name="Accounts Receivable", type="asset", control=True
    )
    app.ledger.create_account(code="Revenue", name="Revenue", type="income")
    app.ledger.create_account(code="Bank", name="Bank", type="asset")
    customer = app.party.register_party(name="Acme", role="customer")
    inv = app.invoicing.issue_invoice(
        number=1,
        party_id=customer.id,
        amount=Money.myr(100_00),
        issued_on=date(2026, 2, 1),
    )
    app.invoicing.mark_paid(invoice_id=inv.id, paid_on=date(2026, 2, 20))

    async def scenario():
        async with mcp_client(app) as client:
            result = await client.call_tool(
                "adjudicate_settlement",
                {"invoice_id": inv.id, "outcome": "not_an_outcome", "on": "2026-02-25"},
            )
            assert result.isError is True

    run(scenario())
