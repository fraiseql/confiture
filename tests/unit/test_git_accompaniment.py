"""Tests for migration accompaniment validation.

Tests that DDL changes are accompanied by migration files.
"""

from pathlib import Path
from tempfile import TemporaryDirectory

from confiture.core.git_accompaniment import MigrationAccompanimentChecker
from confiture.models.git import MigrationAccompanimentReport


class TestMigrationAccompanimentChecker:
    """Tests for MigrationAccompanimentChecker class."""

    def test_check_accompaniment_ddl_with_migration(self):
        """Test valid accompaniment: DDL changes + new migration."""
        with TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            import subprocess

            # Initialize repo
            subprocess.run(
                ["git", "init"],
                cwd=repo_path,
                check=True,
                capture_output=True
            )
            subprocess.run(
                ["git", "config", "user.email", "test@test.com"],
                cwd=repo_path,
                check=True,
                capture_output=True
            )
            subprocess.run(
                ["git", "config", "user.name", "Test User"],
                cwd=repo_path,
                check=True,
                capture_output=True
            )

            # Create confiture config
            config_dir = repo_path / "db" / "environments"
            config_dir.mkdir(parents=True)
            (config_dir / "local.yaml").write_text(
                "database_url: postgresql://localhost/test\n"
                "include_dirs:\n"
                "  - path: db/schema\n"
                "    recursive: true\n"
            )

            # Initial commit with schema
            schema_dir = repo_path / "db" / "schema"
            schema_dir.mkdir(parents=True)
            (schema_dir / "users.sql").write_text("CREATE TABLE users (id INT);")
            migrations_dir = repo_path / "db" / "migrations"
            migrations_dir.mkdir()
            subprocess.run(
                ["git", "add", "."],
                cwd=repo_path,
                check=True,
                capture_output=True
            )
            subprocess.run(
                ["git", "commit", "-m", "Initial"],
                cwd=repo_path,
                check=True,
                capture_output=True
            )

            # Add DDL change and migration
            (schema_dir / "users.sql").write_text(
                "CREATE TABLE users (id INT, email TEXT);"
            )
            (migrations_dir / "001_add_email.up.sql").write_text(
                "ALTER TABLE users ADD COLUMN email TEXT;"
            )
            subprocess.run(
                ["git", "add", "."],
                cwd=repo_path,
                check=True,
                capture_output=True
            )
            subprocess.run(
                ["git", "commit", "-m", "Add email column"],
                cwd=repo_path,
                check=True,
                capture_output=True
            )

            # Check accompaniment
            checker = MigrationAccompanimentChecker("local", repo_path)
            report = checker.check_accompaniment("HEAD~1", "HEAD")

            assert report.has_ddl_changes
            assert report.has_new_migrations
            assert report.is_valid

    def test_check_accompaniment_ddl_without_migration(self):
        """Test invalid accompaniment: DDL changes but no migration."""
        with TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            import subprocess

            # Initialize repo
            subprocess.run(
                ["git", "init"],
                cwd=repo_path,
                check=True,
                capture_output=True
            )
            subprocess.run(
                ["git", "config", "user.email", "test@test.com"],
                cwd=repo_path,
                check=True,
                capture_output=True
            )
            subprocess.run(
                ["git", "config", "user.name", "Test User"],
                cwd=repo_path,
                check=True,
                capture_output=True
            )

            # Create confiture config
            config_dir = repo_path / "db" / "environments"
            config_dir.mkdir(parents=True)
            (config_dir / "local.yaml").write_text(
                "database_url: postgresql://localhost/test\n"
                "include_dirs:\n"
                "  - path: db/schema\n"
                "    recursive: true\n"
            )

            # Initial commit
            schema_dir = repo_path / "db" / "schema"
            schema_dir.mkdir(parents=True)
            (schema_dir / "users.sql").write_text("CREATE TABLE users (id INT);")
            migrations_dir = repo_path / "db" / "migrations"
            migrations_dir.mkdir()
            subprocess.run(
                ["git", "add", "."],
                cwd=repo_path,
                check=True,
                capture_output=True
            )
            subprocess.run(
                ["git", "commit", "-m", "Initial"],
                cwd=repo_path,
                check=True,
                capture_output=True
            )

            # Add DDL change WITHOUT migration
            (schema_dir / "users.sql").write_text(
                "CREATE TABLE users (id INT, email TEXT);"
            )
            subprocess.run(
                ["git", "add", "."],
                cwd=repo_path,
                check=True,
                capture_output=True
            )
            subprocess.run(
                ["git", "commit", "-m", "Add email column"],
                cwd=repo_path,
                check=True,
                capture_output=True
            )

            # Check accompaniment
            checker = MigrationAccompanimentChecker("local", repo_path)
            report = checker.check_accompaniment("HEAD~1", "HEAD")

            assert report.has_ddl_changes
            assert not report.has_new_migrations
            assert not report.is_valid

    def test_check_accompaniment_no_ddl_changes(self):
        """Test valid when no DDL changes at all."""
        with TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            import subprocess

            # Initialize repo
            subprocess.run(
                ["git", "init"],
                cwd=repo_path,
                check=True,
                capture_output=True
            )
            subprocess.run(
                ["git", "config", "user.email", "test@test.com"],
                cwd=repo_path,
                check=True,
                capture_output=True
            )
            subprocess.run(
                ["git", "config", "user.name", "Test User"],
                cwd=repo_path,
                check=True,
                capture_output=True
            )

            # Create confiture config
            config_dir = repo_path / "db" / "environments"
            config_dir.mkdir(parents=True)
            (config_dir / "local.yaml").write_text(
                "database_url: postgresql://localhost/test\n"
                "include_dirs:\n"
                "  - path: db/schema\n"
                "    recursive: true\n"
            )

            # Initial commit
            schema_dir = repo_path / "db" / "schema"
            schema_dir.mkdir(parents=True)
            (schema_dir / "users.sql").write_text("CREATE TABLE users (id INT);")
            migrations_dir = repo_path / "db" / "migrations"
            migrations_dir.mkdir()
            subprocess.run(
                ["git", "add", "."],
                cwd=repo_path,
                check=True,
                capture_output=True
            )
            subprocess.run(
                ["git", "commit", "-m", "Initial"],
                cwd=repo_path,
                check=True,
                capture_output=True
            )

            # Make change that's not DDL (e.g., docs)
            (repo_path / "README.md").write_text("# Updated docs")
            subprocess.run(
                ["git", "add", "."],
                cwd=repo_path,
                check=True,
                capture_output=True
            )
            subprocess.run(
                ["git", "commit", "-m", "Update docs"],
                cwd=repo_path,
                check=True,
                capture_output=True
            )

            # Check accompaniment
            checker = MigrationAccompanimentChecker("local", repo_path)
            report = checker.check_accompaniment("HEAD~1", "HEAD")

            assert not report.has_ddl_changes
            assert not report.has_new_migrations
            assert report.is_valid

    def test_accompaniment_report_to_dict(self):
        """Test report serialization to dictionary."""
        from confiture.models.schema import SchemaChange

        changes = [
            SchemaChange(type="ADD_TABLE", table="users"),
            SchemaChange(type="ADD_COLUMN", table="posts", column="author_id"),
        ]
        files = [
            Path("db/migrations/001_add_users.up.sql"),
            Path("db/migrations/001_add_users.down.sql"),
        ]

        report = MigrationAccompanimentReport(
            has_ddl_changes=True,
            has_new_migrations=True,
            ddl_changes=changes,
            new_migration_files=files,
            base_ref="origin/main",
            target_ref="HEAD",
        )

        data = report.to_dict()

        assert data["is_valid"] is True
        assert data["has_ddl_changes"] is True
        assert data["has_new_migrations"] is True
        assert len(data["ddl_changes"]) == 2
        assert len(data["new_migration_files"]) == 2
        assert data["base_ref"] == "origin/main"
        assert data["target_ref"] == "HEAD"

    def test_accompaniment_report_summary(self):
        """Test report summary generation."""
        from confiture.models.schema import SchemaChange

        # Valid case
        report = MigrationAccompanimentReport(
            has_ddl_changes=True,
            has_new_migrations=True,
            ddl_changes=[SchemaChange(type="ADD_TABLE", table="users")],
            new_migration_files=[Path("db/migrations/001.up.sql")],
        )
        assert "Valid" in report.summary()

        # Invalid case
        report = MigrationAccompanimentReport(
            has_ddl_changes=True,
            has_new_migrations=False,
            ddl_changes=[SchemaChange(type="ADD_TABLE", table="users")],
        )
        assert "Invalid" in report.summary()

        # No changes
        report = MigrationAccompanimentReport(
            has_ddl_changes=False,
            has_new_migrations=False,
        )
        assert "No DDL" in report.summary()
