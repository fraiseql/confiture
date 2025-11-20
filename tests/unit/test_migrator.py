"""Unit tests for Migrator core functionality."""

from unittest.mock import Mock

from confiture.core.migrator import Migrator


class TestMigratorMigrateUp:
    """Test migrate_up method with force flag."""

    def test_migrate_up_force_false_checks_state(self, temp_project_dir):
        """migrate_up(force=False) should check migration state and only apply pending."""
        migrations_dir = temp_project_dir / "db" / "migrations"

        # Create a migration file
        (migrations_dir / "001_test.py").write_text("""
from confiture.models.migration import Migration

class TestMigration(Migration):
    version = "001"
    name = "test"

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

            # Mock: migration already applied (so no pending migrations)
            mock_cursor.fetchall.return_value = [("001",)]

            migrator = Migrator(connection=mock_conn)

            # Should apply only pending migrations (none in this case)
            applied = migrator.migrate_up(force=False, migrations_dir=migrations_dir)

            # Should return empty list since no migrations were applied
            assert applied == []
        finally:
            os.chdir(original_cwd)

    def test_migrate_up_force_true_skips_state_check(self, temp_project_dir):
        """migrate_up(force=True) should skip state check and apply all migrations."""
        migrations_dir = temp_project_dir / "db" / "migrations"

        # Create a migration file
        (migrations_dir / "001_test.py").write_text("""
from confiture.models.migration import Migration

class TestMigration(Migration):
    version = "001"
    name = "test"

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

            # Mock database calls: empty applied versions for get_applied_versions
            # and not applied for _is_applied check
            mock_cursor.fetchall.side_effect = [
                [],  # get_applied_versions returns empty list
                [(0,)],  # _is_applied returns count 0 (not applied)
            ]

            migrator = Migrator(connection=mock_conn)

            # Should apply all migrations regardless of state
            applied = migrator.migrate_up(force=True, migrations_dir=migrations_dir)

            # Should return the applied migration version
            assert applied == ["001"]
        finally:
            os.chdir(original_cwd)

    def test_migrate_up_force_mode_applies_migrations_correctly(self, temp_project_dir):
        """Force mode should still apply migrations correctly."""
        migrations_dir = temp_project_dir / "db" / "migrations"

        # Create a migration file
        (migrations_dir / "001_test.py").write_text("""
from confiture.models.migration import Migration

class TestMigration(Migration):
    version = "001"
    name = "test"

    def up(self):
        self.execute("CREATE TABLE test (id INT)")

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

            # Mock database calls: empty applied versions for get_applied_versions
            # and not applied for _is_applied check
            mock_cursor.fetchall.side_effect = [
                [],  # get_applied_versions returns empty list
                [(0,)],  # _is_applied returns count 0 (not applied)
            ]

            migrator = Migrator(connection=mock_conn)

            # Should apply migrations and execute their up() methods
            applied = migrator.migrate_up(force=True, migrations_dir=migrations_dir)

            # Should return the applied migration version
            assert applied == ["001"]
        finally:
            os.chdir(original_cwd)

    def test_migrate_up_force_mode_updates_tracking_state(self, temp_project_dir):
        """Force mode should update migration tracking state after application."""
        migrations_dir = temp_project_dir / "db" / "migrations"

        # Create a migration file
        (migrations_dir / "001_test.py").write_text("""
from confiture.models.migration import Migration

class TestMigration(Migration):
    version = "001"
    name = "test"

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

            # Mock database calls: empty applied versions for get_applied_versions
            # and not applied for _is_applied check
            mock_cursor.fetchall.side_effect = [
                [],  # get_applied_versions returns empty list
                [(0,)],  # _is_applied returns count 0 (not applied)
            ]

            migrator = Migrator(connection=mock_conn)

            # Should update tracking table after successful application
            applied = migrator.migrate_up(force=True, migrations_dir=migrations_dir)

            # Should return the applied migration version
            assert applied == ["001"]
        finally:
            os.chdir(original_cwd)
