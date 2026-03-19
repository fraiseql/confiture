"""Unit tests for open_connection() SSH tunnel integration."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from typing import Any
from unittest.mock import MagicMock, patch

from confiture.config.environment import SshTunnelConfig
from confiture.core.connection import open_connection

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_env(tunnel: SshTunnelConfig | None = None) -> MagicMock:
    """Minimal fake Environment object."""
    env = MagicMock()
    env.database_url = "postgresql://localhost:${TUNNEL_LOCAL_PORT}/testdb"
    env.ssh_tunnel = tunnel
    return env


# ---------------------------------------------------------------------------
# open_connection — no tunnel path
# ---------------------------------------------------------------------------


def test_open_connection_no_tunnel_calls_create_connection() -> None:
    env = _make_env(tunnel=None)
    fake_conn = MagicMock()
    fake_conn.close = MagicMock()

    with patch(
        "confiture.core.connection.create_connection", return_value=fake_conn
    ) as mock_create:
        with open_connection(env) as conn:
            assert conn is fake_conn

        mock_create.assert_called_once_with(env)
        fake_conn.close.assert_called_once()


# ---------------------------------------------------------------------------
# open_connection — with tunnel
# ---------------------------------------------------------------------------


def test_open_connection_with_tunnel_uses_ssh_tunnel() -> None:
    """open_connection opens an SSH tunnel when ssh_tunnel is configured."""
    tunnel_cfg = SshTunnelConfig(host="db.example.com", user="alice", local_port=15432)
    env = _make_env(tunnel=tunnel_cfg)
    fake_conn = MagicMock()
    fake_conn.close = MagicMock()

    patched_url = "postgresql://localhost:15432/testdb"
    seen_configs: list[SshTunnelConfig] = []

    @contextmanager
    def fake_ssh_tunnel(cfg: SshTunnelConfig, database_url: str) -> Generator[str, None, None]:
        seen_configs.append(cfg)
        yield patched_url

    # Patch ssh_tunnel at its defining module so the lazy import picks it up.
    with (
        patch("confiture.core.ssh_tunnel.ssh_tunnel", fake_ssh_tunnel),
        patch("psycopg.connect", return_value=fake_conn) as mock_connect,
    ):
        with open_connection(env) as conn:
            assert conn is fake_conn

        mock_connect.assert_called_once_with(patched_url)
        fake_conn.close.assert_called_once()

    assert seen_configs == [tunnel_cfg]


def test_open_connection_with_dict_tunnel() -> None:
    """Dict-style config with ssh_tunnel key is supported."""
    config: dict[str, Any] = {
        "database_url": "postgresql://localhost:${TUNNEL_LOCAL_PORT}/testdb",
        "ssh_tunnel": {
            "host": "db.example.com",
            "user": "alice",
            "local_port": 15432,
        },
    }
    fake_conn = MagicMock()
    fake_conn.close = MagicMock()

    @contextmanager
    def fake_ssh_tunnel(cfg: SshTunnelConfig, database_url: str) -> Generator[str, None, None]:
        yield "postgresql://localhost:15432/testdb"

    with (
        patch("confiture.core.ssh_tunnel.ssh_tunnel", fake_ssh_tunnel),
        patch("psycopg.connect", return_value=fake_conn),
    ):
        with open_connection(config) as conn:
            assert conn is fake_conn

    fake_conn.close.assert_called_once()
