"""Unit tests for SshTunnelConfig Pydantic model and Environment.ssh_tunnel field."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from confiture.config.environment import Environment, SshTunnelConfig

# ---------------------------------------------------------------------------
# SshTunnelConfig defaults
# ---------------------------------------------------------------------------


def test_ssh_tunnel_config_defaults() -> None:
    cfg = SshTunnelConfig(host="db.example.com")
    assert cfg.user is None
    assert cfg.remote_host == "localhost"
    assert cfg.remote_port == 5432
    assert cfg.remote_socket is None
    assert cfg.local_port == 0
    assert cfg.identity_file is None
    assert cfg.timeout_s == 10


def test_ssh_tunnel_config_with_user() -> None:
    cfg = SshTunnelConfig(host="db.example.com", user="lionel")
    assert cfg.user == "lionel"
    assert cfg.host == "db.example.com"


def test_ssh_tunnel_config_with_remote_socket() -> None:
    cfg = SshTunnelConfig(
        host="db.example.com",
        remote_socket="/var/run/postgresql/.s.PGSQL.5432",
    )
    assert cfg.remote_socket == "/var/run/postgresql/.s.PGSQL.5432"


def test_ssh_tunnel_config_requires_host() -> None:
    with pytest.raises(ValidationError):
        SshTunnelConfig()  # type: ignore[call-arg]


def test_ssh_tunnel_config_fixed_local_port() -> None:
    cfg = SshTunnelConfig(host="db.example.com", local_port=15432)
    assert cfg.local_port == 15432


def test_ssh_tunnel_config_identity_file() -> None:
    cfg = SshTunnelConfig(host="db.example.com", identity_file="~/.ssh/id_ed25519")
    assert cfg.identity_file == "~/.ssh/id_ed25519"


# ---------------------------------------------------------------------------
# Environment.ssh_tunnel field
# ---------------------------------------------------------------------------


def _make_env_data(**extra: object) -> dict:
    return {
        "name": "local",
        "database_url": "postgresql://localhost/testdb",
        "include_dirs": [],
        **extra,
    }


def test_environment_ssh_tunnel_none_by_default() -> None:
    env = Environment.model_validate(_make_env_data())
    assert env.ssh_tunnel is None


def test_environment_ssh_tunnel_parsed_from_dict() -> None:
    env = Environment.model_validate(
        _make_env_data(
            ssh_tunnel={
                "host": "printoptim.io",
                "user": "lionel",
                "remote_port": 5432,
                "local_port": 0,
            }
        )
    )
    assert env.ssh_tunnel is not None
    assert env.ssh_tunnel.host == "printoptim.io"
    assert env.ssh_tunnel.user == "lionel"


def test_environment_ssh_tunnel_with_remote_socket() -> None:
    env = Environment.model_validate(
        _make_env_data(
            ssh_tunnel={
                "host": "printoptim.io",
                "remote_socket": "/var/run/postgresql/.s.PGSQL.5432",
            }
        )
    )
    assert env.ssh_tunnel is not None
    assert env.ssh_tunnel.remote_socket == "/var/run/postgresql/.s.PGSQL.5432"
