"""CLI wiring tests for --database-url on the migrate family (issue #140).

These exercise the precedence/override plumbing without a live database:
malformed-DSN validation, and the override-only path reaching a real
connection attempt (which fails fast against an unreachable DSN → exit 3).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import psycopg
import pytest
from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()

_UNREACHABLE = "postgresql://localhost:1/nope"


@pytest.mark.parametrize("cmd", ["up", "down", "status", "verify", "preflight"])
def test_database_url_in_help(cmd: str) -> None:
    """Every migrate subcommand documents --database-url (#140 / Phase 2)."""
    out = runner.invoke(app, ["migrate", cmd, "--help"]).output
    assert "--database-url" in out


def test_status_database_url_only_no_config_connects(tmp_path: Path) -> None:
    """`migrate status --database-url` connects without --config.

    The override is honored (no YAML required); an unreachable DSN surfaces as
    the status command's fatal exit (3), proving the connection was attempted.
    """
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    (migrations_dir / "001_x.up.sql").write_text("SELECT 1;")
    (migrations_dir / "001_x.down.sql").write_text("SELECT 1;")

    with patch(
        "confiture.core.connection.psycopg.connect",
        side_effect=psycopg.OperationalError("connection refused"),
    ):
        result = runner.invoke(
            app,
            ["migrate", "status", "--database-url", _UNREACHABLE,
             "--migrations-dir", str(migrations_dir)],
        )
    assert result.exit_code == 3, result.output


def test_up_database_url_only_unreachable_exits_3(tmp_path: Path) -> None:
    """`migrate up --database-url <unreachable>` needs no config and exits 3."""
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()

    with patch(
        "confiture.core.connection.psycopg.connect",
        side_effect=psycopg.OperationalError("connection refused"),
    ):
        result = runner.invoke(
            app,
            ["migrate", "up", "--database-url", _UNREACHABLE,
             "--migrations-dir", str(migrations_dir)],
        )
    assert result.exit_code == 3, result.output


def test_up_malformed_database_url_exits_5(tmp_path: Path) -> None:
    """A malformed --database-url DSN is a config error (CONFIG_003 → exit 5)."""
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()

    result = runner.invoke(
        app,
        ["migrate", "up", "--database-url", "mysql://nope/db",
         "--migrations-dir", str(migrations_dir)],
    )
    assert result.exit_code == 5, result.output


def test_env_var_honored_when_no_flag(tmp_path: Path, monkeypatch) -> None:
    """CONFITURE_DATABASE_URL is honored when no --database-url flag is given."""
    monkeypatch.setenv("CONFITURE_DATABASE_URL", _UNREACHABLE)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()

    with patch(
        "confiture.core.connection.psycopg.connect",
        side_effect=psycopg.OperationalError("connection refused"),
    ):
        result = runner.invoke(
            app,
            ["migrate", "up", "--migrations-dir", str(migrations_dir)],
        )
    # Reached the connection attempt via the env override (exit 3), not a
    # config-file lookup (which would be exit 5 for the missing default YAML).
    assert result.exit_code == 3, result.output
