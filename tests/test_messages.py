"""Tests for pure message helpers (US-005/US-006)."""

import base64
from typing import cast

import pytest
from imap_tools import MailAttachment
from pydantic import SecretStr

from protonmail_mcp.config import AccountConfig
from protonmail_mcp.services import messages
from tests.conftest import FakeAttachment, mail

ACCOUNT = AccountConfig(
    name="default",
    email="me@pm.local",
    display_name="Me Myself",
    password=SecretStr("pw"),
)


class TestBuildEmail:
    def test_basic_message(self) -> None:
        msg = messages.build_email(ACCOUNT, ["a@pm.local"], "Hi", "Body")
        assert msg["From"] == "Me Myself <me@pm.local>"
        assert msg["To"] == "a@pm.local"
        assert msg["Subject"] == "Hi"
        assert "Body" in msg.get_content()

    def test_threading_headers(self) -> None:
        msg = messages.build_email(
            ACCOUNT,
            ["a@pm.local"],
            "Re: Hi",
            "Body",
            in_reply_to="<orig@pm.local>",
            reference_ids=["<root@pm.local>"],
        )
        assert msg["In-Reply-To"] == "<orig@pm.local>"
        assert msg["References"] == "<root@pm.local> <orig@pm.local>"

    def test_html_message_has_alternative(self) -> None:
        msg = messages.build_email(ACCOUNT, ["a@pm.local"], "Hi", "<b>Body</b>", html=True)
        assert msg.get_body(("html",)) is not None

    def test_invalid_recipient_rejected(self) -> None:
        with pytest.raises(ValueError, match="Invalid recipient"):
            messages.build_email(ACCOUNT, ["not-an-address"], "Hi", "Body")

    def test_invalid_cc_rejected(self) -> None:
        with pytest.raises(ValueError, match="Invalid cc"):
            messages.build_email(ACCOUNT, ["a@pm.local"], "Hi", "Body", cc=["bad"])

    def test_no_recipients_rejected(self) -> None:
        with pytest.raises(ValueError, match="At least one recipient"):
            messages.build_email(ACCOUNT, [], "Hi", "Body")


class TestSerialization:
    def test_summarize(self) -> None:
        m = mail(uid="7", flags=("\\Seen",), attachments=[FakeAttachment("a.pdf")])
        summary = messages.summarize(m)
        assert summary["uid"] == "7"
        assert summary["seen"] is True
        assert summary["flagged"] is False
        assert summary["attachments"] == ["a.pdf"]

    def test_full_message_prefers_text(self) -> None:
        m = mail(text="plain", html="<p>html</p>")
        full = messages.full_message(m)
        assert full["body"] == "plain"
        assert full["body_is_html"] is False
        assert "html" not in full

    def test_full_message_falls_back_to_html(self) -> None:
        m = mail(text="", html="<p>html</p>")
        full = messages.full_message(m, include_html=True)
        assert full["body"] == "<p>html</p>"
        assert full["body_is_html"] is True
        assert full["html"] == "<p>html</p>"

    def test_threading_fields_extracted(self) -> None:
        m = mail(
            headers={
                "message-id": ("<me@id>",),
                "in-reply-to": ("<parent@id>",),
                "references": ("<root@id> <parent@id>",),
            }
        )
        full = messages.full_message(m)
        assert full["message_id"] == "<me@id>"
        assert full["in_reply_to"] == "<parent@id>"
        assert full["references"] == ["<root@id>", "<parent@id>"]


class TestAttachments:
    def test_encode(self) -> None:
        att = cast(MailAttachment, FakeAttachment("a.txt", b"hello"))
        encoded = messages.encode_attachment(att)
        assert base64.b64decode(encoded["content_base64"]) == b"hello"
        assert encoded["size"] == 5

    def test_cap_enforced(self) -> None:
        big = cast(
            MailAttachment,
            FakeAttachment("big.bin", b"x" * (messages.MAX_ATTACHMENT_BYTES + 1)),
        )
        with pytest.raises(ValueError, match="5 MB"):
            messages.encode_attachment(big)


class TestSubjectsAndQuoting:
    def test_reply_subject(self) -> None:
        assert messages.reply_subject("Hello") == "Re: Hello"
        assert messages.reply_subject("Re: Hello") == "Re: Hello"
        assert messages.reply_subject("RE: Hello") == "RE: Hello"

    def test_forward_subject(self) -> None:
        assert messages.forward_subject("Hello") == "Fwd: Hello"
        assert messages.forward_subject("Fwd: Hello") == "Fwd: Hello"

    def test_quote_original(self) -> None:
        quoted = messages.quote_original(mail(text="line1\nline2"))
        assert "> line1" in quoted
        assert "> line2" in quoted
        assert "alice@pm.local wrote:" in quoted

    def test_forward_block(self) -> None:
        block = messages.forward_block(mail())
        assert "Forwarded message" in block
        assert "From: alice@pm.local" in block
