"""Period-close tools: the two-tier close (ADR-0008 / ADR-0009).

- soft_close: locks a completed month against casual edits; idempotent,
  never blocks on uncleared items.
- write_off: guided-journal Dr Write-off / Cr Bank that clears a phantom
  bank posting out of the uncleared set (unblocks a hard close).
- hard_close: blocks while stale uncleared items remain (returns them as a
  structured "blocked" result, ADR-0019 spirit); otherwise sweeps net P&L
  to Owner's Equity and locks the whole fiscal year.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from books import App


def register(mcp: FastMCP, books: App) -> None:
    @mcp.tool()
    def soft_close(period: str) -> dict:
        """Soft-close a completed month (YYYY-MM). Locks it against new
        economic entries; corrections still flow via the guided-journal
        path. Idempotent; never blocks on uncleared items (ADR-0009)."""
        books.ledger.soft_close(period)
        return {"status": "soft_closed", "period": period}
