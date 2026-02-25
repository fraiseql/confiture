"""Unit tests for 'confiture migrate reinit' CLI command.

Tests CLI argument parsing, validation, and output without requiring
a database connection. Integration tests are in
tests/integration/test_migrator_reinit.py.
"""

import os

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


class TestMigrateReinitValidation:
    """Test CLI validation for migrate reinit."""

    def test_reinit_missing_config_exits_1(self, tmp_path):
        """Should exit 1 when config file doesn't exist."""
        result = runner.invoke(
            app,
            [
                "migrate",
                "reinit",
                "--config",
                str(tmp_path / "nonexistent.yaml"),
                "--yes",
            ],
        )
        assert result.exit_code == 1
        assert "Config file not found" in result.output

    def test_reinit_missing_migrations_dir_exits_1(self, tmp_path):
        """Should exit 1 when migrations directory doesn't exist."""
        config_file = _make_config_file(tmp_path)
        result = runner.invoke(
            app,
            [
                "migrate",
                "reinit",
                "--config",
                str(config_file),
                "--migrations-dir",
                str(tmp_path / "nonexistent"),
                "--yes",
            ],
        )
        assert result.exit_code == 1
        assert "Migrations directory not found" in result.output

    def test_reinit_duplicate_versions_exits_3(self, tmp_path):
        """Should exit 3 when duplicate migration versions exist."""
        config_file = _make_config_file(tmp_path)
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)

        _make_migration_file(migrations_dir, "001_create_users.py", "001", "create_users")
        _make_migration_file(migrations_dir, "001_backfill_data.py", "001", "backfill_data")

        result = runner.invoke(
            app,
            [
                "migrate",
                "reinit",
                "--config",
                str(config_file),
                "--migrations-dir",
                str(migrations_dir),
                "--yes",
            ],
        )
        assert result.exit_code == 3
        assert "Duplicate migration versions" in result.output


class TestMigrateReinitHelp:
    """Test CLI help output."""

    def test_reinit_help(self):
        """Should show help text."""
        result = runner.invoke(app, ["migrate", "reinit", "--help"])
        assert result.exit_code == 0
        assert "--through" in result.output
        assert "--dry-run" in result.output
        assert "--yes" in result.output
        assert "--config" in result.output
        assert "--migrations-dir" in result.output
