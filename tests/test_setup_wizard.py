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


def bridge_home(tmp_path: Path, with_cert: bool = True) -> Path:
    data_dir = tmp_path / ".config" / "protonmail" / "bridge-v3"
    data_dir.mkdir(parents=True, exist_ok=True)
    if with_cert:
        cert_dir = tmp_path / ".config" / "protonmail-mcp"
        cert_dir.mkdir(parents=True, exist_ok=True)
        (cert_dir / "cert.pem").write_text("fake exported cert")
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


class TestCertExportFlow:
    """Bridge v3 keeps the TLS cert in its encrypted vault — the wizard
    must guide the user through exporting it."""

    def test_missing_cert_shows_export_instructions(self, tmp_path: Path) -> None:
        home = bridge_home(tmp_path, with_cert=False)
        # Answers: 3 failed re-checks (Enter), then account details.
        io = FakeIO(["", "", "", "user@pm.local", "", ""])
        code = run_setup(
            input_fn=io.input,
            getpass_fn=io.getpass,
            print_fn=io.print,
            config_path=tmp_path / "config.toml",
            platform="linux",
            env={},
            home=home,
            login_check=lambda email, password, bridge: [],
        )
        assert "Export TLS certificates" in io.text
        assert "Continuing without the certificate" in io.text
        assert code == 0  # setup itself still completes

    def test_pasted_cert_path_is_used(self, tmp_path: Path) -> None:
        home = bridge_home(tmp_path, with_cert=False)
        exported = tmp_path / "exported-cert.pem"
        exported.write_text("cert")
        seen_cert_paths: list[Path | None] = []

        def record_check(email: str, password: str, bridge: object) -> list[str]:
            seen_cert_paths.append(getattr(bridge, "cert_path", None))
            return []

        io = FakeIO([str(exported), "user@pm.local", "", ""])
        code = run_setup(
            input_fn=io.input,
            getpass_fn=io.getpass,
            print_fn=io.print,
            config_path=tmp_path / "config.toml",
            platform="linux",
            env={},
            home=home,
            login_check=record_check,
        )
        assert code == 0
        assert seen_cert_paths == [exported]

    def test_recheck_finds_freshly_exported_cert(self, tmp_path: Path) -> None:
        home = bridge_home(tmp_path, with_cert=False)
        cert_dir = home / ".config" / "protonmail-mcp"
        cert_dir.mkdir(parents=True, exist_ok=True)

        answers = iter(["", "user@pm.local", "", ""])

        def input_and_export(prompt: str) -> str:
            # Simulate the user exporting the cert before pressing Enter.
            if "cert.pem" in prompt:
                (cert_dir / "cert.pem").write_text("cert")
            return next(answers)

        io = FakeIO([])
        code = run_setup(
            input_fn=input_and_export,
            getpass_fn=io.getpass,
            print_fn=io.print,
            config_path=tmp_path / "config.toml",
            platform="linux",
            env={},
            home=home,
            login_check=lambda email, password, bridge: [],
        )
        assert code == 0
        assert "✓ Found" in io.text
