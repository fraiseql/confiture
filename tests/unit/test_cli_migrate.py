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

        # Should show --force option in help (check in stdout for compatibility)
        output_text = result.stdout if hasattr(result, "stdout") else result.output
        assert "--force" in output_text or "force" in output_text.lower()

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


class TestMigrateStatusCommand:
    """Test migrate status command."""

    def test_migrate_status_detects_orphaned_sql_files(self, tmp_path):
        """Test that migrate status warns about orphaned SQL files."""
        # Create migrations directory with orphaned files
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)

        # Create orphaned SQL files (missing .up/.down suffix)
        (migrations_dir / "001_initial_schema.sql").write_text("CREATE TABLE users (id INT);")
        (migrations_dir / "002_add_columns.sql").write_text("ALTER TABLE users ADD COLUMN email TEXT;")

        # Create properly named SQL migration files
        (migrations_dir / "003_add_indexes.up.sql").write_text(
            "CREATE INDEX idx_users_email ON users(email);"
        )
        (migrations_dir / "003_add_indexes.down.sql").write_text(
            "DROP INDEX idx_users_email;"
        )

        # Run migrate status
        result = runner.invoke(
            app,
            ["migrate", "status", "--migrations-dir", str(migrations_dir)],
        )

        # Should display warning about orphaned files
        assert "Orphaned migration files detected" in result.output
        assert "001_initial_schema.sql" in result.output
        assert "002_add_columns.sql" in result.output
        assert "rename to: 001_initial_schema.up.sql" in result.output
        assert "rename to: 002_add_columns.up.sql" in result.output

    def test_migrate_status_orphaned_files_json_output(self, tmp_path):
        """Test that orphaned files are included in JSON output."""
        import json

        # Create migrations directory with orphaned files
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)

        # Create orphaned SQL files
        (migrations_dir / "001_orphaned.sql").write_text("CREATE TABLE test (id INT);")

        # Create properly named file
        (migrations_dir / "002_proper.up.sql").write_text("CREATE TABLE test2 (id INT);")

        # Run migrate status with JSON output
        result = runner.invoke(
            app,
            [
                "migrate",
                "status",
                "--migrations-dir",
                str(migrations_dir),
                "--format",
                "json",
            ],
        )

        # Parse JSON output
        output = json.loads(result.output)

        # Should include orphaned_migrations field
        assert "orphaned_migrations" in output
        assert "001_orphaned.sql" in output["orphaned_migrations"]
        assert output["total"] == 1  # Only the properly named file is counted


class TestMigrateValidateCommand:
    """Test migrate validate command."""

    def test_migrate_validate_finds_orphaned_files(self, tmp_path):
        """Test that migrate validate detects orphaned migration files."""
        # Create migrations directory with orphaned files
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)

        # Create orphaned SQL files
        (migrations_dir / "001_initial_schema.sql").write_text("CREATE TABLE users (id INT);")
        (migrations_dir / "002_add_columns.sql").write_text("ALTER TABLE users ADD COLUMN email TEXT;")

        # Create properly named files
        (migrations_dir / "003_add_indexes.up.sql").write_text("CREATE INDEX idx_users_email ON users(email);")

        # Run migrate validate
        result = runner.invoke(
            app,
            ["migrate", "validate", "--migrations-dir", str(migrations_dir)],
        )

        # Should find and report orphaned files
        assert "001_initial_schema.sql" in result.output
        assert "002_add_columns.sql" in result.output
        assert result.exit_code == 0  # Validation only, no fix yet

    def test_migrate_validate_dry_run_shows_changes(self, tmp_path):
        """Test that --dry-run shows what would be changed without making changes."""
        # Create migrations directory with orphaned files
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)

        orphaned_file = migrations_dir / "001_initial_schema.sql"
        orphaned_file.write_text("CREATE TABLE users (id INT);")

        # Run migrate validate --dry-run
        result = runner.invoke(
            app,
            [
                "migrate",
                "validate",
                "--migrations-dir",
                str(migrations_dir),
                "--dry-run",
            ],
        )

        # Should show what would be renamed
        assert "001_initial_schema.sql" in result.output
        assert "001_initial_schema.up.sql" in result.output

        # File should NOT be renamed yet
        assert orphaned_file.exists()
        assert not (migrations_dir / "001_initial_schema.up.sql").exists()

    def test_migrate_validate_fix_naming_renames_files(self, tmp_path):
        """Test that --fix-naming actually renames the files."""
        # Create migrations directory with orphaned files
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)

        # Create orphaned SQL files with content
        content1 = "CREATE TABLE users (id INT);"
        content2 = "ALTER TABLE users ADD COLUMN email TEXT;"
        (migrations_dir / "001_initial_schema.sql").write_text(content1)
        (migrations_dir / "002_add_columns.sql").write_text(content2)

        # Run migrate validate --fix-naming
        result = runner.invoke(
            app,
            [
                "migrate",
                "validate",
                "--migrations-dir",
                str(migrations_dir),
                "--fix-naming",
            ],
        )

        # Should report fixes
        assert "Fixed" in result.output or "Renamed" in result.output
        assert "001_initial_schema.sql" in result.output
        assert "002_add_columns.sql" in result.output

        # Files should be renamed
        assert not (migrations_dir / "001_initial_schema.sql").exists()
        assert not (migrations_dir / "002_add_columns.sql").exists()
        assert (migrations_dir / "001_initial_schema.up.sql").exists()
        assert (migrations_dir / "002_add_columns.up.sql").exists()

        # Content should be preserved
        assert (migrations_dir / "001_initial_schema.up.sql").read_text() == content1
        assert (migrations_dir / "002_add_columns.up.sql").read_text() == content2

    def test_migrate_validate_fix_naming_json_output(self, tmp_path):
        """Test that --fix-naming provides JSON output with changes."""
        import json

        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)

        (migrations_dir / "001_orphaned.sql").write_text("CREATE TABLE test (id INT);")

        # Run migrate validate --fix-naming --format json
        result = runner.invoke(
            app,
            [
                "migrate",
                "validate",
                "--migrations-dir",
                str(migrations_dir),
                "--fix-naming",
                "--format",
                "json",
            ],
        )

        # Parse JSON output
        output = json.loads(result.output)

        # Should report the fix
        assert "fixed" in output or "renamed" in output
        assert len(output.get("fixed", [])) > 0 or len(output.get("renamed", [])) > 0

    def test_migrate_validate_no_orphaned_files(self, tmp_path):
        """Test that validate succeeds when all files are properly named."""
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)

        # Create only properly named files
        (migrations_dir / "001_create_users.up.sql").write_text("CREATE TABLE users (id INT);")
        (migrations_dir / "001_create_users.down.sql").write_text("DROP TABLE users;")

        # Run migrate validate
        result = runner.invoke(
            app,
            ["migrate", "validate", "--migrations-dir", str(migrations_dir)],
        )

        # Should succeed with no issues found
        assert "No orphaned migration files found" in result.output or "valid" in result.output.lower()
        assert result.exit_code == 0

    def test_migrate_validate_fix_naming_with_dry_run(self, tmp_path):
        """Test that --dry-run prevents --fix-naming from making changes."""
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)

        (migrations_dir / "001_orphaned.sql").write_text("CREATE TABLE test (id INT);")

        # Run migrate validate --dry-run --fix-naming
        result = runner.invoke(
            app,
            [
                "migrate",
                "validate",
                "--migrations-dir",
                str(migrations_dir),
                "--dry-run",
                "--fix-naming",
            ],
        )

        # Should show what would be done
        assert "001_orphaned.sql" in result.output

        # File should NOT be renamed (dry-run takes precedence)
        assert (migrations_dir / "001_orphaned.sql").exists()
        assert not (migrations_dir / "001_orphaned.up.sql").exists()
