"""Regression: `migrate verify -c <config>` must not crash (found during #182).

v0.36.0 passed `str(config)` to `load_config`, which calls `config_file.exists()`
— so the command's own documented primary invocation,
`confiture migrate verify -c db/environments/local.yaml`, died with
`AttributeError: 'str' object has no attribute 'exists'` at exit 1.

Every other `load_config` call site in the CLI passes the `Path`; this one was
the sole outlier.  It went unnoticed because the existing `migrate verify`
tests reach the command through `--database-url` rather than an explicit
`--config`.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml
from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()


@pytest.fixture
def cfg(tmp_path: Path) -> Path:
    p = tmp_path / "env.yaml"
    p.write_text(
        yaml.safe_dump(
            {
                "name": "test",
                "database_url": "postgresql://localhost/nonexistent_for_test",
                "include_dirs": ["db/schema"],
            }
        )
    )
    return p


@pytest.fixture
def migrations_dir(tmp_path: Path) -> Path:
    d = tmp_path / "migrations"
    d.mkdir()
    return d


def test_explicit_config_path_is_loaded_not_stringified(cfg: Path, migrations_dir: Path) -> None:
    """An explicit --config reaches the ledger probe rather than crashing."""
    with (
        patch("confiture.core.connection.create_connection", return_value=MagicMock()),
        patch("confiture.core.migrator.Migrator.tracking_table_exists", return_value=False),
    ):
        result = runner.invoke(
            app,
            [
                "migrate",
                "verify",
                "-c",
                str(cfg),
                "--migrations-dir",
                str(migrations_dir),
                "--allow-uninitialized",
            ],
        )

    assert result.exit_code == 0
    assert "has no attribute" not in result.output


def test_missing_config_still_reports_config_004(tmp_path: Path, migrations_dir: Path) -> None:
    """The Path is still validated — a missing file is a clean CONFIG_004."""
    result = runner.invoke(
        app,
        [
            "migrate",
            "verify",
            "-c",
            str(tmp_path / "absent.yaml"),
            "--migrations-dir",
            str(migrations_dir),
        ],
    )

    assert result.exit_code == 5
    assert "has no attribute" not in result.output
