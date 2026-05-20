"""MCP tool surface — setup + health smoke."""

from __future__ import annotations

from _mcp_helpers import mcp_client, run


def test_health_tool_returns_ok():
    async def scenario():
        async with mcp_client() as client:
            result = await client.call_tool("health", {})
            # FastMCP serializes a dict return as a TextContent JSON payload.
            assert result.isError is False
            assert result.content
            text = result.content[0].text  # TextContent
            assert "ok" in text

    run(scenario())
