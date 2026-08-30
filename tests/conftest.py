"""Shared test fakes: an in-memory mailbox speaking just enough of the
imap_tools BaseMailBox surface for the service layer."""

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, cast

from imap_tools import MailMessage
from imap_tools.folder import FolderInfo
from imap_tools.mailbox import BaseMailBox


@dataclass
class FakeAttachment:
    filename: str = "file.txt"
    payload: bytes = b"content"
    content_type: str = "text/plain"


@dataclass
class FakeMail:
    uid: str = "1"
    subject: str = "Hello"
    from_: str = "alice@pm.local"
    to: tuple[str, ...] = ("me@pm.local",)
    cc: tuple[str, ...] = ()
    reply_to: tuple[str, ...] = ()
    date: datetime | None = field(default_factory=lambda: datetime(2026, 1, 2, 3, 4))
    flags: tuple[str, ...] = ()
    size: int = 100
    text: str = "body text"
    html: str = ""
    headers: dict[str, tuple[str, ...]] = field(default_factory=dict)
    attachments: list[FakeAttachment] = field(default_factory=list)


def mail(**kwargs: Any) -> MailMessage:
    return cast(MailMessage, FakeMail(**kwargs))


class FakeFolderManager:
    def __init__(self, box: "FakeMailBox") -> None:
        self._box = box
        self.current = "INBOX"

    def list(self, folder: str = "", search_args: str = "*") -> list[FolderInfo]:
        return [
            FolderInfo(name, "/", tuple(data["flags"])) for name, data in self._box.folders.items()
        ]

    def set(self, folder: str) -> None:
        if folder not in self._box.folders:
            raise LookupError(f"no such folder: {folder}")
        self.current = folder

    def status(self, folder: str, options: Any = None) -> dict[str, int]:
        msgs = self._box.folders[folder]["msgs"]
        return {
            "MESSAGES": len(msgs),
            "UNSEEN": sum(1 for m in msgs if "\\Seen" not in m.flags),
        }

    def create(self, folder: str) -> None:
        if folder in self._box.folders:
            raise ValueError(f"folder exists: {folder}")
        self._box.folders[folder] = {"flags": (), "msgs": []}

    def delete(self, folder: str) -> None:
        del self._box.folders[folder]


class FakeClient:
    def noop(self) -> tuple[str, list[bytes]]:
        return ("OK", [b"NOOP"])


class FakeMailBox:
    """In-memory mailbox. folders maps name -> {"flags": tuple, "msgs": [FakeMail]}."""

    def __init__(self, folders: dict[str, list[FakeMail]] | None = None) -> None:
        self.folders: dict[str, dict[str, Any]] = {
            "INBOX": {"flags": (), "msgs": []},
            "Trash": {"flags": ("\\Trash",), "msgs": []},
            "Drafts": {"flags": ("\\Drafts",), "msgs": []},
        }
        for name, msgs in (folders or {}).items():
            self.folders.setdefault(name, {"flags": (), "msgs": []})["msgs"] = list(msgs)
        self.folder = FakeFolderManager(self)
        self.client = FakeClient()
        self.appended: list[tuple[str, bytes, Any]] = []
        self.fetch_criteria: list[str] = []

    # -- helpers -----------------------------------------------------------
    def add_folder(self, name: str, flags: tuple[str, ...] = ()) -> None:
        self.folders[name] = {"flags": flags, "msgs": []}

    def _current_msgs(self) -> list[FakeMail]:
        return cast(list[FakeMail], self.folders[self.folder.current]["msgs"])

    @staticmethod
    def _filter(criteria: Any, msgs: list[FakeMail]) -> list[FakeMail]:
        crit = str(criteria)
        uid_match = re.search(r"UID ([\w,:]+)", crit)
        if uid_match:
            wanted = set(uid_match.group(1).split(","))
            msgs = [m for m in msgs if m.uid in wanted]
        header_match = re.search(r'HEADER "([^"]+)" "([^"]+)"', crit)
        if header_match:
            name, value = header_match.group(1).lower(), header_match.group(2)
            msgs = [m for m in msgs if any(value in v for v in m.headers.get(name, ()))]
        if "UNSEEN" in crit and not uid_match:
            msgs = [m for m in msgs if "\\Seen" not in m.flags]
        return msgs

    # -- BaseMailBox surface ----------------------------------------------
    def logout(self) -> tuple[str, list[bytes]]:
        return ("BYE", [b"LOGOUT"])

    def fetch(self, criteria: Any = "ALL", charset: str = "US-ASCII", **kwargs: Any) -> Any:
        self.fetch_criteria.append(str(criteria))
        msgs = self._filter(criteria, self._current_msgs())
        if kwargs.get("reverse"):
            msgs = list(reversed(msgs))
        limit = kwargs.get("limit")
        if isinstance(limit, slice):
            msgs = msgs[limit]
        elif isinstance(limit, int):
            msgs = msgs[:limit]
        return iter(msgs)

    def uids(self, criteria: Any = "ALL", charset: Any = "US-ASCII", sort: Any = None) -> list[str]:
        return [m.uid for m in self._filter(criteria, self._current_msgs())]

    def move(self, uid_list: Any, destination_folder: str, chunks: Any = None) -> None:
        uids = {uid_list} if isinstance(uid_list, str) else set(uid_list)
        src = self._current_msgs()
        moving = [m for m in src if m.uid in uids]
        self.folders[self.folder.current]["msgs"] = [m for m in src if m.uid not in uids]
        self.folders[destination_folder]["msgs"].extend(moving)

    def delete(self, uid_list: Any, chunks: Any = None) -> None:
        uids = {uid_list} if isinstance(uid_list, str) else set(uid_list)
        src = self._current_msgs()
        self.folders[self.folder.current]["msgs"] = [m for m in src if m.uid not in uids]

    def copy(self, uid_list: Any, destination_folder: str, chunks: Any = None) -> None:
        uids = {uid_list} if isinstance(uid_list, str) else set(uid_list)
        if destination_folder not in self.folders:
            raise LookupError(f"no such folder: {destination_folder}")
        for m in self._current_msgs():
            if m.uid in uids:
                self.folders[destination_folder]["msgs"].append(m)

    def flag(self, uid_list: Any, flag_set: Any, value: bool, chunks: Any = None) -> None:
        uids = {uid_list} if isinstance(uid_list, str) else set(uid_list)
        flags = {flag_set} if isinstance(flag_set, str) else set(flag_set)
        for m in self._current_msgs():
            if m.uid in uids:
                current = set(m.flags)
                m.flags = tuple(current | flags) if value else tuple(current - flags)

    def append(
        self, message: Any, folder: str = "INBOX", dt: Any = None, flag_set: Any = None
    ) -> tuple[str, list[bytes]]:
        self.appended.append((folder, bytes(message), flag_set))
        return ("OK", [b"APPEND"])


def as_mailbox(fake: FakeMailBox) -> BaseMailBox:
    return cast(BaseMailBox, fake)
