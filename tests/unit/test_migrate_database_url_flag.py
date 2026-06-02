"""CLI wiring tests for --database-url on the migrate family (issue #140).

These exercise the precedence/override plumbing without a live database:
malformed-DSN validation, and the override-only path reaching a real
connection attempt (which fails fast against an unreachable DSN → exit 3).
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import patch

import psycopg
import pytest
from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()

_UNREACHABLE = "postgresql://localhost:1/nope"


_ANSI = re.compile(r"\x1b\[[0-9;]*m")


@pytest.mark.parametrize("cmd", ["up", "down", "status", "verify", "preflight"])
def test_database_url_in_help(cmd: str) -> None:
    """Every migrate subcommand documents --database-url (#140 / Phase 2)."""
    out = runner.invoke(app, ["migrate", cmd, "--help"]).output
    # Rich wraps long option names at narrow terminal widths (e.g. CI's 80
    # cols) AND colorizes them when a TTY/FORCE_COLOR is detected, interleaving
    # ANSI SGR codes mid-token (e.g. "--database\x1b[0m-url"). Strip ANSI first,
    # then collapse whitespace, so the assertion is both width- and color-
    # independent (CI forces color; local runs usually don't).
    collapsed = re.sub(r"\s+", "", _ANSI.sub("", out))
    assert "--database-url" in collapsed


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
            [
                "migrate",
                "status",
                "--database-url",
                _UNREACHABLE,
                "--migrations-dir",
                str(migrations_dir),
            ],
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
            [
                "migrate",
                "up",
                "--database-url",
                _UNREACHABLE,
                "--migrations-dir",
                str(migrations_dir),
            ],
        )
    assert result.exit_code == 3, result.output


def test_up_malformed_database_url_exits_5(tmp_path: Path) -> None:
    """A malformed --database-url DSN is a config error (CONFIG_003 → exit 5)."""
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()

    result = runner.invoke(
        app,
        [
            "migrate",
            "up",
            "--database-url",
            "mysql://nope/db",
            "--migrations-dir",
            str(migrations_dir),
        ],
    )
    assert result.exit_code == 5, result.output


def test_explicit_config_plus_canonical_env_conflicts_exit_5(tmp_path: Path, monkeypatch) -> None:
    """#152: an explicit --config AND CONFITURE_DATABASE_URL → CONFIG_007 (exit 5).

    Two explicit sources fail loud (present-at-all, not 'differing') instead of
    silently picking one — even when the --config path does not exist. This
    replaces the pre-0.20.0 'env fallback when config absent' behavior.
    """
    monkeypatch.setenv("CONFITURE_DATABASE_URL", _UNREACHABLE)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    explicit_cfg = tmp_path / "prod.yaml"

    result = runner.invoke(
        app,
        ["migrate", "up", "-c", str(explicit_cfg), "--migrations-dir", str(migrations_dir)],
    )
    assert result.exit_code == 5, result.output


def test_no_config_makes_canonical_env_the_sole_source(tmp_path: Path, monkeypatch) -> None:
    """#152: --no-config + CONFITURE_DATABASE_URL connects via the env var alone.

    No conflict (no explicit --config), config discovery suppressed; the
    unreachable canonical DSN proves the connection was attempted (exit 3).
    """
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
            ["migrate", "up", "--no-config", "--migrations-dir", str(migrations_dir)],
        )
    assert result.exit_code == 3, result.output


def test_up_ambient_only_database_url_refused_exit_5(tmp_path: Path, monkeypatch) -> None:
    """#152: a mutating command refuses to run on an ambient-only DATABASE_URL.

    No flag, no canonical var, no config present in the migrations dir, and the
    default --config (db/environments/local.yaml) is absent under tmp cwd → an
    intentional source is required, so this fails loud (CONFIG_010 → exit 5)
    rather than silently migrating against whatever DATABASE_URL is in the env.
    """
    monkeypatch.delenv("CONFITURE_DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", _UNREACHABLE)
    monkeypatch.chdir(tmp_path)  # no db/environments/local.yaml here
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()

    result = runner.invoke(
        app,
        ["migrate", "up", "--migrations-dir", str(migrations_dir)],
    )
    assert result.exit_code == 5, result.output


def test_status_canonical_env_connects(tmp_path: Path, monkeypatch) -> None:
    """#152: `migrate status` connects on the canonical var (intentional source)."""
    monkeypatch.setenv("CONFITURE_DATABASE_URL", _UNREACHABLE)
    monkeypatch.delenv("DATABASE_URL", raising=False)
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
            ["migrate", "status", "--migrations-dir", str(migrations_dir)],
        )
    assert result.exit_code == 3, result.output


def test_status_ambient_only_stays_unknown_exit_0(tmp_path: Path, monkeypatch) -> None:
    """#152: `migrate status` does NOT auto-connect on an ambient-only DATABASE_URL.

    It stays in the informative status-unknown state (exit 0) instead.
    """
    monkeypatch.delenv("CONFITURE_DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", _UNREACHABLE)
    monkeypatch.chdir(tmp_path)  # no default config present
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    (migrations_dir / "001_x.up.sql").write_text("SELECT 1;")
    (migrations_dir / "001_x.down.sql").write_text("SELECT 1;")

    result = runner.invoke(
        app,
        ["migrate", "status", "--migrations-dir", str(migrations_dir)],
    )
    assert result.exit_code == 0, result.output


def test_preflight_explicit_env_plus_canonical_conflicts_exit_5(
    tmp_path: Path, monkeypatch
) -> None:
    """#152: `preflight --env` + CONFITURE_DATABASE_URL → CONFIG_007 (exit 5).

    Proves two things at once: config_is_explicit recognizes an explicit --env
    (preflight is the family member that has it), and the conflict surfaces with
    its own exit code rather than being masked as the --against path's generic
    'failed to resolve pending' (exit 2).
    """
    monkeypatch.setenv("CONFITURE_DATABASE_URL", _UNREACHABLE)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()

    result = runner.invoke(
        app,
        [
            "migrate",
            "preflight",
            "--against",
            _UNREACHABLE,
            "--env",
            "production",
            "--migrations-dir",
            str(migrations_dir),
        ],
    )
    assert result.exit_code == 5, result.output


def test_env_var_honored_when_no_config_present(tmp_path: Path, monkeypatch) -> None:
    """#152: with no explicit --config and no default config, the canonical var drives.

    The default --config path is absent (tmp cwd), CONFITURE_DATABASE_URL is set
    and no explicit -c → row (d): the canonical var supplies the DSN (exit 3).
    """
    monkeypatch.setenv("CONFITURE_DATABASE_URL", _UNREACHABLE)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.chdir(tmp_path)  # no db/environments/local.yaml here
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
    assert result.exit_code == 3, result.output


def test_env_var_does_not_override_existing_config(tmp_path: Path, monkeypatch) -> None:
    """An ambient env var must NOT override an existing --config (#140 / CI fix)."""
    import yaml

    monkeypatch.setenv("DATABASE_URL", _UNREACHABLE)
    cfg = tmp_path / "env.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "name": "test",
                "database_url": "postgresql://localhost:2/cfgdb",
                "migration": {"tracking_table": "myschema.tb_x"},
            }
        )
    )
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()

    captured: dict = {}

    def _fake_connect(arg, *a, **k):
        captured["dsn"] = arg
        raise psycopg.OperationalError("refused")

    with patch("confiture.core.connection.psycopg.connect", side_effect=_fake_connect):
        runner.invoke(
            app,
            ["migrate", "up", "-c", str(cfg), "--migrations-dir", str(migrations_dir)],
        )
    # The config's DSN was used, not the ambient DATABASE_URL env var.
    assert captured.get("dsn") == "postgresql://localhost:2/cfgdb"
