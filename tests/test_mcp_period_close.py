"""MCP period-close tracer (ADR-0008 / ADR-0009), end-to-end through the
in-memory client. Mirrors test_increment_4_hard_close_gate.py via the MCP
adapter: soft close, write-off, and the two-tier hard-close gate.
"""

from __future__ import annotations

import json

from _mcp_helpers import mcp_client, run
from books import create_app
from books.platform.money import Money


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


def test_soft_close_locks_month_via_mcp():
    app = create_app("sqlite://")
    app.ledger.create_account(
        code="AR", name="Accounts Receivable", type="asset", control=True
    )
    app.ledger.create_account(code="Revenue", name="Revenue", type="income")
    customer = app.party.register_party(name="Acme", role="customer")

    async def scenario():
        async with mcp_client(app) as client:
            result = json.loads(
                (await client.call_tool("soft_close", {"period": "2026-03"}))
                .content[0]
                .text
            )
            assert result == {"status": "soft_closed", "period": "2026-03"}

            rows = json.loads(
                (await client.read_resource("closings://")).contents[0].text
            )
            assert {"period": "2026-03", "kind": "soft"} in rows

            # A new economic entry dated into the locked month is rejected.
            rejected = await client.call_tool(
                "issue_invoice",
                {
                    "number": 1,
                    "party_id": customer.id,
                    "amount_minor": 500_00,
                    "currency": "MYR",
                    "issued_on": "2026-03-15",
                },
            )
            assert rejected.isError is True
            text = rejected.content[0].text
            assert "2026-03" in text or "closed" in text.lower()

    run(scenario())


def test_write_off_clears_blocker_via_mcp():
    app = create_app("sqlite://")
    app.ledger.create_account(
        code="AR", name="Accounts Receivable", type="asset", control=True
    )
    app.ledger.create_account(code="Revenue", name="Revenue", type="income")
    app.ledger.create_account(code="Bank", name="Bank", type="asset")
    app.ledger.create_account(code="Write-off", name="Write-off", type="expense")
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
            await client.call_tool(
                "mark_paid",
                {"invoice_id": issued["invoice_id"], "paid_on": "2026-03-01"},
            )

            before = json.loads(
                (await client.read_resource("year-end-blockers://2026"))
                .contents[0]
                .text
            )
            assert len(before) == 1
            ref = before[0]["ref"]

            result = json.loads(
                (
                    await client.call_tool(
                        "write_off", {"posting_ref": ref, "on": "2026-12-31"}
                    )
                )
                .content[0]
                .text
            )
            assert result == {"status": "written_off", "posting_ref": ref}

            after = json.loads(
                (await client.read_resource("year-end-blockers://2026"))
                .contents[0]
                .text
            )
            assert after == []

    run(scenario())
    assert app.ledger.account_balance(code="Write-off") == Money.myr(1000_00)
    assert app.ledger.account_balance(code="Bank") == Money.myr(0)


def test_hard_close_sweeps_pnl_to_owners_equity_via_mcp():
    app = create_app("sqlite://")
    app.ledger.create_account(
        code="AR", name="Accounts Receivable", type="asset", control=True
    )
    app.ledger.create_account(code="Revenue", name="Revenue", type="income")
    app.ledger.create_account(
        code="Owner's Equity", name="Owner's Equity", type="equity"
    )
    customer = app.party.register_party(name="Acme", role="customer")

    async def scenario():
        async with mcp_client(app) as client:
            # Accrued revenue only — no bank posting, so nothing blocks.
            await client.call_tool(
                "issue_invoice",
                {
                    "number": 1,
                    "party_id": customer.id,
                    "amount_minor": 1500_00,
                    "currency": "MYR",
                    "issued_on": "2026-02-01",
                },
            )
            result = json.loads(
                (await client.call_tool("hard_close", {"year": 2026})).content[0].text
            )
            assert result == {"status": "closed", "year": 2026}

            closings = json.loads(
                (await client.read_resource("closings://")).contents[0].text
            )
            hard = [c for c in closings if c["kind"] == "hard"]
            assert len(hard) == 12

    run(scenario())
    assert app.ledger.account_balance(code="Revenue") == Money.myr(0)
    assert app.ledger.account_balance(code="Owner's Equity") == Money.myr(-1500_00)


def test_hard_close_blocked_then_closes_after_write_off_via_mcp():
    app = create_app("sqlite://")
    app.ledger.create_account(
        code="AR", name="Accounts Receivable", type="asset", control=True
    )
    app.ledger.create_account(code="Revenue", name="Revenue", type="income")
    app.ledger.create_account(code="Bank", name="Bank", type="asset")
    app.ledger.create_account(code="Write-off", name="Write-off", type="expense")
    app.ledger.create_account(
        code="Owner's Equity", name="Owner's Equity", type="equity"
    )
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
            await client.call_tool(
                "mark_paid",
                {"invoice_id": issued["invoice_id"], "paid_on": "2026-03-01"},
            )

            blocked = json.loads(
                (await client.call_tool("hard_close", {"year": 2026})).content[0].text
            )
            assert blocked["status"] == "blocked"
            assert len(blocked["blockers"]) == 1
            ref = blocked["blockers"][0]["ref"]

            await client.call_tool(
                "write_off", {"posting_ref": ref, "on": "2026-12-31"}
            )

            closed = json.loads(
                (await client.call_tool("hard_close", {"year": 2026})).content[0].text
            )
            assert closed == {"status": "closed", "year": 2026}

    run(scenario())
    # Net P&L: Revenue 1,000 booked, Write-off 1,000 → zero swept to equity.
    assert app.ledger.account_balance(code="Revenue") == Money.myr(0)
    assert app.ledger.account_balance(code="Write-off") == Money.myr(0)
    assert app.ledger.account_balance(code="Owner's Equity") == Money.myr(0)
