"""Period-close resources: what's already closed, and what blocks a hard
close (ADR-0008 / ADR-0009).

- closings:// — every locked period and its kind (soft/hard).
- year-end-blockers://{year} — stale uncleared bank postings standing in
  the way of the annual hard close.
"""

from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from books import App


def register(mcp: FastMCP, books: App) -> None:
    @mcp.resource("closings://")
    def list_closings() -> str:
        """Every locked period and its kind (soft/hard), period-ordered."""
        return json.dumps(
            [
                {"period": lk.period, "kind": lk.kind}
                for lk in books.ledger.locked_periods()
            ]
        )
