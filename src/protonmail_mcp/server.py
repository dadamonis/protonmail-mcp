"""MCP server definition and stdio entry point.

Tool implementations live in dedicated modules; this module owns the
MCPServer instance they register against.
"""

from mcp.server.mcpserver import MCPServer

from protonmail_mcp import __version__

mcp = MCPServer(
    name="protonmail-mcp",
    version=__version__,
    instructions=(
        "MCP server for ProtonMail, connected through a locally running ProtonMail Bridge. "
        "Provides tools to read, search, send, organise, and label ProtonMail email over "
        "Bridge's local IMAP/SMTP endpoints. ProtonMail labels are represented as IMAP "
        "folders under the Labels/ prefix."
    ),
)


@mcp.tool()
def ping() -> str:
    """Liveness check — returns "pong" if the server is running."""
    return "pong"


# Register the full tool surface (import placed after mcp exists so tool
# modules can never import the server back).
from protonmail_mcp.tools import register  # noqa: E402

register(mcp)


def run() -> None:
    """Run the MCP server over stdio."""
    mcp.run(transport="stdio")
