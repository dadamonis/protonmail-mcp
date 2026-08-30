"""Tests for the IMAP connection manager: laziness, reuse, reconnect,
error translation, serialization, and shutdown."""

import asyncio
import imaplib
import time
from pathlib import Path

import pytest
from pydantic import SecretStr

from protonmail_mcp.bridge import (
    BridgeAuthError,
    BridgeError,
    BridgeInfo,
    BridgeNotInstalledError,
    BridgeNotRunningError,
)
from protonmail_mcp.config import AccountConfig, Config
from protonmail_mcp.connections import ConnectionManager, ImapSession

BRIDGE = BridgeInfo(
    data_dir=Path("/fake/bridge-v3"),
    imap_port=1143,
    smtp_port=1025,
    ports_source="defaults",
    cert_path=Path("/fake/bridge-v3/cert.pem"),
)

BRIDGE_NOT_INSTALLED = BridgeInfo(
    data_dir=None, imap_port=1143, smtp_port=1025, ports_source="defaults", cert_path=None
)


def make_config(*names: str) -> Config:
    return Config(
        accounts=[
            AccountConfig(name=name, email=f"{name}@pm.local", password=SecretStr("pw"))
            for name in names
        ]
    )


class FakeClient:
    def __init__(self) -> None:
        self.noop_calls = 0
        self.dead = False

    def noop(self) -> tuple[str, list[bytes]]:
        self.noop_calls += 1
        if self.dead:
            raise imaplib.IMAP4.abort("connection gone")
        return ("OK", [b"NOOP"])


class FakeSession:
    def __init__(self) -> None:
        self.client = FakeClient()
        self.logged_out = False

    def logout(self) -> tuple[str, list[bytes]]:
        self.logged_out = True
        return ("BYE", [b"LOGOUT"])


class Factory:
    """Session factory that records calls and can fail on demand."""

    def __init__(self, fail_with: BaseException | None = None) -> None:
        self.sessions: list[FakeSession] = []
        self.fail_with = fail_with

    def __call__(self, account: AccountConfig, bridge: BridgeInfo) -> ImapSession:
        if self.fail_with is not None:
            raise self.fail_with
        session = FakeSession()
        self.sessions.append(session)
        return session


async def test_connection_is_lazy_and_reused() -> None:
    factory = Factory()
    manager = ConnectionManager(make_config("a"), BRIDGE, factory)
    assert factory.sessions == []  # nothing until first use

    first = await manager.with_imap("a", lambda s: s)
    second = await manager.with_imap("a", lambda s: s)
    assert first is second
    assert len(factory.sessions) == 1


async def test_accounts_get_separate_sessions() -> None:
    factory = Factory()
    manager = ConnectionManager(make_config("a", "b"), BRIDGE, factory)
    session_a = await manager.with_imap("a", lambda s: s)
    session_b = await manager.with_imap("b", lambda s: s)
    assert session_a is not session_b
    assert len(factory.sessions) == 2


async def test_stale_session_is_replaced() -> None:
    factory = Factory()
    manager = ConnectionManager(make_config("a"), BRIDGE, factory)
    first = await manager.with_imap("a", lambda s: s)
    assert isinstance(first, FakeSession)
    first.client.dead = True  # health check will now fail

    second = await manager.with_imap("a", lambda s: s)
    assert second is not first
    assert first.logged_out is True  # discard attempts a polite logout
    assert len(factory.sessions) == 2


async def test_unknown_account_raises_key_error() -> None:
    manager = ConnectionManager(make_config("a"), BRIDGE, Factory())
    with pytest.raises(KeyError, match="Available: a"):
        await manager.with_imap("nope", lambda s: s)


async def test_connect_failure_is_classified_not_running() -> None:
    factory = Factory(fail_with=ConnectionRefusedError())
    manager = ConnectionManager(make_config("a"), BRIDGE, factory)
    with pytest.raises(BridgeNotRunningError, match=r"127\.0\.0\.1:1143"):
        await manager.with_imap("a", lambda s: s)


async def test_connect_failure_when_not_installed() -> None:
    factory = Factory(fail_with=ConnectionRefusedError())
    manager = ConnectionManager(make_config("a"), BRIDGE_NOT_INSTALLED, factory)
    with pytest.raises(BridgeNotInstalledError):
        await manager.with_imap("a", lambda s: s)


async def test_auth_failure_is_classified() -> None:
    factory = Factory(fail_with=imaplib.IMAP4.error(b"[AUTHENTICATIONFAILED] Invalid credentials"))
    manager = ConnectionManager(make_config("a"), BRIDGE, factory)
    with pytest.raises(BridgeAuthError, match="bridge password"):
        await manager.with_imap("a", lambda s: s)


async def test_op_connection_error_drops_session_and_reconnects() -> None:
    factory = Factory()
    manager = ConnectionManager(make_config("a"), BRIDGE, factory)

    def broken_op(session: ImapSession) -> None:
        raise imaplib.IMAP4.abort("socket error: EOF")

    with pytest.raises(BridgeError):
        await manager.with_imap("a", broken_op)

    # The broken session was discarded; a new one is created on next use.
    await manager.with_imap("a", lambda s: s)
    assert len(factory.sessions) == 2


async def test_op_command_error_keeps_session() -> None:
    factory = Factory()
    manager = ConnectionManager(make_config("a"), BRIDGE, factory)

    class FolderMissingError(Exception):
        pass

    def bad_command(session: ImapSession) -> None:
        raise FolderMissingError("no such folder")

    with pytest.raises(FolderMissingError):
        await manager.with_imap("a", bad_command)

    await manager.with_imap("a", lambda s: s)
    assert len(factory.sessions) == 1  # session survived the command error


async def test_operations_on_same_account_are_serialized() -> None:
    factory = Factory()
    manager = ConnectionManager(make_config("a"), BRIDGE, factory)
    events: list[tuple[str, int]] = []

    def slow_op(tag: int) -> object:
        def op(session: ImapSession) -> None:
            events.append(("start", tag))
            time.sleep(0.05)
            events.append(("end", tag))

        return op

    await asyncio.gather(
        manager.with_imap("a", slow_op(1)),  # type: ignore[arg-type]
        manager.with_imap("a", slow_op(2)),  # type: ignore[arg-type]
    )
    # No interleaving: each op finishes before the next starts.
    assert [kind for kind, _ in events] == ["start", "end", "start", "end"]
    assert events[0][1] == events[1][1]
    assert events[2][1] == events[3][1]


async def test_close_all_logs_out_everything() -> None:
    factory = Factory()
    manager = ConnectionManager(make_config("a", "b"), BRIDGE, factory)
    await manager.with_imap("a", lambda s: s)
    await manager.with_imap("b", lambda s: s)

    await manager.close_all()
    assert all(session.logged_out for session in factory.sessions)

    # Manager still works after shutdown: reconnects lazily.
    await manager.with_imap("a", lambda s: s)
    assert len(factory.sessions) == 3
