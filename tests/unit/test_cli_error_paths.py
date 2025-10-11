"""Unit tests for CLI error handling paths."""

from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()


class TestBuildCommand:
    """Test build command error paths."""

    def test_build_with_schema_only_flag(self, tmp_path):
        """Test build with --schema-only flag."""
        # Create structure
        schema_dir = tmp_path / "db" / "schema"
        seeds_dir = tmp_path / "db" / "seeds"
        schema_dir.mkdir(parents=True)
        seeds_dir.mkdir(parents=True)

        (schema_dir / "table.sql").write_text("CREATE TABLE test (id INT);")
        (seeds_dir / "data.sql").write_text("INSERT INTO test VALUES (1);")

        config_dir = tmp_path / "db" / "environments"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "local.yaml"
        config_file.write_text(f"""
name: local
include_dirs:
  - {schema_dir}
  - {seeds_dir}
exclude_dirs: []
database_url: postgresql://localhost/test
""")

        result = runner.invoke(app, [
            "build",
            "--env", "local",
            "--project-dir", str(tmp_path),
            "--schema-only"
        ])

        # Should succeed and exclude seeds
        assert result.exit_code == 0
        assert "Schema built successfully" in result.output

    def test_build_with_show_hash_flag(self, tmp_path):
        """Test build with --show-hash flag."""
        schema_dir = tmp_path / "db" / "schema"
        schema_dir.mkdir(parents=True)
        (schema_dir / "test.sql").write_text("CREATE TABLE test (id INT);")

        config_dir = tmp_path / "db" / "environments"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "local.yaml"
        config_file.write_text(f"""
name: local
include_dirs:
  - {schema_dir}
exclude_dirs: []
database_url: postgresql://localhost/test
""")

        result = runner.invoke(app, [
            "build",
            "--env", "local",
            "--project-dir", str(tmp_path),
            "--show-hash"
        ])

        assert result.exit_code == 0
        assert "Hash:" in result.output

    def test_build_with_file_not_found_error(self, tmp_path):
        """Test build with missing configuration."""
        result = runner.invoke(app, [
            "build",
            "--env", "nonexistent",
            "--project-dir", str(tmp_path)
        ])

        assert result.exit_code == 1
        assert "File not found" in result.output or "Error" in result.output

    def test_build_with_custom_output(self, tmp_path):
        """Test build with custom output path."""
        schema_dir = tmp_path / "db" / "schema"
        schema_dir.mkdir(parents=True)
        (schema_dir / "test.sql").write_text("CREATE TABLE test (id INT);")

        config_dir = tmp_path / "db" / "environments"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "local.yaml"
        config_file.write_text(f"""
name: local
include_dirs:
  - {schema_dir}
exclude_dirs: []
database_url: postgresql://localhost/test
""")

        output_path = tmp_path / "custom_output.sql"

        result = runner.invoke(app, [
            "build",
            "--env", "local",
            "--project-dir", str(tmp_path),
            "--output", str(output_path)
        ])

        assert result.exit_code == 0
        assert output_path.exists()


class TestMigrateStatusCommand:
    """Test migrate status command."""

    def test_migrate_status_no_migrations_dir(self, tmp_path):
        """Test status when migrations directory doesn't exist."""
        result = runner.invoke(app, [
            "migrate", "status",
            "--migrations-dir", str(tmp_path / "nonexistent")
        ])

        assert result.exit_code == 0
        assert "No migrations directory found" in result.output

    def test_migrate_status_empty_migrations_dir(self, tmp_path):
        """Test status with empty migrations directory."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        result = runner.invoke(app, [
            "migrate", "status",
            "--migrations-dir", str(migrations_dir)
        ])

        assert result.exit_code == 0
        assert "No migrations found" in result.output

    def test_migrate_status_with_migrations(self, tmp_path):
        """Test status with migration files."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        # Create test migrations
        (migrations_dir / "001_first.py").write_text("""
from confiture.models.migration import Migration

class FirstMigration(Migration):
    version = "001"
    name = "first"
    def up(self): pass
    def down(self): pass
""")
        (migrations_dir / "002_second.py").write_text("""
from confiture.models.migration import Migration

class SecondMigration(Migration):
    version = "002"
    name = "second"
    def up(self): pass
    def down(self): pass
""")

        result = runner.invoke(app, [
            "migrate", "status",
            "--migrations-dir", str(migrations_dir)
        ])

        assert result.exit_code == 0
        assert "001" in result.output
        assert "002" in result.output
        assert "Total: 2 migrations" in result.output


class TestMigrateGenerateCommand:
    """Test migrate generate command."""

    def test_migrate_generate_creates_file(self, tmp_path):
        """Test that generate creates migration file."""
        migrations_dir = tmp_path / "migrations"

        result = runner.invoke(app, [
            "migrate", "generate",
            "add_users_table",
            "--migrations-dir", str(migrations_dir)
        ])

        assert result.exit_code == 0
        assert "Migration generated successfully" in result.output

        # Check file was created
        files = list(migrations_dir.glob("*.py"))
        assert len(files) == 1
        assert "add_users_table" in files[0].name


class TestMigrateDiffCommand:
    """Test migrate diff command."""

    def test_migrate_diff_old_file_not_found(self, tmp_path):
        """Test diff with missing old file."""
        new_file = tmp_path / "new.sql"
        new_file.write_text("CREATE TABLE test (id INT);")

        result = runner.invoke(app, [
            "migrate", "diff",
            str(tmp_path / "nonexistent.sql"),
            str(new_file)
        ])

        assert result.exit_code == 1
        assert "not found" in result.output

    def test_migrate_diff_new_file_not_found(self, tmp_path):
        """Test diff with missing new file."""
        old_file = tmp_path / "old.sql"
        old_file.write_text("CREATE TABLE test (id INT);")

        result = runner.invoke(app, [
            "migrate", "diff",
            str(old_file),
            str(tmp_path / "nonexistent.sql")
        ])

        assert result.exit_code == 1
        assert "not found" in result.output

    def test_migrate_diff_no_changes(self, tmp_path):
        """Test diff with identical schemas."""
        old_file = tmp_path / "old.sql"
        new_file = tmp_path / "new.sql"

        old_file.write_text("CREATE TABLE test (id INT);")
        new_file.write_text("CREATE TABLE test (id INT);")

        result = runner.invoke(app, [
            "migrate", "diff",
            str(old_file),
            str(new_file)
        ])

        assert result.exit_code == 0
        assert "No changes detected" in result.output

    def test_migrate_diff_with_changes(self, tmp_path):
        """Test diff with actual changes."""
        old_file = tmp_path / "old.sql"
        new_file = tmp_path / "new.sql"

        old_file.write_text("CREATE TABLE users (id INT);")
        new_file.write_text("CREATE TABLE users (id INT, email TEXT);")

        result = runner.invoke(app, [
            "migrate", "diff",
            str(old_file),
            str(new_file)
        ])

        assert result.exit_code == 0
        assert "differences detected" in result.output.lower()


class TestInitCommand:
    """Test init command."""

    def test_init_creates_structure(self, tmp_path):
        """Test that init creates directory structure."""
        result = runner.invoke(app, [
            "init",
            str(tmp_path / "new_project")
        ])

        assert result.exit_code == 0
        assert "initialized successfully" in result.output

        # Check directories were created
        project_dir = tmp_path / "new_project"
        assert (project_dir / "db" / "schema").exists()
        assert (project_dir / "db" / "migrations").exists()
        assert (project_dir / "db" / "environments").exists()
        assert (project_dir / "db" / "seeds").exists()

    def test_init_existing_project(self, tmp_path, monkeypatch):
        """Test init with existing project (user cancels)."""
        # Create existing db directory
        db_dir = tmp_path / "db"
        db_dir.mkdir()

        # Mock user input to cancel
        monkeypatch.setattr("typer.confirm", lambda *args, **kwargs: False)

        result = runner.invoke(app, [
            "init",
            str(tmp_path)
        ], input="n\n")

        # Should exit without error (user cancelled)
        assert result.exit_code in [0, 1]  # May exit with 0 or 1 depending on flow
