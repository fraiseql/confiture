"""Behavioral exit-code tests for the migrate family (issue #146).

These assert the *canonical* exit numbers the fraisier-core adapter branches on:
no-table=2, connect-fail=3, config-invalid=5, lock=6. They complement the
registry-contract test in test_exit_code_convention.py by exercising the real
CLI/connection paths that produce those numbers.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import psycopg
import pytest
import yaml
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.core.connection import create_connection, load_config
from confiture.exceptions import ConfigurationError

runner = CliRunner()


# ── connection.py translates to canonical ConfigurationError codes ────────────


def test_load_config_missing_file_raises_config_invalid() -> None:
    """A missing config file is a config error (CONFIG family → exit 5)."""
    with pytest.raises(ConfigurationError) as exc_info:
        load_config(Path("/nonexistent/path/to/config.yaml"))
    assert exc_info.value.exit_code == 5


def test_load_config_invalid_yaml_raises_config_002(tmp_path: Path) -> None:
    """Malformed YAML is a config error (CONFIG_002 → exit 5)."""
    bad = tmp_path / "broken.yaml"
    bad.write_text("database_url: [unterminated\n  : :")
    with pytest.raises(ConfigurationError) as exc_info:
        load_config(bad)
    assert exc_info.value.error_code == "CONFIG_002"
    assert exc_info.value.exit_code == 5


def test_create_connection_failure_raises_config_006() -> None:
    """A failed connection carries CONFIG_006 → exit 3 (connect-fail)."""
    with patch(
        "confiture.core.connection.psycopg.connect",
        side_effect=psycopg.OperationalError("connection refused"),
    ):
        with pytest.raises(ConfigurationError) as exc_info:
            create_connection("postgresql://localhost:1/nope")
    assert exc_info.value.error_code == "CONFIG_006"
    assert exc_info.value.exit_code == 3


# ── migrate up surfaces the canonical numbers ─────────────────────────────────


def _write_valid_config(tmp_path: Path) -> Path:
    cfg = tmp_path / "local.yaml"
    cfg.write_text(
        yaml.safe_dump({"name": "test", "database_url": "postgresql://localhost:1/nope"})
    )
    return cfg


def test_migrate_up_broken_yaml_exits_5(tmp_path: Path) -> None:
    """`migrate up` with a malformed config exits 5 (config invalid)."""
    cfg = tmp_path / "broken.yaml"
    cfg.write_text("database_url: [unterminated\n  : :")
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()

    result = runner.invoke(
        app,
        ["migrate", "up", "--config", str(cfg), "--migrations-dir", str(migrations_dir)],
    )
    assert result.exit_code == 5, result.output


def test_migrate_up_connection_refused_exits_3(tmp_path: Path) -> None:
    """`migrate up` with an unreachable database exits 3 (connect-fail)."""
    cfg = _write_valid_config(tmp_path)
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()

    with patch(
        "confiture.core.connection.psycopg.connect",
        side_effect=psycopg.OperationalError("connection refused"),
    ):
        result = runner.invoke(
            app,
            ["migrate", "up", "--config", str(cfg), "--migrations-dir", str(migrations_dir)],
        )
    assert result.exit_code == 3, result.output
