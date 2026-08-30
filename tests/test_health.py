"""Tests for diagnostics (US-009): bridge_status returns guidance, never raises."""

import socket
from pathlib import Path

from pydantic import SecretStr

from protonmail_mcp.bridge import BridgeInfo, BridgeNotRunningError
from protonmail_mcp.config import AccountConfig, Config
from protonmail_mcp.services import health

CONFIG = Config(
    accounts=[AccountConfig(name="default", email="me@pm.local", password=SecretStr("pw"))]
)


def info(installed: bool, imap_port: int) -> BridgeInfo:
    return BridgeInfo(
        data_dir=Path("/fake/bridge-v3") if installed else None,
        imap_port=imap_port,
        smtp_port=1025,
        ports_source="defaults",
        cert_path=Path("/fake/bridge-v3/cert.pem") if installed else None,
    )


def closed_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


def test_not_installed_gives_install_guidance() -> None:
    status = health.bridge_status(info(False, closed_port()), CONFIG)
    assert status["installed"] is False
    assert status["running"] is False
    assert "Install it" in status["guidance"]


def test_installed_but_down_gives_start_guidance() -> None:
    status = health.bridge_status(info(True, closed_port()), CONFIG)
    assert status["installed"] is True
    assert status["running"] is False
    assert "Start the Bridge" in status["guidance"]


def test_running_bridge_reports_clean() -> None:
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    try:
        status = health.bridge_status(info(True, server.getsockname()[1]), CONFIG)
        assert status["running"] is True
        assert "guidance" not in status
        assert status["accounts_configured"] == ["default"]
        assert status["certificate_found"] is True
    finally:
        server.close()


def test_failure_uses_actionable_message_for_bridge_errors() -> None:
    entry = health.failure(BridgeNotRunningError("127.0.0.1", 1143))
    assert entry["ok"] is False
    assert "Start the Bridge application" in entry["error"]


def test_failure_wraps_unexpected_errors() -> None:
    entry = health.failure(RuntimeError("boom"))
    assert entry["ok"] is False
    assert "boom" in entry["error"]
