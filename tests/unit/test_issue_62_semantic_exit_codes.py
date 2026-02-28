"""Tests for Issue #62: Semantic exit codes for migrate status.

Exit code contract:
    0  All migrations applied (nothing pending) or status unknown (no config).
    1  Pending migrations exist.
    2  Tracking table not found in target database.
    3  Fatal error (connection failure, bad config, permission denied).
"""

from __future__ import annotations

import json
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


def _make_migrator_mock(
    *,
    tracking_table_exists: bool,
    applied_versions: list[str],
) -> MagicMock:
    mock = MagicMock()
    mock.tracking_table_exists.return_value = tracking_table_exists
    mock.initialize.return_value = None
    mock.get_applied_versions.return_value = applied_versions
    mock.get_applied_migrations_with_timestamps.return_value = []
    return mock


# ---------------------------------------------------------------------------
# Exit code 0: all applied
# ---------------------------------------------------------------------------


class TestExitCode0AllApplied:
    def test_exit_0_when_all_migrations_applied(self, tmp_path):
        """Exit 0 when every migration in the directory is applied."""
        config_file = _write_config(tmp_path)
        migrations_dir = tmp_path / "db" / "migrations"
        _write_migrations(migrations_dir, count=3)

        mock_migrator = _make_migrator_mock(
            tracking_table_exists=True, applied_versions=["001", "002", "003"]
        )

        with (
            patch("confiture.core.connection.load_config", return_value=_make_env()),
            patch("confiture.core.connection.create_connection", return_value=MagicMock()),
            patch("confiture.core.migrator.Migrator", return_value=mock_migrator),
        ):
            result = runner.invoke(
                app,
                [
                    "migrate",
                    "status",
                    "--config",
                    str(config_file),
                    "--migrations-dir",
                    str(migrations_dir),
                ],
            )

        assert result.exit_code == 0

    def test_exit_0_when_no_config_provided(self, tmp_path):
        """Exit 0 when no --config flag is given (status unknown, not an error state)."""
        migrations_dir = tmp_path / "db" / "migrations"
        _write_migrations(migrations_dir, count=2)

        result = runner.invoke(
            app,
            [
                "migrate",
                "status",
                "--migrations-dir",
                str(migrations_dir),
            ],
        )

        assert result.exit_code == 0

    def test_exit_0_json_when_all_applied(self, tmp_path):
        """Exit 0 with JSON format when all migrations are applied."""
        config_file = _write_config(tmp_path)
        migrations_dir = tmp_path / "db" / "migrations"
        _write_migrations(migrations_dir, count=2)

        mock_migrator = _make_migrator_mock(
            tracking_table_exists=True, applied_versions=["001", "002"]
        )

        with (
            patch("confiture.core.connection.load_config", return_value=_make_env()),
            patch("confiture.core.connection.create_connection", return_value=MagicMock()),
            patch("confiture.core.migrator.Migrator", return_value=mock_migrator),
        ):
            result = runner.invoke(
                app,
                [
                    "migrate",
                    "status",
                    "--config",
                    str(config_file),
                    "--migrations-dir",
                    str(migrations_dir),
                    "--format",
                    "json",
                ],
            )

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["pending"] == []


# ---------------------------------------------------------------------------
# Exit code 1: pending migrations exist
# ---------------------------------------------------------------------------


class TestExitCode1PendingExist:
    def test_exit_1_when_some_pending(self, tmp_path):
        """Exit 1 when at least one migration is pending."""
        config_file = _write_config(tmp_path)
        migrations_dir = tmp_path / "db" / "migrations"
        _write_migrations(migrations_dir, count=3)

        mock_migrator = _make_migrator_mock(
            tracking_table_exists=True, applied_versions=["001", "002"]
        )

        with (
            patch("confiture.core.connection.load_config", return_value=_make_env()),
            patch("confiture.core.connection.create_connection", return_value=MagicMock()),
            patch("confiture.core.migrator.Migrator", return_value=mock_migrator),
        ):
            result = runner.invoke(
                app,
                [
                    "migrate",
                    "status",
                    "--config",
                    str(config_file),
                    "--migrations-dir",
                    str(migrations_dir),
                ],
            )

        assert result.exit_code == 1

    def test_exit_1_when_all_pending_table_exists(self, tmp_path):
        """Exit 1 when table exists but no migrations have been applied yet."""
        config_file = _write_config(tmp_path)
        migrations_dir = tmp_path / "db" / "migrations"
        _write_migrations(migrations_dir, count=2)

        mock_migrator = _make_migrator_mock(tracking_table_exists=True, applied_versions=[])

        with (
            patch("confiture.core.connection.load_config", return_value=_make_env()),
            patch("confiture.core.connection.create_connection", return_value=MagicMock()),
            patch("confiture.core.migrator.Migrator", return_value=mock_migrator),
        ):
            result = runner.invoke(
                app,
                [
                    "migrate",
                    "status",
                    "--config",
                    str(config_file),
                    "--migrations-dir",
                    str(migrations_dir),
                ],
            )

        assert result.exit_code == 1

    def test_exit_1_json_format_when_pending(self, tmp_path):
        """Exit 1 with JSON format when pending migrations exist."""
        config_file = _write_config(tmp_path)
        migrations_dir = tmp_path / "db" / "migrations"
        _write_migrations(migrations_dir, count=3)

        mock_migrator = _make_migrator_mock(tracking_table_exists=True, applied_versions=["001"])

        with (
            patch("confiture.core.connection.load_config", return_value=_make_env()),
            patch("confiture.core.connection.create_connection", return_value=MagicMock()),
            patch("confiture.core.migrator.Migrator", return_value=mock_migrator),
        ):
            result = runner.invoke(
                app,
                [
                    "migrate",
                    "status",
                    "--config",
                    str(config_file),
                    "--migrations-dir",
                    str(migrations_dir),
                    "--format",
                    "json",
                ],
            )

        assert result.exit_code == 1
        data = json.loads(result.output)
        assert len(data["pending"]) == 2
        assert "warning" not in data


# ---------------------------------------------------------------------------
# Exit code 2: tracking table missing
# ---------------------------------------------------------------------------


class TestExitCode2TrackingTableAbsent:
    def test_exit_2_when_tracking_table_not_found(self, tmp_path):
        """Exit 2 when the tracking table is absent from the target database."""
        config_file = _write_config(tmp_path)
        migrations_dir = tmp_path / "db" / "migrations"
        _write_migrations(migrations_dir, count=2)

        mock_migrator = _make_migrator_mock(tracking_table_exists=False, applied_versions=[])

        with (
            patch("confiture.core.connection.load_config", return_value=_make_env()),
            patch("confiture.core.connection.create_connection", return_value=MagicMock()),
            patch("confiture.core.migrator.Migrator", return_value=mock_migrator),
        ):
            result = runner.invoke(
                app,
                [
                    "migrate",
                    "status",
                    "--config",
                    str(config_file),
                    "--migrations-dir",
                    str(migrations_dir),
                ],
            )

        assert result.exit_code == 2

    def test_exit_2_json_format_when_table_absent(self, tmp_path):
        """Exit 2 with JSON format when tracking table is absent."""
        config_file = _write_config(tmp_path)
        migrations_dir = tmp_path / "db" / "migrations"
        _write_migrations(migrations_dir, count=2)

        mock_migrator = _make_migrator_mock(tracking_table_exists=False, applied_versions=[])

        with (
            patch("confiture.core.connection.load_config", return_value=_make_env()),
            patch("confiture.core.connection.create_connection", return_value=MagicMock()),
            patch("confiture.core.migrator.Migrator", return_value=mock_migrator),
        ):
            result = runner.invoke(
                app,
                [
                    "migrate",
                    "status",
                    "--config",
                    str(config_file),
                    "--migrations-dir",
                    str(migrations_dir),
                    "--format",
                    "json",
                ],
            )

        assert result.exit_code == 2
        data = json.loads(result.output)
        assert "warning" in data

    def test_exit_2_not_3_when_table_absent(self, tmp_path):
        """Absence of tracking table returns 2, not 3 (not a fatal error)."""
        config_file = _write_config(tmp_path)
        migrations_dir = tmp_path / "db" / "migrations"
        _write_migrations(migrations_dir, count=1)

        mock_migrator = _make_migrator_mock(tracking_table_exists=False, applied_versions=[])

        with (
            patch("confiture.core.connection.load_config", return_value=_make_env()),
            patch("confiture.core.connection.create_connection", return_value=MagicMock()),
            patch("confiture.core.migrator.Migrator", return_value=mock_migrator),
        ):
            result = runner.invoke(
                app,
                [
                    "migrate",
                    "status",
                    "--config",
                    str(config_file),
                    "--migrations-dir",
                    str(migrations_dir),
                ],
            )

        assert result.exit_code == 2
        assert result.exit_code != 3


# ---------------------------------------------------------------------------
# Exit code 3: fatal error
# ---------------------------------------------------------------------------


class TestExitCode3FatalError:
    def test_exit_3_on_connection_refused(self, tmp_path):
        """Exit 3 when the database connection fails."""
        config_file = _write_config(tmp_path)
        migrations_dir = tmp_path / "db" / "migrations"
        _write_migrations(migrations_dir, count=2)

        with (
            patch("confiture.core.connection.load_config", return_value=_make_env()),
            patch(
                "confiture.core.connection.create_connection",
                side_effect=RuntimeError("Connection refused"),
            ),
        ):
            result = runner.invoke(
                app,
                [
                    "migrate",
                    "status",
                    "--config",
                    str(config_file),
                    "--migrations-dir",
                    str(migrations_dir),
                ],
            )

        assert result.exit_code == 3

    def test_exit_3_not_1_on_connection_error(self, tmp_path):
        """Fatal errors return 3, not 1 (distinguishable from pending-migrations state)."""
        config_file = _write_config(tmp_path)
        migrations_dir = tmp_path / "db" / "migrations"
        _write_migrations(migrations_dir, count=2)

        with (
            patch("confiture.core.connection.load_config", return_value=_make_env()),
            patch(
                "confiture.core.connection.create_connection",
                side_effect=OSError("Network unreachable"),
            ),
        ):
            result = runner.invoke(
                app,
                [
                    "migrate",
                    "status",
                    "--config",
                    str(config_file),
                    "--migrations-dir",
                    str(migrations_dir),
                ],
            )

        assert result.exit_code == 3
        assert result.exit_code != 1
