"""Tests for IMAP mail operations against the fake mailbox (US-005/US-007)."""

import pytest

from protonmail_mcp.services import mail_ops
from tests.conftest import FakeAttachment, FakeMail, FakeMailBox, as_mailbox


def inbox_with(*msgs: FakeMail) -> FakeMailBox:
    return FakeMailBox({"INBOX": list(msgs)})


class TestListMailboxes:
    def test_lists_with_counts(self) -> None:
        fake = inbox_with(FakeMail(uid="1"), FakeMail(uid="2", flags=("\\Seen",)))
        result = mail_ops.list_mailboxes(as_mailbox(fake))
        inbox = next(f for f in result if f["name"] == "INBOX")
        assert inbox["messages"] == 2
        assert inbox["unread"] == 1

    def test_noselect_folder_skips_status(self) -> None:
        fake = FakeMailBox()
        fake.add_folder("Labels", flags=("\\Noselect",))
        result = mail_ops.list_mailboxes(as_mailbox(fake))
        labels = next(f for f in result if f["name"] == "Labels")
        assert "messages" not in labels


class TestListEmails:
    def test_pagination_newest_first(self) -> None:
        fake = inbox_with(*(FakeMail(uid=str(i)) for i in range(1, 6)))
        result = mail_ops.list_emails(as_mailbox(fake), limit=2, offset=1)
        assert result["total"] == 5
        assert [e["uid"] for e in result["emails"]] == ["4", "3"]  # newest first, skip 1

    def test_unread_filter_in_criteria(self) -> None:
        fake = inbox_with(FakeMail(uid="1", flags=("\\Seen",)), FakeMail(uid="2"))
        result = mail_ops.list_emails(as_mailbox(fake), unread_only=True)
        assert [e["uid"] for e in result["emails"]] == ["2"]

    def test_date_filters_build_imap_criteria(self) -> None:
        fake = inbox_with(FakeMail())
        mail_ops.list_emails(as_mailbox(fake), since="2026-01-01", before="2026-02-01")
        assert "SINCE 1-Jan-2026" in fake.fetch_criteria[-1]
        assert "BEFORE 1-Feb-2026" in fake.fetch_criteria[-1]


class TestGetEmail:
    def test_found(self) -> None:
        fake = inbox_with(FakeMail(uid="9", subject="Target"))
        result = mail_ops.get_email(as_mailbox(fake), "INBOX", "9")
        assert result["subject"] == "Target"
        assert result["folder"] == "INBOX"

    def test_missing_raises(self) -> None:
        with pytest.raises(ValueError, match="UID 404"):
            mail_ops.get_email(as_mailbox(inbox_with()), "INBOX", "404")


class TestSearch:
    def test_criteria_covers_subject_sender_body(self) -> None:
        fake = inbox_with(FakeMail())
        mail_ops.search_emails(as_mailbox(fake), "invoice")
        criteria = fake.fetch_criteria[-1]
        for token in ('SUBJECT "invoice"', 'FROM "invoice"', 'TEXT "invoice"'):
            assert token in criteria


class TestThread:
    def test_thread_collects_by_message_id_and_references(self) -> None:
        root = FakeMail(uid="1", headers={"message-id": ("<root@id>",)})
        reply = FakeMail(
            uid="2",
            headers={"message-id": ("<reply@id>",), "references": ("<root@id>",)},
        )
        stranger = FakeMail(uid="3", headers={"message-id": ("<other@id>",)})
        fake = inbox_with(root, reply, stranger)

        result = mail_ops.get_thread(as_mailbox(fake), "INBOX", "2")
        assert result["length"] == 2
        assert [m["uid"] for m in result["messages"]] == ["1", "2"]


class TestAttachments:
    def test_download(self) -> None:
        fake = inbox_with(FakeMail(uid="1", attachments=[FakeAttachment("a.txt", b"data")]))
        result = mail_ops.download_attachment(as_mailbox(fake), "INBOX", "1", "a.txt")
        assert result["filename"] == "a.txt"

    def test_missing_lists_available(self) -> None:
        fake = inbox_with(FakeMail(uid="1", attachments=[FakeAttachment("real.pdf")]))
        with pytest.raises(ValueError, match=r"Available: real\.pdf"):
            mail_ops.download_attachment(as_mailbox(fake), "INBOX", "1", "nope.pdf")


class TestOrganise:
    def test_move(self) -> None:
        fake = inbox_with(FakeMail(uid="1"))
        fake.add_folder("Folders/Receipts")
        result = mail_ops.move_email(as_mailbox(fake), "INBOX", "1", "Folders/Receipts")
        assert result["moved"] is True
        assert fake.folders["INBOX"]["msgs"] == []
        assert len(fake.folders["Folders/Receipts"]["msgs"]) == 1

    def test_delete_defaults_to_trash(self) -> None:
        fake = inbox_with(FakeMail(uid="1"))
        result = mail_ops.delete_email(as_mailbox(fake), "INBOX", "1")
        assert result["deleted"] == "moved_to_trash"
        assert len(fake.folders["Trash"]["msgs"]) == 1

    def test_permanent_delete(self) -> None:
        fake = inbox_with(FakeMail(uid="1"))
        result = mail_ops.delete_email(as_mailbox(fake), "INBOX", "1", permanent=True)
        assert result["deleted"] == "permanent"
        assert fake.folders["Trash"]["msgs"] == []

    def test_all_mail_operations_rejected(self) -> None:
        fake = FakeMailBox({"All Mail": [FakeMail(uid="1")]})
        with pytest.raises(ValueError, match="virtual"):
            mail_ops.delete_email(as_mailbox(fake), "All Mail", "1")
        with pytest.raises(ValueError, match="virtual"):
            mail_ops.move_email(as_mailbox(fake), "All Mail", "1", "INBOX")

    def test_mark_read_and_flagged(self) -> None:
        message = FakeMail(uid="1")
        fake = inbox_with(message)
        mail_ops.mark_email(as_mailbox(fake), "INBOX", "1", read=True, flagged=True)
        assert set(message.flags) == {"\\Seen", "\\Flagged"}
        mail_ops.mark_email(as_mailbox(fake), "INBOX", "1", read=False)
        assert "\\Seen" not in message.flags

    def test_mark_nothing_rejected(self) -> None:
        with pytest.raises(ValueError, match="Nothing to change"):
            mail_ops.mark_email(as_mailbox(FakeMailBox()), "INBOX", "1")

    def test_create_mailbox_prefixes_folders_namespace(self) -> None:
        fake = FakeMailBox()
        result = mail_ops.create_mailbox(as_mailbox(fake), "Receipts")
        assert result["created"] == "Folders/Receipts"
        assert "Folders/Receipts" in fake.folders

    def test_create_mailbox_respects_explicit_path(self) -> None:
        fake = FakeMailBox()
        result = mail_ops.create_mailbox(as_mailbox(fake), "Labels/Urgent")
        assert result["created"] == "Labels/Urgent"
