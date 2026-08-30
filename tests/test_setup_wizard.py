"""Tests for the guided setup wizard (US-009)."""

import stat
from pathlib import Path

from protonmail_mcp.config import load_config
from protonmail_mcp.setup_wizard import run_setup


class FakeIO:
    def __init__(self, answers: list[str], password: str = "bridge-pw") -> None:
        self.answers = iter(answers)
        self.password = password
        self.output: list[str] = []

    def input(self, prompt: str) -> str:
        return next(self.answers)

    def getpass(self, prompt: str) -> str:
        return self.password

    def print(self, text: str) -> None:
        self.output.append(text)

    @property
    def text(self) -> str:
        return "\n".join(self.output)


def bridge_home(tmp_path: Path) -> Path:
    data_dir = tmp_path / ".config" / "protonmail" / "bridge-v3"
    data_dir.mkdir(parents=True, exist_ok=True)
    return tmp_path


def run(
    tmp_path: Path,
    io: FakeIO,
    problems: list[str] | None = None,
    installed: bool = True,
) -> tuple[int, Path]:
    home = bridge_home(tmp_path) if installed else tmp_path
    config_path = tmp_path / "config.toml"
    code = run_setup(
        input_fn=io.input,
        getpass_fn=io.getpass,
        print_fn=io.print,
        config_path=config_path,
        platform="linux",
        env={},
        home=home,
        login_check=lambda email, password, bridge: problems or [],
    )
    return code, config_path


def test_not_installed_aborts_with_guidance(tmp_path: Path) -> None:
    io = FakeIO([])
    code, config_path = run(tmp_path, io, installed=False)
    assert code == 1
    assert "proton.me/mail/bridge" in io.text
    assert not config_path.exists()


def test_happy_path_writes_private_config(tmp_path: Path) -> None:
    io = FakeIO(["user@pm.local", "User Name", "personal"])
    code, config_path = run(tmp_path, io)
    assert code == 0
    assert "ready to go" in io.text

    mode = stat.S_IMODE(config_path.stat().st_mode)
    assert mode == 0o600

    config = load_config(config_path, env={})
    account = config.get_account("personal")
    assert account.email == "user@pm.local"
    assert account.display_name == "User Name"
    assert account.password.get_secret_value() == "bridge-pw"


def test_existing_account_of_same_name_is_replaced(tmp_path: Path) -> None:
    first = FakeIO(["old@pm.local", "", ""])  # name defaults to "default"
    run(tmp_path, first)
    second = FakeIO(["new@pm.local", "", ""])
    code, config_path = run(tmp_path, second)
    assert code == 0

    config = load_config(config_path, env={})
    assert len(config.accounts) == 1
    assert config.get_account("default").email == "new@pm.local"


def test_failed_login_check_reports_and_exits_nonzero(tmp_path: Path) -> None:
    io = FakeIO(["user@pm.local", "", ""])
    code, config_path = run(tmp_path, io, problems=["IMAP: Bridge is not reachable"])
    assert code == 1
    assert "connection check failed" in io.text
    assert config_path.exists()  # config still saved for a later retry


def test_missing_email_aborts(tmp_path: Path) -> None:
    io = FakeIO(["", "", ""])
    code, _ = run(tmp_path, io)
    assert code == 1
    assert "required" in io.text


def test_password_never_echoed_to_output(tmp_path: Path) -> None:
    io = FakeIO(["user@pm.local", "", ""], password="s3cret-bridge-pw")
    run(tmp_path, io)
    assert "s3cret-bridge-pw" not in io.text
