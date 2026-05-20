"""MCP server composition.

A thin stdio adapter over the existing composition root. The server
captures one App via closure across all tool/resource handlers. The
factory accepts an injected App for tests; if None, builds the file-
backed default that coexists with books-web on the same SQLite file.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mcp.server.fastmcp import FastMCP

from books import create_app

if TYPE_CHECKING:
    from books import App


def create_mcp_server(books_app: App | None = None) -> FastMCP:
    books = books_app or create_app(db_url="sqlite:///books.db")  # noqa: F841 — captured by tool closures added in Tasks 5–7
    mcp = FastMCP("books")

    # A trivial health tool, present to (a) make the otherwise empty
    # server testable end-to-end via the in-memory client, and (b)
    # provide a no-op the LLM can call to confirm the connection is up.
    @mcp.tool()
    def health() -> dict:
        """Return a simple status payload to verify the MCP server is reachable."""
        return {"status": "ok"}

    from books.interfaces.mcp.tools import register as register_tools

    register_tools(mcp, books)

    return mcp


def main() -> None:
    create_mcp_server().run()
