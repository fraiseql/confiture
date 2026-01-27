"""Unit tests for migration discovery functionality."""

from unittest.mock import Mock

from confiture.core.migrator import Migrator


class TestMigrationDiscovery:
    """Test migration file discovery and version tracking."""

    def test_find_migration_files(self, temp_project_dir):
        """Should find all migration files in db/migrations/."""
        migrations_dir = temp_project_dir / "db" / "migrations"

        # Create sample migration files
        (migrations_dir / "001_create_users.py").write_text("""
from confiture.models.migration import Migration

class CreateUsers(Migration):
    version = "001"
    name = "create_users"

    def up(self):
        self.execute("CREATE TABLE users (id INT)")

    def down(self):
        self.execute("DROP TABLE users")
""")

        (migrations_dir / "002_add_email.py").write_text("""
from confiture.models.migration import Migration

class AddEmail(Migration):
    version = "002"
    name = "add_email"

    def up(self):
        self.execute("ALTER TABLE users ADD COLUMN email TEXT")

    def down(self):
        self.execute("ALTER TABLE users DROP COLUMN email")
""")

        # Change to temp directory
        import os

        original_cwd = os.getcwd()
        os.chdir(temp_project_dir)

        try:
            mock_conn = Mock()
            migrator = Migrator(connection=mock_conn)

            migration_files = migrator.find_migration_files()

            # Should find 2 migrations
            assert len(migration_files) == 2

            # Should be in order
            assert migration_files[0].name == "001_create_users.py"
            assert migration_files[1].name == "002_add_email.py"
        finally:
            os.chdir(original_cwd)

    def test_find_pending_migrations_empty(self, temp_project_dir):
        """Should return all migrations when none are applied."""
        migrations_dir = temp_project_dir / "db" / "migrations"

        # Create sample migration files
        (migrations_dir / "001_create_users.py").write_text("""
from confiture.models.migration import Migration

class CreateUsers(Migration):
    version = "001"
    name = "create_users"

    def up(self):
        pass

    def down(self):
        pass
""")

        import os

        original_cwd = os.getcwd()
        os.chdir(temp_project_dir)

        try:
            mock_conn = Mock()
            mock_cursor = Mock()
            mock_conn.cursor.return_value.__enter__ = Mock(return_value=mock_cursor)
            mock_conn.cursor.return_value.__exit__ = Mock(return_value=None)

            # Mock: no migrations applied
            mock_cursor.fetchall.return_value = []

            migrator = Migrator(connection=mock_conn)

            pending = migrator.find_pending()

            # All migrations are pending
            assert len(pending) == 1
            assert pending[0].name == "001_create_users.py"
        finally:
            os.chdir(original_cwd)

    def test_find_pending_migrations_with_applied(self, temp_project_dir):
        """Should exclude applied migrations from pending list."""
        migrations_dir = temp_project_dir / "db" / "migrations"

        # Create sample migration files
        (migrations_dir / "001_create_users.py").write_text("""
from confiture.models.migration import Migration

class CreateUsers(Migration):
    version = "001"
    name = "create_users"

    def up(self):
        pass

    def down(self):
        pass
""")

        (migrations_dir / "002_add_email.py").write_text("""
from confiture.models.migration import Migration

class AddEmail(Migration):
    version = "002"
    name = "add_email"

    def up(self):
        pass

    def down(self):
        pass
""")

        import os

        original_cwd = os.getcwd()
        os.chdir(temp_project_dir)

        try:
            mock_conn = Mock()
            mock_cursor = Mock()
            mock_conn.cursor.return_value.__enter__ = Mock(return_value=mock_cursor)
            mock_conn.cursor.return_value.__exit__ = Mock(return_value=None)

            # Mock: migration 001 already applied
            mock_cursor.fetchall.return_value = [("001",)]

            migrator = Migrator(connection=mock_conn)

            pending = migrator.find_pending()

            # Only migration 002 is pending
            assert len(pending) == 1
            assert pending[0].name == "002_add_email.py"
        finally:
            os.chdir(original_cwd)

    def test_version_from_filename(self):
        """Should extract version from migration filename."""
        mock_conn = Mock()
        migrator = Migrator(connection=mock_conn)

        # Test various filename formats
        assert migrator._version_from_filename("001_create_users.py") == "001"
        assert migrator._version_from_filename("042_add_column.py") == "042"
        assert migrator._version_from_filename("100_big_migration.py") == "100"

    def test_empty_migrations_directory(self, temp_project_dir):
        """Should handle empty migrations directory gracefully."""
        import os

        original_cwd = os.getcwd()
        os.chdir(temp_project_dir)

        try:
            mock_conn = Mock()
            migrator = Migrator(connection=mock_conn)

            migration_files = migrator.find_migration_files()

            assert migration_files == []
        finally:
            os.chdir(original_cwd)

    def test_find_orphaned_sql_files(self, temp_project_dir):
        """Should detect .sql files that don't match the naming pattern."""
        migrations_dir = temp_project_dir / "db" / "migrations"

        # Create orphaned SQL files (missing .up/.down suffix)
        (migrations_dir / "001_initial_schema.sql").write_text("CREATE TABLE users (id INT);")
        (migrations_dir / "002_add_columns.sql").write_text("ALTER TABLE users ADD COLUMN email TEXT;")

        # Create properly named SQL files
        (migrations_dir / "003_add_indexes.up.sql").write_text("CREATE INDEX idx_users_email ON users(email);")
        (migrations_dir / "003_add_indexes.down.sql").write_text("DROP INDEX idx_users_email;")

        import os

        original_cwd = os.getcwd()
        os.chdir(temp_project_dir)

        try:
            mock_conn = Mock()
            migrator = Migrator(connection=mock_conn)

            orphaned = migrator.find_orphaned_sql_files()

            # Should find 2 orphaned files
            assert len(orphaned) == 2
            assert orphaned[0].name == "001_initial_schema.sql"
            assert orphaned[1].name == "002_add_columns.sql"
        finally:
            os.chdir(original_cwd)

    def test_find_orphaned_sql_files_none(self, temp_project_dir):
        """Should return empty list when all SQL files are properly named."""
        migrations_dir = temp_project_dir / "db" / "migrations"

        # Create only properly named files
        (migrations_dir / "001_create_users.up.sql").write_text("CREATE TABLE users (id INT);")
        (migrations_dir / "001_create_users.down.sql").write_text("DROP TABLE users;")
        (migrations_dir / "002_add_email.py").write_text("""
from confiture.models.migration import Migration

class AddEmail(Migration):
    version = "002"
    name = "add_email"

    def up(self):
        pass

    def down(self):
        pass
""")

        import os

        original_cwd = os.getcwd()
        os.chdir(temp_project_dir)

        try:
            mock_conn = Mock()
            migrator = Migrator(connection=mock_conn)

            orphaned = migrator.find_orphaned_sql_files()

            assert orphaned == []
        finally:
            os.chdir(original_cwd)

    def test_fix_orphaned_sql_files_renames_files(self, temp_project_dir):
        """Should rename orphaned SQL files to match naming pattern."""
        migrations_dir = temp_project_dir / "db" / "migrations"

        # Create orphaned SQL files
        content1 = "CREATE TABLE users (id INT);"
        content2 = "ALTER TABLE users ADD COLUMN email TEXT;"
        (migrations_dir / "001_users.sql").write_text(content1)
        (migrations_dir / "002_add_email.sql").write_text(content2)

        import os

        original_cwd = os.getcwd()
        os.chdir(temp_project_dir)

        try:
            mock_conn = Mock()
            migrator = Migrator(connection=mock_conn)

            # Fix the files
            result = migrator.fix_orphaned_sql_files(dry_run=False)

            # Should have renamed 2 files
            assert len(result["renamed"]) == 2
            assert ("001_users.sql", "001_users.up.sql") in result["renamed"]
            assert ("002_add_email.sql", "002_add_email.up.sql") in result["renamed"]
            assert len(result["errors"]) == 0

            # Files should be renamed
            assert not (migrations_dir / "001_users.sql").exists()
            assert not (migrations_dir / "002_add_email.sql").exists()
            assert (migrations_dir / "001_users.up.sql").exists()
            assert (migrations_dir / "002_add_email.up.sql").exists()

            # Content should be preserved
            assert (migrations_dir / "001_users.up.sql").read_text() == content1
            assert (migrations_dir / "002_add_email.up.sql").read_text() == content2
        finally:
            os.chdir(original_cwd)

    def test_fix_orphaned_sql_files_dry_run(self, temp_project_dir):
        """Should not rename files when dry_run is True."""
        migrations_dir = temp_project_dir / "db" / "migrations"

        # Create orphaned SQL file
        (migrations_dir / "001_orphaned.sql").write_text("CREATE TABLE test (id INT);")

        import os

        original_cwd = os.getcwd()
        os.chdir(temp_project_dir)

        try:
            mock_conn = Mock()
            migrator = Migrator(connection=mock_conn)

            # Dry-run the fix
            result = migrator.fix_orphaned_sql_files(dry_run=True)

            # Should report what would be done
            assert len(result["renamed"]) == 1
            assert ("001_orphaned.sql", "001_orphaned.up.sql") in result["renamed"]

            # File should NOT be renamed (dry-run)
            assert (migrations_dir / "001_orphaned.sql").exists()
            assert not (migrations_dir / "001_orphaned.up.sql").exists()
        finally:
            os.chdir(original_cwd)
