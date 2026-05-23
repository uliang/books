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
from books.interfaces.mcp.forms import date_from


def register(mcp: FastMCP, books: App) -> None:
    @mcp.tool()
    def soft_close(period: str) -> dict:
        """Soft-close a completed month (YYYY-MM). Locks it against new
        economic entries; corrections still flow via the guided-journal
        path. Idempotent; never blocks on uncleared items (ADR-0009)."""
        books.ledger.soft_close(period)
        return {"status": "soft_closed", "period": period}

    @mcp.tool()
    def write_off(posting_ref: int, on: str) -> dict:
        """Write off a phantom bank posting (ADR-0006): a guided-journal
        Dr Write-off / Cr Bank reversal. Once recorded, the posting no
        longer appears among the year-end hard-close blockers. An unknown
        posting_ref surfaces as an error."""
        books.ledger.write_off(posting_ref=posting_ref, on=date_from(on))
        return {"status": "written_off", "posting_ref": posting_ref}

    @mcp.tool()
    def hard_close(year: int) -> dict:
        """Annual hard close (ADR-0008 / ADR-0009). Pre-checks the year-end
        blockers: if any uncleared bank posting remains, returns a structured
        "blocked" result listing them — the agent guides the owner to write
        each off or adjudicate; the system never auto-decides (ADR-0019).
        Otherwise sweeps net P&L to Owner's Equity via the guided-journal
        path, locks all 12 months, and the fiscal year becomes immutable."""
        blockers = books.reporting.year_end_blockers(year)
        if blockers:
            # Any uncleared bank posting blocks (ADR-0009 amended); each
            # carries its timing/stale classification so the agent can guide
            # the owner (chase a late statement vs write off a phantom).
            return {
                "status": "blocked",
                "blockers": [
                    {
                        "ref": b.ref,
                        "amount_minor": b.amount.minor_units,
                        "currency": b.amount.currency.value,
                        "age_days": b.age_days,
                        "classification": b.classification,
                    }
                    for b in blockers
                ],
            }
        books.ledger.hard_close(year)
        return {"status": "closed", "year": year}
