"""Unit tests for CLI migrate commands."""

from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()


class TestMigrateUpCommand:
    """Test migrate up command."""

    def test_migrate_up_force_flag_parsing(self, tmp_path):
        """Test that --force flag is parsed correctly."""
        # Create minimal config
        config_dir = tmp_path / "db" / "environments"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "test.yaml"
        config_file.write_text("""
name: test
database:
  host: localhost
  port: 5432
  database: test_db
  user: postgres
  password: postgres
""")

        # Test that --force flag is accepted (should not fail with unknown option)
        result = runner.invoke(app, ["migrate", "up", "--config", str(config_file), "--force"])

        # Should not fail with "No such option: --force"
        # Note: This will fail initially since --force is not implemented yet
        assert "--force" not in result.output or "No such option" not in result.output

    def test_migrate_up_force_flag_defaults_to_false(self, tmp_path):
        """Test that --force flag defaults to False when not provided."""
        # Create minimal config
        config_dir = tmp_path / "db" / "environments"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "test.yaml"
        config_file.write_text("""
name: test
database:
  host: localhost
  port: 5432
  database: test_db
  user: postgres
  password: postgres
""")

        # Test without --force flag (should work normally)
        result = runner.invoke(app, ["migrate", "up", "--config", str(config_file)])

        # Should not mention force in output (since it's not provided)
        assert "force" not in result.output.lower()

    def test_migrate_up_force_flag_help_text(self, tmp_path):
        """Test that --force flag appears in help text."""
        result = runner.invoke(app, ["migrate", "up", "--help"])

        # Should show --force option in help
        assert "--force" in result.output

    def test_migrate_up_force_shows_warning_message(self, tmp_path):
        """Test that force mode shows warning messages."""
        # Create minimal config
        config_dir = tmp_path / "db" / "environments"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "test.yaml"
        config_file.write_text("""
name: test
database:
  host: localhost
  port: 5432
  database: test_db
  user: postgres
  password: postgres
""")

        # Create a migration file
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)
        (migrations_dir / "001_test.py").write_text("""
from confiture.models.migration import Migration

class TestMigration(Migration):
    version = "001"
    name = "test"

    def up(self):
        pass

    def down(self):
        pass
""")

        # Test force mode shows warnings
        result = runner.invoke(
            app,
            [
                "migrate",
                "up",
                "--config",
                str(config_file),
                "--migrations-dir",
                str(migrations_dir),
                "--force",
            ],
        )

        # Should show warning messages
        assert "Force mode enabled" in result.output
        assert "skipping migration state checks" in result.output
        assert "Use with caution" in result.output
