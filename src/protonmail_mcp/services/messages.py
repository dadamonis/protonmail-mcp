"""Pure message helpers: serialization, construction, validation.

No IMAP/SMTP calls in this module — everything here is testable with
plain MailMessage-like objects.
"""

import base64
import re
from email.message import EmailMessage
from email.utils import formataddr
from typing import Any

from imap_tools import MailAttachment, MailMessage

from protonmail_mcp.config import AccountConfig

MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024  # 5 MB, matching email-mcp

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_MSGID_RE = re.compile(r"<[^<>\s]+>")


def validate_addresses(addresses: list[str], kind: str) -> list[str]:
    for address in addresses:
        if not _EMAIL_RE.match(address):
            raise ValueError(f'Invalid {kind} address: "{address}"')
    return addresses


def summarize(msg: MailMessage) -> dict[str, Any]:
    """Compact listing entry for one message."""
    return {
        "uid": msg.uid,
        "subject": msg.subject,
        "from": msg.from_,
        "to": list(msg.to),
        "date": msg.date.isoformat() if msg.date else None,
        "seen": "\\Seen" in msg.flags,
        "flagged": "\\Flagged" in msg.flags,
        "size": msg.size,
        "attachments": [att.filename for att in msg.attachments],
    }


def full_message(msg: MailMessage, include_html: bool = False) -> dict[str, Any]:
    """Complete representation for get_email. Prefers the text body."""
    result = summarize(msg)
    result.update(
        {
            "cc": list(msg.cc),
            "reply_to": list(msg.reply_to),
            "message_id": message_id(msg),
            "in_reply_to": _first_header(msg, "in-reply-to"),
            "references": references(msg),
            "body": msg.text or msg.html or "",
            "body_is_html": not msg.text and bool(msg.html),
            "attachments": [
                {
                    "filename": att.filename,
                    "content_type": att.content_type,
                    "size": len(att.payload),
                }
                for att in msg.attachments
            ],
        }
    )
    if include_html and msg.html:
        result["html"] = msg.html
    return result


def encode_attachment(att: MailAttachment) -> dict[str, Any]:
    if len(att.payload) > MAX_ATTACHMENT_BYTES:
        raise ValueError(
            f'Attachment "{att.filename}" is {len(att.payload)} bytes — larger than the '
            f"{MAX_ATTACHMENT_BYTES // (1024 * 1024)} MB download limit."
        )
    return {
        "filename": att.filename,
        "content_type": att.content_type,
        "size": len(att.payload),
        "content_base64": base64.b64encode(att.payload).decode("ascii"),
    }


def message_id(msg: MailMessage) -> str:
    return _first_header(msg, "message-id")


def references(msg: MailMessage) -> list[str]:
    headers: dict[str, tuple[str, ...]] = dict(msg.headers)
    raw = " ".join(headers.get("references", ()))
    return _MSGID_RE.findall(raw)


def _first_header(msg: MailMessage, name: str) -> str:
    headers: dict[str, tuple[str, ...]] = dict(msg.headers)
    values = headers.get(name, ())
    return values[0].strip() if values else ""


def build_email(
    account: AccountConfig,
    to: list[str],
    subject: str,
    body: str,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    html: bool = False,
    in_reply_to: str = "",
    reference_ids: list[str] | None = None,
) -> EmailMessage:
    """Construct an outgoing message with correct threading headers."""
    validate_addresses(to, "recipient")
    validate_addresses(cc or [], "cc")
    validate_addresses(bcc or [], "bcc")
    if not to:
        raise ValueError("At least one recipient is required.")

    message = EmailMessage()
    sender = (
        formataddr((account.display_name, account.email)) if account.display_name else account.email
    )
    message["From"] = sender
    message["To"] = ", ".join(to)
    if cc:
        message["Cc"] = ", ".join(cc)
    if bcc:
        message["Bcc"] = ", ".join(bcc)
    message["Subject"] = subject
    if in_reply_to:
        message["In-Reply-To"] = in_reply_to
        message["References"] = " ".join([*(reference_ids or []), in_reply_to])
    if html:
        message.set_content("This message requires an HTML-capable client.")
        message.add_alternative(body, subtype="html")
    else:
        message.set_content(body)
    return message


def reply_subject(original: str) -> str:
    return original if original.lower().startswith("re:") else f"Re: {original}"


def forward_subject(original: str) -> str:
    return original if original.lower().startswith("fwd:") else f"Fwd: {original}"


def quote_original(msg: MailMessage) -> str:
    date = msg.date.strftime("%Y-%m-%d %H:%M") if msg.date else "an unknown date"
    quoted = "\n".join(f"> {line}" for line in (msg.text or "").splitlines())
    return f"On {date}, {msg.from_} wrote:\n{quoted}"


def forward_block(msg: MailMessage) -> str:
    date = msg.date.strftime("%Y-%m-%d %H:%M") if msg.date else ""
    return (
        "---------- Forwarded message ----------\n"
        f"From: {msg.from_}\n"
        f"Date: {date}\n"
        f"Subject: {msg.subject}\n"
        f"To: {', '.join(msg.to)}\n\n"
        f"{msg.text or ''}"
    )
