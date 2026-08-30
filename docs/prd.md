# PRD: ProtonMail MCP Connector (Python)

> **Status (2026-08-30): implemented and live-verified.** All ten user
> stories are built in this repo (123 tests, strict mypy + ruff clean; CI
> green on Ubuntu and macOS). End-to-end verification ran against a real
> Bridge v3 install and a real Proton account: setup wizard → health check,
> a live send that landed in INBOX and Sent, and the full label round-trip
> (chip appeared and disappeared in the ProtonMail web UI). Remaining:
> configure PyPI trusted publishing and tag `0.1.0`. See the resolved Open
> Questions at the bottom for findings that superseded parts of this
> document.
>
> This document was authored in the sibling
> [email-mcp](https://github.com/codefuturist/email-mcp) repository (the
> TypeScript reference implementation) and moved here; relative source
> paths in the text refer to email-mcp unless stated otherwise.

## Introduction / Overview

Build a dedicated MCP (Model Context Protocol) server for **ProtonMail**, written in **Python**, that connects through **ProtonMail Bridge** — the local IMAP/SMTP proxy Proton requires for third-party mail clients.

The existing TypeScript server, [email-mcp](https://github.com/codefuturist/email-mcp), is a generic multi-provider email server that treats Bridge as "just another IMAP server": a static preset pointing at `127.0.0.1:1143/1025` with SSL verification disabled (`src/cli/providers.ts:117-135`), plus a runtime-detected label strategy for Proton's `Labels/` folder convention (`src/services/label-strategy.ts`). That works, but it leaves Bridge-specific problems on the user: wrong ports when Bridge is configured differently, cryptic connection errors when Bridge isn't running, and blanket-disabled TLS verification.

This project produces a **Proton-first** connector that solves those problems natively: it auto-detects Bridge, discovers its actual ports and certificate from Bridge's local configuration, verifies TLS against Bridge's own cert instead of disabling verification, and returns actionable errors ("Bridge is not running — start it and retry") instead of raw socket failures. The tool surface is a curated core-email MVP (~21 tools) whose names and parameter shapes follow `email-mcp` conventions so users of the TS server feel at home.

**This PRD covers this repository** (`protonmail-mcp`, originally planned as a sibling of email-mcp). The `email-mcp` repo is the behavioral reference; no changes are made to it.

## Goals

- Ship a working MCP server (stdio transport) that reads, searches, sends, organises, and labels ProtonMail email through a locally running Bridge.
- Zero-config happy path: with Bridge running and one account configured in it, `uvx protonmail-mcp setup` detects Bridge, discovers ports and cert, and only asks for the Bridge password.
- TLS verification **on** by default, trusting Bridge's self-signed certificate explicitly (custom SSL context) — never `verify=False`.
- Every Bridge-related failure mode (not installed, not running, wrong password, port mismatch, cert changed) produces a distinct, actionable error message.
- Proton label semantics (labels-as-`Labels/`-folders) work identically to the reference implementation in `email-mcp`.
- Installable and runnable via `uvx protonmail-mcp` from PyPI; multi-account capable.

## User Stories

### US-001: Project scaffolding
**Description:** As a developer, I need a runnable Python project skeleton so all later stories have a home with quality gates wired in.

**Acceptance Criteria:**
- [ ] New repo initialised with `uv` + `pyproject.toml`; package name `protonmail_mcp`; Python ≥ 3.12; license LGPL-3.0-or-later (matching email-mcp)
- [ ] Depends on the official `mcp` Python SDK; a FastMCP server starts over stdio and answers `initialize` with a server name/description
- [ ] One placeholder tool (e.g. `ping`) callable via MCP Inspector or a scripted stdio client
- [ ] `ruff check`, `ruff format --check`, `mypy --strict` (or pyright strict), and `pytest` all run clean via documented commands
- [ ] Conventional-commit convention documented in CONTRIBUTING/README (mirrors email-mcp's cocogitto usage)

### US-002: Configuration loading
**Description:** As a user, I want my accounts defined in a config file with env-var overrides so the server knows how to log in without hardcoding secrets.

**Acceptance Criteria:**
- [ ] TOML config read from `~/.config/protonmail-mcp/config.toml` (XDG-compliant, `XDG_CONFIG_HOME` respected), schema-validated (pydantic) with clear error messages naming the offending key
- [ ] Multi-account: `[[accounts]]` array with `name`, `email`, `username`, `password`, optional per-account `imap`/`smtp` host/port overrides
- [ ] Env-var overrides for a single default account (`PROTONMAIL_MCP_ADDRESS`, `PROTONMAIL_MCP_PASSWORD`, `PROTONMAIL_MCP_IMAP_PORT`, `PROTONMAIL_MCP_SMTP_PORT`) work with no config file present
- [ ] Config file created by the server/CLI gets `0600` permissions; a warning is emitted if an existing config is group/world-readable
- [ ] Passwords never appear in logs or MCP error payloads (unit test asserts this)
- [ ] Typecheck/lint/tests pass

### US-003: Bridge detection and discovery
**Description:** As a user, I want the connector to find my Bridge installation, its actual IMAP/SMTP ports, and its TLS certificate automatically so I don't copy settings by hand.

**Acceptance Criteria:**
- [ ] Discovery module locates Bridge's data directory per platform (macOS: `~/Library/Application Support/protonmail/bridge-v3/`, Linux: `~/.config/protonmail/bridge-v3/`, Windows: `%APPDATA%/protonmail/bridge-v3/`) and reads configured IMAP/SMTP ports from Bridge's config; falls back to defaults `1143`/`1025` when discovery fails, with a logged notice
- [ ] Bridge's self-signed TLS certificate (`cert.pem` in the Bridge data dir) is loaded into an `ssl.SSLContext` used for STARTTLS verification; connections verify against it (no `verify=False` anywhere in the codebase — enforced by a grep-style test)
- [ ] "Is Bridge running?" check via TCP probe of the discovered IMAP port, exposed as a reusable function
- [ ] Distinct, actionable error strings for: Bridge not installed (no data dir), Bridge installed but not running, port probe succeeds but auth fails (wrong Bridge password), certificate mismatch
- [ ] Discovery paths/format verified against a real installed Bridge v3 and documented in the repo (exact filenames may differ per Bridge version — see Open Questions)
- [ ] Unit tests cover discovery with fixture directories for all three platforms; typecheck/lint pass

### US-004: IMAP connection manager
**Description:** As a developer, I need lazy, reusable, self-healing IMAP connections per account so tool calls are fast and resilient (mirrors `email-mcp`'s `src/connections/manager.ts`).

**Acceptance Criteria:**
- [ ] First tool call per account opens an IMAP connection (STARTTLS with the Bridge SSL context from US-003); subsequent calls reuse it
- [ ] Dead/stale connections are detected, closed, and transparently reopened on next use
- [ ] Connection errors are translated through the US-003 error classifier before reaching the MCP client
- [ ] Graceful shutdown logs out all connections
- [ ] Concurrency-safe within the server's async model (no interleaved commands on one connection; lock or per-account serialization)
- [ ] Unit tests with a fake/mocked IMAP layer cover reuse, reconnect, and shutdown; typecheck/lint pass

### US-005: Reading, listing, and searching email
**Description:** As an AI-assistant user, I want to list mailboxes, browse and read messages, follow threads, and download attachments from my ProtonMail account.

**Acceptance Criteria:**
- [ ] Tools implemented: `list_accounts`, `list_mailboxes` (with unread counts and special-use flags), `list_emails` (pagination + since/before/from/unread filters), `get_email` (full body, text preferred, attachment metadata), `search_emails` (subject/sender/body keyword), `get_thread` (walks References/In-Reply-To), `download_attachment` (base64, size-capped at 5 MB like email-mcp)
- [ ] Tool names, parameter names, and result shapes follow the email-mcp equivalents (documented divergences only)
- [ ] `list_emails` documents that `mailbox="Labels/<name>"` lists mail carrying that Proton label
- [ ] Message bodies are never logged at info level or above
- [ ] Unit tests against mocked IMAP responses; manual verification against a live Bridge account documented in PR; typecheck/lint pass

### US-006: Sending email
**Description:** As an AI-assistant user, I want to send new mail, reply with correct threading, forward with quoted content, and save drafts through Bridge's SMTP.

**Acceptance Criteria:**
- [ ] Tools implemented: `send_email` (text or HTML, cc/bcc), `reply_email` (sets In-Reply-To and References from the original), `forward_email` (quotes original), `save_draft` (APPENDs to the Drafts mailbox via IMAP)
- [ ] SMTP uses STARTTLS with the Bridge SSL context; wrong-password and bridge-down failures surface the US-003 actionable errors
- [ ] Sent messages appear in the account's Sent folder (Bridge handles this; verified manually)
- [ ] Recipient addresses validated before send; a send to an invalid address fails with a clear message, not a stack trace
- [ ] Unit tests for message construction (headers, threading, MIME multipart); manual live-Bridge send verified; typecheck/lint pass

### US-007: Organising email
**Description:** As an AI-assistant user, I want to move, delete, flag, and file messages so my mailbox stays organised.

**Acceptance Criteria:**
- [ ] Tools implemented: `move_email`, `delete_email` (move to Trash by default; permanent delete only with an explicit `permanent: true` flag), `mark_email` (read/unread, flag/unflag), `create_mailbox` (under Proton's `Folders/` namespace when appropriate)
- [ ] Deleting from `All Mail` is rejected with an explanatory error (Proton's All Mail is a virtual view)
- [ ] Each mutation returns the affected UID(s) and target mailbox in its result
- [ ] Unit tests with mocked IMAP; typecheck/lint pass

### US-008: Proton label tools
**Description:** As a ProtonMail user, I want label operations that understand Bridge's labels-as-folders model, matching the semantics already proven in email-mcp's `src/services/label-strategy.ts`.

**Acceptance Criteria:**
- [ ] `list_labels` returns folders under `Labels/` (excluding `\Noselect`), names stripped of the prefix
- [ ] `add_label` copies the message into `Labels/<name>` and reports failure when the server rejects the COPY
- [ ] `remove_label` fetches the message's Message-ID, finds matching UID(s) inside `Labels/<name>`, and deletes them there; errors clearly when the message isn't in the label
- [ ] `create_label` / `delete_label` create/delete the `Labels/<name>` mailbox
- [ ] Tool descriptions explain the folder-based model and point to `list_emails` with `mailbox="Labels/<name>"` for finding labeled mail
- [ ] Unit tests mirror the scenarios covered by email-mcp's label tests; typecheck/lint pass

### US-009: Health and Bridge diagnostics
**Description:** As a user, I want one command that tells me whether everything between the MCP client and Proton's servers is healthy, and what to fix if not.

**Acceptance Criteria:**
- [ ] `check_health` reports, per account: Bridge reachable (yes/no), IMAP login + latency, SMTP login + latency, mailbox count
- [ ] `bridge_status` reports: Bridge installed (path), running (port probe), discovered IMAP/SMTP ports, certificate found and loaded, config source (discovered vs manual vs defaults)
- [ ] With Bridge stopped, both tools return structured "Bridge not running" guidance rather than raising
- [ ] A `setup` CLI subcommand (`protonmail-mcp setup`) runs discovery, prompts for email + Bridge password, writes the config, and runs `check_health` — mirroring email-mcp's guided wizard
- [ ] Typecheck/lint/tests pass

### US-010: Packaging, CI, and release
**Description:** As a user, I want to run the server with `uvx protonmail-mcp` and add it to my MCP client config in one line.

**Acceptance Criteria:**
- [ ] `pyproject.toml` exposes the `protonmail-mcp` console script (server by default; `setup` subcommand from US-009)
- [ ] Published to PyPI; `uvx protonmail-mcp` starts the stdio server on a clean machine with Python ≥ 3.12
- [ ] README documents: Bridge prerequisite, install, setup wizard, Claude Desktop / Claude Code MCP client config snippet, full tool table, security notes
- [ ] GitHub Actions CI: ruff + typecheck + pytest on Linux and macOS; release workflow publishes on tag (trusted publishing)
- [ ] CI is green on main

## Functional Requirements

**Connection & Bridge**
- FR-1: The server must communicate with ProtonMail exclusively through ProtonMail Bridge's local IMAP and SMTP endpoints; it must never call Proton's web API or remote servers directly.
- FR-2: The server must discover Bridge's data directory per platform and read the configured IMAP/SMTP ports from it, falling back to `127.0.0.1:1143` (IMAP) and `127.0.0.1:1025` (SMTP) when discovery fails.
- FR-3: All IMAP and SMTP connections must use STARTTLS with certificate verification against Bridge's own certificate loaded into a custom SSL context. `verify=False` / `ssl.CERT_NONE` must not appear in the codebase.
- FR-4: When a connection fails, the server must classify the failure (Bridge not installed / not running / auth failed / cert mismatch / port mismatch) and return the matching actionable message.
- FR-5: IMAP connections must be created lazily per account, reused across tool calls, and transparently re-established when stale.

**Configuration**
- FR-6: Configuration must load from `~/.config/protonmail-mcp/config.toml` (XDG-aware) with env-var overrides for a single account; multiple accounts must be supported via a config array.
- FR-7: Credentials must never be written to logs or included in MCP error payloads; config files created by the tool must have `0600` permissions.

**Tools**
- FR-8: The server must expose exactly the 21 MVP tools listed in this PRD's user stories (US-005 through US-009), with names and parameter shapes consistent with email-mcp where behavior matches.
- FR-9: Label operations must implement the labels-as-folders model: list/add/remove/create/delete against the `Labels/` IMAP namespace, with `remove_label` locating the copy in the label folder by Message-ID.
- FR-10: `delete_email` must default to moving to Trash; permanent deletion requires an explicit parameter. Destructive operations on the `All Mail` virtual folder must be rejected with an explanation.
- FR-11: `reply_email` must set In-Reply-To and References headers so threads render correctly in ProtonMail's UI.
- FR-12: Attachment downloads must be capped at 5 MB and returned base64-encoded.

**Distribution**
- FR-13: The package must be runnable via `uvx protonmail-mcp` (stdio transport) and provide a `setup` subcommand implementing the guided wizard.

## Non-Goals (Out of Scope)

- Email scheduling, IMAP IDLE watcher, AI triage/presets, desktop/webhook notifications
- Calendar (ICS) extraction, reminders, analytics, templates
- MCP prompts and resources beyond basic server metadata (may come in v2)
- OAuth2 (Bridge authenticates with an app-specific bridge password; there is no OAuth surface)
- Support for any provider other than ProtonMail via Bridge (no Gmail/Outlook/generic IMAP)
- Streamable HTTP transport, Docker images (stdio + PyPI only for v1)
- Bridge lifecycle management: installing, launching, logging into, or restarting Bridge; driving Bridge's CLI
- Changes to the existing `email-mcp` TypeScript repo

## Design Considerations

- **API familiarity**: tool names/shapes track email-mcp so documentation and user muscle-memory transfer; divergences (e.g. `bridge_status`) are Proton-specific additions.
- **Error UX is the product**: the connector's main differentiator over generic IMAP MCP servers is that every Bridge failure mode explains itself. Error strings should name the fix ("Start ProtonMail Bridge and retry", "Re-copy the bridge password from Bridge → Mailbox details").
- **Layering (mirrors email-mcp)**: `services/` (IMAP/SMTP/bridge-discovery business logic, unit-testable with no MCP dependency), `tools/` (thin MCP wiring), `config/`, `connections/`. Services must be testable without a running Bridge.

## Technical Considerations

- **Stack**: Python ≥ 3.12, `uv`, official `mcp` SDK (pinned `>=2.1` — SDK v2 renamed `FastMCP` to `MCPServer`, imported from `mcp.server.mcpserver`), pydantic for config/schemas, `imap-tools` 1.15 (`MailBoxStartTls`), stdlib `smtplib`, ruff + mypy strict + pytest.
- **Reference implementations to port** (read before implementing):
  - `email-mcp/src/services/label-strategy.ts` — ProtonMail label strategy (the exact COPY / Message-ID-search / delete flow)
  - `email-mcp/src/connections/manager.ts` — lazy connection manager semantics
  - `email-mcp/src/cli/providers.ts:117-135` — Bridge default ports and STARTTLS settings
  - `email-mcp/src/tools/label.tool.ts`, `emails.tool.ts` — tool descriptions that teach the AI client Proton's label model
- **Bridge cert trust** *(updated after live verification)*: Bridge v3 does **not** write `cert.pem` to its data dir — the certificate lives inside the encrypted `vault.enc` and must be exported once via Bridge → Settings → Advanced settings → "Export TLS certificates". The connector searches `$PROTONMAIL_MCP_CERT`, then `~/.config/protonmail-mcp/cert.pem` (the wizard-suggested export target), then the legacy data-dir path, and loads the cert as the sole trust root. Empirically, full verification **including hostname checking** passes against `127.0.0.1` — no `check_hostname = False` pinning fallback was needed.
- **Concurrency**: FastMCP handlers are async; a single IMAP connection cannot multiplex commands. Serialize per-account IMAP access with an `asyncio.Lock` (sync imaplib calls go through `asyncio.to_thread`).
- **Bridge version drift**: directory names (`bridge-v3`) and config format have changed across Bridge major versions; discovery must degrade gracefully to defaults and say so.

## Success Metrics

- With Bridge running: `uvx protonmail-mcp setup` to a working `check_health` in under 2 minutes, entering only email + bridge password.
- With Bridge stopped: 100% of tool calls return the actionable "Bridge not running" message; zero raw `ConnectionRefusedError` tracebacks reach the MCP client.
- Zero `verify=False`/`CERT_NONE` in the codebase (CI-enforced).
- Label add/remove round-trip is visible in the ProtonMail web UI (label chip appears/disappears).
- All 21 tools pass an end-to-end smoke test against a live Bridge account.

## Open Questions — resolutions (2026-08-30)

1. **Naming** — ✅ resolved: `protonmail-mcp`. Checked PyPI: `protonmail-mcp` returns 404 (free); `proton-bridge-mcp` is taken.
2. **Password storage** — ✅ resolved as proposed: config file with `0600` perms in v1 (wizard enforces it and the loader warns on loose permissions); keyring remains a possible v1.x enhancement.
3. **Bridge config format** — ✅ resolved against a real Bridge v3 install on macOS: the data dir contains only `vault.enc`, `gluon/`, `logs/`, etc. Ports and the TLS certificate are inside the encrypted vault; `prefs.json` does not exist on v3 (kept as a best-effort read for v2 layouts). Port discovery therefore falls back to 1143/1025 with a logged notice and a config override; the certificate requires the one-time UI export (see Technical Considerations).
4. **Batch tools** — resolved for v1: not included. Single-message operations proved sufficient for the MVP surface; `get_emails`/`bulk_action` remain v1.x candidates.
5. **Integration testing** — resolved for v1: no Bridge-in-CI. Unit tests run against an in-memory fake mailbox; live-Bridge verification is a documented manual step and was performed successfully (send → INBOX + Sent, label round-trip visible in the web UI, reconnect path exercised). A dovecot fixture with a `Labels/` namespace remains an option if regressions warrant it.

### Deviations from this PRD

- The SDK class is `MCPServer` (mcp 2.x), not `FastMCP` — upstream rename, same API shape.
- The tool count is 23: the 22 tools listed in the user stories plus the `ping` liveness tool retained from US-001 scaffolding (FR-8 said "exactly the 21 MVP tools"; the stories actually enumerate 22).
- `AccountConfig` gained an optional `display_name` field (used for the From header), mirroring email-mcp's `full_name`.
