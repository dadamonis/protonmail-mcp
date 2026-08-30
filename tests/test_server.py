"""Smoke tests for the FastMCP server skeleton."""

from protonmail_mcp.server import mcp


async def test_ping_tool_is_registered() -> None:
    tools = await mcp.list_tools()
    assert "ping" in [tool.name for tool in tools]


async def test_ping_returns_pong() -> None:
    result = await mcp.call_tool("ping", {})
    assert "pong" in str(result)
