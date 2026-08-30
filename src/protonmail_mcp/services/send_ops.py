"""Construction of replies, forwards, and drafts.

Reply and forward need the original message, so these run inside the
connection manager's IMAP thread; the actual SMTP send happens
afterwards in the tool layer.
"""

from email.message import EmailMessage

from imap_tools import MailMessageFlags
from imap_tools.mailbox import BaseMailBox

from protonmail_mcp.config import AccountConfig
from protonmail_mcp.services import messages
from protonmail_mcp.services.mail_ops import _fetch_one

DRAFTS_FOLDER = "Drafts"


def build_reply(
    mailbox: BaseMailBox,
    account: AccountConfig,
    folder: str,
    uid: str,
    body: str,
    reply_all: bool = False,
    quote: bool = True,
) -> EmailMessage:
    original = _fetch_one(mailbox, folder, uid)
    to = list(original.reply_to) or [original.from_]
    cc: list[str] = []
    if reply_all:
        own = {account.email.lower()}
        cc = [addr for addr in (*original.to, *original.cc) if addr.lower() not in own]
    full_body = f"{body}\n\n{messages.quote_original(original)}" if quote else body
    return messages.build_email(
        account,
        to=to,
        cc=cc or None,
        subject=messages.reply_subject(original.subject),
        body=full_body,
        in_reply_to=messages.message_id(original),
        reference_ids=messages.references(original),
    )


def build_forward(
    mailbox: BaseMailBox,
    account: AccountConfig,
    folder: str,
    uid: str,
    to: list[str],
    body: str = "",
) -> EmailMessage:
    original = _fetch_one(mailbox, folder, uid)
    parts = [body, messages.forward_block(original)] if body else [messages.forward_block(original)]
    return messages.build_email(
        account,
        to=to,
        subject=messages.forward_subject(original.subject),
        body="\n\n".join(parts),
    )


def save_draft(mailbox: BaseMailBox, message: EmailMessage) -> dict[str, str]:
    mailbox.append(bytes(message), DRAFTS_FOLDER, flag_set=[MailMessageFlags.DRAFT])
    return {"saved_to": DRAFTS_FOLDER, "subject": message["Subject"] or ""}
