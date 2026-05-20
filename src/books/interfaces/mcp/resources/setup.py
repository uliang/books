"""Setup resources: browsable lists of parties and accounts.

Returns JSON strings; FastMCP wraps the return value as a single text
resource content. URIs are static (no template params) — clients can
just read parties:// or accounts:// to enumerate.
"""

from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from books import App


def register(mcp: FastMCP, books: App) -> None:
    @mcp.resource("parties://")
    def list_parties() -> str:
        """Every Party registered in the books, in insertion order."""
        parties = books.party.list()
        payload = [{"id": p.id, "name": p.name, "role": p.role} for p in parties]
        return json.dumps(payload)

    @mcp.resource("accounts://")
    def list_accounts() -> str:
        """Every Chart of Accounts entry, in creation order."""
        return json.dumps(
            [
                {"code": a.code, "name": a.name, "type": a.type, "control": a.control}
                for a in books.ledger.accounts()
            ]
        )
