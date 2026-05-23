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
