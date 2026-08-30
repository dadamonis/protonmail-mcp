# protonmail-mcp

An MCP (Model Context Protocol) server for **ProtonMail**, connected through
[ProtonMail Bridge](https://proton.me/mail/bridge).

Unlike generic IMAP MCP servers, this connector is Bridge-aware: it
auto-detects a local Bridge installation, discovers its configured IMAP/SMTP
ports and TLS certificate, verifies TLS against Bridge's own certificate
(never `verify=False`), and turns Bridge failure modes into actionable error
messages.

> Status: pre-release, under active development. See
> [`tasks/prd-protonmail-mcp-python.md`](https://github.com/codefuturist/email-mcp/blob/main/tasks/prd-protonmail-mcp-python.md)
> in the sibling `email-mcp` repository for the full PRD.

## Prerequisites

- [ProtonMail Bridge](https://proton.me/mail/bridge) installed, running, and
  logged in to your Proton account (Bridge requires a paid Proton plan)
- Python ≥ 3.12 (or just [`uv`](https://docs.astral.sh/uv/), which provisions one)

## Install / Run

```bash
uvx protonmail-mcp          # run the stdio MCP server
uvx protonmail-mcp --version
```

## Development

```bash
uv sync                     # install dependencies (creates .venv)
uv run ruff format --check . && uv run ruff check .   # format + lint
uv run mypy                 # type-check (strict)
uv run pytest               # tests
```

## License

LGPL-3.0-or-later — see [LICENSE](LICENSE).
