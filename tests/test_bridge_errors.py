"""Tests for the Bridge error classifier — every failure mode gets a
distinct, actionable message."""

import imaplib
import smtplib
import ssl

from protonmail_mcp.bridge import (
    BridgeAuthError,
    BridgeCertificateError,
    BridgeError,
    BridgeNotInstalledError,
    BridgeNotRunningError,
    classify_connection_error,
)


def classify(exc: BaseException, installed: bool = True) -> BridgeError:
    return classify_connection_error(
        exc, host="127.0.0.1", port=1143, account="default", installed=installed
    )


def test_connection_refused_when_installed_means_not_running() -> None:
    error = classify(ConnectionRefusedError())
    assert isinstance(error, BridgeNotRunningError)
    assert "Start the Bridge application" in str(error)
    assert "127.0.0.1:1143" in str(error)


def test_connection_refused_when_not_installed_means_not_installed() -> None:
    error = classify(ConnectionRefusedError(), installed=False)
    assert isinstance(error, BridgeNotInstalledError)
    assert "proton.me/mail/bridge" in str(error)


def test_imap_auth_failure_names_bridge_password() -> None:
    error = classify(imaplib.IMAP4.error(b"[AUTHENTICATIONFAILED] Invalid credentials"))
    assert isinstance(error, BridgeAuthError)
    assert "bridge password" in str(error)
    assert "default" in str(error)


def test_smtp_auth_failure() -> None:
    error = classify(smtplib.SMTPAuthenticationError(535, b"authentication failed"))
    assert isinstance(error, BridgeAuthError)


def test_cert_verification_failure() -> None:
    exc = ssl.SSLCertVerificationError()
    exc.verify_message = "self-signed certificate"
    error = classify(exc)
    assert isinstance(error, BridgeCertificateError)
    assert "self-signed certificate" in str(error)


def test_generic_imap_error_stays_generic() -> None:
    error = classify(imaplib.IMAP4.error(b"UNAVAILABLE try later"))
    assert type(error) is BridgeError


def test_bridge_error_passes_through_unchanged() -> None:
    original = BridgeNotRunningError("127.0.0.1", 1143)
    assert classify(original) is original


def test_messages_never_include_credentials() -> None:
    for error in (
        BridgeAuthError("acct"),
        BridgeNotRunningError("127.0.0.1", 1143),
        BridgeNotInstalledError(),
        BridgeCertificateError(),
    ):
        assert "password" not in str(error).lower() or "bridge password" in str(error).lower()
