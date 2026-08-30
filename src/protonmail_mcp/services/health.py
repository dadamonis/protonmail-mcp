"""Diagnostics: bridge_status and check_health.

Both return structured guidance instead of raising when Bridge is down —
the whole point is telling the user what to fix.
"""

import time
from typing import Any

from imap_tools.mailbox import BaseMailBox

from protonmail_mcp.bridge import BridgeError, BridgeInfo, is_bridge_running
from protonmail_mcp.config import Config

BRIDGE_DOWN_GUIDANCE = (
    "ProtonMail Bridge is not running. Start the Bridge application, make sure "
    "it is logged in, and retry."
)
BRIDGE_MISSING_GUIDANCE = (
    "ProtonMail Bridge does not appear to be installed. Install it from "
    "https://proton.me/mail/bridge and log in to your Proton account."
)


def bridge_status(bridge: BridgeInfo, config: Config) -> dict[str, Any]:
    running = bridge.installed and is_bridge_running(port=bridge.imap_port)
    status: dict[str, Any] = {
        "installed": bridge.installed,
        "data_dir": str(bridge.data_dir) if bridge.data_dir else None,
        "running": running,
        "imap_port": bridge.imap_port,
        "smtp_port": bridge.smtp_port,
        "ports_source": bridge.ports_source,
        "certificate_found": bridge.cert_path is not None,
        "certificate_path": str(bridge.cert_path) if bridge.cert_path else None,
        "accounts_configured": [account.name for account in config.accounts],
    }
    if not bridge.installed:
        status["guidance"] = BRIDGE_MISSING_GUIDANCE
    elif not running:
        status["guidance"] = BRIDGE_DOWN_GUIDANCE
    return status


def imap_health_op(mailbox: BaseMailBox) -> dict[str, Any]:
    """Runs inside the connection manager thread: measure a folder listing."""
    started = time.monotonic()
    folders = mailbox.folder.list()
    return {
        "ok": True,
        "latency_ms": round((time.monotonic() - started) * 1000, 1),
        "mailboxes": len(folders),
    }


def failure(error: BaseException) -> dict[str, Any]:
    """Structured failure entry from a (usually Bridge-classified) error."""
    return {"ok": False, "error": str(error) if isinstance(error, BridgeError) else repr(error)}
