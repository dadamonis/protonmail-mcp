# protonmail-mcp

An MCP (Model Context Protocol) server for **ProtonMail**, connected through
[ProtonMail Bridge](https://proton.me/mail/bridge).

Unlike generic IMAP MCP servers, this connector is **Bridge-aware**:

- Auto-detects a local Bridge install and discovers its IMAP/SMTP ports and
  TLS certificate.
- Verifies TLS against Bridge's own certificate — **never `verify=False`**
  (enforced by a test that scans the source tree).
- Understands ProtonMail's model: labels are folders under `Labels/`, custom
  folders live under `Folders/`, and destructive operations on the virtual
  `All Mail` view are refused with an explanation.
- Turns every Bridge failure mode into an actionable message: *not
  installed*, *not running*, *wrong bridge password*, *certificate mismatch*.

## Prerequisites

- [ProtonMail Bridge](https://proton.me/mail/bridge) installed, running, and
  logged in (Bridge requires a paid Proton plan).
- Python ≥ 3.12, or just [`uv`](https://docs.astral.sh/uv/) — it provisions
  Python for you.

## Install

```bash
# Guided setup: discovers Bridge, writes config, checks the login
uvx protonmail-mcp setup

# Run the MCP server (stdio)
uvx protonmail-mcp
```

### MCP client configuration

Claude Code:

```bash
claude mcp add protonmail -- uvx protonmail-mcp
```

Claude Desktop (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "protonmail": {
      "command": "uvx",
      "args": ["protonmail-mcp"]
    }
  }
}
```

## Configuration

`~/.config/protonmail-mcp/config.toml` (created by `setup`, permissions 600):

```toml
[[accounts]]
name = "default"
email = "you@proton.me"
display_name = "Your Name"
password = "<bridge password from Bridge → Mailbox details>"
# Optional — only needed when Bridge uses non-default ports:
# imap = { port = 1143 }
# smtp = { port = 1025 }
```

Multiple `[[accounts]]` blocks are supported; tools take an `account`
parameter (default `"default"`).

Environment variables configure a single account without a file:
`PROTONMAIL_MCP_ADDRESS`, `PROTONMAIL_MCP_PASSWORD`, and optionally
`PROTONMAIL_MCP_USERNAME`, `PROTONMAIL_MCP_ACCOUNT_NAME`,
`PROTONMAIL_MCP_IMAP_HOST`, `PROTONMAIL_MCP_IMAP_PORT`,
`PROTONMAIL_MCP_SMTP_HOST`, `PROTONMAIL_MCP_SMTP_PORT`.

## Tools

### Reading

| Tool | Description |
|---|---|
| `list_accounts` | List configured accounts (no credentials) |
| `list_mailboxes` | Folders with message/unread counts |
| `list_emails` | Paginated listing with unread/sender/date filters; `mailbox="Labels/<name>"` lists labeled mail |
| `get_email` | Full body, headers, threading ids, attachment metadata |
| `search_emails` | Keyword search across subject, sender, and body |
| `get_thread` | Conversation reconstruction via Message-ID/References |
| `download_attachment` | One attachment, base64, capped at 5 MB |

### Sending

| Tool | Description |
|---|---|
| `send_email` | New email (text or HTML, cc/bcc); Bridge files it into Sent |
| `reply_email` | Reply with In-Reply-To/References threading, quoting, reply-all |
| `forward_email` | Forward with the original quoted |
| `save_draft` | Save to Drafts without sending |

### Organisation

| Tool | Description |
|---|---|
| `move_email` | Move between folders |
| `delete_email` | To Trash by default; permanent only with `permanent=true`; refused on All Mail |
| `mark_email` | Read/unread, flagged/unflagged |
| `create_mailbox` | New folder (bare names go under `Folders/`) |

### ProtonMail labels

| Tool | Description |
|---|---|
| `list_labels` | Labels (folders under `Labels/`) |
| `add_label` | Copy the email into `Labels/<name>` |
| `remove_label` | Delete the email's copy from the label folder (located by Message-ID) |
| `create_label` / `delete_label` | Manage label folders |

### Diagnostics

| Tool | Description |
|---|---|
| `bridge_status` | Bridge install, ports (and how they were discovered), certificate, accounts |
| `check_health` | IMAP + SMTP login and latency per account; structured guidance when Bridge is down |
| `ping` | Server liveness |

## Security

- All Bridge connections use STARTTLS, verified against Bridge's own
  self-signed certificate loaded as the *only* trust root (certificate
  pinning). TLS verification is never disabled.
- Passwords live in a `chmod 600` config file (or env vars) and are never
  logged; validation errors name keys, not values.
- Message bodies are never logged at info level or above.
- Attachment downloads are capped at 5 MB.
- Everything stays on 127.0.0.1 — this server talks only to your local
  Bridge, never to Proton's servers directly.

## Development

```bash
uv sync
uv run ruff format --check . && uv run ruff check .
uv run mypy
uv run pytest
```

Conventional Commits are required — see [CONTRIBUTING.md](CONTRIBUTING.md).
The product requirements, including live-verification results against a
real Bridge v3 install, live in [`docs/prd.md`](docs/prd.md). The
behavioral reference for Proton label semantics is the sibling
[email-mcp](https://github.com/codefuturist/email-mcp) TypeScript server.

**Bridge v3 notes** (verified against a real install):

- Port settings live in Bridge's encrypted vault, so discovery falls back to
  the defaults (1143/1025) with a logged notice; override ports in the
  config if you changed them in Bridge.
- The TLS certificate also lives in the vault and must be exported once:
  Bridge → Settings → Advanced settings → "Export TLS certificates", saving
  `cert.pem` to `~/.config/protonmail-mcp/` (or set `PROTONMAIL_MCP_CERT`
  to its location). The `setup` wizard walks you through this.

## License

LGPL-3.0-or-later — see [LICENSE](LICENSE).
