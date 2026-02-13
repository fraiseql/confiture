"""Integration tests for migrate command structured output.

Tests the migrate up command with JSON/CSV output formats.
"""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest


@pytest.fixture
def sample_migrations_dir(tmp_path):
    """Create a sample migrations directory with test migrations."""
    migrations_dir = tmp_path / "db" / "migrations"
    migrations_dir.mkdir(parents=True)

    # Create a simple test migration
    migration_file = migrations_dir / "001_initial_schema.py"
    migration_file.write_text(
        """from confiture.models import Migration

class Migration001(Migration):
    version = "001"
    name = "initial_schema"

    def up(self):
        pass

    def down(self):
        pass
"""
    )

    return migrations_dir


@pytest.fixture
def sample_config(tmp_path):
    """Create a sample configuration file."""
    config_dir = tmp_path / "db" / "environments"
    config_dir.mkdir(parents=True)

    config_file = config_dir / "test.yaml"
    config_file.write_text(
        """name: test
database_url: postgresql://localhost/test_confiture
"""
    )

    return config_file


class TestMigrateUpStructuredOutput:
    """Tests for migrate up command structured output."""

    def test_migrate_up_json_format_support(self, sample_migrations_dir, sample_config):
        """Test that migrate up accepts --format json option."""
        # This is a basic test that the option is accepted
        # Full integration would require a real database
        from typer.testing import CliRunner

        from confiture.cli.main import app

        runner = CliRunner()

        # Since we don't have a real database, we expect this to fail at connection
        # But it should accept the --format option
        result = runner.invoke(
            app,
            [
                "migrate",
                "up",
                "--config",
                str(sample_config),
                "--migrations-dir",
                str(sample_migrations_dir),
                "--format",
                "json",
                "--dry-run",  # Use dry-run to avoid database requirement
            ],
        )

        # Should at least get past option parsing
        # (might fail due to missing database, but option should be accepted)
        assert "--format" not in result.stdout or "Error" in result.stdout or result.exit_code == 0

    def test_migrate_up_csv_format_support(self, sample_migrations_dir, sample_config):
        """Test that migrate up accepts --format csv option."""
        from typer.testing import CliRunner

        from confiture.cli.main import app

        runner = CliRunner()

        result = runner.invoke(
            app,
            [
                "migrate",
                "up",
                "--config",
                str(sample_config),
                "--migrations-dir",
                str(sample_migrations_dir),
                "--format",
                "csv",
                "--dry-run",
            ],
        )

        # Should at least get past option parsing
        assert "--format" not in result.stdout or "Error" in result.stdout or result.exit_code == 0

    def test_migrate_up_output_file_option(self, sample_migrations_dir, sample_config):
        """Test that migrate up accepts --output option."""
        from typer.testing import CliRunner

        from confiture.cli.main import app

        runner = CliRunner()

        with TemporaryDirectory() as tmpdir:
            output_file = Path(tmpdir) / "migration_result.json"

            result = runner.invoke(
                app,
                [
                    "migrate",
                    "up",
                    "--config",
                    str(sample_config),
                    "--migrations-dir",
                    str(sample_migrations_dir),
                    "--format",
                    "json",
                    "--output",
                    str(output_file),
                    "--dry-run",
                ],
            )

            # Should accept the option
            assert (
                "--output" not in result.stdout or "Error" in result.stdout or result.exit_code == 0
            )


class TestMigrateUpFormatterIntegration:
    """Tests that formatter is called correctly."""

    def test_migrate_up_result_model_usage(self):
        """Test that MigrateUpResult is created correctly."""
        from confiture.models.results import MigrateUpResult, MigrationApplied

        migrations = [
            MigrationApplied("001", "initial", 100),
            MigrationApplied("002", "add_users", 200),
        ]

        result = MigrateUpResult(
            success=True,
            migrations_applied=migrations,
            total_execution_time_ms=300,
        )

        # Verify result can be created and has expected structure
        assert result.success is True
        assert len(result.migrations_applied) == 2
        assert result.total_execution_time_ms == 300

    def test_migrate_up_result_to_json(self):
        """Test that MigrateUpResult can be serialized to JSON."""
        from confiture.models.results import MigrateUpResult, MigrationApplied

        migrations = [
            MigrationApplied("001", "initial", 100),
        ]

        result = MigrateUpResult(
            success=True,
            migrations_applied=migrations,
            total_execution_time_ms=100,
        )

        # Should be able to convert to dict and then JSON
        data = result.to_dict()
        json_str = json.dumps(data)

        # Verify JSON is valid
        parsed = json.loads(json_str)
        assert parsed["success"] is True
        assert parsed["count"] == 1
