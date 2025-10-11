"""Edge case tests for Migration base class."""

import pytest
from unittest.mock import MagicMock

from confiture.models.migration import Migration
from confiture.exceptions import MigrationError


class TestMigrationEdgeCases:
    """Test Migration base class edge cases."""

    def test_migration_without_version(self):
        """Test that migration validates version attribute."""

        class InvalidMigration(Migration):
            # Missing version attribute
            name = "test"

            def up(self):
                pass

            def down(self):
                pass

        mock_conn = MagicMock()

        # Should raise error during initialization
        with pytest.raises((AttributeError, TypeError, MigrationError)):
            migration = InvalidMigration(connection=mock_conn)
            # Try to access version
            _ = migration.version

    def test_execute_with_sql_error(self):
        """Test execute method when SQL fails."""

        class TestMigration(Migration):
            version = "001"
            name = "test"

            def up(self):
                self.execute("INVALID SQL SYNTAX")

            def down(self):
                pass

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        # Simulate SQL execution error
        mock_cursor.execute.side_effect = Exception("SQL error")

        migration = TestMigration(connection=mock_conn)

        with pytest.raises(Exception, match="SQL error"):
            migration.execute("INVALID SQL SYNTAX")
