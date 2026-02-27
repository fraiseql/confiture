"""Unit tests for migrate status behaviour when the tracking table is absent.

Issue #57: migrate status should report "pending" (not "unknown") when the
tb_confiture tracking table is absent from the target database, and should exit
with code 1 with an actionable advisory message.
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
    config_file.write_text(
        """
name: test
database:
  host: localhost
  port: 5432
  database: test_db
  user: postgres
  password: postgres
"""
    )
    return config_file


def _write_migrations(migrations_dir: Path, count: int = 3) -> None:
    migrations_dir.mkdir(parents=True, exist_ok=True)
    for i in range(1, count + 1):
        (migrations_dir / f"00{i}_migration_{i}.up.sql").write_text(f"-- migration {i}\nSELECT 1;")


def _make_migrator_mock(
    *,
    tracking_table_exists: bool,
    applied_versions: list[str],
) -> MagicMock:
    mock = MagicMock()
    mock.tracking_table_exists.return_value = tracking_table_exists
    mock.initialize.return_value = None
    mock.get_applied_versions.return_value = applied_versions
    return mock


# ---------------------------------------------------------------------------
# Tests: tracking table absent
# ---------------------------------------------------------------------------


class TestMigrateStatusTrackingTableAbsent:
    def test_all_migrations_shown_as_pending_when_table_absent(self, tmp_path):
        """When tb_confiture is absent, all migrations must be shown as pending."""
        config_file = _write_config(tmp_path)
        migrations_dir = tmp_path / "db" / "migrations"
        _write_migrations(migrations_dir, count=3)

        mock_migrator = _make_migrator_mock(tracking_table_exists=False, applied_versions=[])

        with (
            patch("confiture.core.connection.load_config", return_value=MagicMock()),
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
        assert "pending" in result.output
        # No migration status cell should show "applied" (word appears in advisory text but not as status)
        assert "✅ applied" not in result.output

    def test_advisory_message_shown_when_table_absent(self, tmp_path):
        """Advisory message must be printed when tb_confiture is absent."""
        config_file = _write_config(tmp_path)
        migrations_dir = tmp_path / "db" / "migrations"
        _write_migrations(migrations_dir, count=2)

        mock_migrator = _make_migrator_mock(tracking_table_exists=False, applied_versions=[])

        with (
            patch("confiture.core.connection.load_config", return_value=MagicMock()),
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
        assert "tb_confiture" in result.output

    def test_exit_code_1_when_table_absent(self, tmp_path):
        """Exit code must be 1 when the tracking table is absent."""
        config_file = _write_config(tmp_path)
        migrations_dir = tmp_path / "db" / "migrations"
        _write_migrations(migrations_dir, count=1)

        mock_migrator = _make_migrator_mock(tracking_table_exists=False, applied_versions=[])

        with (
            patch("confiture.core.connection.load_config", return_value=MagicMock()),
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

    def test_json_format_includes_warning_when_table_absent(self, tmp_path):
        """JSON output must include a 'warning' key when tb_confiture is absent."""
        config_file = _write_config(tmp_path)
        migrations_dir = tmp_path / "db" / "migrations"
        _write_migrations(migrations_dir, count=2)

        mock_migrator = _make_migrator_mock(tracking_table_exists=False, applied_versions=[])

        with (
            patch("confiture.core.connection.load_config", return_value=MagicMock()),
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
        assert "warning" in data
        assert "tb_confiture" in data["warning"]
        # All migrations must be in pending list
        assert len(data["pending"]) == 2
        assert data["applied"] == []

    def test_json_all_migrations_pending_when_table_absent(self, tmp_path):
        """JSON pending list must contain all migration versions when table absent."""
        config_file = _write_config(tmp_path)
        migrations_dir = tmp_path / "db" / "migrations"
        _write_migrations(migrations_dir, count=3)

        mock_migrator = _make_migrator_mock(tracking_table_exists=False, applied_versions=[])

        with (
            patch("confiture.core.connection.load_config", return_value=MagicMock()),
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

        data = json.loads(result.output)
        assert len(data["pending"]) == 3
        for m in data["migrations"]:
            assert m["status"] == "pending"


# ---------------------------------------------------------------------------
# Tests: tracking table present, no applied migrations
# ---------------------------------------------------------------------------


class TestMigrateStatusTablePresentEmpty:
    def test_all_pending_exit_zero_when_table_exists_but_empty(self, tmp_path):
        """When table exists but no migrations applied, exit code should be 0."""
        config_file = _write_config(tmp_path)
        migrations_dir = tmp_path / "db" / "migrations"
        _write_migrations(migrations_dir, count=2)

        # Table exists, nothing applied yet
        mock_migrator = _make_migrator_mock(tracking_table_exists=True, applied_versions=[])

        with (
            patch("confiture.core.connection.load_config", return_value=MagicMock()),
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

        # Normal pending state: exit 0, no advisory about tb_confiture
        assert result.exit_code == 0
        assert "tb_confiture" not in result.output


# ---------------------------------------------------------------------------
# Tests: no config provided
# ---------------------------------------------------------------------------


class TestMigrateStatusNoConfig:
    def test_unknown_status_when_no_config(self, tmp_path):
        """Without --config, status is 'unknown' (no regression)."""
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
        # Should show no applied/pending counts without config
        assert "unknown" in result.output.lower() or "no config" in result.output.lower()


# ---------------------------------------------------------------------------
# Tests: regression — table present with applied migrations
# ---------------------------------------------------------------------------


class TestMigrateStatusTablePresentWithApplied:
    def test_applied_and_pending_correctly_distinguished(self, tmp_path):
        """Regression: table present, some applied → applied/pending correctly reported."""
        config_file = _write_config(tmp_path)
        migrations_dir = tmp_path / "db" / "migrations"
        _write_migrations(migrations_dir, count=3)

        # versions 001 and 002 are applied
        mock_migrator = _make_migrator_mock(
            tracking_table_exists=True, applied_versions=["001", "002"]
        )

        with (
            patch("confiture.core.connection.load_config", return_value=MagicMock()),
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
        assert "001" in data["applied"]
        assert "002" in data["applied"]
        assert "003" in data["pending"]
        assert "warning" not in data
