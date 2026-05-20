"""Single resource-wiring point. Each module is its own focused area
(setup, postings), registered here against a captured App."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from books import App


def register(mcp: FastMCP, books: App) -> None:
    from books.interfaces.mcp.resources.postings import register as register_postings
    from books.interfaces.mcp.resources.setup import register as register_setup

    register_setup(mcp, books)
    register_postings(mcp, books)
