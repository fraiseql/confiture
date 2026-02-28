"""End-to-end tests for CLI commands (Milestone 1.12)."""

from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()


class TestCLIBasics:
    """Test basic CLI functionality."""

    def test_cli_help(self):
        """Should display help message."""
        result = runner.invoke(app, ["--help"])

        assert result.exit_code == 0
        assert "confiture" in result.stdout.lower()
        assert "PostgreSQL migrations" in result.stdout or "migration" in result.stdout.lower()

    def test_cli_version(self):
        """Should display version."""
        result = runner.invoke(app, ["--version"])

        assert result.exit_code == 0
        # Should output something like "0.1.0"
        assert any(char.isdigit() for char in result.stdout)


class TestInitCommand:
    """Test 'confiture init' command."""

    def test_init_creates_directory_structure(self, tmp_path):
        """Should create necessary directories."""
        result = runner.invoke(app, ["init", str(tmp_path)])

        assert result.exit_code == 0
        assert (tmp_path / "db").exists()
        assert (tmp_path / "db" / "schema").exists()
        assert (tmp_path / "db" / "migrations").exists()

    def test_init_creates_config_files(self, tmp_path):
        """Should create configuration files."""
        result = runner.invoke(app, ["init", str(tmp_path)])

        assert result.exit_code == 0
        assert (tmp_path / "db" / "environments").exists()
        assert (tmp_path / "db" / "environments" / "local.yaml").exists()

    def test_init_creates_example_schema(self, tmp_path):
        """Should create example schema file."""
        result = runner.invoke(app, ["init", str(tmp_path)])

        assert result.exit_code == 0
        schema_dir = tmp_path / "db" / "schema"

        # Should have at least one example file
        schema_files = list(schema_dir.rglob("*.sql"))
        assert len(schema_files) > 0

    def test_init_displays_success_message(self, tmp_path):
        """Should display success message."""
        result = runner.invoke(app, ["init", str(tmp_path)])

        assert result.exit_code == 0
        assert "initialized" in result.stdout.lower() or "created" in result.stdout.lower()

    def test_init_fails_if_already_initialized(self, tmp_path):
        """Should fail if project already initialized."""
        # Initialize once
        runner.invoke(app, ["init", str(tmp_path)])

        # Try to initialize again
        result = runner.invoke(app, ["init", str(tmp_path)])

        # Should fail or warn
        assert "already exists" in result.stdout.lower() or result.exit_code != 0


class TestMigrateStatusCommand:
    """Test 'confiture migrate status' command."""

    def test_status_shows_no_migrations(self, tmp_path):
        """Should show no migrations when directory is empty."""
        # Set up directory structure
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)

        result = runner.invoke(app, ["migrate", "status", "--migrations-dir", str(migrations_dir)])

        assert result.exit_code == 0
        assert "no migrations" in result.stdout.lower() or "0 migrations" in result.stdout.lower()

    def test_status_shows_pending_migrations(self, tmp_path):
        """Should list pending migrations."""
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)

        # Create a migration file
        migration_file = migrations_dir / "001_add_users.py"
        migration_file.write_text("""
from confiture.models.migration import Migration

class AddUsers(Migration):
    version = "001"
    name = "add_users"

    def up(self) -> None:
        self.execute("CREATE TABLE users (id INT)")

    def down(self) -> None:
        self.execute("DROP TABLE users")
""")

        result = runner.invoke(app, ["migrate", "status", "--migrations-dir", str(migrations_dir)])

        assert result.exit_code == 0
        assert "001_add_users" in result.stdout or "add_users" in result.stdout


class TestMigrateGenerateCommand:
    """Test 'confiture migrate generate' command."""

    def test_generate_creates_migration_file(self, tmp_path):
        """Should create a new migration file."""
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)

        result = runner.invoke(
            app,
            [
                "migrate",
                "generate",
                "add_users_table",
                "--migrations-dir",
                str(migrations_dir),
            ],
        )

        assert result.exit_code == 0

        # Should create migration file
        migration_files = list(migrations_dir.glob("*.py"))
        assert len(migration_files) == 1
        assert "add_users_table" in migration_files[0].name

    def test_generate_with_custom_sql(self, tmp_path):
        """Should generate migration with custom SQL."""
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)

        # Note: This test assumes we can pass SQL via stdin or flag
        # For MVP, we might just generate empty template
        result = runner.invoke(
            app,
            [
                "migrate",
                "generate",
                "test_migration",
                "--migrations-dir",
                str(migrations_dir),
            ],
        )

        assert result.exit_code == 0

        # Check file was created
        migration_files = list(migrations_dir.glob("*.py"))
        assert len(migration_files) == 1

    def test_generate_displays_file_path(self, tmp_path):
        """Should display path to generated file."""
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)

        result = runner.invoke(
            app,
            [
                "migrate",
                "generate",
                "test_migration",
                "--migrations-dir",
                str(migrations_dir),
            ],
        )

        assert result.exit_code == 0
        # Check for timestamp-based migration file in output
        assert "test_migration" in result.stdout
        assert ".py" in result.stdout  # File was created


class TestMigrateDiffCommand:
    """Test 'confiture migrate diff' command."""

    def test_diff_compares_two_schemas(self, tmp_path):
        """Should compare two schema files and show differences."""
        schema_dir = tmp_path / "schemas"
        schema_dir.mkdir()

        old_schema = schema_dir / "old.sql"
        old_schema.write_text("CREATE TABLE users (id INT PRIMARY KEY);")

        new_schema = schema_dir / "new.sql"
        new_schema.write_text("CREATE TABLE users (id INT PRIMARY KEY, name TEXT);")

        result = runner.invoke(
            app,
            ["migrate", "diff", str(old_schema), str(new_schema)],
        )

        assert result.exit_code == 0
        assert "ADD_COLUMN" in result.stdout or "add column" in result.stdout.lower()
        assert "name" in result.stdout.lower()

    def test_diff_with_no_changes(self, tmp_path):
        """Should report no changes when schemas are identical."""
        schema_dir = tmp_path / "schemas"
        schema_dir.mkdir()

        schema_sql = "CREATE TABLE users (id INT PRIMARY KEY);"
        old_schema = schema_dir / "old.sql"
        old_schema.write_text(schema_sql)

        new_schema = schema_dir / "new.sql"
        new_schema.write_text(schema_sql)

        result = runner.invoke(
            app,
            ["migrate", "diff", str(old_schema), str(new_schema)],
        )

        assert result.exit_code == 0
        assert "no changes" in result.stdout.lower() or "identical" in result.stdout.lower()

    def test_diff_with_generate_flag(self, tmp_path):
        """Should generate migration from diff when --generate flag is used."""
        schema_dir = tmp_path / "schemas"
        schema_dir.mkdir()
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        old_schema = schema_dir / "old.sql"
        old_schema.write_text("CREATE TABLE users (id INT);")

        new_schema = schema_dir / "new.sql"
        new_schema.write_text("CREATE TABLE users (id INT, name TEXT);")

        result = runner.invoke(
            app,
            [
                "migrate",
                "diff",
                str(old_schema),
                str(new_schema),
                "--generate",
                "--name",
                "add_name_column",
                "--migrations-dir",
                str(migrations_dir),
            ],
        )

        assert result.exit_code == 0

        # Should create migration file
        migration_files = list(migrations_dir.glob("*.py"))
        assert len(migration_files) == 1
        assert "add_name_column" in migration_files[0].name


class TestMigrateUpCommand:
    """Test 'confiture migrate up' command (Milestone 1.13)."""

    def test_up_applies_pending_migrations(self, tmp_path, test_db_connection):
        """Should apply all pending migrations."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir(parents=True)

        # Create migration file
        migration_file = migrations_dir / "001_create_test_table.py"
        migration_file.write_text("""
from confiture.models.migration import Migration

class CreateTestTable(Migration):
    version = "001"
    name = "create_test_table"

    def up(self) -> None:
        self.execute("CREATE TABLE cli_test_table (id SERIAL PRIMARY KEY)")

    def down(self) -> None:
        self.execute("DROP TABLE cli_test_table")
""")

        # Create temp config file
        config_dir = tmp_path / "environments"
        config_dir.mkdir()
        config_file = config_dir / "test.yaml"
        config_file.write_text(f"""
name: test
database:
  host: {test_db_connection.info.host}
  port: {test_db_connection.info.port}
  database: {test_db_connection.info.dbname}
  user: {test_db_connection.info.user}
  password: ""
""")

        result = runner.invoke(
            app,
            [
                "migrate",
                "up",
                "--migrations-dir",
                str(migrations_dir),
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code == 0, (
            f"CLI failed with exit code {result.exit_code}. Output: {result.output}"
        )
        assert "applied" in result.stdout.lower() or "success" in result.stdout.lower()

        # Verify table was created
        with test_db_connection.cursor() as cursor:
            cursor.execute("""
                SELECT EXISTS (
                    SELECT FROM pg_tables
                    WHERE tablename = 'cli_test_table'
                )
            """)
            exists = cursor.fetchone()[0]
            assert exists is True

        # Cleanup
        with test_db_connection.cursor() as cursor:
            cursor.execute("DROP TABLE IF EXISTS cli_test_table")
            cursor.execute("DELETE FROM tb_confiture WHERE version = '001'")
        test_db_connection.commit()

    def test_up_with_no_pending_migrations(self, tmp_path, test_db_connection):
        """Should report when no migrations need to be applied."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir(parents=True)

        config_dir = tmp_path / "environments"
        config_dir.mkdir()
        config_file = config_dir / "test.yaml"
        config_file.write_text(f"""
name: test
database:
  host: {test_db_connection.info.host}
  port: {test_db_connection.info.port}
  database: {test_db_connection.info.dbname}
  user: {test_db_connection.info.user}
  password: ""
""")

        result = runner.invoke(
            app,
            [
                "migrate",
                "up",
                "--migrations-dir",
                str(migrations_dir),
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code == 0
        assert "no pending" in result.stdout.lower() or "up to date" in result.stdout.lower()


class TestMigrateDownCommand:
    """Test 'confiture migrate down' command (Milestone 1.13)."""

    def test_down_rolls_back_last_migration(self, tmp_path, test_db_connection):
        """Should rollback the last applied migration."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir(parents=True)

        # Create and apply a migration first
        migration_file = migrations_dir / "001_create_rollback_test.py"
        migration_file.write_text("""
from confiture.models.migration import Migration

class CreateRollbackTest(Migration):
    version = "001"
    name = "create_rollback_test"

    def up(self) -> None:
        self.execute("CREATE TABLE rollback_test_table (id SERIAL PRIMARY KEY)")

    def down(self) -> None:
        self.execute("DROP TABLE rollback_test_table")
""")

        config_dir = tmp_path / "environments"
        config_dir.mkdir()
        config_file = config_dir / "test.yaml"
        config_file.write_text(f"""
name: test
database:
  host: {test_db_connection.info.host}
  port: {test_db_connection.info.port}
  database: {test_db_connection.info.dbname}
  user: {test_db_connection.info.user}
  password: ""
""")

        # Apply migration first
        runner.invoke(
            app,
            [
                "migrate",
                "up",
                "--migrations-dir",
                str(migrations_dir),
                "--config",
                str(config_file),
            ],
        )

        # Now rollback
        result = runner.invoke(
            app,
            [
                "migrate",
                "down",
                "--migrations-dir",
                str(migrations_dir),
                "--config",
                str(config_file),
            ],
        )

        assert result.exit_code == 0
        assert "rolled back" in result.stdout.lower() or "rollback" in result.stdout.lower()

        # Verify table was dropped
        with test_db_connection.cursor() as cursor:
            cursor.execute("""
                SELECT EXISTS (
                    SELECT FROM pg_tables
                    WHERE tablename = 'rollback_test_table'
                )
            """)
            exists = cursor.fetchone()[0]
            assert exists is False


class TestCLIErrorHandling:
    """Test CLI error handling."""

    def test_nonexistent_command(self):
        """Should show error for nonexistent command."""
        result = runner.invoke(app, ["nonexistent"])

        assert result.exit_code != 0

    def test_missing_required_argument(self):
        """Should show error for missing required argument."""
        result = runner.invoke(app, ["migrate", "diff"])

        assert result.exit_code != 0
        # Should mention missing argument (could be in stdout or stderr)
        output = (result.stdout + result.stderr).lower()
        assert "missing" in output or "required" in output or result.exit_code == 2

    def test_invalid_file_path(self):
        """Should show error for invalid file path."""
        result = runner.invoke(
            app,
            ["migrate", "diff", "/nonexistent/old.sql", "/nonexistent/new.sql"],
        )

        assert result.exit_code != 0
        assert "not found" in result.stdout.lower() or "does not exist" in result.stdout.lower()
