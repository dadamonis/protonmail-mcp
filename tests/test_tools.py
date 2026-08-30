"""End-to-end tool tests through the MCP server with a fake runtime."""

from collections.abc import Iterator
from email.message import EmailMessage
from pathlib import Path
from typing import cast

import pytest
from pydantic import SecretStr

from protonmail_mcp.bridge import BridgeInfo, BridgeNotRunningError
from protonmail_mcp.config import AccountConfig, Config
from protonmail_mcp.connections import ConnectionManager, ImapSession
from protonmail_mcp.runtime import Runtime, set_runtime
from protonmail_mcp.server import mcp
from tests.conftest import FakeMail, FakeMailBox

EXPECTED_TOOLS = {
    # reading
    "list_accounts", "list_mailboxes", "list_emails", "get_email",
    "search_emails", "get_thread", "download_attachment",
    # sending
    "send_email", "reply_email", "forward_email", "save_draft",
    # organisation
    "move_email", "delete_email", "mark_email", "create_mailbox",
    # labels
    "list_labels", "add_label", "remove_label", "create_label", "delete_label",
    # diagnostics
    "check_health", "bridge_status",
}  # fmt: skip


class FakeSmtp:
    def __init__(self) -> None:
        self.sent: list[EmailMessage] = []
        self.fail_with: Exception | None = None

    def send(self, account: AccountConfig, bridge: BridgeInfo, message: EmailMessage) -> None:
        if self.fail_with:
            raise self.fail_with
        self.sent.append(message)

    def check(self, account: AccountConfig, bridge: BridgeInfo) -> None:
        if self.fail_with:
            raise self.fail_with


@pytest.fixture
def fake_world() -> Iterator[tuple[FakeMailBox, FakeSmtp]]:
    fake_box = FakeMailBox(
        {
            "INBOX": [
                FakeMail(
                    uid="1",
                    subject="Welcome",
                    headers={"message-id": ("<w@pm.local>",)},
                )
            ]
        }
    )
    fake_box.add_folder("Labels/Work")
    config = Config(
        accounts=[AccountConfig(name="default", email="me@pm.local", password=SecretStr("pw"))]
    )
    bridge = BridgeInfo(
        data_dir=Path("/fake/bridge-v3"),
        imap_port=1143,
        smtp_port=1025,
        ports_source="defaults",
        cert_path=Path("/fake/bridge-v3/cert.pem"),
    )
    manager = ConnectionManager(config, bridge, lambda account, info: cast(ImapSession, fake_box))
    smtp = FakeSmtp()
    set_runtime(
        Runtime(
            config=config,
            bridge=bridge,
            manager=manager,
            smtp_send=smtp.send,
            smtp_check=smtp.check,
        )
    )
    yield fake_box, smtp
    set_runtime(None)


async def test_full_tool_surface_registered() -> None:
    names = {tool.name for tool in await mcp.list_tools()}
    missing = EXPECTED_TOOLS - names
    assert not missing, f"missing tools: {missing}"


async def test_list_emails_flow(fake_world: tuple[FakeMailBox, FakeSmtp]) -> None:
    result = await mcp.call_tool("list_emails", {})
    text = str(result)
    assert "Welcome" in text
    assert "total" in text


async def test_send_email_flow(fake_world: tuple[FakeMailBox, FakeSmtp]) -> None:
    _, smtp = fake_world
    await mcp.call_tool("send_email", {"to": ["a@pm.local"], "subject": "Hi there", "body": "Body"})
    assert len(smtp.sent) == 1
    assert smtp.sent[0]["To"] == "a@pm.local"
    assert smtp.sent[0]["From"] == "me@pm.local"


async def test_reply_email_flow_threads(fake_world: tuple[FakeMailBox, FakeSmtp]) -> None:
    _, smtp = fake_world
    await mcp.call_tool("reply_email", {"uid": "1", "body": "Thanks"})
    assert smtp.sent[0]["In-Reply-To"] == "<w@pm.local>"
    assert smtp.sent[0]["Subject"] == "Re: Welcome"


async def test_add_label_flow(fake_world: tuple[FakeMailBox, FakeSmtp]) -> None:
    fake_box, _ = fake_world
    await mcp.call_tool("add_label", {"uid": "1", "label": "Work"})
    assert [m.uid for m in fake_box.folders["Labels/Work"]["msgs"]] == ["1"]


async def test_check_health_reports_smtp_failure_structurally(
    fake_world: tuple[FakeMailBox, FakeSmtp],
) -> None:
    _, smtp = fake_world
    smtp.fail_with = BridgeNotRunningError("127.0.0.1", 1025)
    result = await mcp.call_tool("check_health", {})
    text = str(result)
    assert "Start the Bridge application" in text  # structured guidance, not an exception
    assert "'imap'" in text or "imap" in text
