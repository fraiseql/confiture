"""Tests for Issue #84: --auto-detect-baseline should error on missing/empty snapshots dir.

When a user explicitly passes --auto-detect-baseline, a missing or empty snapshots
directory should be a hard error (exit 2), not a silent warning.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_config(config_dir: Path) -> Path:
    config_file = config_dir / "test.yaml"
    config_file.write_text("name: test\ndatabase_url: postgresql://localhost/test_db\n")
    return config_file


def _write_migrations(migrations_dir: Path, count: int = 3) -> None:
    migrations_dir.mkdir(parents=True, exist_ok=True)
    for i in range(1, count + 1):
        (migrations_dir / f"00{i}_migration_{i}.up.sql").write_text(f"-- migration {i}\nSELECT 1;")


def _make_env(tracking_table: str = "tb_confiture"):
    from confiture.config.environment import Environment

    return Environment.model_validate(
        {
            "name": "test",
            "database_url": "postgresql://localhost/test_db",
            "include_dirs": ["db/schema"],
            "migration": {"tracking_table": tracking_table},
        }
    )


def _make_migrator_mock(*, tracking_table_exists: bool) -> MagicMock:
    mock = MagicMock()
    mock.tracking_table_exists.return_value = tracking_table_exists
    mock.initialize.return_value = None
    mock.get_applied_versions.return_value = []
    mock.get_applied_migrations_with_timestamps.return_value = []
    mock.find_migration_files.return_value = []
    mock.find_pending.return_value = []
    return mock


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAutoDetectBaselineMissingSnapshotsDir:
    """--auto-detect-baseline with non-existent snapshots dir should exit 2."""

    def test_errors_when_snapshots_dir_does_not_exist(self, tmp_path):
        config_file = _write_config(tmp_path)
        migrations_dir = tmp_path / "db" / "migrations"
        _write_migrations(migrations_dir, count=2)
        missing_dir = tmp_path / "db" / "schema_history"
        # Do NOT create missing_dir

        mock_migrator = _make_migrator_mock(tracking_table_exists=False)

        with (
            patch("confiture.core.connection.load_config", return_value=_make_env()),
            patch("confiture.core.connection.create_connection", return_value=MagicMock()),
            patch("confiture.core.migrator.Migrator", return_value=mock_migrator),
        ):
            result = runner.invoke(
                app,
                [
                    "migrate",
                    "up",
                    "--config",
                    str(config_file),
                    "--migrations-dir",
                    str(migrations_dir),
                    "--auto-detect-baseline",
                    "--snapshots-dir",
                    str(missing_dir),
                ],
            )

        # Exit code 2 = configuration error.
        # Error messages go to stderr (error_console), so result.output is empty.
        # Typer's CliRunner does not support mix_stderr, so we only check exit_code.
        assert result.exit_code == 2, f"Expected exit 2, got {result.exit_code}\n{result.output}"


class TestAutoDetectBaselineEmptySnapshotsDir:
    """--auto-detect-baseline with empty snapshots dir should exit 2."""

    def test_errors_when_snapshots_dir_is_empty(self, tmp_path):
        config_file = _write_config(tmp_path)
        migrations_dir = tmp_path / "db" / "migrations"
        _write_migrations(migrations_dir, count=2)
        empty_dir = tmp_path / "db" / "schema_history"
        empty_dir.mkdir(parents=True)
        # Dir exists but has no .sql files

        mock_migrator = _make_migrator_mock(tracking_table_exists=False)

        with (
            patch("confiture.core.connection.load_config", return_value=_make_env()),
            patch("confiture.core.connection.create_connection", return_value=MagicMock()),
            patch("confiture.core.migrator.Migrator", return_value=mock_migrator),
        ):
            result = runner.invoke(
                app,
                [
                    "migrate",
                    "up",
                    "--config",
                    str(config_file),
                    "--migrations-dir",
                    str(migrations_dir),
                    "--auto-detect-baseline",
                    "--snapshots-dir",
                    str(empty_dir),
                ],
            )

        assert result.exit_code == 2, f"Expected exit 2, got {result.exit_code}\n{result.output}"
