"""Unit tests for pgGit migration generator.

Tests for MigrationGenerator and GeneratedMigration classes.
These tests do NOT require an actual PostgreSQL database with pgGit installed.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch
import tempfile

import pytest

from confiture.integrations.pggit.generator import (
    GeneratedMigration,
    MigrationGenerator,
)
from confiture.integrations.pggit.client import DiffEntry


class TestGeneratedMigration:
    """Test GeneratedMigration dataclass."""

    def test_create_migration(self):
        """GeneratedMigration should store all fields."""
        migration = GeneratedMigration(
            version="20250115143022_001",
            name="add_users_table",
            description="Add users table for authentication",
            up_sql="CREATE TABLE users (id SERIAL PRIMARY KEY)",
            down_sql="DROP TABLE IF EXISTS users",
            source_commits=["abc123", "def456"],
            metadata={"source_branch": "feature/users"},
        )

        assert migration.version == "20250115143022_001"
        assert migration.name == "add_users_table"
        assert "users" in migration.up_sql
        assert "DROP TABLE" in migration.down_sql
        assert len(migration.source_commits) == 2

    def test_write_to_file(self):
        """GeneratedMigration should write to Python file."""
        migration = GeneratedMigration(
            version="20250115143022_001",
            name="add_users_table",
            description="Add users table",
            up_sql="CREATE TABLE users (id SERIAL PRIMARY KEY)",
            down_sql="DROP TABLE IF EXISTS users",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            filepath = migration.write_to_file(output_dir)

            assert filepath.exists()
            assert filepath.name == "20250115143022_001_add_users_table.py"

            content = filepath.read_text()
            assert "class AddUsersTable(Migration):" in content
            assert "CREATE TABLE users" in content
            assert "DROP TABLE IF EXISTS users" in content
            assert "version = \"20250115143022_001\"" in content

    def test_render_includes_metadata(self):
        """Generated file should include metadata comments."""
        migration = GeneratedMigration(
            version="001",
            name="test",
            description="Test migration",
            up_sql="SELECT 1",
            down_sql="SELECT 2",
            source_commits=["abc123"],
        )

        content = migration._render()

        assert "Generated from pgGit commits: abc123" in content
        assert "Generated at:" in content

    def test_to_class_name(self):
        """Should convert names to PascalCase."""
        migration = GeneratedMigration(
            version="001",
            name="add_user_payments",
            description="Test",
            up_sql="",
            down_sql="",
        )

        assert migration._to_class_name("add_user_payments") == "AddUserPayments"
        assert migration._to_class_name("feature_test") == "FeatureTest"
        assert migration._to_class_name("simple") == "Simple"

    def test_indent(self):
        """Should properly indent SQL."""
        migration = GeneratedMigration(
            version="001",
            name="test",
            description="Test",
            up_sql="",
            down_sql="",
        )

        sql = "CREATE TABLE users (\n    id SERIAL\n)"
        indented = migration._indent(sql, 4)

        assert indented.startswith("    CREATE TABLE")
        # Each line should be indented by 4 spaces
        assert "    id SERIAL" in indented

    def test_empty_sql_handled(self):
        """Should handle empty SQL gracefully."""
        migration = GeneratedMigration(
            version="001",
            name="test",
            description="Test",
            up_sql="",
            down_sql="",
        )

        indented = migration._indent("", 4)
        assert "No SQL statements" in indented


class TestMigrationGeneratorInitialization:
    """Test MigrationGenerator initialization."""

    def test_initializes_with_connection(self):
        """MigrationGenerator should initialize with pgGit client."""
        mock_conn = MagicMock()

        with patch(
            "confiture.integrations.pggit.generator.PgGitClient"
        ) as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value = mock_client

            generator = MigrationGenerator(mock_conn)

            assert generator._connection == mock_conn
            assert generator._client == mock_client
            mock_client_class.assert_called_once_with(mock_conn)

    def test_client_property(self):
        """Should expose client property."""
        mock_conn = MagicMock()

        with patch(
            "confiture.integrations.pggit.generator.PgGitClient"
        ) as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value = mock_client

            generator = MigrationGenerator(mock_conn)

            assert generator.client == mock_client


class TestMigrationGeneratorGeneration:
    """Test migration generation methods."""

    def test_generate_from_branch_empty_diff(self):
        """Should return empty list when no diff."""
        mock_conn = MagicMock()

        with patch(
            "confiture.integrations.pggit.generator.PgGitClient"
        ) as mock_client_class:
            mock_client = MagicMock()
            mock_client.diff.return_value = []
            mock_client_class.return_value = mock_client

            generator = MigrationGenerator(mock_conn)
            migrations = generator.generate_from_branch("feature/test")

            assert migrations == []
            mock_client.diff.assert_called_once_with("main", "feature/test")

    def test_generate_from_branch_with_changes(self):
        """Should generate migrations for changes."""
        mock_conn = MagicMock()

        with patch(
            "confiture.integrations.pggit.generator.PgGitClient"
        ) as mock_client_class:
            mock_client = MagicMock()
            mock_client.diff.return_value = [
                DiffEntry(
                    object_type="TABLE",
                    object_name="users",
                    operation="CREATE",
                    new_ddl="CREATE TABLE users (id SERIAL PRIMARY KEY)",
                ),
            ]
            mock_client_class.return_value = mock_client

            generator = MigrationGenerator(mock_conn)
            migrations = generator.generate_from_branch("feature/users")

            assert len(migrations) == 1
            assert "users" in migrations[0].name.lower() or "test" in migrations[0].name.lower()
            assert "CREATE TABLE" in migrations[0].up_sql
            assert "DROP TABLE" in migrations[0].down_sql

    def test_generate_combined_empty_diff(self):
        """Should return None when no diff."""
        mock_conn = MagicMock()

        with patch(
            "confiture.integrations.pggit.generator.PgGitClient"
        ) as mock_client_class:
            mock_client = MagicMock()
            mock_client.diff.return_value = []
            mock_client_class.return_value = mock_client

            generator = MigrationGenerator(mock_conn)
            migration = generator.generate_combined("feature/test")

            assert migration is None

    def test_generate_combined_with_changes(self):
        """Should generate single combined migration."""
        mock_conn = MagicMock()

        with patch(
            "confiture.integrations.pggit.generator.PgGitClient"
        ) as mock_client_class:
            mock_client = MagicMock()
            mock_client.diff.return_value = [
                DiffEntry(
                    object_type="TABLE",
                    object_name="users",
                    operation="CREATE",
                    new_ddl="CREATE TABLE users (id SERIAL)",
                ),
                DiffEntry(
                    object_type="TABLE",
                    object_name="orders",
                    operation="CREATE",
                    new_ddl="CREATE TABLE orders (id SERIAL)",
                ),
            ]
            mock_client_class.return_value = mock_client

            generator = MigrationGenerator(mock_conn)
            migration = generator.generate_combined("feature/multi")

            assert migration is not None
            assert migration.metadata.get("combined") is True
            assert migration.metadata.get("changes_count") == 2
            assert "CREATE TABLE users" in migration.up_sql
            assert "CREATE TABLE orders" in migration.up_sql

    def test_generate_from_diff(self):
        """Should generate migration from diff list."""
        mock_conn = MagicMock()

        with patch(
            "confiture.integrations.pggit.generator.PgGitClient"
        ):
            generator = MigrationGenerator(mock_conn)

            diff = [
                DiffEntry(
                    object_type="FUNCTION",
                    object_name="calculate_total",
                    operation="CREATE",
                    new_ddl="CREATE FUNCTION calculate_total() RETURNS INT AS $$ SELECT 1 $$ LANGUAGE SQL",
                ),
            ]

            migration = generator.generate_from_diff(diff, "add_function")

            assert migration.name == "add_function"
            assert "CREATE FUNCTION" in migration.up_sql
            assert "DROP FUNCTION" in migration.down_sql

    def test_preview(self):
        """Should return preview of changes."""
        mock_conn = MagicMock()

        with patch(
            "confiture.integrations.pggit.generator.PgGitClient"
        ) as mock_client_class:
            mock_client = MagicMock()
            mock_client.diff.return_value = [
                DiffEntry(
                    object_type="TABLE",
                    object_name="users",
                    operation="CREATE",
                    new_ddl="CREATE TABLE users",
                ),
            ]
            mock_client_class.return_value = mock_client

            generator = MigrationGenerator(mock_conn)
            preview = generator.preview("feature/test")

            assert len(preview) == 1
            assert preview[0]["operation"] == "CREATE"
            assert preview[0]["object_type"] == "TABLE"
            assert preview[0]["object_name"] == "users"
            assert preview[0]["has_new_ddl"] is True


class TestMigrationGeneratorSQLGeneration:
    """Test SQL generation methods."""

    def test_generate_up_sql_create(self):
        """Should use new_ddl for CREATE."""
        mock_conn = MagicMock()

        with patch("confiture.integrations.pggit.generator.PgGitClient"):
            generator = MigrationGenerator(mock_conn)

            entry = DiffEntry(
                object_type="TABLE",
                object_name="users",
                operation="CREATE",
                new_ddl="CREATE TABLE users (id INT)",
            )

            sql = generator._generate_up_sql(entry)
            assert sql == "CREATE TABLE users (id INT)"

    def test_generate_up_sql_drop(self):
        """Should generate DROP statement."""
        mock_conn = MagicMock()

        with patch("confiture.integrations.pggit.generator.PgGitClient"):
            generator = MigrationGenerator(mock_conn)

            entry = DiffEntry(
                object_type="TABLE",
                object_name="old_table",
                operation="DROP",
            )

            sql = generator._generate_up_sql(entry)
            assert "DROP TABLE" in sql
            assert "old_table" in sql

    def test_generate_down_sql_create(self):
        """Should generate DROP for CREATE reverse."""
        mock_conn = MagicMock()

        with patch("confiture.integrations.pggit.generator.PgGitClient"):
            generator = MigrationGenerator(mock_conn)

            entry = DiffEntry(
                object_type="TABLE",
                object_name="users",
                operation="CREATE",
            )

            sql = generator._generate_down_sql(entry)
            assert "DROP TABLE" in sql
            assert "users" in sql

    def test_generate_down_sql_drop_with_old_ddl(self):
        """Should use old_ddl for DROP reverse."""
        mock_conn = MagicMock()

        with patch("confiture.integrations.pggit.generator.PgGitClient"):
            generator = MigrationGenerator(mock_conn)

            entry = DiffEntry(
                object_type="TABLE",
                object_name="users",
                operation="DROP",
                old_ddl="CREATE TABLE users (id INT)",
            )

            sql = generator._generate_down_sql(entry)
            assert "CREATE TABLE users" in sql

    def test_generate_down_sql_drop_without_old_ddl(self):
        """Should generate comment when no old_ddl for DROP."""
        mock_conn = MagicMock()

        with patch("confiture.integrations.pggit.generator.PgGitClient"):
            generator = MigrationGenerator(mock_conn)

            entry = DiffEntry(
                object_type="TABLE",
                object_name="users",
                operation="DROP",
            )

            sql = generator._generate_down_sql(entry)
            assert "Cannot reverse" in sql or "--" in sql


class TestMigrationGeneratorVersioning:
    """Test version generation."""

    def test_generate_version(self):
        """Should generate timestamp-based version."""
        mock_conn = MagicMock()

        with patch("confiture.integrations.pggit.generator.PgGitClient"):
            generator = MigrationGenerator(mock_conn)

            version = generator._generate_version()

            # Should be format: YYYYMMDDHHMMSS_000
            assert len(version) >= 15
            assert "_" in version
            # Should start with year
            assert version.startswith("20")

    def test_generate_version_with_index(self):
        """Should include index in version."""
        mock_conn = MagicMock()

        with patch("confiture.integrations.pggit.generator.PgGitClient"):
            generator = MigrationGenerator(mock_conn)

            version = generator._generate_version(index=5)

            assert "_005" in version


class TestMigrationGeneratorNameSanitization:
    """Test name sanitization."""

    def test_sanitize_branch_name(self):
        """Should convert branch name to safe name."""
        mock_conn = MagicMock()

        with patch("confiture.integrations.pggit.generator.PgGitClient"):
            generator = MigrationGenerator(mock_conn)

            assert generator._sanitize_branch_name("feature/add-users") == "add_users"
            assert generator._sanitize_branch_name("hotfix/bug-123") == "bug_123"
            assert generator._sanitize_branch_name("main") == "main"

    def test_sanitize_name(self):
        """Should sanitize any name."""
        mock_conn = MagicMock()

        with patch("confiture.integrations.pggit.generator.PgGitClient"):
            generator = MigrationGenerator(mock_conn)

            assert generator._sanitize_name("Add Users Table!") == "add_users_table"
            assert generator._sanitize_name("feature/test") == "feature_test"
            assert generator._sanitize_name("   spaces   ") == "spaces"

    def test_sanitize_name_truncates_long_names(self):
        """Should truncate very long names."""
        mock_conn = MagicMock()

        with patch("confiture.integrations.pggit.generator.PgGitClient"):
            generator = MigrationGenerator(mock_conn)

            long_name = "a" * 100
            sanitized = generator._sanitize_name(long_name)

            assert len(sanitized) <= 50


class TestMigrationGeneratorFileOutput:
    """Test file output functionality."""

    def test_generate_from_branch_writes_files(self):
        """Should write files when output_dir provided."""
        mock_conn = MagicMock()

        with patch(
            "confiture.integrations.pggit.generator.PgGitClient"
        ) as mock_client_class:
            mock_client = MagicMock()
            mock_client.diff.return_value = [
                DiffEntry(
                    object_type="TABLE",
                    object_name="users",
                    operation="CREATE",
                    new_ddl="CREATE TABLE users (id SERIAL)",
                ),
            ]
            mock_client_class.return_value = mock_client

            generator = MigrationGenerator(mock_conn)

            with tempfile.TemporaryDirectory() as tmpdir:
                output_dir = Path(tmpdir)
                migrations = generator.generate_from_branch(
                    "feature/test",
                    output_dir=output_dir,
                )

                # Check file was created
                files = list(output_dir.glob("*.py"))
                assert len(files) == 1

                # Verify content
                content = files[0].read_text()
                assert "CREATE TABLE users" in content

    def test_generate_combined_writes_file(self):
        """Should write combined file when output_dir provided."""
        mock_conn = MagicMock()

        with patch(
            "confiture.integrations.pggit.generator.PgGitClient"
        ) as mock_client_class:
            mock_client = MagicMock()
            mock_client.diff.return_value = [
                DiffEntry(
                    object_type="TABLE",
                    object_name="users",
                    operation="CREATE",
                    new_ddl="CREATE TABLE users",
                ),
            ]
            mock_client_class.return_value = mock_client

            generator = MigrationGenerator(mock_conn)

            with tempfile.TemporaryDirectory() as tmpdir:
                output_dir = Path(tmpdir)
                migration = generator.generate_combined(
                    "feature/test",
                    output_dir=output_dir,
                )

                files = list(output_dir.glob("*.py"))
                assert len(files) == 1
                assert migration is not None
