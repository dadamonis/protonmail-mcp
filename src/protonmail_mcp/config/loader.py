"""Config file loading: TOML + environment-variable overrides.

Precedence: environment variables > config file > defaults. Env vars
describe a single account (the common Bridge setup); the config file
supports any number.
"""

import logging
import os
import stat
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from protonmail_mcp.config.schema import Config

logger = logging.getLogger(__name__)

ENV_PREFIX = "PROTONMAIL_MCP_"


class ConfigError(Exception):
    """Invalid or unreadable configuration. Messages never include
    configured values — only key paths — so secrets cannot leak."""


def default_config_path() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "protonmail-mcp" / "config.toml"


def _check_permissions(path: Path) -> None:
    mode = path.stat().st_mode
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        logger.warning(
            "Config file %s is readable by other users (mode %o). "
            "It contains your Bridge password — run: chmod 600 %s",
            path,
            stat.S_IMODE(mode),
            path,
        )


def _format_validation_error(err: ValidationError) -> str:
    # include_input=False keeps passwords and other values out of the message.
    lines = []
    for item in err.errors(include_url=False, include_input=False):
        location = ".".join(str(part) for part in item["loc"]) or "(root)"
        lines.append(f"  {location}: {item['msg']}")
    return "Invalid configuration:\n" + "\n".join(lines)


def _account_from_env(env: Mapping[str, str]) -> dict[str, Any] | None:
    address = env.get(f"{ENV_PREFIX}ADDRESS")
    password = env.get(f"{ENV_PREFIX}PASSWORD")
    if not address and not password:
        return None
    if not (address and password):
        raise ConfigError(
            f"Both {ENV_PREFIX}ADDRESS and {ENV_PREFIX}PASSWORD must be set "
            "to configure an account from the environment."
        )

    account: dict[str, Any] = {
        "name": env.get(f"{ENV_PREFIX}ACCOUNT_NAME", "default"),
        "email": address,
        "password": password,
    }
    if username := env.get(f"{ENV_PREFIX}USERNAME"):
        account["username"] = username
    for proto in ("imap", "smtp"):
        endpoint: dict[str, Any] = {}
        if host := env.get(f"{ENV_PREFIX}{proto.upper()}_HOST"):
            endpoint["host"] = host
        if port := env.get(f"{ENV_PREFIX}{proto.upper()}_PORT"):
            try:
                endpoint["port"] = int(port)
            except ValueError as exc:
                raise ConfigError(f"{ENV_PREFIX}{proto.upper()}_PORT must be an integer.") from exc
        if endpoint:
            account[proto] = endpoint
    return account


def _read_config_file(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ConfigError(f"Cannot read config file {path}: {exc.strerror}") from exc
    try:
        return tomllib.loads(raw.decode("utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise ConfigError(f"Config file {path} is not valid TOML: {exc}") from exc


def load_config(
    path: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> Config:
    """Load configuration from ``path`` (default: XDG location) and apply
    environment overrides. Works with no config file at all when the
    account is fully described by environment variables."""
    if env is None:
        env = os.environ
    if path is None:
        path = default_config_path()

    data: dict[str, Any] = {}
    if path.is_file():
        _check_permissions(path)
        data = _read_config_file(path)

    accounts: list[dict[str, Any]] = list(data.get("accounts", []))
    if env_account := _account_from_env(env):
        # Replace the file-defined account of the same name, else prepend.
        existing = next(
            (
                i
                for i, account in enumerate(accounts)
                if isinstance(account, dict)
                and account.get("name", "default") == env_account["name"]
            ),
            None,
        )
        if existing is None:
            accounts.insert(0, env_account)
        else:
            merged = {**accounts[existing], **env_account}
            accounts[existing] = merged
    data["accounts"] = accounts

    try:
        return Config.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(_format_validation_error(exc)) from exc
