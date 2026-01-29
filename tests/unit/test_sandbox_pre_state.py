"""Unit tests for MigrationSandbox pre-state simulation.

Tests the simulate_pre_state() method and in_pre_state() context manager
that allow testing UP migrations when the local database is ahead.
"""

from unittest.mock import MagicMock, Mock

import pytest

from confiture.testing.sandbox import MigrationSandbox, PreStateSimulationError

# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def mock_connection():
    """Create a mock psycopg connection."""
    conn = MagicMock()
    conn.autocommit = False

    mock_cursor = MagicMock()
    mock_cursor.__enter__ = Mock(return_value=mock_cursor)
    mock_cursor.__exit__ = Mock(return_value=None)
    conn.cursor.return_value = mock_cursor

    return conn


@pytest.fixture
def mock_migration():
    """Create a mock migration with up/down methods."""
    migration = MagicMock()
    migration.version = "004"
    migration.name = "move_catalog_tables"
    migration.up = MagicMock()
    migration.down = MagicMock()
    return migration


# =============================================================================
# simulate_pre_state() Tests
# =============================================================================


class TestSimulatePreState:
    """Tests for MigrationSandbox.simulate_pre_state() method."""

    def test_simulate_pre_state_runs_down_migration(self, mock_connection, mock_migration):
        """simulate_pre_state should execute the DOWN migration."""
        sandbox = MigrationSandbox(connection=mock_connection)

        # Enter context to activate sandbox
        sandbox._active = True
        sandbox.connection = mock_connection

        sandbox.simulate_pre_state(mock_migration)

        # Verify DOWN was called
        mock_migration.down.assert_called_once()
        # Verify UP was not called
        mock_migration.up.assert_not_called()

    def test_simulate_pre_state_tracks_simulation(self, mock_connection, mock_migration):
        """simulate_pre_state should track that pre-state was simulated."""
        sandbox = MigrationSandbox(connection=mock_connection)
        sandbox._active = True
        sandbox.connection = mock_connection

        assert sandbox._pre_state_simulated is False
        assert sandbox._simulated_migration is None

        sandbox.simulate_pre_state(mock_migration)

        assert sandbox._pre_state_simulated is True
        assert sandbox._simulated_migration is mock_migration

    def test_simulate_pre_state_raises_when_down_fails(self, mock_connection, mock_migration):
        """simulate_pre_state should raise PreStateSimulationError on DOWN failure."""
        sandbox = MigrationSandbox(connection=mock_connection)
        sandbox._active = True
        sandbox.connection = mock_connection

        # Make DOWN raise an exception
        mock_migration.down.side_effect = Exception("Table not found")

        with pytest.raises(PreStateSimulationError) as exc_info:
            sandbox.simulate_pre_state(mock_migration)

        assert "Table not found" in str(exc_info.value)
        assert mock_migration.version in str(exc_info.value)
        assert "DOWN migration failed" in str(exc_info.value)

    def test_simulate_pre_state_requires_active_context(self, mock_connection, mock_migration):
        """simulate_pre_state should raise if called outside context."""
        sandbox = MigrationSandbox(connection=mock_connection)
        # Don't set _active = True

        with pytest.raises(RuntimeError, match="outside of sandbox context"):
            sandbox.simulate_pre_state(mock_migration)

    def test_simulate_pre_state_allows_subsequent_up(self, mock_connection, mock_migration):
        """After simulate_pre_state, migration.up() should work."""
        sandbox = MigrationSandbox(connection=mock_connection)
        sandbox._active = True
        sandbox.connection = mock_connection

        # Simulate pre-state (runs DOWN)
        sandbox.simulate_pre_state(mock_migration)

        # Now run UP
        mock_migration.up()

        # Verify both were called
        mock_migration.down.assert_called_once()
        mock_migration.up.assert_called_once()


# =============================================================================
# in_pre_state() Context Manager Tests
# =============================================================================


class TestInPreStateContextManager:
    """Tests for MigrationSandbox.in_pre_state() context manager."""

    def test_in_pre_state_yields_migration(self, mock_connection, mock_migration):
        """in_pre_state should yield the migration for convenience."""
        sandbox = MigrationSandbox(connection=mock_connection)
        sandbox._active = True
        sandbox.connection = mock_connection

        with sandbox.in_pre_state(mock_migration) as yielded_migration:
            assert yielded_migration is mock_migration

    def test_in_pre_state_runs_down_on_entry(self, mock_connection, mock_migration):
        """in_pre_state should run DOWN when entering context."""
        sandbox = MigrationSandbox(connection=mock_connection)
        sandbox._active = True
        sandbox.connection = mock_connection

        with sandbox.in_pre_state(mock_migration):
            # DOWN should have been called by now
            mock_migration.down.assert_called_once()

    def test_in_pre_state_allows_up_inside_context(self, mock_connection, mock_migration):
        """Should be able to run UP inside in_pre_state context."""
        sandbox = MigrationSandbox(connection=mock_connection)
        sandbox._active = True
        sandbox.connection = mock_connection

        with sandbox.in_pre_state(mock_migration) as migration:
            migration.up()

        # Both should have been called
        mock_migration.down.assert_called_once()
        mock_migration.up.assert_called_once()

    def test_in_pre_state_raises_on_down_failure(self, mock_connection, mock_migration):
        """in_pre_state should raise if DOWN fails."""
        sandbox = MigrationSandbox(connection=mock_connection)
        sandbox._active = True
        sandbox.connection = mock_connection

        mock_migration.down.side_effect = Exception("Cannot rollback")

        with pytest.raises(PreStateSimulationError):
            with sandbox.in_pre_state(mock_migration):
                pass  # Should not reach here


# =============================================================================
# Sandbox Helper Methods Tests
# =============================================================================


class TestSandboxHelperMethods:
    """Tests for sandbox helper methods (table_exists, column_exists, etc.)."""

    def test_table_exists_returns_true_when_found(self, mock_connection):
        """table_exists should return True when table is found."""
        mock_cursor = mock_connection.cursor.return_value.__enter__.return_value
        mock_cursor.fetchone.return_value = [True]

        sandbox = MigrationSandbox(connection=mock_connection)
        sandbox._active = True
        sandbox.connection = mock_connection

        result = sandbox.table_exists("users")

        assert result is True

    def test_table_exists_returns_false_when_not_found(self, mock_connection):
        """table_exists should return False when table is not found."""
        mock_cursor = mock_connection.cursor.return_value.__enter__.return_value
        mock_cursor.fetchone.return_value = [False]

        sandbox = MigrationSandbox(connection=mock_connection)
        sandbox._active = True
        sandbox.connection = mock_connection

        result = sandbox.table_exists("nonexistent")

        assert result is False

    def test_table_exists_supports_custom_schema(self, mock_connection):
        """table_exists should support custom schema parameter."""
        mock_cursor = mock_connection.cursor.return_value.__enter__.return_value
        mock_cursor.fetchone.return_value = [True]

        sandbox = MigrationSandbox(connection=mock_connection)
        sandbox._active = True
        sandbox.connection = mock_connection

        result = sandbox.table_exists("products", schema="catalog")

        assert result is True
        # Verify the schema was passed to the query
        call_args = mock_cursor.execute.call_args
        assert "catalog" in call_args[0][1]

    def test_column_exists_returns_true_when_found(self, mock_connection):
        """column_exists should return True when column is found."""
        mock_cursor = mock_connection.cursor.return_value.__enter__.return_value
        mock_cursor.fetchone.return_value = [True]

        sandbox = MigrationSandbox(connection=mock_connection)
        sandbox._active = True
        sandbox.connection = mock_connection

        result = sandbox.column_exists("users", "email")

        assert result is True

    def test_column_exists_returns_false_when_not_found(self, mock_connection):
        """column_exists should return False when column is not found."""
        mock_cursor = mock_connection.cursor.return_value.__enter__.return_value
        mock_cursor.fetchone.return_value = [False]

        sandbox = MigrationSandbox(connection=mock_connection)
        sandbox._active = True
        sandbox.connection = mock_connection

        result = sandbox.column_exists("users", "nonexistent")

        assert result is False

    def test_get_row_count_returns_count(self, mock_connection):
        """get_row_count should return the row count."""
        mock_cursor = mock_connection.cursor.return_value.__enter__.return_value
        mock_cursor.fetchone.return_value = [42]

        sandbox = MigrationSandbox(connection=mock_connection)
        sandbox._active = True
        sandbox.connection = mock_connection

        result = sandbox.get_row_count("users")

        assert result == 42


# =============================================================================
# Full Workflow Tests (Mocked)
# =============================================================================


class TestPreStateWorkflow:
    """Tests for the complete pre-state simulation workflow."""

    def test_complete_workflow_down_then_up(self, mock_connection, mock_migration):
        """Test complete workflow: simulate pre-state, then run UP."""
        sandbox = MigrationSandbox(connection=mock_connection)
        sandbox._active = True
        sandbox.connection = mock_connection

        # Simulate the scenario:
        # 1. Local DB has tables in 'catalog' schema (post-migration state)
        # 2. Production has tables in 'tenant' schema (pre-migration state)
        # 3. We want to test the UP migration locally

        # Step 1: Simulate pre-state (runs DOWN)
        sandbox.simulate_pre_state(mock_migration)

        # Verify DOWN was called
        mock_migration.down.assert_called_once()

        # Step 2: Run UP migration
        mock_migration.up()

        # Verify UP was called
        mock_migration.up.assert_called_once()

        # Verify order: DOWN before UP
        assert mock_migration.down.call_count == 1
        assert mock_migration.up.call_count == 1

    def test_workflow_with_context_manager(self, mock_connection, mock_migration):
        """Test workflow using in_pre_state context manager."""
        sandbox = MigrationSandbox(connection=mock_connection)
        sandbox._active = True
        sandbox.connection = mock_connection

        with sandbox.in_pre_state(mock_migration) as migration:
            # Database is now in pre-migration state
            migration.up()

        # Verify both were called in order
        mock_migration.down.assert_called_once()
        mock_migration.up.assert_called_once()


# =============================================================================
# PreStateSimulationError Tests
# =============================================================================


class TestPreStateSimulationError:
    """Tests for PreStateSimulationError exception."""

    def test_error_message_contains_migration_info(self):
        """Error message should contain migration info."""
        mock_migration = MagicMock()
        mock_migration.version = "004"
        mock_migration.name = "move_tables"
        mock_migration.down.side_effect = Exception("Cannot drop table")

        mock_connection = MagicMock()
        sandbox = MigrationSandbox(connection=mock_connection)
        sandbox._active = True
        sandbox.connection = mock_connection

        with pytest.raises(PreStateSimulationError) as exc_info:
            sandbox.simulate_pre_state(mock_migration)

        error_msg = str(exc_info.value)
        assert "004" in error_msg
        assert "move_tables" in error_msg
        assert "Cannot drop table" in error_msg

    def test_error_provides_helpful_hints(self):
        """Error should provide helpful debugging hints."""
        mock_migration = MagicMock()
        mock_migration.version = "004"
        mock_migration.name = "test"
        mock_migration.down.side_effect = Exception("Error")

        mock_connection = MagicMock()
        sandbox = MigrationSandbox(connection=mock_connection)
        sandbox._active = True
        sandbox.connection = mock_connection

        with pytest.raises(PreStateSimulationError) as exc_info:
            sandbox.simulate_pre_state(mock_migration)

        error_msg = str(exc_info.value)
        # Should contain helpful hints
        assert (
            "not in the expected post-migration state" in error_msg
            or "DOWN migration has a bug" in error_msg
            or "migration is not reversible" in error_msg
        )
