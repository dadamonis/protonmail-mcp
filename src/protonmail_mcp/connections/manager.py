"""Lazy, reusable, self-healing IMAP connections per account.

Mirrors the semantics of email-mcp's TypeScript ConnectionManager:
connections open on first use, are reused across tool calls, get
health-checked and transparently reopened when stale, and are all
logged out on shutdown.

Concurrency model: one IMAP connection cannot interleave commands, so
every operation on an account runs under that account's asyncio.Lock,
with the blocking IMAP work pushed to a thread via asyncio.to_thread.
"""

import asyncio
import imaplib
import logging
import ssl
from collections.abc import Callable
from typing import Any, Protocol

from imap_tools import MailBoxStartTls

from protonmail_mcp.bridge import (
    BridgeCertificateError,
    BridgeInfo,
    BridgeNotInstalledError,
    classify_connection_error,
    create_bridge_ssl_context,
)
from protonmail_mcp.config import AccountConfig, Config

logger = logging.getLogger(__name__)

CONNECT_TIMEOUT_SECONDS = 30.0


class ImapSession(Protocol):
    """The slice of imap_tools.BaseMailBox the manager itself needs.
    Tool code receives the full mailbox object; tests inject fakes."""

    # Any: imaplib.IMAP4 at runtime; typed loosely so test fakes can
    # substitute a stub without inheriting from imaplib.
    client: Any

    def logout(self) -> object: ...


SessionFactory = Callable[[AccountConfig, BridgeInfo], ImapSession]

# Failures that mean "this connection is broken", as opposed to a normal
# IMAP command error (folder missing, bad search, ...) which must
# propagate without killing the session.
_CONNECTION_ERRORS = (OSError, ssl.SSLError, imaplib.IMAP4.abort)


def default_session_factory(account: AccountConfig, bridge: BridgeInfo) -> ImapSession:
    """Connect and log in to Bridge's IMAP endpoint for one account."""
    host = account.imap.host
    port = account.imap.port or bridge.imap_port

    if not bridge.installed:
        raise BridgeNotInstalledError()
    if bridge.cert_path is None:
        raise BridgeCertificateError(
            "(Bridge's cert.pem was not found in its data directory — "
            "has Bridge finished first-time setup?)"
        )

    context = create_bridge_ssl_context(bridge.cert_path)
    mailbox = MailBoxStartTls(
        host=host, port=port, timeout=CONNECT_TIMEOUT_SECONDS, ssl_context=context
    )
    mailbox.login(account.effective_username, account.password.get_secret_value())
    return mailbox


class ConnectionManager:
    """Owns one lazy IMAP session per account."""

    def __init__(
        self,
        config: Config,
        bridge: BridgeInfo,
        session_factory: SessionFactory = default_session_factory,
    ) -> None:
        self._config = config
        self._bridge = bridge
        self._factory = session_factory
        self._sessions: dict[str, ImapSession] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock(self, account_name: str) -> asyncio.Lock:
        return self._locks.setdefault(account_name, asyncio.Lock())

    async def with_imap[T](self, account_name: str, op: Callable[[ImapSession], T]) -> T:
        """Run ``op`` against the account's IMAP session, serialized per
        account, in a worker thread. Connection-level failures are
        translated into actionable BridgeErrors and drop the session so
        the next call reconnects."""
        account = self._config.get_account(account_name)
        async with self._lock(account_name):
            return await asyncio.to_thread(self._run_sync, account, op)

    def _run_sync[T](self, account: AccountConfig, op: Callable[[ImapSession], T]) -> T:
        session = self._healthy_session(account)
        try:
            return op(session)
        except _CONNECTION_ERRORS as exc:
            self._discard(account.name)
            raise self._classify(exc, account) from exc

    def _healthy_session(self, account: AccountConfig) -> ImapSession:
        session = self._sessions.get(account.name)
        if session is not None:
            try:
                session.client.noop()
                return session
            except Exception:
                logger.info('Stale IMAP connection for "%s" — reconnecting', account.name)
                self._discard(account.name)

        try:
            session = self._factory(account, self._bridge)
        except Exception as exc:
            raise self._classify(exc, account) from exc
        logger.info(
            'IMAP connected to %s:%s for "%s"',
            account.imap.host,
            account.imap.port or self._bridge.imap_port,
            account.name,
        )
        self._sessions[account.name] = session
        return session

    def _classify(self, exc: BaseException, account: AccountConfig) -> Exception:
        return classify_connection_error(
            exc,
            host=account.imap.host,
            port=account.imap.port or self._bridge.imap_port,
            account=account.name,
            installed=self._bridge.installed,
        )

    def _discard(self, account_name: str) -> None:
        session = self._sessions.pop(account_name, None)
        if session is not None:
            try:
                session.logout()
            except Exception:
                logger.debug('Ignoring logout failure for "%s"', account_name)

    async def close_all(self) -> None:
        """Log out every open session. Safe to call multiple times."""

        async def close_one(account_name: str) -> None:
            async with self._lock(account_name):
                await asyncio.to_thread(self._discard, account_name)

        names = list(self._sessions)
        if names:
            logger.info("Closing %d IMAP connection(s)", len(names))
        await asyncio.gather(*(close_one(name) for name in names))
