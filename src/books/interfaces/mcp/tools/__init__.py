"""Single tool-wiring point. Each module is its own focused workflow
area (setup, expense), registered here against a captured App."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from books import App


def register(mcp: FastMCP, books: App) -> None:
    from books.interfaces.mcp.tools.expense import register as register_expense
    from books.interfaces.mcp.tools.setup import register as register_setup

    register_setup(mcp, books)
    register_expense(mcp, books)
