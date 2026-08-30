# Project Status

> Start here when picking this project back up. Last updated: **2026-08-30**.
> The full requirements document is [`prd.md`](prd.md); this file is the
> working snapshot: what exists, what was learned the hard way, and what's next.

## What this is

An MCP server (stdio) for ProtonMail via a locally running ProtonMail Bridge.
23 tools (read/search/thread, send/reply/forward/draft, move/delete/mark/
folders, Proton labels-as-folders, diagnostics, ping). Python ≥ 3.12, `uv`,
published from `dadamonis/protonmail-mcp` on GitHub.

**Current state: feature-complete for v0.1, live-verified, NOT yet on PyPI.**

- 123 tests green, `mypy --strict` and ruff clean, CI green on Ubuntu + macOS.
- Live-verified end to end against a real Bridge v3 + real Proton account:
  setup wizard → health check, send arrived in INBOX + Sent, label round-trip
  (chip appeared/disappeared in the web UI), delete-to-Trash, stale-connection
  reconnect.
- Registered in Claude Code (user scope) as `protonmail`, running from this
  repo's source: `uv --directory <this repo> run protonmail-mcp`.

## Architecture map

```
src/protonmail_mcp/
├── server.py          MCPServer instance + ping; calls tools.register(mcp)
├── cli.py             console entry: serve (default) | setup | --version
├── setup_wizard.py    guided setup incl. TLS-cert export flow (injectable I/O)
├── runtime.py         lazy Runtime {config, bridge, manager, smtp_send/check};
│                      set_runtime() for tests
├── config/            pydantic schema (SecretStr passwords, extra=forbid),
│                      TOML loader, PROTONMAIL_MCP_* env overrides, 0600 warning
├── bridge/
│   ├── discovery.py   data-dir per platform, port discovery (prefs.json →
│   │                  1143/1025 fallback), find_cert search order, SSL context
│   │                  pinned to Bridge's cert, TCP probe
│   └── errors.py      BridgeError taxonomy + classify_connection_error()
├── connections/
│   ├── manager.py     lazy per-account IMAP (imap-tools MailBoxStartTls),
│   │                  NOOP health check, per-account asyncio.Lock, reconnect
│   └── smtp.py        per-send SMTP: STARTTLS + pinned cert, login, classify
├── services/          business logic, unit-testable, no MCP imports:
│   ├── messages.py    serialization, EmailMessage building, validation, 5MB cap
│   ├── mail_ops.py    list/get/search/thread/attachment + move/delete/mark/
│   │                  create_mailbox (All Mail guard, Folders/ prefixing)
│   ├── labels.py      Proton labels-as-folders (port of email-mcp strategy)
│   ├── send_ops.py    reply/forward construction, drafts
│   └── health.py      bridge_status / check_health helpers (guidance, no raise)
└── tools/register.py  all MCP tool definitions (thin async wrappers)

tests/conftest.py      FakeMailBox — in-memory imap-tools stand-in used everywhere
```

Layering rule (same as email-mcp): `services/` never import MCP; `tools/` stay
thin. The behavioral reference for Proton semantics is
[email-mcp](https://github.com/codefuturist/email-mcp)
(`src/services/label-strategy.ts`, `src/connections/manager.ts`).

## Hard-won facts (do not re-litigate)

- **mcp SDK is 2.x**: `FastMCP` was renamed → `from mcp.server.mcpserver import MCPServer`;
  client results are snake_case (`server_info`). Pinned `mcp>=2.1`.
- **Bridge v3 stores ports AND its TLS cert inside the encrypted `vault.enc`**
  (verified on a real macOS install — data dir has only vault/gluon/logs, and
  nothing goes to the keychain). Hence: ports fall back to 1143/1025 with a
  logged notice, and the cert requires a one-time export via Bridge →
  Settings → Advanced settings → "Export TLS certificates".
  `find_cert` search order: `$PROTONMAIL_MCP_CERT` → `~/.config/protonmail-mcp/cert.pem`
  → `<data dir>/cert.pem`.
- **TLS verification with full hostname checking passes** against `127.0.0.1`
  using the exported cert as sole trust root — no pinning workaround needed.
  A test (`test_no_disabled_tls_verification_anywhere`) bans
  `CERT_NONE`/`verify=False`/`check_hostname = False` in `src/`.
- **Bridge's real folder names** (confirmed live): `INBOX`, `Sent`, `Trash`,
  `Drafts`, `Spam`, `Archive`, `Starred`, `All Mail` (virtual — mutations
  refused), custom folders `Folders/<name>` (nesting like
  `Folders/my_archive/x`), labels `Labels/<name>` with a `\Noselect`
  `Labels` parent.
- **Bridge password ≠ Proton password**; it changes if the account is
  logged out/in of Bridge (surface: `BridgeAuthError`).
- One IMAP connection cannot interleave commands → every op runs under the
  account's `asyncio.Lock` via `asyncio.to_thread`; connection-level errors
  (`OSError`/`ssl.SSLError`/`IMAP4.abort`) drop the session, command errors don't.

## Dev commands

```bash
uv sync                                   # deps
uv run ruff format --check . && uv run ruff check .
uv run mypy && uv run pytest              # all must pass before "done"
uv run protonmail-mcp setup               # wizard against real Bridge
uv build                                  # dist check
```

Conventional Commits enforced by convention (see CONTRIBUTING.md). MCP tool
names/schemas are public API — renames are breaking changes.

## Next steps

1. **Publish 0.1.0** (user said "not yet" on 2026-08-30): add trusted
   publisher on pypi.org — project `protonmail-mcp`, repo
   `dadamonis/protonmail-mcp`, workflow `release.yml`, environment `pypi` —
   then `git tag 0.1.0 && git push --tags`. Afterwards, re-register the MCP
   client as `uvx protonmail-mcp`.
2. Bump CI actions (`actions/checkout@v5`, `astral-sh/setup-uv@v6`) to clear
   Node-20 deprecation annotations.
3. v1.x candidates from the PRD: batch tools (`get_emails`, `bulk_action`),
   OS-keyring password storage, MCP prompts/resources, dovecot-based
   integration tests with a `Labels/` namespace.
4. Housekeeping: the empty leftover fork `dadamonis/email-mcp` on GitHub can
   be deleted in the web UI.
