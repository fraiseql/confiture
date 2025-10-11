"""Unit tests for Migration base class."""

from unittest.mock import Mock

import pytest

from confiture.models.migration import Migration


class TestMigrationBase:
    """Test Migration base class functionality."""

    def test_migration_base_class(self):
        """Migration should have up/down methods."""

        class TestMigration(Migration):
            version = "001"
            name = "test_migration"

            def up(self):
                self.execute("CREATE TABLE test (id INT)")

            def down(self):
                self.execute("DROP TABLE test")

        # Create mock connection
        mock_conn = Mock()

        migration = TestMigration(connection=mock_conn)

        # Test attributes
        assert hasattr(migration, "up")
        assert hasattr(migration, "down")
        assert hasattr(migration, "execute")
        assert migration.version == "001"
        assert migration.name == "test_migration"

    def test_migration_requires_version_and_name(self):
        """Migration subclass must define version and name."""

        class InvalidMigration(Migration):
            def up(self):
                pass

            def down(self):
                pass

        mock_conn = Mock()

        # Should raise error if version or name not defined
        with pytest.raises(TypeError):
            InvalidMigration(connection=mock_conn)

    def test_execute_runs_sql(self):
        """execute() should run SQL statement."""

        class TestMigration(Migration):
            version = "001"
            name = "test"

            def up(self):
                self.execute("CREATE TABLE test (id INT)")

            def down(self):
                pass

        # Create mock connection and cursor
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor.return_value.__enter__ = Mock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = Mock(return_value=None)

        migration = TestMigration(connection=mock_conn)
        migration.up()

        # Verify execute was called
        mock_cursor.execute.assert_called_once_with("CREATE TABLE test (id INT)")

    def test_migration_must_implement_up_and_down(self):
        """Migration subclass must implement both up() and down()."""
        mock_conn = Mock()

        # Missing down() - ABC prevents instantiation
        with pytest.raises(TypeError, match="abstract method down"):

            class MissingDownMigration(Migration):
                version = "001"
                name = "test"

                def up(self):
                    pass

            MissingDownMigration(connection=mock_conn)

        # Missing up() - ABC prevents instantiation
        with pytest.raises(TypeError, match="abstract method up"):

            class MissingUpMigration(Migration):
                version = "001"
                name = "test"

                def down(self):
                    pass

            MissingUpMigration(connection=mock_conn)
