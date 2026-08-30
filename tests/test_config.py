"""Tests for config schema and loader."""

import logging
from pathlib import Path

import pytest

from protonmail_mcp.config import ConfigError, load_config
from protonmail_mcp.config.loader import default_config_path

VALID_TOML = """
[[accounts]]
name = "personal"
email = "user@pm.local"
password = "bridge-pass-123"

[[accounts]]
name = "work"
email = "work@pm.local"
username = "work-bridge-user"
password = "bridge-pass-456"
imap = { port = 2143 }
smtp = { port = 2025 }
"""


def write_config(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(content)
    path.chmod(0o600)
    return path


def test_load_valid_config(tmp_path: Path) -> None:
    config = load_config(write_config(tmp_path, VALID_TOML), env={})
    assert [a.name for a in config.accounts] == ["personal", "work"]

    personal = config.get_account("personal")
    assert personal.effective_username == "user@pm.local"
    assert personal.imap.host == "127.0.0.1"
    assert personal.imap.port is None  # discovered later

    work = config.get_account("work")
    assert work.effective_username == "work-bridge-user"
    assert work.imap.port == 2143
    assert work.smtp.port == 2025


def test_missing_config_file_and_no_env_gives_empty_config(tmp_path: Path) -> None:
    config = load_config(tmp_path / "nope.toml", env={})
    assert config.accounts == []


def test_env_only_account(tmp_path: Path) -> None:
    env = {
        "PROTONMAIL_MCP_ADDRESS": "env@pm.local",
        "PROTONMAIL_MCP_PASSWORD": "env-pass",
        "PROTONMAIL_MCP_IMAP_PORT": "3143",
    }
    config = load_config(tmp_path / "nope.toml", env=env)
    account = config.get_account("default")
    assert account.email == "env@pm.local"
    assert account.imap.port == 3143
    assert account.smtp.port is None


def test_env_overrides_file_account_with_same_name(tmp_path: Path) -> None:
    toml = """
[[accounts]]
name = "default"
email = "file@pm.local"
password = "file-pass"
imap = { port = 1143 }
"""
    env = {
        "PROTONMAIL_MCP_ADDRESS": "env@pm.local",
        "PROTONMAIL_MCP_PASSWORD": "env-pass",
    }
    config = load_config(write_config(tmp_path, toml), env=env)
    assert len(config.accounts) == 1
    account = config.get_account("default")
    assert account.email == "env@pm.local"
    # Field not present in env keeps the file value.
    assert account.imap.port == 1143


def test_partial_env_account_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="PROTONMAIL_MCP_PASSWORD"):
        load_config(tmp_path / "nope.toml", env={"PROTONMAIL_MCP_ADDRESS": "x@pm.local"})


def test_validation_error_names_key_but_not_value(tmp_path: Path) -> None:
    toml = """
[[accounts]]
name = "broken"
email = "not-an-email"
password = "super-secret-value"
"""
    with pytest.raises(ConfigError) as excinfo:
        load_config(write_config(tmp_path, toml), env={})
    message = str(excinfo.value)
    assert "email" in message
    assert "super-secret-value" not in message
    assert "not-an-email" not in message


def test_duplicate_account_names_rejected(tmp_path: Path) -> None:
    toml = """
[[accounts]]
name = "dup"
email = "a@pm.local"
password = "p1"

[[accounts]]
name = "dup"
email = "b@pm.local"
password = "p2"
"""
    with pytest.raises(ConfigError, match="dup"):
        load_config(write_config(tmp_path, toml), env={})


def test_password_not_exposed_in_repr(tmp_path: Path) -> None:
    config = load_config(write_config(tmp_path, VALID_TOML), env={})
    assert "bridge-pass-123" not in repr(config)
    assert "bridge-pass-123" not in str(config)
    account = config.get_account("personal")
    assert account.password.get_secret_value() == "bridge-pass-123"


def test_world_readable_config_warns(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    path = write_config(tmp_path, VALID_TOML)
    path.chmod(0o644)
    with caplog.at_level(logging.WARNING):
        load_config(path, env={})
    assert any("chmod 600" in record.message for record in caplog.records)


def test_private_config_does_not_warn(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    path = write_config(tmp_path, VALID_TOML)
    with caplog.at_level(logging.WARNING):
        load_config(path, env={})
    assert not caplog.records


def test_default_config_path_respects_xdg(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", "/custom/xdg")
    assert default_config_path() == Path("/custom/xdg/protonmail-mcp/config.toml")

    monkeypatch.delenv("XDG_CONFIG_HOME")
    assert default_config_path() == Path.home() / ".config/protonmail-mcp/config.toml"


def test_unknown_key_rejected(tmp_path: Path) -> None:
    toml = """
[[accounts]]
name = "typo"
email = "a@pm.local"
password = "p"
imapp = { port = 1143 }
"""
    with pytest.raises(ConfigError, match="imapp"):
        load_config(write_config(tmp_path, toml), env={})
