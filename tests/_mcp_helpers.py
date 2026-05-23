"""Async in-memory MCP client wrapper for tests.

Uses the SDK's create_connected_server_and_client_session to wire a
FastMCP server to a ClientSession over an in-memory transport. No
subprocess, no stdio — just an event loop.

Tests use the synchronous helper `run(coro)` so individual test
functions can stay sync; each test creates its own server (and so its
own in-memory App / SQLite database), keeping them isolated.

SDK note (mcp 1.27.x): create_connected_server_and_client_session
accepts FastMCP directly (not just the low-level Server), so we pass
the FastMCP instance as-is rather than going through server._mcp_server.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from mcp import ClientSession
from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import create_connected_server_and_client_session

from books import App, create_app
from books.interfaces.mcp.app import create_mcp_server


def run(coro):
    """Synchronously drive an awaitable from a sync test function."""
    return asyncio.run(coro)


@asynccontextmanager
async def mcp_client(books_app: App | None = None) -> AsyncIterator[ClientSession]:
    """Yield a ClientSession bound to a fresh MCP server over in-memory pipes."""
    server: FastMCP = create_mcp_server(books_app or create_app("sqlite://"))
    # SDK 1.27.x: create_connected_server_and_client_session accepts FastMCP
    # directly; it unpacks _mcp_server internally when needed.
    async with create_connected_server_and_client_session(server) as client:
        yield client
