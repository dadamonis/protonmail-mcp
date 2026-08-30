"""ProtonMail label operations over Bridge's labels-as-folders model.

Port of email-mcp's ProtonMail label strategy: labels are IMAP folders
under the ``Labels/`` prefix; a message "has" a label when a copy of it
(same Message-ID) exists in that label folder.
"""

from typing import Any

from imap_tools import AND
from imap_tools.mailbox import BaseMailBox
from imap_tools.query import Header

from protonmail_mcp.services import messages
from protonmail_mcp.services.mail_ops import LABELS_PREFIX, _fetch_one


def list_labels(mailbox: BaseMailBox) -> list[dict[str, Any]]:
    result = []
    for folder in mailbox.folder.list():
        if folder.name.startswith(LABELS_PREFIX) and "\\Noselect" not in folder.flags:
            result.append({"name": folder.name[len(LABELS_PREFIX) :], "path": folder.name})
    return result


def add_label(mailbox: BaseMailBox, folder: str, uid: str, label: str) -> dict[str, Any]:
    """Copy the message into Labels/<label> — that is what tagging means
    under Bridge."""
    target = f"{LABELS_PREFIX}{label}"
    mailbox.folder.set(folder)
    mailbox.copy(uid, target)
    return {"uid": uid, "label": label, "added": True}


def remove_label(mailbox: BaseMailBox, folder: str, uid: str, label: str) -> dict[str, Any]:
    """Find the message's copy inside the label folder by Message-ID and
    delete it there."""
    label_path = f"{LABELS_PREFIX}{label}"

    msg = _fetch_one(mailbox, folder, uid)
    msg_id = messages.message_id(msg)
    if not msg_id:
        raise ValueError(
            "Could not read this email's Message-ID, which is needed to locate "
            "it inside the label folder."
        )

    mailbox.folder.set(label_path)
    label_uids = mailbox.uids(AND(header=Header("Message-ID", msg_id)))
    if not label_uids:
        raise ValueError(f'This email does not carry the label "{label}".')
    mailbox.delete(label_uids)
    return {"uid": uid, "label": label, "removed": True}


def create_label(mailbox: BaseMailBox, name: str) -> dict[str, Any]:
    path = f"{LABELS_PREFIX}{name}"
    mailbox.folder.create(path)
    return {"created": path}


def delete_label(mailbox: BaseMailBox, name: str) -> dict[str, Any]:
    path = f"{LABELS_PREFIX}{name}"
    mailbox.folder.delete(path)
    return {"deleted": path}
