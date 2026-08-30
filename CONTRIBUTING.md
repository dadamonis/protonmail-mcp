# Contributing

## Commit convention

This project uses [Conventional Commits](https://www.conventionalcommits.org/):
`feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`, `ci:`. Breaking
changes to tool names or parameter schemas (the MCP API surface) require a
`!` marker / `BREAKING CHANGE:` footer and a major version bump.

## Quality gates

Run before every push — all must pass:

```bash
uv run ruff format --check . && uv run ruff check .
uv run mypy
uv run pytest
```

## Layout

- `src/protonmail_mcp/services/` — business logic (IMAP/SMTP/Bridge
  discovery); must be unit-testable without any MCP transport or a running
  Bridge.
- `src/protonmail_mcp/tools/` — thin MCP wiring around services.
- `src/protonmail_mcp/config/` — TOML config loading and validation.
- `src/protonmail_mcp/connections/` — connection lifecycle management.

## Security rules

- Never log passwords or full message bodies at `info` level or above.
- Never disable TLS verification (`verify=False` / `ssl.CERT_NONE`); trust
  Bridge's own certificate via an explicit SSL context instead.
- No hardcoded credentials or real email domains in source or tests.
