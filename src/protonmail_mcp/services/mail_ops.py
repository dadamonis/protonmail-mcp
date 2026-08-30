"""Synchronous IMAP operations against one mailbox session.

Every function takes an imap_tools BaseMailBox as its first argument
and is executed inside the connection manager's worker thread. These
are deliberately plain functions so they can be unit-tested with fake
mailboxes and no MCP or network involvement.
"""

from datetime import date
from typing import Any

from imap_tools import AND, OR
from imap_tools.mailbox import BaseMailBox
from imap_tools.query import Header

from protonmail_mcp.services import messages

ALL_MAIL_FOLDER = "All Mail"
TRASH_FOLDER = "Trash"
FOLDERS_PREFIX = "Folders/"
LABELS_PREFIX = "Labels/"
_SYSTEM_FOLDERS = frozenset(
    {"INBOX", "Drafts", "Sent", "Starred", "Archive", "Spam", "Trash", ALL_MAIL_FOLDER}
)
_THREAD_LOOKUP_CAP = 20


def list_mailboxes(mailbox: BaseMailBox) -> list[dict[str, Any]]:
    result = []
    for folder in mailbox.folder.list():
        info: dict[str, Any] = {
            "name": folder.name,
            "flags": list(folder.flags),
        }
        if "\\Noselect" not in folder.flags:
            try:
                status = mailbox.folder.status(folder.name, ["MESSAGES", "UNSEEN"])
                info["messages"] = status.get("MESSAGES", 0)
                info["unread"] = status.get("UNSEEN", 0)
            except Exception:
                # STATUS can fail on exotic folders; the listing is still useful.
                info["messages"] = None
                info["unread"] = None
        result.append(info)
    return result


def _criteria(
    unread_only: bool = False,
    from_addr: str | None = None,
    since: str | None = None,
    before: str | None = None,
) -> Any:  # imap-tools criteria are UserStrings; Any keeps call sites simple
    kwargs: dict[str, Any] = {}
    if unread_only:
        kwargs["seen"] = False
    if from_addr:
        kwargs["from_"] = from_addr
    if since:
        kwargs["date_gte"] = date.fromisoformat(since)
    if before:
        kwargs["date_lt"] = date.fromisoformat(before)
    return AND(**kwargs) if kwargs else "ALL"


def list_emails(
    mailbox: BaseMailBox,
    folder: str = "INBOX",
    limit: int = 20,
    offset: int = 0,
    unread_only: bool = False,
    from_addr: str | None = None,
    since: str | None = None,
    before: str | None = None,
) -> dict[str, Any]:
    mailbox.folder.set(folder)
    criteria = _criteria(unread_only, from_addr, since, before)
    total = len(mailbox.uids(criteria))
    fetched = mailbox.fetch(
        criteria,
        limit=slice(offset, offset + limit),
        reverse=True,  # newest first
        mark_seen=False,
        headers_only=True,
        bulk=True,
    )
    return {
        "folder": folder,
        "total": total,
        "offset": offset,
        "emails": [messages.summarize(msg) for msg in fetched],
    }


def _fetch_one(mailbox: BaseMailBox, folder: str, uid: str, mark_seen: bool = False) -> Any:
    mailbox.folder.set(folder)
    found = list(mailbox.fetch(AND(uid=uid), mark_seen=mark_seen))
    if not found:
        raise ValueError(f'Email with UID {uid} not found in "{folder}".')
    return found[0]


def get_email(
    mailbox: BaseMailBox,
    folder: str,
    uid: str,
    include_html: bool = False,
    mark_seen: bool = False,
) -> dict[str, Any]:
    msg = _fetch_one(mailbox, folder, uid, mark_seen=mark_seen)
    result = messages.full_message(msg, include_html=include_html)
    result["folder"] = folder
    return result


def search_emails(
    mailbox: BaseMailBox,
    query: str,
    folder: str = "INBOX",
    limit: int = 20,
) -> dict[str, Any]:
    mailbox.folder.set(folder)
    criteria = OR(subject=query, from_=query, text=query)
    fetched = mailbox.fetch(
        criteria, limit=limit, reverse=True, mark_seen=False, headers_only=True, bulk=True
    )
    results = [messages.summarize(msg) for msg in fetched]
    return {"folder": folder, "query": query, "count": len(results), "emails": results}


def get_thread(mailbox: BaseMailBox, folder: str, uid: str) -> dict[str, Any]:
    """Reconstruct the conversation around one message via
    Message-ID / References / In-Reply-To, within the given folder."""
    msg = _fetch_one(mailbox, folder, uid)
    own_id = messages.message_id(msg)
    related_ids = set(messages.references(msg))
    if own_id:
        related_ids.add(own_id)

    thread_uids = {msg.uid} if msg.uid else set()
    for mid in sorted(related_ids)[:_THREAD_LOOKUP_CAP]:
        thread_uids.update(mailbox.uids(AND(header=Header("Message-ID", mid))))
    if own_id:
        thread_uids.update(mailbox.uids(AND(header=Header("References", own_id))))

    fetched = mailbox.fetch(AND(uid=sorted(thread_uids)), mark_seen=False)
    ordered = sorted(fetched, key=lambda m: (m.date.isoformat() if m.date else "", m.uid or ""))
    return {
        "folder": folder,
        "uid": uid,
        "length": len(ordered),
        "messages": [messages.full_message(m) for m in ordered],
    }


def download_attachment(
    mailbox: BaseMailBox, folder: str, uid: str, filename: str
) -> dict[str, Any]:
    msg = _fetch_one(mailbox, folder, uid)
    for att in msg.attachments:
        if att.filename == filename:
            return messages.encode_attachment(att)
    names = ", ".join(att.filename for att in msg.attachments) or "(none)"
    raise ValueError(f'No attachment "{filename}" on this email. Available: {names}')


# ---------------------------------------------------------------------------
# Organisation (US-007)
# ---------------------------------------------------------------------------


def _reject_all_mail(folder: str, action: str) -> None:
    if folder.strip().lower() == ALL_MAIL_FOLDER.lower():
        raise ValueError(
            f'Cannot {action} from "{ALL_MAIL_FOLDER}": it is ProtonMail\'s virtual '
            "view of every message. Use the message's real folder instead "
            "(find it via list_mailboxes or get_thread)."
        )


def move_email(mailbox: BaseMailBox, folder: str, uid: str, destination: str) -> dict[str, Any]:
    _reject_all_mail(folder, "move an email")
    mailbox.folder.set(folder)
    mailbox.move(uid, destination)
    return {"uid": uid, "from": folder, "to": destination, "moved": True}


def delete_email(
    mailbox: BaseMailBox, folder: str, uid: str, permanent: bool = False
) -> dict[str, Any]:
    _reject_all_mail(folder, "delete an email")
    mailbox.folder.set(folder)
    if permanent:
        mailbox.delete(uid)
        return {"uid": uid, "folder": folder, "deleted": "permanent"}
    mailbox.move(uid, TRASH_FOLDER)
    return {"uid": uid, "folder": folder, "deleted": "moved_to_trash", "to": TRASH_FOLDER}


def mark_email(
    mailbox: BaseMailBox,
    folder: str,
    uid: str,
    read: bool | None = None,
    flagged: bool | None = None,
) -> dict[str, Any]:
    if read is None and flagged is None:
        raise ValueError("Nothing to change: pass read and/or flagged.")
    mailbox.folder.set(folder)
    if read is not None:
        mailbox.flag(uid, "\\Seen", read)
    if flagged is not None:
        mailbox.flag(uid, "\\Flagged", flagged)
    return {"uid": uid, "folder": folder, "read": read, "flagged": flagged}


def create_mailbox(mailbox: BaseMailBox, name: str) -> dict[str, Any]:
    """Create a folder. Bare names go under Proton's Folders/ namespace;
    explicit Folders/... or Labels/... paths are respected."""
    path = name
    if not name.startswith((FOLDERS_PREFIX, LABELS_PREFIX)) and name not in _SYSTEM_FOLDERS:
        path = f"{FOLDERS_PREFIX}{name}"
    mailbox.folder.create(path)
    return {"created": path}
