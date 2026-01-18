"""Tests for confiture.testing.loader module."""

import tempfile
from pathlib import Path

import pytest

from confiture.testing.loader import (
    MigrationLoadError,
    MigrationNotFoundError,
    find_migration_by_version,
    load_migration,
)


class TestLoadMigration:
    """Tests for load_migration() function."""

    def test_load_migration_requires_name_or_version(self):
        """Test that either name or version must be provided."""
        with pytest.raises(ValueError, match="Either 'name' or 'version'"):
            load_migration()

    def test_load_migration_rejects_both_name_and_version(self):
        """Test that providing both name and version raises error."""
        with pytest.raises(ValueError, match="Provide either 'name' or 'version'"):
            load_migration("003_test", version="003")

    def test_load_migration_not_found_error(self):
        """Test error when migration doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            migrations_dir = Path(tmpdir)
            with pytest.raises(MigrationNotFoundError, match="Migration not found"):
                load_migration("nonexistent", migrations_dir=migrations_dir)

    def test_load_migration_directory_not_found(self):
        """Test error when migrations directory doesn't exist."""
        with pytest.raises(MigrationNotFoundError, match="Migrations directory not found"):
            load_migration("test", migrations_dir=Path("/nonexistent/path"))

    def test_load_python_migration_by_name(self):
        """Test loading Python migration by name."""
        with tempfile.TemporaryDirectory() as tmpdir:
            migrations_dir = Path(tmpdir)

            # Create a simple Python migration
            migration_file = migrations_dir / "001_create_users.py"
            migration_file.write_text("""
from confiture.models.migration import Migration

class CreateUsers(Migration):
    version = "001"
    name = "create_users"

    def up(self):
        pass

    def down(self):
        pass
""")

            MigrationClass = load_migration("001_create_users", migrations_dir=migrations_dir)
            assert MigrationClass.version == "001"
            assert MigrationClass.name == "create_users"

    def test_load_sql_migration_by_name(self):
        """Test loading SQL-only migration by name."""
        with tempfile.TemporaryDirectory() as tmpdir:
            migrations_dir = Path(tmpdir)

            # Create SQL migration files
            up_file = migrations_dir / "002_add_posts.up.sql"
            down_file = migrations_dir / "002_add_posts.down.sql"
            up_file.write_text("CREATE TABLE posts (id SERIAL PRIMARY KEY);")
            down_file.write_text("DROP TABLE posts;")

            MigrationClass = load_migration("002_add_posts", migrations_dir=migrations_dir)
            assert MigrationClass.version == "002"
            assert MigrationClass.name == "add_posts"

    def test_load_sql_migration_missing_down_file(self):
        """Test error when .down.sql is missing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            migrations_dir = Path(tmpdir)

            # Create only up file
            up_file = migrations_dir / "003_orphan.up.sql"
            up_file.write_text("CREATE TABLE orphan (id INT);")

            with pytest.raises(MigrationNotFoundError, match="missing .down.sql"):
                load_migration("003_orphan", migrations_dir=migrations_dir)

    def test_load_migration_by_version_python(self):
        """Test loading Python migration by version."""
        with tempfile.TemporaryDirectory() as tmpdir:
            migrations_dir = Path(tmpdir)

            # Create a Python migration
            migration_file = migrations_dir / "004_settings.py"
            migration_file.write_text("""
from confiture.models.migration import Migration

class AddSettings(Migration):
    version = "004"
    name = "settings"

    def up(self):
        pass

    def down(self):
        pass
""")

            MigrationClass = load_migration(version="004", migrations_dir=migrations_dir)
            assert MigrationClass.version == "004"

    def test_load_migration_by_version_sql(self):
        """Test loading SQL migration by version."""
        with tempfile.TemporaryDirectory() as tmpdir:
            migrations_dir = Path(tmpdir)

            # Create SQL migration files
            up_file = migrations_dir / "005_indexes.up.sql"
            down_file = migrations_dir / "005_indexes.down.sql"
            up_file.write_text("CREATE INDEX idx_users_email ON users(email);")
            down_file.write_text("DROP INDEX idx_users_email;")

            MigrationClass = load_migration(version="005", migrations_dir=migrations_dir)
            assert MigrationClass.version == "005"
            assert MigrationClass.name == "indexes"

    def test_load_migration_prefers_python_over_sql(self):
        """Test that Python migration is loaded when both formats exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            migrations_dir = Path(tmpdir)

            # Create both Python and SQL migrations with same name
            py_file = migrations_dir / "006_both.py"
            py_file.write_text("""
from confiture.models.migration import Migration

class Both(Migration):
    version = "006"
    name = "both_python"

    def up(self):
        pass

    def down(self):
        pass
""")

            up_file = migrations_dir / "006_both.up.sql"
            down_file = migrations_dir / "006_both.down.sql"
            up_file.write_text("-- SQL version")
            down_file.write_text("-- SQL version")

            MigrationClass = load_migration("006_both", migrations_dir=migrations_dir)
            # Should load Python version
            assert MigrationClass.name == "both_python"

    def test_load_migration_multiple_versions_error(self):
        """Test error when multiple migrations have same version."""
        with tempfile.TemporaryDirectory() as tmpdir:
            migrations_dir = Path(tmpdir)

            # Create two migrations with same version
            file1 = migrations_dir / "007_first.py"
            file1.write_text("""
from confiture.models.migration import Migration

class First(Migration):
    version = "007"
    name = "first"

    def up(self):
        pass

    def down(self):
        pass
""")

            file2 = migrations_dir / "007_second.py"
            file2.write_text("""
from confiture.models.migration import Migration

class Second(Migration):
    version = "007"
    name = "second"

    def up(self):
        pass

    def down(self):
        pass
""")

            with pytest.raises(MigrationNotFoundError, match="Multiple migrations"):
                load_migration(version="007", migrations_dir=migrations_dir)


class TestFindMigrationByVersion:
    """Tests for find_migration_by_version() function."""

    def test_find_python_migration(self):
        """Test finding Python migration by version."""
        with tempfile.TemporaryDirectory() as tmpdir:
            migrations_dir = Path(tmpdir)

            migration_file = migrations_dir / "008_test.py"
            migration_file.write_text("# dummy")

            result = find_migration_by_version("008", migrations_dir=migrations_dir)
            assert result == migration_file

    def test_find_sql_migration(self):
        """Test finding SQL migration by version."""
        with tempfile.TemporaryDirectory() as tmpdir:
            migrations_dir = Path(tmpdir)

            up_file = migrations_dir / "009_sql.up.sql"
            down_file = migrations_dir / "009_sql.down.sql"
            up_file.write_text("-- up")
            down_file.write_text("-- down")

            result = find_migration_by_version("009", migrations_dir=migrations_dir)
            assert result == up_file

    def test_find_returns_none_for_nonexistent(self):
        """Test that None is returned for nonexistent version."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = find_migration_by_version("999", migrations_dir=Path(tmpdir))
            assert result is None

    def test_find_returns_none_for_multiple_matches(self):
        """Test that None is returned when multiple migrations match."""
        with tempfile.TemporaryDirectory() as tmpdir:
            migrations_dir = Path(tmpdir)

            file1 = migrations_dir / "010_first.py"
            file2 = migrations_dir / "010_second.py"
            file1.write_text("# first")
            file2.write_text("# second")

            result = find_migration_by_version("010", migrations_dir=migrations_dir)
            assert result is None

    def test_find_returns_none_for_nonexistent_directory(self):
        """Test that None is returned for nonexistent directory."""
        result = find_migration_by_version("001", migrations_dir=Path("/nonexistent"))
        assert result is None

    def test_find_ignores_sql_without_down_file(self):
        """Test that SQL migrations without .down.sql are ignored."""
        with tempfile.TemporaryDirectory() as tmpdir:
            migrations_dir = Path(tmpdir)

            # Create only up file
            up_file = migrations_dir / "011_orphan.up.sql"
            up_file.write_text("-- orphan")

            result = find_migration_by_version("011", migrations_dir=migrations_dir)
            assert result is None
