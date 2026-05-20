"""Postings resource: read GL postings for an account, including
provenance dimensions. The agent calls this after writing an expense
to confirm the posting landed as expected.

URI template: postings://{account_code}
"""

from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from books import App


def register(mcp: FastMCP, books: App) -> None:
    @mcp.resource("postings://{account_code}")
    def postings_for(account_code: str) -> str:
        """All postings against `account_code`, in insertion order.

        Each posting includes its ADR-0007 dimensions (party in v1) so
        the agent can verify supplier provenance is preserved.
        """
        postings = books.ledger.postings_for(code=account_code)
        return json.dumps(
            [
                {
                    "ref": p.ref,
                    "account_code": p.account_code,
                    "amount_minor": p.amount.minor_units,
                    "currency": p.amount.currency.value,
                    "date": p.date.isoformat(),
                    "party_name": p.party_name,
                    "dimensions": {
                        t: {"id": v.id, "name": v.name} for t, v in p.dimensions.items()
                    },
                }
                for p in postings
            ]
        )
