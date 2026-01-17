"""Tests for rollback generation and testing."""

from unittest.mock import MagicMock, Mock

import pytest

from confiture.core.rollback_generator import (
    RollbackSuggestion,
    RollbackTester,
    RollbackTestResult,
    generate_rollback,
    generate_rollback_script,
    suggest_backup_for_destructive_operations,
)


class TestRollbackSuggestion:
    """Tests for RollbackSuggestion dataclass."""

    def test_suggestion_creation(self):
        """Test creating a rollback suggestion."""
        suggestion = RollbackSuggestion(
            original_sql="CREATE TABLE users (id INT)",
            rollback_sql="DROP TABLE IF EXISTS users",
            confidence="high",
            notes="Table will be dropped",
        )
        assert suggestion.confidence == "high"
        assert "DROP TABLE" in suggestion.rollback_sql

    def test_suggestion_to_dict(self):
        """Test converting suggestion to dictionary."""
        suggestion = RollbackSuggestion(
            original_sql="CREATE TABLE users (id INT)",
            rollback_sql="DROP TABLE IF EXISTS users",
            confidence="high",
        )
        result = suggestion.to_dict()
        assert result["confidence"] == "high"
        assert result["rollback_sql"] == "DROP TABLE IF EXISTS users"


class TestRollbackTestResult:
    """Tests for RollbackTestResult dataclass."""

    def test_successful_result(self):
        """Test successful rollback test result."""
        result = RollbackTestResult(
            migration_version="001",
            migration_name="create_users",
            clean_state=True,
        )
        assert result.is_successful
        assert result.clean_state

    def test_failed_result_with_error(self):
        """Test failed rollback test result."""
        result = RollbackTestResult(
            migration_version="001",
            migration_name="create_users",
            clean_state=True,
            error="Migration failed",
        )
        assert not result.is_successful

    def test_failed_result_dirty_state(self):
        """Test failed result with dirty state."""
        result = RollbackTestResult(
            migration_version="001",
            migration_name="create_users",
            clean_state=False,
            tables_before={"users"},
            tables_after={"users", "new_table"},
        )
        assert not result.is_successful

    def test_result_to_dict(self):
        """Test converting result to dictionary."""
        result = RollbackTestResult(
            migration_version="001",
            migration_name="create_users",
            clean_state=True,
            duration_ms=100,
        )
        data = result.to_dict()
        assert data["migration_version"] == "001"
        assert data["is_successful"] is True
        assert data["duration_ms"] == 100


class TestGenerateRollback:
    """Tests for generate_rollback function."""

    def test_create_table_rollback(self):
        """Test rollback for CREATE TABLE."""
        result = generate_rollback("CREATE TABLE users (id INT)")
        assert result is not None
        assert result.confidence == "high"
        assert "DROP TABLE IF EXISTS users" in result.rollback_sql

    def test_create_table_if_not_exists_rollback(self):
        """Test rollback for CREATE TABLE IF NOT EXISTS."""
        result = generate_rollback("CREATE TABLE IF NOT EXISTS users (id INT)")
        assert result is not None
        assert "DROP TABLE IF EXISTS users" in result.rollback_sql

    def test_create_index_rollback(self):
        """Test rollback for CREATE INDEX."""
        result = generate_rollback("CREATE INDEX idx_users_email ON users (email)")
        assert result is not None
        assert result.confidence == "high"
        assert "DROP INDEX" in result.rollback_sql
        assert "idx_users_email" in result.rollback_sql

    def test_create_unique_index_rollback(self):
        """Test rollback for CREATE UNIQUE INDEX."""
        result = generate_rollback("CREATE UNIQUE INDEX idx_users_email ON users (email)")
        assert result is not None
        assert "DROP INDEX" in result.rollback_sql

    def test_create_index_concurrently_rollback(self):
        """Test rollback for CREATE INDEX CONCURRENTLY."""
        result = generate_rollback("CREATE INDEX CONCURRENTLY idx_users_email ON users (email)")
        assert result is not None
        assert "DROP INDEX CONCURRENTLY" in result.rollback_sql

    def test_add_column_rollback(self):
        """Test rollback for ADD COLUMN."""
        result = generate_rollback("ALTER TABLE users ADD COLUMN email TEXT")
        assert result is not None
        assert result.confidence == "high"
        assert "DROP COLUMN" in result.rollback_sql
        assert "email" in result.rollback_sql

    def test_add_column_if_not_exists_rollback(self):
        """Test rollback for ADD COLUMN IF NOT EXISTS."""
        result = generate_rollback("ALTER TABLE users ADD COLUMN IF NOT EXISTS email TEXT")
        assert result is not None
        assert "DROP COLUMN IF EXISTS email" in result.rollback_sql

    def test_add_constraint_rollback(self):
        """Test rollback for ADD CONSTRAINT."""
        result = generate_rollback(
            "ALTER TABLE orders ADD CONSTRAINT fk_user FOREIGN KEY (user_id) REFERENCES users(id)"
        )
        assert result is not None
        assert result.confidence == "high"
        assert "DROP CONSTRAINT" in result.rollback_sql
        assert "fk_user" in result.rollback_sql

    def test_create_sequence_rollback(self):
        """Test rollback for CREATE SEQUENCE."""
        result = generate_rollback("CREATE SEQUENCE users_id_seq")
        assert result is not None
        assert "DROP SEQUENCE IF EXISTS users_id_seq" in result.rollback_sql

    def test_create_type_rollback(self):
        """Test rollback for CREATE TYPE."""
        result = generate_rollback("CREATE TYPE mood AS ENUM ('happy', 'sad')")
        assert result is not None
        assert "DROP TYPE IF EXISTS mood" in result.rollback_sql

    def test_create_extension_rollback(self):
        """Test rollback for CREATE EXTENSION."""
        result = generate_rollback("CREATE EXTENSION IF NOT EXISTS uuid-ossp")
        assert result is not None
        assert result.confidence == "medium"  # Lower confidence for extensions
        assert "DROP EXTENSION" in result.rollback_sql

    def test_no_rollback_for_select(self):
        """Test no rollback for SELECT statement."""
        result = generate_rollback("SELECT * FROM users")
        assert result is None

    def test_no_rollback_for_update(self):
        """Test no rollback for UPDATE statement."""
        result = generate_rollback("UPDATE users SET name = 'test'")
        assert result is None

    def test_no_rollback_for_insert(self):
        """Test no rollback for INSERT statement."""
        result = generate_rollback("INSERT INTO users (name) VALUES ('test')")
        assert result is None

    def test_no_rollback_for_delete(self):
        """Test no rollback for DELETE statement."""
        result = generate_rollback("DELETE FROM users WHERE id = 1")
        assert result is None


class TestGenerateRollbackScript:
    """Tests for generate_rollback_script function."""

    def test_multiple_statements(self):
        """Test generating rollback for multiple statements."""
        sql = """
        CREATE TABLE users (id INT);
        CREATE INDEX idx_users_id ON users (id);
        ALTER TABLE users ADD COLUMN email TEXT;
        """
        suggestions = generate_rollback_script(sql)

        assert len(suggestions) == 3
        # Should be in reverse order
        assert "DROP COLUMN" in suggestions[0].rollback_sql
        assert "DROP INDEX" in suggestions[1].rollback_sql
        assert "DROP TABLE" in suggestions[2].rollback_sql

    def test_mixed_statements(self):
        """Test with mix of supported and unsupported statements."""
        sql = """
        CREATE TABLE users (id INT);
        INSERT INTO users (id) VALUES (1);
        CREATE INDEX idx_users_id ON users (id);
        """
        suggestions = generate_rollback_script(sql)

        # Should only have 2 (CREATE TABLE and CREATE INDEX)
        assert len(suggestions) == 2


class TestRollbackTester:
    """Tests for RollbackTester class."""

    @pytest.fixture
    def mock_connection(self):
        """Create mock connection."""
        conn = Mock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__ = Mock(return_value=cursor)
        conn.cursor.return_value.__exit__ = Mock(return_value=False)
        cursor.fetchall.return_value = [("users",)]
        return conn, cursor

    def test_test_migration_success(self, mock_connection):
        """Test successful migration rollback test."""
        conn, cursor = mock_connection
        # Return same tables before and after
        cursor.fetchall.side_effect = [
            [("users",)],  # tables before
            [("idx_users",)],  # indexes before
            [("users",)],  # tables after
            [("idx_users",)],  # indexes after
        ]

        migration = Mock()
        migration.version = "001"
        migration.name = "test_migration"
        migration.up = Mock()
        migration.down = Mock()

        tester = RollbackTester(conn)
        result = tester.test_migration(migration)

        assert result.is_successful
        assert result.clean_state
        assert migration.up.called
        assert migration.down.called

    def test_test_migration_no_down_method(self, mock_connection):
        """Test migration without down() method."""
        conn, cursor = mock_connection
        cursor.fetchall.return_value = []

        migration = Mock(spec=["version", "name", "up"])
        migration.version = "001"
        migration.name = "test_migration"

        tester = RollbackTester(conn)
        result = tester.test_migration(migration)

        assert not result.is_successful
        assert "no down() method" in result.error

    def test_test_migration_dirty_state(self, mock_connection):
        """Test migration that leaves dirty state."""
        conn, cursor = mock_connection
        # Return different tables after rollback
        cursor.fetchall.side_effect = [
            [("users",)],  # tables before
            [],  # indexes before
            [("users",), ("leftover",)],  # tables after (extra table!)
            [],  # indexes after
        ]

        migration = Mock()
        migration.version = "001"
        migration.name = "test_migration"
        migration.up = Mock()
        migration.down = Mock()

        tester = RollbackTester(conn)
        result = tester.test_migration(migration)

        assert not result.is_successful
        assert not result.clean_state
        assert result.error is not None
        assert "leftover" in result.error

    def test_test_migration_exception(self, mock_connection):
        """Test migration that throws exception."""
        conn, cursor = mock_connection
        cursor.fetchall.return_value = []

        migration = Mock()
        migration.version = "001"
        migration.name = "test_migration"
        migration.up = Mock(side_effect=Exception("Migration failed"))

        tester = RollbackTester(conn)
        result = tester.test_migration(migration)

        assert not result.is_successful
        assert "Migration failed" in result.error


class TestSuggestBackup:
    """Tests for backup suggestions."""

    def test_suggest_backup_drop_table(self):
        """Test backup suggestion for DROP TABLE."""
        suggestions = suggest_backup_for_destructive_operations("DROP TABLE users")
        assert len(suggestions) == 1
        assert "backup" in suggestions[0].lower()
        assert "users" in suggestions[0]

    def test_suggest_backup_drop_column(self):
        """Test backup suggestion for DROP COLUMN."""
        suggestions = suggest_backup_for_destructive_operations(
            "ALTER TABLE users DROP COLUMN email"
        )
        assert len(suggestions) == 1
        assert "backup" in suggestions[0].lower()
        assert "email" in suggestions[0]

    def test_suggest_backup_truncate(self):
        """Test backup suggestion for TRUNCATE."""
        suggestions = suggest_backup_for_destructive_operations("TRUNCATE TABLE users")
        assert len(suggestions) == 1
        assert "backup" in suggestions[0].lower()

    def test_no_backup_for_create(self):
        """Test no backup suggestion for CREATE."""
        suggestions = suggest_backup_for_destructive_operations("CREATE TABLE users (id INT)")
        assert len(suggestions) == 0

    def test_no_backup_for_select(self):
        """Test no backup suggestion for SELECT."""
        suggestions = suggest_backup_for_destructive_operations("SELECT * FROM users")
        assert len(suggestions) == 0
