"""Integration tests for idempotency validation workflow."""

from pathlib import Path
from textwrap import dedent

from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()


class TestIdempotencyWorkflow:
    """Tests for the complete validate -> fix -> validate workflow."""

    def test_full_workflow_validate_fix_validate(self, tmp_path: Path):
        """Test: validate -> fix -> validate produces clean result."""
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)

        # Create non-idempotent migrations
        (migrations_dir / "001_create_users.up.sql").write_text(
            dedent("""
                -- User table migration
                CREATE TABLE users (
                    id SERIAL PRIMARY KEY,
                    username TEXT NOT NULL,
                    email TEXT UNIQUE
                );
            """).strip()
        )

        (migrations_dir / "002_create_index.up.sql").write_text(
            "CREATE INDEX idx_users_email ON users(email);"
        )

        (migrations_dir / "003_add_function.up.sql").write_text(
            dedent("""
                CREATE FUNCTION get_user_count()
                RETURNS INTEGER AS $$
                    SELECT COUNT(*) FROM users;
                $$ LANGUAGE sql;
            """).strip()
        )

        # Step 1: Validate - should find violations
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
        assert "CREATE_TABLE" in result.stdout or "violation" in result.stdout.lower()

        # Step 2: Fix the issues
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

        # Step 3: Validate again - should be clean now
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

        # Verify the files were transformed correctly
        users_sql = (migrations_dir / "001_create_users.up.sql").read_text()
        assert "IF NOT EXISTS" in users_sql

        index_sql = (migrations_dir / "002_create_index.up.sql").read_text()
        assert "IF NOT EXISTS" in index_sql

        function_sql = (migrations_dir / "003_add_function.up.sql").read_text()
        assert "OR REPLACE" in function_sql

    def test_dry_run_does_not_modify_files(self, tmp_path: Path):
        """Dry run shows changes without modifying files."""
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)

        original_content = "CREATE TABLE users (id INT);"
        migration_file = migrations_dir / "001_create_users.up.sql"
        migration_file.write_text(original_content)

        # Run fix with --dry-run
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
        assert "IF NOT EXISTS" in result.stdout  # Shows what would change

        # File should NOT be modified
        assert migration_file.read_text() == original_content

    def test_already_idempotent_passes_validation(self, tmp_path: Path):
        """Already idempotent migrations pass validation."""
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)

        # Create fully idempotent migrations
        (migrations_dir / "001_create_users.up.sql").write_text(
            "CREATE TABLE IF NOT EXISTS users (id INT PRIMARY KEY);"
        )
        (migrations_dir / "002_create_index.up.sql").write_text(
            "CREATE INDEX IF NOT EXISTS idx_users ON users(id);"
        )
        (migrations_dir / "003_add_function.up.sql").write_text(
            "CREATE OR REPLACE FUNCTION test() RETURNS VOID AS $$ BEGIN END; $$ LANGUAGE plpgsql;"
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

    def test_json_output_for_ci_integration(self, tmp_path: Path):
        """JSON output works for CI/CD pipeline integration."""
        import json

        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)

        (migrations_dir / "001_create_users.up.sql").write_text("CREATE TABLE users (id INT);")

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

        assert result.exit_code == 1

        # Parse JSON output
        output = json.loads(result.stdout)

        assert output["status"] == "issues_found"
        assert output["violation_count"] == 1
        assert len(output["violations"]) == 1
        assert output["violations"][0]["pattern"] == "CREATE_TABLE"
        assert output["violations"][0]["fix_available"] is True

    def test_multiple_patterns_detected(self, tmp_path: Path):
        """Multiple different pattern types are detected."""
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)

        (migrations_dir / "001_complex.up.sql").write_text(
            dedent("""
                CREATE TABLE users (id INT);
                CREATE INDEX idx_users ON users(id);
                CREATE VIEW v_users AS SELECT * FROM users;
                DROP TABLE old_table;
            """).strip()
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

        output = json.loads(result.stdout)

        # Should find all 4 violations
        patterns_found = {v["pattern"] for v in output["violations"]}
        assert "CREATE_TABLE" in patterns_found
        assert "CREATE_INDEX" in patterns_found
        assert "CREATE_VIEW" in patterns_found
        assert "DROP_TABLE" in patterns_found

    def test_exit_code_reflects_violations_for_ci(self, tmp_path: Path):
        """Exit code is non-zero when violations found (for CI/CD)."""
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)

        # Non-idempotent migration
        (migrations_dir / "001_create_users.up.sql").write_text("CREATE TABLE users (id INT);")

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

        assert result.exit_code == 1  # Non-zero for CI failure

    def test_fix_preserves_sql_structure(self, tmp_path: Path):
        """Fix command preserves SQL structure and only adds idempotency."""
        migrations_dir = tmp_path / "db" / "migrations"
        migrations_dir.mkdir(parents=True)

        migration_file = migrations_dir / "001_create_users.up.sql"
        migration_file.write_text(
            dedent("""
                -- Migration: Create users table
                CREATE TABLE users (
                    id SERIAL PRIMARY KEY,
                    username TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT NOW()
                );
            """).strip()
        )

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

        fixed_content = migration_file.read_text()

        # Should preserve comments
        assert "Migration: Create users table" in fixed_content

        # Should preserve table structure
        assert "id SERIAL PRIMARY KEY" in fixed_content
        assert "username TEXT NOT NULL" in fixed_content
        assert "created_at TIMESTAMP DEFAULT NOW()" in fixed_content

        # Should add IF NOT EXISTS
        assert "IF NOT EXISTS" in fixed_content
