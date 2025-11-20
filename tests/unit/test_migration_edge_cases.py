"""Edge case tests for Migration base class."""

from unittest.mock import MagicMock

import pytest

from confiture.exceptions import MigrationError, SQLError
from confiture.models.migration import Migration


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
        original_error = Exception("SQL syntax error")
        mock_cursor.execute.side_effect = original_error

        migration = TestMigration(connection=mock_conn)

        with pytest.raises(SQLError) as exc_info:
            migration.execute("INVALID SQL SYNTAX")

        # Verify SQLError contains the right information
        sql_error = exc_info.value
        assert sql_error.sql == "INVALID SQL SYNTAX"
        assert sql_error.params is None
        assert sql_error.original_error == original_error
        assert "SQL execution failed" in str(sql_error)
        assert "INVALID SQL SYNTAX" in str(sql_error)

    def test_execute_with_sql_error_and_params(self):
        """Test execute method when parameterized SQL fails."""

        class TestMigration(Migration):
            version = "001"
            name = "test"

            def up(self):
                pass

            def down(self):
                pass

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        # Simulate SQL execution error
        original_error = Exception("Parameter error")
        mock_cursor.execute.side_effect = original_error

        migration = TestMigration(connection=mock_conn)
        params = ("test_value", 123)

        with pytest.raises(SQLError) as exc_info:
            migration.execute("INSERT INTO test (name, id) VALUES (%s, %s)", params)

        # Verify SQLError contains the right information
        sql_error = exc_info.value
        assert sql_error.sql == "INSERT INTO test (name, id) VALUES (%s, %s)"
        assert sql_error.params == params
        assert sql_error.original_error == original_error
        assert "Parameters: ('test_value', 123)" in str(sql_error)

    def test_migration_with_multiple_sql_statements_error_reporting(self):
        """Test that when a migration has multiple SQL statements, errors are properly reported."""

        class MultiStatementMigration(Migration):
            version = "001"
            name = "multi_statement_test"

            def up(self):
                # First statement succeeds
                self.execute("CREATE TABLE test_table (id INT)")
                # Second statement fails
                self.execute("INVALID SQL STATEMENT HERE")
                # Third statement would succeed but never reached
                self.execute("DROP TABLE test_table")

            def down(self):
                self.execute("DROP TABLE IF EXISTS test_table")

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        # Mock successful first execution
        def mock_execute(sql, params=None):
            if "INVALID SQL STATEMENT" in sql:
                raise Exception("Syntax error in SQL statement")
            # Other statements succeed

        mock_cursor.execute.side_effect = mock_execute

        migration = MultiStatementMigration(connection=mock_conn)

        with pytest.raises(SQLError) as exc_info:
            migration.up()

        # Verify the error is for the failing SQL statement
        sql_error = exc_info.value
        assert "INVALID SQL STATEMENT HERE" in sql_error.sql
        assert "Syntax error in SQL statement" in str(sql_error)
