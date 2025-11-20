# tests/e2e/test_cli_error_reporting.py

import tempfile
from pathlib import Path

from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()


def test_migrate_up_shows_detailed_error_on_sql_failure():
    """CLI should show detailed error message when migration SQL fails"""

    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)

        # Initialize project
        result = runner.invoke(app, ["init", str(project_dir)])
        assert result.exit_code == 0

        # Create failing migration
        migrations_dir = project_dir / "db" / "migrations"
        migration_file = migrations_dir / "001_failing_migration.py"
        migration_file.write_text("""
from confiture.models.migration import Migration

class FailingMigration(Migration):
    version = "001"
    name = "failing_migration"

    def up(self):
        self.execute("CREATE TABLE users (id INT)")  # OK
        self.execute("INVALID SQL SYNTAX HERE")      # FAIL

    def down(self):
        self.execute("DROP TABLE IF EXISTS users")
""")

        # Create test config
        config_file = project_dir / "db" / "environments" / "local.yaml"
        config_file.write_text("""
name: local
database:
  host: localhost
  port: 5432
  database: confiture_test
  user: postgres
  password: postgres
include_dirs:
  - db/schema
exclude_dirs: []
""")

        # Run migration (should fail)
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

        # Verify CLI behavior
        assert result.exit_code == 1, "Should return non-zero exit code"

        # Verify error message contains:
        output = result.stdout
        assert "❌" in output or "Error" in output, "Should show error indicator"
        assert "001" in output, "Should show migration version"
        assert "failing_migration" in output, "Should show migration name"
        assert "SQL" in output, "Should mention SQL error"

        # Verify detailed error is shown (not just generic message)
        assert "INVALID SQL" in output or "syntax" in output.lower()


def test_migrate_up_shows_progress_and_stops_on_error(clean_test_db):
    """CLI should show which migrations succeeded before stopping"""

    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)

        # Initialize project
        result = runner.invoke(app, ["init", str(project_dir)])

        # Update config to use test database
        config_file = project_dir / "db" / "environments" / "local.yaml"
        config_file.write_text(f"""
name: local
database:
  host: {clean_test_db.info.host}
  port: {clean_test_db.info.port}
  database: {clean_test_db.info.dbname}
  user: {clean_test_db.info.user}
  password: ""
include_dirs:
  - db/schema/00_common
  - db/schema/10_tables
exclude_dirs: []
""")

        migrations_dir = project_dir / "db" / "migrations"

        # Create 3 migrations: 2 succeed, 1 fails
        (migrations_dir / "001_success.py").write_text("""
from confiture.models.migration import Migration

class Success1(Migration):
    version = "001"
    name = "success"

    def up(self):
        self.execute("CREATE TABLE table1 (id INT)")

    def down(self):
        self.execute("DROP TABLE table1")
""")

        (migrations_dir / "002_success2.py").write_text("""
from confiture.models.migration import Migration

class Success2(Migration):
    version = "002"
    name = "success2"

    def up(self):
        self.execute("CREATE TABLE table2 (id INT)")

    def down(self):
        self.execute("DROP TABLE table2")
""")

        (migrations_dir / "003_fail.py").write_text("""
from confiture.models.migration import Migration

class Failure(Migration):
    version = "003"
    name = "fail"

    def up(self):
        self.execute("INVALID SQL")

    def down(self):
        pass
""")

        # Run migrations
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

        # Should show progress
        output = result.stdout
        assert "001" in output, "Should show first migration started"
        assert "002" in output, "Should show second migration started"
        assert "003" in output, "Should show third migration started"

        # Should show success markers for first two
        assert output.count("✅") >= 2 or output.count("applied") >= 2

        # Should show error for third
        assert "❌" in output or "Error" in output
        assert result.exit_code == 1


def test_error_message_includes_troubleshooting_hints(clean_test_db):
    """Error messages should include helpful troubleshooting guidance"""

    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)
        result = runner.invoke(app, ["init", str(project_dir)])

        # Update config to use test database
        config_file = project_dir / "db" / "environments" / "local.yaml"
        config_file.write_text(f"""
name: local
database:
  host: {clean_test_db.info.host}
  port: {clean_test_db.info.port}
  database: {clean_test_db.info.dbname}
  user: {clean_test_db.info.user}
  password: ""
include_dirs:
  - db/schema/00_common
  - db/schema/10_tables
exclude_dirs: []
""")

        migrations_dir = project_dir / "db" / "migrations"

        # Create migration with schema error
        (migrations_dir / "001_schema_error.py").write_text("""
from confiture.models.migration import Migration

class SchemaError(Migration):
    version = "001"
    name = "schema_error"

    def up(self):
        self.execute("CREATE TABLE nonexistent_schema.users (id INT)")

    def down(self):
        pass
""")

        # Run migration
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

        output = result.stdout

        # Should include helpful guidance
        assert "schema" in output.lower()
        assert "does not exist" in output.lower() or "not found" in output.lower()
