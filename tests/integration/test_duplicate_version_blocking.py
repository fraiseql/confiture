"""Integration tests for duplicate version blocking in migrate up and baseline.

These tests use the CLI runner and verify that migrate up / baseline
refuse to proceed when duplicate migration versions are detected.
They require a database connection (integration tests).
"""

import os

import pytest
from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()


def _make_config_file(tmp_path):
    """Create a minimal config file pointing to test database."""
    config_dir = tmp_path / "db" / "environments"
    config_dir.mkdir(parents=True)
    config_file = config_dir / "local.yaml"
    db_url = os.getenv("CONFITURE_TEST_DB_URL", "postgresql://localhost/confiture_test")
    config_file.write_text(f"name: local\ndatabase_url: {db_url}\n")
    return config_file


def _make_migration_file(migrations_dir, filename, version, name):
    """Create a Python migration file."""
    class_name = "".join(word.capitalize() for word in name.split("_"))
    (migrations_dir / filename).write_text(f"""
from confiture.models.migration import Migration

class {class_name}(Migration):
    version = "{version}"
    name = "{name}"

    def up(self):
        pass

    def down(self):
        pass
""")


@pytest.mark.integration
class TestMigrateUpDuplicateBlocking:
    """Test that migrate up refuses to run with duplicate versions."""

    def test_migrate_up_blocks_on_duplicates(self, tmp_path):
        """migrate up should exit 3 when duplicate versions exist."""
        config_file = _make_config_file(tmp_path)
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)

        _make_migration_file(migrations_dir, "001_create_users.py", "001", "create_users")
        _make_migration_file(migrations_dir, "001_backfill_data.py", "001", "backfill_data")

        result = runner.invoke(
            app,
            [
                "migrate",
                "up",
                "--config",
                str(config_file),
                "--migrations-dir",
                str(migrations_dir),
            ],
        )

        assert result.exit_code == 3
        # Error messages are now written to stderr for deployment automation.
        # The test verifies the correct exit code; the error message content
        # is verified in unit tests.

    def test_migrate_up_proceeds_without_duplicates(self, tmp_path):
        """migrate up should not block when no duplicate versions exist."""
        config_file = _make_config_file(tmp_path)
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)

        _make_migration_file(migrations_dir, "001_create_users.py", "001", "create_users")
        _make_migration_file(migrations_dir, "002_add_email.py", "002", "add_email")

        result = runner.invoke(
            app,
            [
                "migrate",
                "up",
                "--config",
                str(config_file),
                "--migrations-dir",
                str(migrations_dir),
            ],
        )

        # Should not fail with exit code 3 (may fail for other reasons like DB)
        assert result.exit_code != 3


@pytest.mark.integration
class TestMigrateBaselineDuplicateBlocking:
    """Test that migrate baseline refuses to run with duplicate versions."""

    def test_baseline_blocks_on_duplicates(self, tmp_path):
        """migrate baseline should exit 3 when duplicate versions exist."""
        config_file = _make_config_file(tmp_path)
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)

        _make_migration_file(migrations_dir, "001_create_users.py", "001", "create_users")
        _make_migration_file(migrations_dir, "001_backfill_data.py", "001", "backfill_data")

        result = runner.invoke(
            app,
            [
                "migrate",
                "baseline",
                "--through",
                "001",
                "--config",
                str(config_file),
                "--migrations-dir",
                str(migrations_dir),
            ],
        )

        assert result.exit_code == 3
        # Error messages are now written to stderr for deployment automation.
        # The test verifies the correct exit code; the error message content
        # is verified in unit tests.
