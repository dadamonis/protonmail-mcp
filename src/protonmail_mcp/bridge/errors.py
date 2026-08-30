"""Actionable errors for every Bridge failure mode.

The messages here are the product: instead of a raw socket traceback,
the MCP client (and through it, the user) gets told what is wrong and
what to do about it.
"""

import imaplib
import smtplib
import socket
import ssl


class BridgeError(Exception):
    """Base class for ProtonMail Bridge failures."""


class BridgeNotInstalledError(BridgeError):
    def __init__(self, detail: str = "") -> None:
        message = (
            "ProtonMail Bridge does not appear to be installed on this machine "
            "(no Bridge data directory found). Install it from "
            "https://proton.me/mail/bridge, log in to your Proton account, and retry."
        )
        super().__init__(f"{message} {detail}".strip())


class BridgeNotRunningError(BridgeError):
    def __init__(self, host: str, port: int) -> None:
        super().__init__(
            f"ProtonMail Bridge is not reachable at {host}:{port}. "
            "Start the Bridge application (and make sure it is logged in), then retry. "
            "If Bridge uses non-default ports, set them in the account config."
        )


class BridgeAuthError(BridgeError):
    def __init__(self, account: str) -> None:
        super().__init__(
            f'Bridge rejected the credentials for account "{account}". '
            "Use the bridge password from Bridge → Mailbox details (not your Proton "
            "account password) — re-copy it into the config and retry."
        )


class BridgeCertificateError(BridgeError):
    def __init__(self, detail: str = "") -> None:
        message = (
            "TLS certificate verification against ProtonMail Bridge failed. "
            "Bridge may have regenerated its certificate — restart the MCP server "
            "so it re-reads Bridge's cert.pem. If the problem persists, check that "
            "nothing else is listening on Bridge's ports."
        )
        super().__init__(f"{message} {detail}".strip())


def classify_connection_error(
    exc: BaseException,
    *,
    host: str,
    port: int,
    account: str,
    installed: bool,
) -> BridgeError:
    """Translate a low-level IMAP/SMTP/socket/TLS failure into the matching
    actionable :class:`BridgeError`. Falls back to a generic BridgeError
    wrapping the original message."""
    if isinstance(exc, BridgeError):
        return exc

    if isinstance(exc, ssl.SSLCertVerificationError):
        return BridgeCertificateError(f"(verification error: {exc.verify_message})")
    if isinstance(exc, ssl.SSLError):
        return BridgeCertificateError(f"(TLS error: {exc})")

    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return BridgeAuthError(account)
    if isinstance(exc, imaplib.IMAP4.error) and _looks_like_auth_failure(exc):
        return BridgeAuthError(account)

    if isinstance(exc, ConnectionRefusedError | ConnectionResetError | socket.timeout | OSError):
        if not installed:
            return BridgeNotInstalledError()
        return BridgeNotRunningError(host, port)

    return BridgeError(f"Unexpected error talking to ProtonMail Bridge at {host}:{port}: {exc}")


def _looks_like_auth_failure(exc: BaseException) -> bool:
    text = str(exc).upper()
    return any(
        marker in text for marker in ("AUTHENTICATIONFAILED", "LOGIN FAILED", "INVALID CREDENTIALS")
    )
