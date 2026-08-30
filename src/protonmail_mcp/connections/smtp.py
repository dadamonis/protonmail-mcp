"""SMTP against Bridge: STARTTLS with the pinned Bridge certificate.

Sends open a fresh connection per message — Bridge is local, so the
handshake is cheap, and it keeps the failure surface simple.
"""

import contextlib
import smtplib
from email.message import EmailMessage

from protonmail_mcp.bridge import (
    BridgeCertificateError,
    BridgeInfo,
    BridgeNotInstalledError,
    classify_connection_error,
    create_bridge_ssl_context,
)
from protonmail_mcp.bridge.discovery import CERT_EXPORT_INSTRUCTIONS
from protonmail_mcp.config import AccountConfig

SEND_TIMEOUT_SECONDS = 60.0


def _open(account: AccountConfig, bridge: BridgeInfo) -> smtplib.SMTP:
    host = account.smtp.host
    port = account.smtp.port or bridge.smtp_port

    if not bridge.installed:
        raise BridgeNotInstalledError()
    if bridge.cert_path is None:
        raise BridgeCertificateError(f"(no certificate found: {CERT_EXPORT_INSTRUCTIONS})")

    try:
        smtp = smtplib.SMTP(host, port, timeout=SEND_TIMEOUT_SECONDS)
        smtp.starttls(context=create_bridge_ssl_context(bridge.cert_path))
        smtp.login(account.effective_username, account.password.get_secret_value())
    except Exception as exc:
        raise classify_connection_error(
            exc, host=host, port=port, account=account.name, installed=bridge.installed
        ) from exc
    return smtp


def send_message(account: AccountConfig, bridge: BridgeInfo, message: EmailMessage) -> None:
    """Send one message. Bridge files it into the Sent folder itself."""
    smtp = _open(account, bridge)
    try:
        smtp.send_message(message)
    except smtplib.SMTPException as exc:
        raise classify_connection_error(
            exc,
            host=account.smtp.host,
            port=account.smtp.port or bridge.smtp_port,
            account=account.name,
            installed=bridge.installed,
        ) from exc
    finally:
        with contextlib.suppress(Exception):  # already disconnected
            smtp.quit()


def check_login(account: AccountConfig, bridge: BridgeInfo) -> None:
    """Connect + STARTTLS + login + quit, raising a classified BridgeError
    on failure. Used by check_health."""
    smtp = _open(account, bridge)
    with contextlib.suppress(Exception):  # health signal was the login, not the goodbye
        smtp.quit()
