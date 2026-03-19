"""Unit tests for confiture.core.ssh_tunnel."""

from __future__ import annotations

import socket
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from confiture.config.environment import SshTunnelConfig
from confiture.core.ssh_tunnel import (
    _build_ssh_cmd,
    _find_free_port,
    _wait_for_port,
    ssh_tunnel,
)

# ---------------------------------------------------------------------------
# _find_free_port
# ---------------------------------------------------------------------------


def test_find_free_port_returns_valid_port() -> None:
    port = _find_free_port()
    assert 1 <= port <= 65535


def test_find_free_port_returns_integer() -> None:
    assert isinstance(_find_free_port(), int)


# ---------------------------------------------------------------------------
# _wait_for_port
# ---------------------------------------------------------------------------


def test_wait_for_port_times_out_when_nothing_listening() -> None:
    """A port with nothing listening should raise TimeoutError quickly."""
    # Find a port that is definitely closed
    with socket.socket() as s:
        s.bind(("localhost", 0))
        free_port = s.getsockname()[1]
    # Port is now released; nothing listening
    with pytest.raises(TimeoutError, match="SSH tunnel did not open"):
        _wait_for_port(free_port, timeout=1)


def test_wait_for_port_succeeds_when_already_open() -> None:
    """Bind a real socket and verify _wait_for_port returns immediately."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("localhost", 0))
        srv.listen(1)
        port = srv.getsockname()[1]
        _wait_for_port(port, timeout=5)  # should not raise


# ---------------------------------------------------------------------------
# _build_ssh_cmd
# ---------------------------------------------------------------------------


def test_build_ssh_cmd_tcp_mode() -> None:
    cfg = SshTunnelConfig(host="db.example.com", user="alice", remote_port=5432)
    cmd = _build_ssh_cmd(cfg, local_port=54321)
    assert "ssh" in cmd
    assert "-N" in cmd
    assert "54321:localhost:5432" in cmd
    assert "alice@db.example.com" in cmd


def test_build_ssh_cmd_socket_mode() -> None:
    cfg = SshTunnelConfig(
        host="db.example.com",
        user="alice",
        remote_socket="/var/run/postgresql/.s.PGSQL.5432",
    )
    cmd = _build_ssh_cmd(cfg, local_port=54321)
    assert "54321:/var/run/postgresql/.s.PGSQL.5432" in cmd
    # remote_host:remote_port must NOT appear
    assert "localhost:5432" not in " ".join(cmd)


def test_build_ssh_cmd_no_user() -> None:
    cfg = SshTunnelConfig(host="db.example.com")
    cmd = _build_ssh_cmd(cfg, local_port=1234)
    assert "db.example.com" in cmd
    assert "@" not in cmd[-1]  # last arg is bare host, no user@


def test_build_ssh_cmd_identity_file() -> None:
    cfg = SshTunnelConfig(host="db.example.com", identity_file="~/.ssh/id_ed25519")
    cmd = _build_ssh_cmd(cfg, local_port=1234)
    assert "-i" in cmd
    identity_idx = cmd.index("-i")
    assert "id_ed25519" in cmd[identity_idx + 1]


# ---------------------------------------------------------------------------
# ssh_tunnel context manager
# ---------------------------------------------------------------------------


def _make_mock_popen(returncode: int = 0) -> MagicMock:
    mock = MagicMock()
    mock.terminate.return_value = None
    mock.wait.return_value = returncode
    return mock


@patch("confiture.core.ssh_tunnel._wait_for_port")
@patch("subprocess.Popen")
def test_ssh_tunnel_yields_patched_url(mock_popen: MagicMock, mock_wait: MagicMock) -> None:
    mock_popen.return_value = _make_mock_popen()
    cfg = SshTunnelConfig(host="db.example.com", user="alice", local_port=15432)
    url = "postgresql://localhost:${TUNNEL_LOCAL_PORT}/mydb"

    with ssh_tunnel(cfg, url) as patched:
        assert patched == "postgresql://localhost:15432/mydb"


@patch("confiture.core.ssh_tunnel._wait_for_port")
@patch("subprocess.Popen")
def test_ssh_tunnel_terminates_process_on_exit(mock_popen: MagicMock, mock_wait: MagicMock) -> None:
    proc = _make_mock_popen()
    mock_popen.return_value = proc
    cfg = SshTunnelConfig(host="db.example.com", user="alice", local_port=15432)

    with ssh_tunnel(cfg, "postgresql://localhost:${TUNNEL_LOCAL_PORT}/mydb"):
        pass

    proc.terminate.assert_called_once()


@patch("confiture.core.ssh_tunnel._wait_for_port")
@patch("subprocess.Popen")
def test_ssh_tunnel_terminates_on_body_exception(
    mock_popen: MagicMock, mock_wait: MagicMock
) -> None:
    proc = _make_mock_popen()
    mock_popen.return_value = proc
    cfg = SshTunnelConfig(host="db.example.com", user="alice", local_port=15432)

    with pytest.raises(RuntimeError):
        with ssh_tunnel(cfg, "postgresql://localhost:${TUNNEL_LOCAL_PORT}/mydb"):
            raise RuntimeError("body error")

    proc.terminate.assert_called_once()


@patch("confiture.core.ssh_tunnel._find_free_port", return_value=55555)
@patch("confiture.core.ssh_tunnel._wait_for_port")
@patch("subprocess.Popen")
def test_ssh_tunnel_auto_assigns_port(
    mock_popen: MagicMock, mock_wait: MagicMock, mock_free: MagicMock
) -> None:
    proc = _make_mock_popen()
    mock_popen.return_value = proc
    cfg = SshTunnelConfig(host="db.example.com", user="alice", local_port=0)

    with ssh_tunnel(cfg, "postgresql://localhost:${TUNNEL_LOCAL_PORT}/mydb") as url:
        assert "55555" in url

    mock_free.assert_called_once()


@patch("confiture.core.ssh_tunnel._wait_for_port")
@patch("subprocess.Popen")
def test_ssh_tunnel_uses_identity_file(mock_popen: MagicMock, mock_wait: MagicMock) -> None:
    proc = _make_mock_popen()
    mock_popen.return_value = proc
    cfg = SshTunnelConfig(
        host="db.example.com",
        user="alice",
        local_port=15432,
        identity_file="~/.ssh/id_ed25519",
    )

    with ssh_tunnel(cfg, "postgresql://localhost:${TUNNEL_LOCAL_PORT}/mydb"):
        pass

    popen_args = mock_popen.call_args[0][0]
    assert "-i" in popen_args


@patch("confiture.core.ssh_tunnel._wait_for_port")
@patch("subprocess.Popen")
def test_ssh_tunnel_kills_when_terminate_hangs(mock_popen: MagicMock, mock_wait: MagicMock) -> None:
    proc = _make_mock_popen()
    # First call (with timeout) raises; second call (after kill) returns normally.
    proc.wait.side_effect = [subprocess.TimeoutExpired(cmd="ssh", timeout=5), None]
    mock_popen.return_value = proc
    cfg = SshTunnelConfig(host="db.example.com", user="alice", local_port=15432)

    with ssh_tunnel(cfg, "postgresql://localhost:${TUNNEL_LOCAL_PORT}/mydb"):
        pass

    proc.kill.assert_called_once()
