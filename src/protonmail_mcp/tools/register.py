"""Registers every MCP tool. Tools stay thin: argument passing, runtime
lookup, and thread handoff — the behavior lives in services/."""

import asyncio
import time
from typing import Any, cast

from imap_tools.mailbox import BaseMailBox
from mcp.server.mcpserver import MCPServer

from protonmail_mcp.connections.manager import ImapSession
from protonmail_mcp.runtime import get_runtime
from protonmail_mcp.services import health, labels, mail_ops, messages, send_ops


def _mb(session: ImapSession) -> BaseMailBox:
    # The manager hands us its minimal session protocol; at runtime it is
    # always an imap_tools mailbox (tests inject compatible fakes).
    return cast(BaseMailBox, session)


def register(mcp: MCPServer) -> None:
    # ------------------------------------------------------------------
    # Reading (US-005)
    # ------------------------------------------------------------------

    @mcp.tool()
    def list_accounts() -> list[dict[str, Any]]:
        """List configured ProtonMail accounts (never includes credentials)."""
        rt = get_runtime()
        return [
            {"name": a.name, "email": a.email, "display_name": a.display_name}
            for a in rt.config.accounts
        ]

    @mcp.tool()
    async def list_mailboxes(account: str = "default") -> list[dict[str, Any]]:
        """List folders with message and unread counts. ProtonMail labels
        appear as folders under Labels/, custom folders under Folders/."""
        rt = get_runtime()
        return await rt.manager.with_imap(account, lambda s: mail_ops.list_mailboxes(_mb(s)))

    @mcp.tool()
    async def list_emails(
        mailbox: str = "INBOX",
        limit: int = 20,
        offset: int = 0,
        unread_only: bool = False,
        from_addr: str | None = None,
        since: str | None = None,
        before: str | None = None,
        account: str = "default",
    ) -> dict[str, Any]:
        """List emails in a folder, newest first, with pagination and
        date/sender/unread filters (dates are ISO YYYY-MM-DD). To list
        emails carrying a ProtonMail label, pass mailbox="Labels/<name>"."""
        rt = get_runtime()
        return await rt.manager.with_imap(
            account,
            lambda s: mail_ops.list_emails(
                _mb(s), mailbox, limit, offset, unread_only, from_addr, since, before
            ),
        )

    @mcp.tool()
    async def get_email(
        uid: str,
        mailbox: str = "INBOX",
        include_html: bool = False,
        mark_seen: bool = False,
        account: str = "default",
    ) -> dict[str, Any]:
        """Read one email in full: body (text preferred), headers, threading
        ids, and attachment metadata."""
        rt = get_runtime()
        return await rt.manager.with_imap(
            account, lambda s: mail_ops.get_email(_mb(s), mailbox, uid, include_html, mark_seen)
        )

    @mcp.tool()
    async def search_emails(
        query: str,
        mailbox: str = "INBOX",
        limit: int = 20,
        account: str = "default",
    ) -> dict[str, Any]:
        """Search a folder by keyword across subject, sender, and body."""
        rt = get_runtime()
        return await rt.manager.with_imap(
            account, lambda s: mail_ops.search_emails(_mb(s), query, mailbox, limit)
        )

    @mcp.tool()
    async def get_thread(
        uid: str, mailbox: str = "INBOX", account: str = "default"
    ) -> dict[str, Any]:
        """Reconstruct the conversation thread around an email via its
        Message-ID / References headers (within the given folder)."""
        rt = get_runtime()
        return await rt.manager.with_imap(
            account, lambda s: mail_ops.get_thread(_mb(s), mailbox, uid)
        )

    @mcp.tool()
    async def download_attachment(
        uid: str, filename: str, mailbox: str = "INBOX", account: str = "default"
    ) -> dict[str, Any]:
        """Download one attachment (base64), capped at 5 MB."""
        rt = get_runtime()
        return await rt.manager.with_imap(
            account, lambda s: mail_ops.download_attachment(_mb(s), mailbox, uid, filename)
        )

    # ------------------------------------------------------------------
    # Sending (US-006)
    # ------------------------------------------------------------------

    @mcp.tool()
    async def send_email(
        to: list[str],
        subject: str,
        body: str,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        html: bool = False,
        account: str = "default",
    ) -> dict[str, Any]:
        """Send a new email through Bridge. Bridge files it into Sent."""
        rt = get_runtime()
        acct = rt.config.get_account(account)
        message = messages.build_email(acct, to, subject, body, cc, bcc, html)
        await asyncio.to_thread(rt.smtp_send, acct, rt.bridge, message)
        return {"sent": True, "to": to, "subject": subject}

    @mcp.tool()
    async def reply_email(
        uid: str,
        body: str,
        mailbox: str = "INBOX",
        reply_all: bool = False,
        quote: bool = True,
        account: str = "default",
    ) -> dict[str, Any]:
        """Reply to an email with correct threading (In-Reply-To/References)
        so the conversation stays intact in ProtonMail."""
        rt = get_runtime()
        acct = rt.config.get_account(account)
        message = await rt.manager.with_imap(
            account,
            lambda s: send_ops.build_reply(_mb(s), acct, mailbox, uid, body, reply_all, quote),
        )
        await asyncio.to_thread(rt.smtp_send, acct, rt.bridge, message)
        return {"sent": True, "in_reply_to": message["In-Reply-To"], "subject": message["Subject"]}

    @mcp.tool()
    async def forward_email(
        uid: str,
        to: list[str],
        body: str = "",
        mailbox: str = "INBOX",
        account: str = "default",
    ) -> dict[str, Any]:
        """Forward an email with the original content quoted."""
        rt = get_runtime()
        acct = rt.config.get_account(account)
        message = await rt.manager.with_imap(
            account, lambda s: send_ops.build_forward(_mb(s), acct, mailbox, uid, to, body)
        )
        await asyncio.to_thread(rt.smtp_send, acct, rt.bridge, message)
        return {"sent": True, "to": to, "subject": message["Subject"]}

    @mcp.tool()
    async def save_draft(
        to: list[str],
        subject: str,
        body: str,
        cc: list[str] | None = None,
        html: bool = False,
        account: str = "default",
    ) -> dict[str, Any]:
        """Save an email as a draft in the Drafts folder without sending."""
        rt = get_runtime()
        acct = rt.config.get_account(account)
        message = messages.build_email(acct, to, subject, body, cc, None, html)
        return await rt.manager.with_imap(account, lambda s: send_ops.save_draft(_mb(s), message))

    # ------------------------------------------------------------------
    # Organisation (US-007)
    # ------------------------------------------------------------------

    @mcp.tool()
    async def move_email(
        uid: str, destination: str, mailbox: str = "INBOX", account: str = "default"
    ) -> dict[str, Any]:
        """Move an email to another folder."""
        rt = get_runtime()
        return await rt.manager.with_imap(
            account, lambda s: mail_ops.move_email(_mb(s), mailbox, uid, destination)
        )

    @mcp.tool()
    async def delete_email(
        uid: str, mailbox: str = "INBOX", permanent: bool = False, account: str = "default"
    ) -> dict[str, Any]:
        """Delete an email: moves it to Trash unless permanent=true.
        Refused on the virtual All Mail folder."""
        rt = get_runtime()
        return await rt.manager.with_imap(
            account, lambda s: mail_ops.delete_email(_mb(s), mailbox, uid, permanent)
        )

    @mcp.tool()
    async def mark_email(
        uid: str,
        mailbox: str = "INBOX",
        read: bool | None = None,
        flagged: bool | None = None,
        account: str = "default",
    ) -> dict[str, Any]:
        """Mark an email read/unread and/or flagged/unflagged."""
        rt = get_runtime()
        return await rt.manager.with_imap(
            account, lambda s: mail_ops.mark_email(_mb(s), mailbox, uid, read, flagged)
        )

    @mcp.tool()
    async def create_mailbox(name: str, account: str = "default") -> dict[str, Any]:
        """Create a folder. Bare names are created under ProtonMail's
        Folders/ namespace; pass an explicit Folders/... or Labels/... path
        to control placement."""
        rt = get_runtime()
        return await rt.manager.with_imap(account, lambda s: mail_ops.create_mailbox(_mb(s), name))

    # ------------------------------------------------------------------
    # Labels (US-008)
    # ------------------------------------------------------------------

    @mcp.tool()
    async def list_labels(account: str = "default") -> list[dict[str, Any]]:
        """List ProtonMail labels. Labels are IMAP folders under Labels/ —
        use list_emails with mailbox="Labels/<name>" to see tagged mail."""
        rt = get_runtime()
        return await rt.manager.with_imap(account, lambda s: labels.list_labels(_mb(s)))

    @mcp.tool()
    async def add_label(
        uid: str, label: str, mailbox: str = "INBOX", account: str = "default"
    ) -> dict[str, Any]:
        """Add a ProtonMail label to an email (copies it into the
        Labels/<name> folder — that is how Bridge represents labels)."""
        rt = get_runtime()
        return await rt.manager.with_imap(
            account, lambda s: labels.add_label(_mb(s), mailbox, uid, label)
        )

    @mcp.tool()
    async def remove_label(
        uid: str, label: str, mailbox: str = "INBOX", account: str = "default"
    ) -> dict[str, Any]:
        """Remove a ProtonMail label from an email (deletes its copy from
        the Labels/<name> folder, located by Message-ID)."""
        rt = get_runtime()
        return await rt.manager.with_imap(
            account, lambda s: labels.remove_label(_mb(s), mailbox, uid, label)
        )

    @mcp.tool()
    async def create_label(name: str, account: str = "default") -> dict[str, Any]:
        """Create a new ProtonMail label (a folder under Labels/)."""
        rt = get_runtime()
        return await rt.manager.with_imap(account, lambda s: labels.create_label(_mb(s), name))

    @mcp.tool()
    async def delete_label(name: str, account: str = "default") -> dict[str, Any]:
        """Delete a ProtonMail label (removes the Labels/<name> folder)."""
        rt = get_runtime()
        return await rt.manager.with_imap(account, lambda s: labels.delete_label(_mb(s), name))

    # ------------------------------------------------------------------
    # Diagnostics (US-009)
    # ------------------------------------------------------------------

    @mcp.tool()
    def bridge_status() -> dict[str, Any]:
        """Report on the local ProtonMail Bridge: installed, running,
        ports, certificate, and configured accounts."""
        rt = get_runtime()
        return health.bridge_status(rt.bridge, rt.config)

    @mcp.tool()
    async def check_health(account: str | None = None) -> dict[str, Any]:
        """Check IMAP and SMTP connectivity (with latency) for one account
        or all of them. Returns guidance instead of failing when Bridge is
        down."""
        rt = get_runtime()
        names = [account] if account else [a.name for a in rt.config.accounts]
        report: dict[str, Any] = {"bridge": health.bridge_status(rt.bridge, rt.config)}
        accounts: dict[str, Any] = {}
        for name in names:
            entry: dict[str, Any] = {}
            try:
                entry["imap"] = await rt.manager.with_imap(
                    name, lambda s: health.imap_health_op(_mb(s))
                )
            except Exception as exc:
                entry["imap"] = health.failure(exc)
            try:
                acct = rt.config.get_account(name)
                started = time.monotonic()
                await asyncio.to_thread(rt.smtp_check, acct, rt.bridge)
                entry["smtp"] = {
                    "ok": True,
                    "latency_ms": round((time.monotonic() - started) * 1000, 1),
                }
            except Exception as exc:
                entry["smtp"] = health.failure(exc)
            accounts[name] = entry
        report["accounts"] = accounts
        return report
