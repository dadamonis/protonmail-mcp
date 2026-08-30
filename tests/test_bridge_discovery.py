"""Tests for Bridge discovery: data dir per platform, ports, cert, probe."""

import contextlib
import json
import socket
import ssl
import threading
from pathlib import Path

import pytest

from protonmail_mcp.bridge import (
    DEFAULT_IMAP_PORT,
    DEFAULT_SMTP_PORT,
    BridgeCertificateError,
    bridge_data_dir,
    create_bridge_ssl_context,
    discover,
    is_bridge_running,
)

FIXTURES = Path(__file__).parent / "fixtures"


def make_bridge_dir(base: Path, *parts: str) -> Path:
    data_dir = base.joinpath(*parts)
    data_dir.mkdir(parents=True)
    return data_dir


class TestDataDir:
    def test_macos(self, tmp_path: Path) -> None:
        expected = make_bridge_dir(
            tmp_path, "Library", "Application Support", "protonmail", "bridge-v3"
        )
        assert bridge_data_dir(platform="darwin", env={}, home=tmp_path) == expected

    def test_linux_default(self, tmp_path: Path) -> None:
        expected = make_bridge_dir(tmp_path, ".config", "protonmail", "bridge-v3")
        assert bridge_data_dir(platform="linux", env={}, home=tmp_path) == expected

    def test_linux_xdg(self, tmp_path: Path) -> None:
        expected = make_bridge_dir(tmp_path, "xdg", "protonmail", "bridge-v3")
        env = {"XDG_CONFIG_HOME": str(tmp_path / "xdg")}
        assert bridge_data_dir(platform="linux", env=env, home=tmp_path) == expected

    def test_windows_appdata(self, tmp_path: Path) -> None:
        expected = make_bridge_dir(tmp_path, "Roaming", "protonmail", "bridge-v3")
        env = {"APPDATA": str(tmp_path / "Roaming")}
        assert bridge_data_dir(platform="win32", env=env, home=tmp_path) == expected

    def test_prefers_v3_over_legacy(self, tmp_path: Path) -> None:
        make_bridge_dir(tmp_path, ".config", "protonmail", "bridge")
        v3 = make_bridge_dir(tmp_path, ".config", "protonmail", "bridge-v3")
        assert bridge_data_dir(platform="linux", env={}, home=tmp_path) == v3

    def test_legacy_v2_found_when_no_v3(self, tmp_path: Path) -> None:
        v2 = make_bridge_dir(tmp_path, ".config", "protonmail", "bridge")
        assert bridge_data_dir(platform="linux", env={}, home=tmp_path) == v2

    def test_not_installed(self, tmp_path: Path) -> None:
        assert bridge_data_dir(platform="linux", env={}, home=tmp_path) is None


class TestDiscover:
    def test_not_installed_falls_back_to_defaults(self, tmp_path: Path) -> None:
        info = discover(platform="linux", env={}, home=tmp_path)
        assert not info.installed
        assert info.imap_port == DEFAULT_IMAP_PORT
        assert info.smtp_port == DEFAULT_SMTP_PORT
        assert info.ports_source == "defaults"
        assert info.cert_path is None

    def test_ports_from_prefs_json(self, tmp_path: Path) -> None:
        data_dir = make_bridge_dir(tmp_path, ".config", "protonmail", "bridge-v3")
        (data_dir / "prefs.json").write_text(
            json.dumps({"user_ports_imap": "2143", "user_ports_smtp": 2025})
        )
        info = discover(platform="linux", env={}, home=tmp_path)
        assert info.installed
        assert (info.imap_port, info.smtp_port) == (2143, 2025)
        assert info.ports_source == "discovered"

    def test_unreadable_prefs_falls_back_to_defaults(self, tmp_path: Path) -> None:
        data_dir = make_bridge_dir(tmp_path, ".config", "protonmail", "bridge-v3")
        (data_dir / "prefs.json").write_text("{not json")
        info = discover(platform="linux", env={}, home=tmp_path)
        assert info.ports_source == "defaults"
        assert info.imap_port == DEFAULT_IMAP_PORT

    def test_absurd_ports_rejected(self, tmp_path: Path) -> None:
        data_dir = make_bridge_dir(tmp_path, ".config", "protonmail", "bridge-v3")
        (data_dir / "prefs.json").write_text(
            json.dumps({"user_ports_imap": 0, "user_ports_smtp": 99999})
        )
        info = discover(platform="linux", env={}, home=tmp_path)
        assert info.ports_source == "defaults"

    def test_cert_discovered(self, tmp_path: Path) -> None:
        data_dir = make_bridge_dir(tmp_path, ".config", "protonmail", "bridge-v3")
        (data_dir / "cert.pem").write_bytes((FIXTURES / "bridge-test-cert.pem").read_bytes())
        info = discover(platform="linux", env={}, home=tmp_path)
        assert info.cert_path == data_dir / "cert.pem"


class TestSslContext:
    def test_context_trusts_only_bridge_cert(self) -> None:
        context = create_bridge_ssl_context(FIXTURES / "bridge-test-cert.pem")
        assert context.verify_mode == ssl.CERT_REQUIRED
        assert context.check_hostname is True
        assert context.cert_store_stats()["x509_ca"] == 1

    def test_garbage_cert_raises_actionable_error(self, tmp_path: Path) -> None:
        bad = tmp_path / "cert.pem"
        bad.write_text("not a certificate")
        with pytest.raises(BridgeCertificateError, match=r"cert\.pem"):
            create_bridge_ssl_context(bad)

    def test_missing_cert_raises_actionable_error(self, tmp_path: Path) -> None:
        with pytest.raises(BridgeCertificateError):
            create_bridge_ssl_context(tmp_path / "missing.pem")


class TestProbe:
    def test_detects_listening_port(self) -> None:
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]

        def accept_quietly() -> None:
            # OSError: socket closed by the test teardown
            with contextlib.suppress(OSError):
                server.accept()

        accepted = threading.Thread(target=accept_quietly, daemon=True)
        accepted.start()
        try:
            assert is_bridge_running("127.0.0.1", port, timeout=2.0) is True
        finally:
            server.close()

    def test_detects_closed_port(self) -> None:
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()  # nothing listening any more
        assert is_bridge_running("127.0.0.1", port, timeout=0.5) is False


def test_no_disabled_tls_verification_anywhere() -> None:
    """FR-3: verify=False / CERT_NONE / check_hostname = False must not
    appear in the source tree."""
    src = Path(__file__).parent.parent / "src"
    offenders = []
    for path in src.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for needle in ("CERT_NONE", "verify=False", "check_hostname = False"):
            if needle in text:
                offenders.append(f"{path}: {needle}")
    assert not offenders, offenders
