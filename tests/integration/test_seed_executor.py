"""Integration tests for SeedExecutor with savepoint management.

Phase 9, Cycle 3-4: Savepoint execution and rollback
"""

from unittest.mock import MagicMock

import pytest

from confiture.core.seed_executor import SeedExecutor
from confiture.exceptions import SeedError


@pytest.fixture
def mock_connection():
    """Create a mock database connection."""
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=None)
    return conn


def test_seed_executor_creation(mock_connection):
    """Test SeedExecutor can be created with connection."""
    executor = SeedExecutor(connection=mock_connection)
    assert executor.connection == mock_connection


def test_execute_file_creates_savepoint(mock_connection, tmp_path):
    """Test that execute_file creates and releases savepoint."""
    # Create a test seed file
    seed_file = tmp_path / "test_seed.sql"
    seed_file.write_text("INSERT INTO users (id) VALUES (1);")

    executor = SeedExecutor(connection=mock_connection)

    # Execute the file
    executor.execute_file(seed_file, savepoint_name="sp_test")

    # Verify savepoint operations were called
    cursor = mock_connection.cursor.return_value.__enter__.return_value
    # Should have at least 3 calls: SAVEPOINT, INSERT, RELEASE
    assert cursor.execute.call_count >= 3, (
        f"Expected at least 3 execute calls, got {cursor.execute.call_count}"
    )


def test_execute_file_reads_sql_content(mock_connection, tmp_path):
    """Test that execute_file reads and executes SQL content."""
    seed_file = tmp_path / "test_seed.sql"
    test_sql = "INSERT INTO users (id, name) VALUES (1, 'Alice');"
    seed_file.write_text(test_sql)

    executor = SeedExecutor(connection=mock_connection)
    executor.execute_file(seed_file, savepoint_name="sp_test")

    # Verify SQL executed
    cursor = mock_connection.cursor.return_value.__enter__.return_value
    cursor.execute.assert_called()


def test_execute_file_error_raises_seed_error(mock_connection, tmp_path):
    """Test that SQL errors raise SeedError."""
    seed_file = tmp_path / "bad_seed.sql"
    seed_file.write_text("INVALID SQL SYNTAX HERE;")

    # Mock cursor to raise an error
    cursor = mock_connection.cursor.return_value.__enter__.return_value
    cursor.execute.side_effect = Exception("Syntax error")

    executor = SeedExecutor(connection=mock_connection)

    with pytest.raises(SeedError):
        executor.execute_file(seed_file, savepoint_name="sp_test")


def test_reject_seed_with_begin_command(mock_connection, tmp_path):
    """Test that seed files with BEGIN are rejected."""
    seed_file = tmp_path / "bad_seed.sql"
    seed_file.write_text("""
        BEGIN;
        INSERT INTO users VALUES (1);
    """)

    executor = SeedExecutor(connection=mock_connection)

    with pytest.raises(SeedError, match="transaction"):
        executor.execute_file(seed_file, savepoint_name="sp_test")


def test_reject_seed_with_commit_command(mock_connection, tmp_path):
    """Test that seed files with COMMIT are rejected."""
    seed_file = tmp_path / "bad_seed.sql"
    seed_file.write_text("""
        INSERT INTO users VALUES (1);
        COMMIT;
    """)

    executor = SeedExecutor(connection=mock_connection)

    with pytest.raises(SeedError, match="transaction"):
        executor.execute_file(seed_file, savepoint_name="sp_test")


def test_reject_seed_with_rollback_command(mock_connection, tmp_path):
    """Test that seed files with ROLLBACK are rejected."""
    seed_file = tmp_path / "bad_seed.sql"
    seed_file.write_text("""
        INSERT INTO users VALUES (1);
        ROLLBACK;
    """)

    executor = SeedExecutor(connection=mock_connection)

    with pytest.raises(SeedError, match="transaction"):
        executor.execute_file(seed_file, savepoint_name="sp_test")


def test_seed_error_includes_file_context(mock_connection, tmp_path):
    """Test that SeedError includes file path."""
    seed_file = tmp_path / "test_seed.sql"
    seed_file.write_text("INSERT INTO users VALUES (1);")

    cursor = mock_connection.cursor.return_value.__enter__.return_value
    cursor.execute.side_effect = Exception("Database error")

    executor = SeedExecutor(connection=mock_connection)

    with pytest.raises(SeedError) as exc_info:
        executor.execute_file(seed_file, savepoint_name="sp_test")

    # Verify error includes context about the file
    error_msg = str(exc_info.value)
    assert str(seed_file) in error_msg or seed_file.name in error_msg
