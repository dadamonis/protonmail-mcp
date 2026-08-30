"""Process-wide runtime: config, Bridge info, and connection manager.

Built lazily on first tool call so that `protonmail-mcp --version` and
friends never touch config or the network. Tests replace it with
set_runtime().
"""

from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Protocol

from protonmail_mcp.bridge import BridgeInfo, discover
from protonmail_mcp.config import AccountConfig, Config, load_config
from protonmail_mcp.connections import ConnectionManager


class SmtpSendFn(Protocol):
    def __call__(
        self, account: AccountConfig, bridge: BridgeInfo, message: EmailMessage
    ) -> None: ...


class SmtpCheckFn(Protocol):
    def __call__(self, account: AccountConfig, bridge: BridgeInfo) -> None: ...


def _default_smtp_send() -> SmtpSendFn:
    from protonmail_mcp.connections.smtp import send_message

    return send_message


def _default_smtp_check() -> SmtpCheckFn:
    from protonmail_mcp.connections.smtp import check_login

    return check_login


@dataclass
class Runtime:
    config: Config
    bridge: BridgeInfo
    manager: ConnectionManager
    smtp_send: SmtpSendFn = field(default_factory=_default_smtp_send)
    smtp_check: SmtpCheckFn = field(default_factory=_default_smtp_check)


_runtime: Runtime | None = None


def get_runtime() -> Runtime:
    global _runtime
    if _runtime is None:
        config = load_config()
        bridge = discover()
        _runtime = Runtime(config=config, bridge=bridge, manager=ConnectionManager(config, bridge))
    return _runtime


def set_runtime(runtime: Runtime | None) -> None:
    global _runtime
    _runtime = runtime
