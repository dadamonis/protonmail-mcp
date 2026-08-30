"""Tests for reply/forward construction and drafts (US-006)."""

import pytest
from imap_tools import MailMessageFlags
from pydantic import SecretStr

from protonmail_mcp.config import AccountConfig
from protonmail_mcp.services import messages, send_ops
from tests.conftest import FakeMail, FakeMailBox, as_mailbox

ACCOUNT = AccountConfig(name="default", email="me@pm.local", password=SecretStr("pw"))

ORIGINAL = FakeMail(
    uid="5",
    subject="Quarterly numbers",
    from_="alice@pm.local",
    to=("me@pm.local", "bob@pm.local"),
    cc=("carol@pm.local",),
    text="Here are the numbers.",
    headers={
        "message-id": ("<orig@pm.local>",),
        "references": ("<root@pm.local>",),
    },
)


def box() -> FakeMailBox:
    return FakeMailBox({"INBOX": [ORIGINAL]})


class TestReply:
    def test_reply_threads_correctly(self) -> None:
        msg = send_ops.build_reply(as_mailbox(box()), ACCOUNT, "INBOX", "5", "Thanks!")
        assert msg["To"] == "alice@pm.local"
        assert msg["Subject"] == "Re: Quarterly numbers"
        assert msg["In-Reply-To"] == "<orig@pm.local>"
        assert msg["References"] == "<root@pm.local> <orig@pm.local>"

    def test_reply_quotes_original(self) -> None:
        msg = send_ops.build_reply(as_mailbox(box()), ACCOUNT, "INBOX", "5", "Thanks!")
        content = msg.get_content()
        assert "Thanks!" in content
        assert "> Here are the numbers." in content

    def test_reply_all_ccs_everyone_but_me(self) -> None:
        msg = send_ops.build_reply(
            as_mailbox(box()), ACCOUNT, "INBOX", "5", "Thanks!", reply_all=True
        )
        assert msg["Cc"] == "bob@pm.local, carol@pm.local"

    def test_reply_missing_uid(self) -> None:
        with pytest.raises(ValueError, match="not found"):
            send_ops.build_reply(as_mailbox(FakeMailBox()), ACCOUNT, "INBOX", "404", "hi")


class TestForward:
    def test_forward_quotes_original(self) -> None:
        msg = send_ops.build_forward(
            as_mailbox(box()), ACCOUNT, "INBOX", "5", ["dave@pm.local"], "FYI"
        )
        assert msg["To"] == "dave@pm.local"
        assert msg["Subject"] == "Fwd: Quarterly numbers"
        content = msg.get_content()
        assert "FYI" in content
        assert "Forwarded message" in content
        assert "Here are the numbers." in content

    def test_forward_validates_recipients(self) -> None:
        with pytest.raises(ValueError, match="Invalid recipient"):
            send_ops.build_forward(as_mailbox(box()), ACCOUNT, "INBOX", "5", ["bad"], "")


class TestDraft:
    def test_saved_to_drafts_with_flag(self) -> None:
        fake = FakeMailBox()
        message = messages.build_email(ACCOUNT, ["a@pm.local"], "Draft", "text")
        result = send_ops.save_draft(as_mailbox(fake), message)
        assert result["saved_to"] == "Drafts"
        folder, raw, flags = fake.appended[0]
        assert folder == "Drafts"
        assert b"Subject: Draft" in raw
        assert MailMessageFlags.DRAFT in flags
