"""Setup tools: party + account creation.

Thin wrappers over PartyService.register_party and LedgerService.
create_account. Returns JSON-friendly dicts; FastMCP serializes them
to TextContent on the wire.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mcp.server.fastmcp import FastMCP

if TYPE_CHECKING:
    from books import App


def register(mcp: FastMCP, books: App) -> None:
    @mcp.tool()
    def register_party(name: str, role: str) -> dict:
        """Register a new Party (typically `role="supplier"` for the
        expense flow, `role="customer"` for invoicing). Returns the
        new party's id, name, and role."""
        p = books.party.register_party(name=name, role=role)
        return {"id": p.id, "name": p.name, "role": role}

    @mcp.tool()
    def create_account(code: str, name: str, type: str, control: bool = False) -> dict:
        """Create a Chart of Accounts entry. `type` is one of
        asset/liability/equity/income/expense. `control` marks the
        account as a control account (e.g. AR)."""
        books.ledger.create_account(code=code, name=name, type=type, control=control)
        return {"code": code, "name": name, "type": type, "control": control}
