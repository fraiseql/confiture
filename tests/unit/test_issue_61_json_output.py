"""Tests for Issue #61: Complete JSON output for migrate status and migrate up.

Verifies that:
- migrate status JSON includes tracking_table and applied_at fields
- migrate up JSON uses canonical key names (applied, total_duration_ms, errors, skipped)
"""

import json
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.models.results import MigrateUpResult, MigrationApplied


def _make_env(tracking_table: str = "tb_confiture"):
    """Create an Environment object for mocking load_config."""
    from confiture.config.environment import Environment

    return Environment.model_validate(
        {
            "name": "test",
            "database_url": "postgresql://localhost/test_db",
            "include_dirs": ["db/schema"],
            "migration": {"tracking_table": tracking_table},
        }
    )


class TestMigrateStatusJsonOutput:
    """Tests for migrate status --format json completeness."""

    def test_migrate_status_json_includes_tracking_table(self, tmp_path):
        """JSON output must include a tracking_table field."""
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)
        (migrations_dir / "001_init.up.sql").write_text("SELECT 1;")

        config_file = tmp_path / "local.yaml"
        config_file.write_text("name: local\ndatabase_url: postgresql://localhost/test\n")

        runner = CliRunner()

        mock_migrator = MagicMock()
        mock_migrator.tracking_table_exists.return_value = True
        mock_migrator.get_applied_versions.return_value = ["001"]
        mock_migrator.get_applied_migrations_with_timestamps.return_value = []

        with (
            patch(
                "confiture.core.connection.load_config",
                return_value=_make_env("myschema.my_migrations"),
            ),
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

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert "tracking_table" in data
        assert data["tracking_table"] == "myschema.my_migrations"

    def test_migrate_status_json_includes_applied_at_when_db_available(self, tmp_path):
        """JSON migrations list must include applied_at for applied migrations."""
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)
        (migrations_dir / "001_init.up.sql").write_text("SELECT 1;")
        (migrations_dir / "002_add_users.up.sql").write_text("SELECT 2;")

        config_file = tmp_path / "local.yaml"
        config_file.write_text("name: local\ndatabase_url: postgresql://localhost/test\n")

        runner = CliRunner()

        mock_migrator = MagicMock()
        mock_migrator.tracking_table_exists.return_value = True
        mock_migrator.get_applied_versions.return_value = ["001"]
        mock_migrator.get_applied_migrations_with_timestamps.return_value = [
            {
                "version": "001",
                "name": "init",
                "applied_at": "2025-01-15T10:30:00+00:00",
            }
        ]

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

        assert result.exit_code == 1, result.output
        data = json.loads(result.output)
        migrations = {m["version"]: m for m in data["migrations"]}
        assert "applied_at" in migrations["001"]
        assert migrations["001"]["applied_at"] == "2025-01-15T10:30:00+00:00"
        # pending migration has null applied_at
        assert "applied_at" in migrations["002"]
        assert migrations["002"]["applied_at"] is None

    def test_migrate_status_json_summary_structure(self, tmp_path):
        """JSON output must include a summary sub-object with counts."""
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)
        (migrations_dir / "001_init.up.sql").write_text("SELECT 1;")
        (migrations_dir / "002_users.up.sql").write_text("SELECT 2;")

        config_file = tmp_path / "local.yaml"
        config_file.write_text("name: local\ndatabase_url: postgresql://localhost/test\n")

        runner = CliRunner()

        mock_migrator = MagicMock()
        mock_migrator.tracking_table_exists.return_value = True
        mock_migrator.get_applied_versions.return_value = ["001"]
        mock_migrator.get_applied_migrations_with_timestamps.return_value = [
            {"version": "001", "name": "init", "applied_at": "2025-01-15T10:30:00+00:00"}
        ]

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

        assert result.exit_code == 1, result.output
        data = json.loads(result.output)
        assert "summary" in data
        summary = data["summary"]
        assert "applied" in summary
        assert "pending" in summary
        assert "total" in summary
        assert summary["applied"] == 1
        assert summary["pending"] == 1
        assert summary["total"] == 2


class TestMigrateUpJsonKeys:
    """Tests for migrate up --format json canonical key names."""

    def test_migrate_up_json_uses_applied_key(self):
        """to_dict() must use 'applied' instead of 'migrations_applied'."""
        result = MigrateUpResult(
            success=True,
            migrations_applied=[MigrationApplied("001", "init", 100)],
            total_execution_time_ms=100,
        )
        data = result.to_dict()
        assert "applied" in data
        assert "migrations_applied" not in data

    def test_migrate_up_json_uses_total_duration_ms_key(self):
        """to_dict() must use 'total_duration_ms' instead of 'total_execution_time_ms'."""
        result = MigrateUpResult(
            success=True,
            migrations_applied=[],
            total_execution_time_ms=500,
        )
        data = result.to_dict()
        assert "total_duration_ms" in data
        assert data["total_duration_ms"] == 500
        assert "total_execution_time_ms" not in data

    def test_migrate_up_json_includes_skipped_list(self):
        """to_dict() must include a 'skipped' list field."""
        result = MigrateUpResult(
            success=True,
            migrations_applied=[],
            total_execution_time_ms=0,
            skipped=["001", "002"],
        )
        data = result.to_dict()
        assert "skipped" in data
        assert data["skipped"] == ["001", "002"]

    def test_migrate_up_json_uses_errors_array(self):
        """to_dict() must use 'errors' list instead of singular 'error'."""
        result = MigrateUpResult(
            success=False,
            migrations_applied=[],
            total_execution_time_ms=0,
            errors=["Lock timeout", "Connection reset"],
        )
        data = result.to_dict()
        assert "errors" in data
        assert data["errors"] == ["Lock timeout", "Connection reset"]
        assert "error" not in data

    def test_migration_applied_uses_duration_ms_key(self):
        """MigrationApplied.to_dict() must use 'duration_ms' instead of 'execution_time_ms'."""
        migration = MigrationApplied("001", "init", 250, 10)
        data = migration.to_dict()
        assert "duration_ms" in data
        assert data["duration_ms"] == 250
        assert "execution_time_ms" not in data

    def test_migrate_up_json_skipped_empty_by_default(self):
        """skipped defaults to empty list."""
        result = MigrateUpResult(
            success=True,
            migrations_applied=[],
            total_execution_time_ms=0,
        )
        data = result.to_dict()
        assert data["skipped"] == []

    def test_migrate_up_json_errors_empty_by_default(self):
        """errors defaults to empty list."""
        result = MigrateUpResult(
            success=True,
            migrations_applied=[],
            total_execution_time_ms=0,
        )
        data = result.to_dict()
        assert data["errors"] == []

    def test_migrate_up_json_no_count_field(self):
        """to_dict() must not include redundant 'count' field."""
        result = MigrateUpResult(
            success=True,
            migrations_applied=[MigrationApplied("001", "init", 100)],
            total_execution_time_ms=100,
        )
        data = result.to_dict()
        assert "count" not in data
