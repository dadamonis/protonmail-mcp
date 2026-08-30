"""Guided setup: discover Bridge, collect credentials, write config,
and run a first health check.

All I/O is injectable so the wizard is unit-testable.
"""

import getpass
import json
from collections.abc import Callable, Mapping
from pathlib import Path

from protonmail_mcp.bridge import BridgeInfo, discover, is_bridge_running
from protonmail_mcp.config import default_config_path, load_config

CheckFn = Callable[[str, str, BridgeInfo], list[str]]


def _default_login_check(email: str, password: str, bridge: BridgeInfo) -> list[str]:
    """Try a real IMAP and SMTP login through Bridge. Returns problem
    descriptions (empty = all good)."""
    from pydantic import SecretStr

    from protonmail_mcp.config import AccountConfig
    from protonmail_mcp.connections.manager import default_session_factory
    from protonmail_mcp.connections.smtp import check_login

    account = AccountConfig(email=email, password=SecretStr(password))
    problems = []
    try:
        session = default_session_factory(account, bridge)
        session.logout()
    except Exception as exc:
        problems.append(f"IMAP: {exc}")
    try:
        check_login(account, bridge)
    except Exception as exc:
        problems.append(f"SMTP: {exc}")
    return problems


def _toml_str(value: str) -> str:
    # json.dumps produces a valid TOML basic string (quoting + escapes).
    return json.dumps(value)


def _render_config(accounts: list[dict[str, str]]) -> str:
    blocks = []
    for account in accounts:
        lines = ["[[accounts]]"]
        lines.extend(f"{key} = {_toml_str(value)}" for key, value in account.items() if value)
        blocks.append("\n".join(lines))
    return "# protonmail-mcp configuration\n# Keep this file private: chmod 600\n\n" + (
        "\n\n".join(blocks) + "\n"
    )


def run_setup(
    input_fn: Callable[[str], str] = input,
    getpass_fn: Callable[[str], str] = getpass.getpass,
    print_fn: Callable[[str], None] = print,
    config_path: Path | None = None,
    platform: str | None = None,
    env: Mapping[str, str] | None = None,
    home: Path | None = None,
    login_check: CheckFn = _default_login_check,
) -> int:
    """Interactive account setup. Returns a process exit code."""
    path = config_path or default_config_path()

    print_fn("protonmail-mcp setup")
    print_fn("")

    bridge = discover(platform=platform, env=env, home=home)
    if not bridge.installed:
        print_fn(
            "ProtonMail Bridge was not found on this machine. Install it from "
            "https://proton.me/mail/bridge, log in to your Proton account, and rerun setup."
        )
        return 1

    print_fn(f"Found ProtonMail Bridge data at {bridge.data_dir}")
    print_fn(f"IMAP port {bridge.imap_port}, SMTP port {bridge.smtp_port} ({bridge.ports_source})")
    running = is_bridge_running(port=bridge.imap_port)
    if not running:
        print_fn(
            "Note: Bridge does not appear to be running right now — the connection "
            "check at the end will fail until you start it."
        )
    if bridge.cert_path is None:
        print_fn(
            "Warning: Bridge's cert.pem was not found; connections cannot be "
            "verified until Bridge has generated it."
        )

    print_fn("")
    email = input_fn("Proton email address: ").strip()
    display_name = input_fn("Display name (optional): ").strip()
    name = input_fn("Account name [default]: ").strip() or "default"
    password = getpass_fn(
        "Bridge password (from Bridge → Mailbox details, NOT your Proton password): "
    ).strip()
    if not email or not password:
        print_fn("Email address and bridge password are both required — aborting.")
        return 1

    # Merge with any existing config: replace the same-named account.
    existing: list[dict[str, str]] = []
    if path.is_file():
        current = load_config(path, env={})
        existing = [
            {
                "name": a.name,
                "email": a.email,
                "display_name": a.display_name or "",
                "username": a.username or "",
                "password": a.password.get_secret_value(),
            }
            for a in current.accounts
            if a.name != name
        ]
    accounts = [
        *existing,
        {"name": name, "email": email, "display_name": display_name, "password": password},
    ]

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_render_config(accounts), encoding="utf-8")
    path.chmod(0o600)
    print_fn(f"Wrote {path} (permissions 600)")

    print_fn("")
    print_fn("Checking IMAP and SMTP login through Bridge...")
    problems = login_check(email, password, bridge)
    if problems:
        for problem in problems:
            print_fn(f"  ✗ {problem}")
        print_fn("Setup saved, but the connection check failed — fix the above and retry.")
        return 1
    print_fn("  ✓ IMAP and SMTP logins succeeded. You're ready to go.")
    return 0
