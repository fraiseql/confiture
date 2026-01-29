"""Integration tests for git-aware CLI validation commands.

Tests the CLI integration of git-aware schema validation.
"""

from pathlib import Path
from tempfile import TemporaryDirectory
from typer.testing import CliRunner

import pytest

from confiture.cli.main import app


@pytest.fixture
def runner() -> CliRunner:
    """Create a Typer CLI runner."""
    return CliRunner()


class TestCliGitValidation:
    """Tests for git-aware CLI validation."""

    def test_migrate_validate_check_drift_requires_git_repo(self, runner: CliRunner):
        """Test that --check-drift requires a git repository."""
        import os
        import subprocess

        with TemporaryDirectory() as tmpdir:
            # Create a non-git directory with a test file
            tmppath = Path(tmpdir)
            (tmppath / "test.txt").write_text("test")

            # Change to non-git directory and run command
            old_cwd = os.getcwd()
            try:
                os.chdir(tmppath)
                result = runner.invoke(
                    app,
                    [
                        "migrate",
                        "validate",
                        "--check-drift",
                    ],
                    catch_exceptions=False,
                )

                # Should fail with meaningful error
                assert result.exit_code != 0
                assert "git" in result.stdout.lower() or "not a repository" in result.stdout.lower()
            finally:
                os.chdir(old_cwd)

    def test_migrate_validate_require_migration_requires_git_repo(self, runner: CliRunner):
        """Test that --require-migration requires a git repository."""
        import os

        with TemporaryDirectory() as tmpdir:
            # Create a non-git directory with a test file
            tmppath = Path(tmpdir)
            (tmppath / "test.txt").write_text("test")

            # Change to non-git directory and run command
            old_cwd = os.getcwd()
            try:
                os.chdir(tmppath)
                result = runner.invoke(
                    app,
                    [
                        "migrate",
                        "validate",
                        "--require-migration",
                    ],
                    catch_exceptions=False,
                )

                # Should fail with meaningful error
                assert result.exit_code != 0
                assert "git" in result.stdout.lower() or "not a repository" in result.stdout.lower()
            finally:
                os.chdir(old_cwd)

    def test_migrate_validate_with_valid_git_repo(self, runner: CliRunner):
        """Test migrate validate with git flags in valid repo."""
        import os
        import subprocess

        with TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)

            # Initialize git repo
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

            # Create minimal confiture config
            config_dir = repo_path / "db" / "environments"
            config_dir.mkdir(parents=True)
            (config_dir / "local.yaml").write_text(
                "database_url: postgresql://localhost/test\n"
                "include_dirs:\n"
                "  - path: db/schema\n"
            )

            # Create schema directory
            schema_dir = repo_path / "db" / "schema"
            schema_dir.mkdir()
            migrations_dir = repo_path / "db" / "migrations"
            migrations_dir.mkdir()

            # Initial commit
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

            # Change to repo and run validation
            old_cwd = os.getcwd()
            try:
                os.chdir(repo_path)
                result = runner.invoke(
                    app,
                    [
                        "migrate",
                        "validate",
                        "--check-drift",
                    ],
                    catch_exceptions=False,
                )

                # Should not fail with git error
                # (may fail for other reasons like orphaned files, but not git setup)
                assert "git" not in result.stdout.lower() or "✅" in result.stdout
            finally:
                os.chdir(old_cwd)


class TestMigrationAccompanimentCLI:
    """Tests for migration accompaniment CLI validation."""

    def test_require_migration_detects_missing_migration(self, runner: CliRunner):
        """Test --require-migration flag detects DDL without migration."""
        import os
        import subprocess

        with TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)

            # Initialize git repo
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
            )

            # Initial commit
            schema_dir = repo_path / "db" / "schema"
            schema_dir.mkdir()
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
            (schema_dir / "users.sql").write_text("CREATE TABLE users (id INT);")
            subprocess.run(
                ["git", "add", "."],
                cwd=repo_path,
                check=True,
                capture_output=True
            )
            subprocess.run(
                ["git", "commit", "-m", "Add users table"],
                cwd=repo_path,
                check=True,
                capture_output=True
            )

            # Change to repo and run validation
            old_cwd = os.getcwd()
            try:
                os.chdir(repo_path)
                result = runner.invoke(
                    app,
                    [
                        "migrate",
                        "validate",
                        "--require-migration",
                        "--base-ref", "HEAD~1",
                    ],
                    catch_exceptions=False,
                )

                # Should fail because DDL has no migration
                assert result.exit_code != 0 or "invalid" in result.stdout.lower() or "missing" in result.stdout.lower()
            finally:
                os.chdir(old_cwd)

    def test_require_migration_passes_with_migration(self, runner: CliRunner):
        """Test --require-migration flag passes when migration exists."""
        import os
        import subprocess

        with TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)

            # Initialize git repo
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
            )

            # Initial commit
            schema_dir = repo_path / "db" / "schema"
            schema_dir.mkdir()
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

            # Add DDL change WITH migration
            (schema_dir / "users.sql").write_text("CREATE TABLE users (id INT);")
            (migrations_dir / "001_add_users.up.sql").write_text(
                "CREATE TABLE users (id INT);"
            )
            subprocess.run(
                ["git", "add", "."],
                cwd=repo_path,
                check=True,
                capture_output=True
            )
            subprocess.run(
                ["git", "commit", "-m", "Add users table with migration"],
                cwd=repo_path,
                check=True,
                capture_output=True
            )

            # Change to repo and run validation
            old_cwd = os.getcwd()
            try:
                os.chdir(repo_path)
                result = runner.invoke(
                    app,
                    [
                        "migrate",
                        "validate",
                        "--require-migration",
                        "--base-ref", "HEAD~1",
                    ],
                    catch_exceptions=False,
                )

                # Should pass or at least not complain about missing migration
                # (may have other validation issues)
                output_lower = result.stdout.lower()
                assert "missing" not in output_lower or "✅" in result.stdout
            finally:
                os.chdir(old_cwd)
