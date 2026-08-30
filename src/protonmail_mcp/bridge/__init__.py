"""ProtonMail Bridge awareness: discovery, TLS trust, and error classification."""

from protonmail_mcp.bridge.discovery import (
    DEFAULT_IMAP_PORT,
    DEFAULT_SMTP_PORT,
    BridgeInfo,
    bridge_data_dir,
    create_bridge_ssl_context,
    discover,
    is_bridge_running,
)
from protonmail_mcp.bridge.errors import (
    BridgeAuthError,
    BridgeCertificateError,
    BridgeError,
    BridgeNotInstalledError,
    BridgeNotRunningError,
    classify_connection_error,
)

__all__ = [
    "DEFAULT_IMAP_PORT",
    "DEFAULT_SMTP_PORT",
    "BridgeAuthError",
    "BridgeCertificateError",
    "BridgeError",
    "BridgeInfo",
    "BridgeNotInstalledError",
    "BridgeNotRunningError",
    "bridge_data_dir",
    "classify_connection_error",
    "create_bridge_ssl_context",
    "discover",
    "is_bridge_running",
]
