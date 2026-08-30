"""Tests for ProtonMail label semantics (US-008) — ported scenarios from
email-mcp's label-strategy."""

import pytest

from protonmail_mcp.services import labels
from tests.conftest import FakeMail, FakeMailBox, as_mailbox


def bridge_box() -> FakeMailBox:
    fake = FakeMailBox(
        {"INBOX": [FakeMail(uid="1", headers={"message-id": ("<msg-1@pm.local>",)})]}
    )
    fake.add_folder("Labels", flags=("\\Noselect",))
    fake.add_folder("Labels/Work")
    fake.add_folder("Labels/Urgent")
    return fake


def test_list_labels_strips_prefix_and_skips_noselect() -> None:
    result = labels.list_labels(as_mailbox(bridge_box()))
    assert [label["name"] for label in result] == ["Work", "Urgent"]
    assert result[0]["path"] == "Labels/Work"


def test_add_label_copies_into_label_folder() -> None:
    fake = bridge_box()
    result = labels.add_label(as_mailbox(fake), "INBOX", "1", "Work")
    assert result["added"] is True
    assert [m.uid for m in fake.folders["Labels/Work"]["msgs"]] == ["1"]
    # Original stays in INBOX — labels are copies, not moves.
    assert [m.uid for m in fake.folders["INBOX"]["msgs"]] == ["1"]


def test_add_label_to_missing_label_folder_fails() -> None:
    fake = bridge_box()
    with pytest.raises(LookupError):
        labels.add_label(as_mailbox(fake), "INBOX", "1", "Nope")


def test_remove_label_deletes_copy_by_message_id() -> None:
    fake = bridge_box()
    labels.add_label(as_mailbox(fake), "INBOX", "1", "Work")
    result = labels.remove_label(as_mailbox(fake), "INBOX", "1", "Work")
    assert result["removed"] is True
    assert fake.folders["Labels/Work"]["msgs"] == []
    assert [m.uid for m in fake.folders["INBOX"]["msgs"]] == ["1"]


def test_remove_label_not_carried_errors() -> None:
    fake = bridge_box()
    with pytest.raises(ValueError, match='does not carry the label "Work"'):
        labels.remove_label(as_mailbox(fake), "INBOX", "1", "Work")


def test_remove_label_without_message_id_errors() -> None:
    fake = FakeMailBox({"INBOX": [FakeMail(uid="1")]})  # no message-id header
    fake.add_folder("Labels/Work")
    with pytest.raises(ValueError, match="Message-ID"):
        labels.remove_label(as_mailbox(fake), "INBOX", "1", "Work")


def test_create_and_delete_label() -> None:
    fake = bridge_box()
    created = labels.create_label(as_mailbox(fake), "Finance")
    assert created["created"] == "Labels/Finance"
    assert "Labels/Finance" in fake.folders

    deleted = labels.delete_label(as_mailbox(fake), "Finance")
    assert deleted["deleted"] == "Labels/Finance"
    assert "Labels/Finance" not in fake.folders
