"""Tests for idempotency CLI integration."""

from pathlib import Path

from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()


class TestIdempotencyValidateCLI:
    """Tests for confiture migrate validate --idempotent command."""

    def test_validate_idempotent_clean_migrations(self, tmp_path: Path):
        """Clean idempotent migrations pass validation."""
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)

        # Create an idempotent migration
        (migrations_dir / "001_create_users.up.sql").write_text(
            "CREATE TABLE IF NOT EXISTS users (id INT PRIMARY KEY);"
        )

        result = runner.invoke(
            app,
            [
                "migrate",
                "validate",
                "--idempotent",
                "--migrations-dir",
                str(migrations_dir),
            ],
        )

        assert result.exit_code == 0
        assert "idempotent" in result.stdout.lower() or "✅" in result.stdout

    def test_validate_idempotent_finds_violations(self, tmp_path: Path):
        """Non-idempotent migrations are flagged."""
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)

        # Create a non-idempotent migration
        (migrations_dir / "001_create_users.up.sql").write_text(
            "CREATE TABLE users (id INT PRIMARY KEY);"
        )

        result = runner.invoke(
            app,
            [
                "migrate",
                "validate",
                "--idempotent",
                "--migrations-dir",
                str(migrations_dir),
            ],
        )

        assert result.exit_code == 1
        assert "CREATE TABLE" in result.stdout or "violation" in result.stdout.lower()

    def test_validate_idempotent_shows_suggestions(self, tmp_path: Path):
        """Validation shows fix suggestions for violations."""
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)

        (migrations_dir / "001_create_users.up.sql").write_text(
            "CREATE TABLE users (id INT PRIMARY KEY);"
        )

        result = runner.invoke(
            app,
            [
                "migrate",
                "validate",
                "--idempotent",
                "--migrations-dir",
                str(migrations_dir),
            ],
        )

        assert "IF NOT EXISTS" in result.stdout

    def test_validate_idempotent_multiple_files(self, tmp_path: Path):
        """Validates multiple migration files."""
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)

        (migrations_dir / "001_create_users.up.sql").write_text(
            "CREATE TABLE users (id INT PRIMARY KEY);"
        )
        (migrations_dir / "002_create_index.up.sql").write_text(
            "CREATE INDEX idx_users ON users(id);"
        )

        result = runner.invoke(
            app,
            [
                "migrate",
                "validate",
                "--idempotent",
                "--migrations-dir",
                str(migrations_dir),
            ],
        )

        # Both files should have violations reported
        assert result.exit_code == 1
        assert "001_create_users" in result.stdout or "users" in result.stdout.lower()
        assert "002_create_index" in result.stdout or "index" in result.stdout.lower()

    def test_validate_idempotent_json_output(self, tmp_path: Path):
        """JSON output format works for idempotency validation."""
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)

        (migrations_dir / "001_create_users.up.sql").write_text(
            "CREATE TABLE users (id INT PRIMARY KEY);"
        )

        result = runner.invoke(
            app,
            [
                "migrate",
                "validate",
                "--idempotent",
                "--format",
                "json",
                "--migrations-dir",
                str(migrations_dir),
            ],
        )

        import json

        # Should be valid JSON
        output = json.loads(result.stdout)
        assert "violations" in output or "status" in output

    def test_validate_idempotent_file_output(self, tmp_path: Path):
        """Can save validation report to file."""
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)
        output_file = tmp_path / "report.json"

        (migrations_dir / "001_create_users.up.sql").write_text(
            "CREATE TABLE users (id INT PRIMARY KEY);"
        )

        runner.invoke(
            app,
            [
                "migrate",
                "validate",
                "--idempotent",
                "--format",
                "json",
                "--output",
                str(output_file),
                "--migrations-dir",
                str(migrations_dir),
            ],
        )

        assert output_file.exists()

    def test_validate_idempotent_empty_dir(self, tmp_path: Path):
        """Empty migrations directory handles gracefully."""
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)

        result = runner.invoke(
            app,
            [
                "migrate",
                "validate",
                "--idempotent",
                "--migrations-dir",
                str(migrations_dir),
            ],
        )

        assert result.exit_code == 0


class TestIdempotencyFixCLI:
    """Tests for confiture migrate fix --idempotent command."""

    def test_fix_idempotent_transforms_sql(self, tmp_path: Path):
        """Fix command transforms non-idempotent SQL to idempotent."""
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)

        migration_file = migrations_dir / "001_create_users.up.sql"
        migration_file.write_text("CREATE TABLE users (id INT PRIMARY KEY);")

        result = runner.invoke(
            app,
            [
                "migrate",
                "fix",
                "--idempotent",
                "--migrations-dir",
                str(migrations_dir),
            ],
        )

        assert result.exit_code == 0

        # File should be modified
        fixed_content = migration_file.read_text()
        assert "IF NOT EXISTS" in fixed_content

    def test_fix_idempotent_dry_run(self, tmp_path: Path):
        """Dry run shows changes without modifying files."""
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)

        migration_file = migrations_dir / "001_create_users.up.sql"
        original_content = "CREATE TABLE users (id INT PRIMARY KEY);"
        migration_file.write_text(original_content)

        result = runner.invoke(
            app,
            [
                "migrate",
                "fix",
                "--idempotent",
                "--dry-run",
                "--migrations-dir",
                str(migrations_dir),
            ],
        )

        assert result.exit_code == 0

        # File should NOT be modified
        assert migration_file.read_text() == original_content

        # Output should show what would change
        assert "IF NOT EXISTS" in result.stdout

    def test_fix_idempotent_multiple_files(self, tmp_path: Path):
        """Fix command handles multiple files."""
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)

        file1 = migrations_dir / "001_create_users.up.sql"
        file1.write_text("CREATE TABLE users (id INT);")

        file2 = migrations_dir / "002_create_index.up.sql"
        file2.write_text("CREATE INDEX idx_users ON users(id);")

        result = runner.invoke(
            app,
            [
                "migrate",
                "fix",
                "--idempotent",
                "--migrations-dir",
                str(migrations_dir),
            ],
        )

        assert result.exit_code == 0
        assert "IF NOT EXISTS" in file1.read_text()
        assert "IF NOT EXISTS" in file2.read_text()

    def test_fix_idempotent_preserves_already_idempotent(self, tmp_path: Path):
        """Fix command preserves files that are already idempotent."""
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)

        migration_file = migrations_dir / "001_create_users.up.sql"
        idempotent_content = "CREATE TABLE IF NOT EXISTS users (id INT PRIMARY KEY);"
        migration_file.write_text(idempotent_content)

        result = runner.invoke(
            app,
            [
                "migrate",
                "fix",
                "--idempotent",
                "--migrations-dir",
                str(migrations_dir),
            ],
        )

        assert result.exit_code == 0
        # Content should remain unchanged
        assert migration_file.read_text() == idempotent_content

    def test_fix_idempotent_json_output(self, tmp_path: Path):
        """JSON output format works for fix command."""
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)

        (migrations_dir / "001_create_users.up.sql").write_text(
            "CREATE TABLE users (id INT PRIMARY KEY);"
        )

        result = runner.invoke(
            app,
            [
                "migrate",
                "fix",
                "--idempotent",
                "--dry-run",
                "--format",
                "json",
                "--migrations-dir",
                str(migrations_dir),
            ],
        )

        import json

        output = json.loads(result.stdout)
        assert "files" in output or "fixed" in output or "changes" in output


class TestIdempotencyValidateCombined:
    """Tests for combined naming + idempotency validation."""

    def test_validate_both_naming_and_idempotent(self, tmp_path: Path):
        """Can run both naming and idempotency validation together."""
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)

        # Valid naming but not idempotent
        (migrations_dir / "001_create_users.up.sql").write_text(
            "CREATE TABLE users (id INT PRIMARY KEY);"
        )

        result = runner.invoke(
            app,
            [
                "migrate",
                "validate",
                "--idempotent",
                "--migrations-dir",
                str(migrations_dir),
            ],
        )

        # Should fail due to idempotency issue
        assert result.exit_code == 1

    def test_validate_naming_only_by_default(self, tmp_path: Path):
        """Without --idempotent flag, only naming is checked."""
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)

        # Valid naming but not idempotent - should pass without --idempotent
        (migrations_dir / "001_create_users.up.sql").write_text(
            "CREATE TABLE users (id INT PRIMARY KEY);"
        )

        result = runner.invoke(
            app,
            [
                "migrate",
                "validate",
                "--migrations-dir",
                str(migrations_dir),
            ],
        )

        # Should pass since naming is valid
        assert result.exit_code == 0
