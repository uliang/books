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

    @mcp.resource("year-end-blockers://{year}")
    def year_end_blockers(year: str) -> str:
        """Stale uncleared bank postings blocking the {year} hard close.
        Path params arrive as strings, so coerce to int before lookup."""
        return json.dumps(
            [
                {
                    "ref": b.ref,
                    "amount_minor": b.amount.minor_units,
                    "currency": b.amount.currency.value,
                    "age_days": b.age_days,
                    "classification": b.classification,
                }
                for b in books.reporting.year_end_blockers(int(year))
            ]
        )
