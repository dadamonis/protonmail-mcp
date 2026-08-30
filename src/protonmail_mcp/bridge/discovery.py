"""Locate a local ProtonMail Bridge install and discover its settings.

Bridge exposes IMAP on 127.0.0.1:1143 and SMTP on 127.0.0.1:1025 by
default, using STARTTLS with a self-signed certificate it writes into
its data directory. This module finds that directory per platform,
tries to read the configured ports, and builds an SSL context that
trusts Bridge's certificate — verification is never disabled.

Port discovery is best-effort: Bridge v2 kept ports in a plain
``prefs.json``; Bridge v3 moved most settings into an encrypted vault,
so on v3 installs discovery typically falls back to the defaults (or
the user's explicit config) and says so.
"""

import json
import logging
import os
import socket
import ssl
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from protonmail_mcp.bridge.errors import BridgeCertificateError

logger = logging.getLogger(__name__)

DEFAULT_IMAP_PORT = 1143
DEFAULT_SMTP_PORT = 1025

# Newest first: prefer a v3 install over a leftover v2 one.
_DATA_DIR_NAMES = ("bridge-v3", "bridge")


@dataclass(frozen=True)
class BridgeInfo:
    """Result of Bridge discovery. ``data_dir is None`` means no install
    was found; ports are always usable (discovered or defaults)."""

    data_dir: Path | None
    imap_port: int
    smtp_port: int
    ports_source: Literal["discovered", "defaults"]
    cert_path: Path | None

    @property
    def installed(self) -> bool:
        return self.data_dir is not None


def bridge_data_dir(
    platform: str | None = None,
    env: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> Path | None:
    """Return the Bridge data directory for this platform, or None if no
    Bridge install is found. Parameters exist for testing."""
    platform = platform or sys.platform
    env = env if env is not None else os.environ
    home = home or Path.home()

    if platform == "darwin":
        base = home / "Library" / "Application Support" / "protonmail"
    elif platform.startswith("win"):
        appdata = env.get("APPDATA")
        base = (Path(appdata) if appdata else home / "AppData" / "Roaming") / "protonmail"
    else:
        xdg = env.get("XDG_CONFIG_HOME")
        base = (Path(xdg) if xdg else home / ".config") / "protonmail"

    for name in _DATA_DIR_NAMES:
        candidate = base / name
        if candidate.is_dir():
            return candidate
    return None


def _read_ports_from_prefs(data_dir: Path) -> tuple[int, int] | None:
    """Try Bridge's plain-text prefs.json (Bridge v2, and some v3 installs).
    Returns (imap_port, smtp_port) or None if unreadable/absent."""
    prefs_path = data_dir / "prefs.json"
    if not prefs_path.is_file():
        return None
    try:
        prefs = json.loads(prefs_path.read_text(encoding="utf-8"))
        imap = int(prefs["user_ports_imap"])
        smtp = int(prefs["user_ports_smtp"])
    except (OSError, ValueError, KeyError, TypeError):
        logger.debug("Could not read ports from %s", prefs_path)
        return None
    if not (0 < imap < 65536 and 0 < smtp < 65536):
        return None
    return imap, smtp


CERT_EXPORT_INSTRUCTIONS = (
    "Bridge v3 keeps its TLS certificate inside its encrypted vault, so it must "
    "be exported once: open Bridge → Settings → Advanced settings → "
    '"Export TLS certificates", and save cert.pem to ~/.config/protonmail-mcp/ '
    "(or set PROTONMAIL_MCP_CERT to wherever you saved it)."
)


def find_cert(
    data_dir: Path,
    env: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> Path | None:
    """Locate Bridge's TLS certificate.

    Bridge v3 stores the certificate inside its encrypted vault and does
    not write cert.pem to the data dir (verified against Bridge v3 on
    macOS); users export it via Settings → Advanced settings → "Export
    TLS certificates". Search order:

    1. $PROTONMAIL_MCP_CERT (explicit path)
    2. <config dir>/cert.pem — the location our setup wizard suggests
    3. <bridge data dir>/cert.pem — where Bridge v2 wrote it
    """
    env = env if env is not None else os.environ
    home = home or Path.home()

    if explicit := env.get("PROTONMAIL_MCP_CERT"):
        path = Path(explicit)
        if path.is_file():
            return path
        logger.warning("PROTONMAIL_MCP_CERT is set to %s but no file exists there", path)

    xdg = env.get("XDG_CONFIG_HOME")
    config_dir = (Path(xdg) if xdg else home / ".config") / "protonmail-mcp"
    for candidate in (config_dir / "cert.pem", data_dir / "cert.pem"):
        if candidate.is_file():
            return candidate
    return None


def create_bridge_ssl_context(cert_path: Path) -> ssl.SSLContext:
    """SSL context that trusts exactly Bridge's own self-signed certificate.

    Verification stays on: the context's only trust root is Bridge's
    cert, which pins the connection to this Bridge install.
    """
    try:
        context = ssl.create_default_context(cafile=str(cert_path))
    except (ssl.SSLError, OSError) as exc:
        raise BridgeCertificateError(f"(could not load {cert_path}: {exc})") from exc
    return context


def is_bridge_running(
    host: str = "127.0.0.1",
    port: int = DEFAULT_IMAP_PORT,
    timeout: float = 1.0,
) -> bool:
    """TCP probe of Bridge's IMAP port."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def discover(
    platform: str | None = None,
    env: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> BridgeInfo:
    """Full discovery: data dir, ports, certificate."""
    data_dir = bridge_data_dir(platform=platform, env=env, home=home)
    if data_dir is None:
        return BridgeInfo(
            data_dir=None,
            imap_port=DEFAULT_IMAP_PORT,
            smtp_port=DEFAULT_SMTP_PORT,
            ports_source="defaults",
            cert_path=None,
        )

    ports = _read_ports_from_prefs(data_dir)
    if ports is None:
        logger.info(
            "Bridge found at %s but its port settings are not readable "
            "(Bridge v3 keeps them in an encrypted vault) — assuming defaults "
            "%d/%d. Override in the account config if Bridge uses other ports.",
            data_dir,
            DEFAULT_IMAP_PORT,
            DEFAULT_SMTP_PORT,
        )

    return BridgeInfo(
        data_dir=data_dir,
        imap_port=ports[0] if ports else DEFAULT_IMAP_PORT,
        smtp_port=ports[1] if ports else DEFAULT_SMTP_PORT,
        ports_source="discovered" if ports else "defaults",
        cert_path=find_cert(data_dir, env=env, home=home),
    )
