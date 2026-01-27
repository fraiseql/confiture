"""Unit tests for migration preconditions.

Tests the precondition validation system that provides fail-fast behavior
before migration execution.
"""

from unittest.mock import MagicMock, Mock

import pytest

from confiture.core.preconditions import (
    ColumnExists,
    ColumnNotExists,
    ColumnType,
    ConstraintExists,
    ConstraintNotExists,
    CustomSQL,
    IndexExists,
    IndexNotExists,
    PreconditionError,
    PreconditionValidationError,
    PreconditionValidator,
    RowCountEquals,
    RowCountGreaterThan,
    SchemaExists,
    SchemaNotExists,
    TableExists,
    TableIsEmpty,
    TableNotExists,
)

# =============================================================================
# Helper to create mock connections with specific query results
# =============================================================================


def create_mock_connection(query_results: dict[str, list]) -> MagicMock:
    """Create a mock connection that returns predefined results for queries.

    Args:
        query_results: Dict mapping SQL query substrings to return values
    """
    mock_conn = MagicMock()
    mock_cursor = MagicMock()

    def execute_side_effect(sql, params=None):
        for query_substring, result in query_results.items():
            if query_substring in sql:
                mock_cursor.fetchone.return_value = result
                return
        mock_cursor.fetchone.return_value = None

    mock_cursor.execute.side_effect = execute_side_effect
    mock_cursor.__enter__ = Mock(return_value=mock_cursor)
    mock_cursor.__exit__ = Mock(return_value=None)
    mock_conn.cursor.return_value = mock_cursor

    return mock_conn


# =============================================================================
# Table Preconditions Tests
# =============================================================================


class TestTableExists:
    """Tests for TableExists precondition."""

    def test_table_exists_passes_when_table_found(self):
        """TableExists should pass when table is found in database."""
        mock_conn = create_mock_connection({"information_schema.tables": [True]})
        precondition = TableExists("users", schema="public")

        passed, message = precondition.check(mock_conn)

        assert passed is True
        assert "exists" in message.lower()

    def test_table_exists_fails_when_table_not_found(self):
        """TableExists should fail when table is not found."""
        mock_conn = create_mock_connection({"information_schema.tables": [False]})
        precondition = TableExists("users", schema="public")

        passed, message = precondition.check(mock_conn)

        assert passed is False

    def test_table_exists_default_schema_is_public(self):
        """TableExists should default to public schema."""
        precondition = TableExists("users")
        assert precondition.schema == "public"

    def test_table_exists_str_representation(self):
        """TableExists should have readable string representation."""
        precondition = TableExists("users", schema="tenant")
        assert str(precondition) == "TableExists(tenant.users)"


class TestTableNotExists:
    """Tests for TableNotExists precondition."""

    def test_table_not_exists_passes_when_table_missing(self):
        """TableNotExists should pass when table is not found."""
        mock_conn = create_mock_connection({"information_schema.tables": [True]})  # NOT EXISTS returns True
        precondition = TableNotExists("users_backup")

        passed, message = precondition.check(mock_conn)

        assert passed is True
        assert "does not exist" in message.lower()

    def test_table_not_exists_fails_when_table_found(self):
        """TableNotExists should fail when table exists."""
        mock_conn = create_mock_connection({"information_schema.tables": [False]})  # NOT EXISTS returns False
        precondition = TableNotExists("users")

        passed, message = precondition.check(mock_conn)

        assert passed is False


# =============================================================================
# Column Preconditions Tests
# =============================================================================


class TestColumnExists:
    """Tests for ColumnExists precondition."""

    def test_column_exists_passes_when_column_found(self):
        """ColumnExists should pass when column is found."""
        mock_conn = create_mock_connection({"information_schema.columns": [True]})
        precondition = ColumnExists("users", "email")

        passed, message = precondition.check(mock_conn)

        assert passed is True

    def test_column_exists_fails_when_column_missing(self):
        """ColumnExists should fail when column is not found."""
        mock_conn = create_mock_connection({"information_schema.columns": [False]})
        precondition = ColumnExists("users", "legacy_field")

        passed, message = precondition.check(mock_conn)

        assert passed is False

    def test_column_exists_str_representation(self):
        """ColumnExists should have readable string representation."""
        precondition = ColumnExists("users", "email", schema="public")
        assert str(precondition) == "ColumnExists(public.users.email)"


class TestColumnNotExists:
    """Tests for ColumnNotExists precondition."""

    def test_column_not_exists_passes_when_column_missing(self):
        """ColumnNotExists should pass when column is not found."""
        mock_conn = create_mock_connection({"information_schema.columns": [True]})
        precondition = ColumnNotExists("users", "legacy_field")

        passed, message = precondition.check(mock_conn)

        assert passed is True

    def test_column_not_exists_fails_when_column_found(self):
        """ColumnNotExists should fail when column exists."""
        mock_conn = create_mock_connection({"information_schema.columns": [False]})
        precondition = ColumnNotExists("users", "email")

        passed, message = precondition.check(mock_conn)

        assert passed is False


class TestColumnType:
    """Tests for ColumnType precondition."""

    def test_column_type_passes_when_type_matches(self):
        """ColumnType should pass when column has expected type."""
        mock_conn = create_mock_connection({"information_schema.columns": ["uuid"]})
        precondition = ColumnType("users", "id", "uuid")

        passed, message = precondition.check(mock_conn)

        assert passed is True

    def test_column_type_fails_when_type_mismatch(self):
        """ColumnType should fail when column has different type."""
        mock_conn = create_mock_connection({"information_schema.columns": ["integer"]})
        precondition = ColumnType("users", "id", "uuid")

        passed, message = precondition.check(mock_conn)

        assert passed is False
        assert "uuid" in message.lower()
        assert "integer" in message.lower()

    def test_column_type_handles_aliases(self):
        """ColumnType should handle PostgreSQL type aliases."""
        mock_conn = create_mock_connection({"information_schema.columns": ["integer"]})
        precondition = ColumnType("users", "count", "int")

        passed, message = precondition.check(mock_conn)

        # 'int' should be recognized as 'integer'
        assert passed is True

    def test_column_type_handles_varchar(self):
        """ColumnType should handle varchar -> character varying alias."""
        mock_conn = create_mock_connection({"information_schema.columns": ["character varying"]})
        precondition = ColumnType("users", "name", "varchar")

        passed, message = precondition.check(mock_conn)

        assert passed is True


# =============================================================================
# Constraint Preconditions Tests
# =============================================================================


class TestConstraintExists:
    """Tests for ConstraintExists precondition."""

    def test_constraint_exists_passes_when_found(self):
        """ConstraintExists should pass when constraint is found."""
        mock_conn = create_mock_connection({"table_constraints": [True]})
        precondition = ConstraintExists("users", "users_pkey")

        passed, message = precondition.check(mock_conn)

        assert passed is True

    def test_constraint_exists_fails_when_missing(self):
        """ConstraintExists should fail when constraint is not found."""
        mock_conn = create_mock_connection({"table_constraints": [False]})
        precondition = ConstraintExists("users", "fk_nonexistent")

        passed, message = precondition.check(mock_conn)

        assert passed is False


class TestConstraintNotExists:
    """Tests for ConstraintNotExists precondition."""

    def test_constraint_not_exists_passes_when_missing(self):
        """ConstraintNotExists should pass when constraint is not found."""
        mock_conn = create_mock_connection({"table_constraints": [True]})
        precondition = ConstraintNotExists("users", "old_constraint")

        passed, message = precondition.check(mock_conn)

        assert passed is True


# =============================================================================
# Index Preconditions Tests
# =============================================================================


class TestIndexExists:
    """Tests for IndexExists precondition."""

    def test_index_exists_passes_when_found(self):
        """IndexExists should pass when index is found."""
        mock_conn = create_mock_connection({"pg_indexes": [True]})
        precondition = IndexExists("users", "idx_users_email")

        passed, message = precondition.check(mock_conn)

        assert passed is True

    def test_index_exists_fails_when_missing(self):
        """IndexExists should fail when index is not found."""
        mock_conn = create_mock_connection({"pg_indexes": [False]})
        precondition = IndexExists("users", "idx_nonexistent")

        passed, message = precondition.check(mock_conn)

        assert passed is False


class TestIndexNotExists:
    """Tests for IndexNotExists precondition."""

    def test_index_not_exists_passes_when_missing(self):
        """IndexNotExists should pass when index is not found."""
        mock_conn = create_mock_connection({"pg_indexes": [True]})
        precondition = IndexNotExists("users", "idx_old")

        passed, message = precondition.check(mock_conn)

        assert passed is True


# =============================================================================
# Schema Preconditions Tests
# =============================================================================


class TestSchemaExists:
    """Tests for SchemaExists precondition."""

    def test_schema_exists_passes_when_found(self):
        """SchemaExists should pass when schema is found."""
        mock_conn = create_mock_connection({"information_schema.schemata": [True]})
        precondition = SchemaExists("tenant")

        passed, message = precondition.check(mock_conn)

        assert passed is True

    def test_schema_exists_str_representation(self):
        """SchemaExists should have readable string representation."""
        precondition = SchemaExists("catalog")
        assert str(precondition) == "SchemaExists(catalog)"


class TestSchemaNotExists:
    """Tests for SchemaNotExists precondition."""

    def test_schema_not_exists_passes_when_missing(self):
        """SchemaNotExists should pass when schema is not found."""
        mock_conn = create_mock_connection({"information_schema.schemata": [True]})
        precondition = SchemaNotExists("legacy_schema")

        passed, message = precondition.check(mock_conn)

        assert passed is True


# =============================================================================
# Row Count Preconditions Tests
# =============================================================================


class TestRowCountEquals:
    """Tests for RowCountEquals precondition."""

    def test_row_count_equals_passes_when_match(self):
        """RowCountEquals should pass when count matches."""
        mock_conn = create_mock_connection({"COUNT(*)": [5]})
        precondition = RowCountEquals("users", 5)

        passed, message = precondition.check(mock_conn)

        assert passed is True

    def test_row_count_equals_fails_when_mismatch(self):
        """RowCountEquals should fail when count doesn't match."""
        mock_conn = create_mock_connection({"COUNT(*)": [10]})
        precondition = RowCountEquals("users", 5)

        passed, message = precondition.check(mock_conn)

        assert passed is False
        assert "5" in message
        assert "10" in message


class TestRowCountGreaterThan:
    """Tests for RowCountGreaterThan precondition."""

    def test_row_count_greater_than_passes_when_greater(self):
        """RowCountGreaterThan should pass when count > threshold."""
        mock_conn = create_mock_connection({"COUNT(*)": [10]})
        precondition = RowCountGreaterThan("users", 5)

        passed, message = precondition.check(mock_conn)

        assert passed is True

    def test_row_count_greater_than_fails_when_equal(self):
        """RowCountGreaterThan should fail when count == threshold."""
        mock_conn = create_mock_connection({"COUNT(*)": [5]})
        precondition = RowCountGreaterThan("users", 5)

        passed, message = precondition.check(mock_conn)

        assert passed is False

    def test_row_count_greater_than_fails_when_less(self):
        """RowCountGreaterThan should fail when count < threshold."""
        mock_conn = create_mock_connection({"COUNT(*)": [3]})
        precondition = RowCountGreaterThan("users", 5)

        passed, message = precondition.check(mock_conn)

        assert passed is False


class TestTableIsEmpty:
    """Tests for TableIsEmpty precondition."""

    def test_table_is_empty_passes_when_empty(self):
        """TableIsEmpty should pass when table has no rows."""
        mock_conn = create_mock_connection({"COUNT(*)": [0]})
        precondition = TableIsEmpty("temp_data")

        passed, message = precondition.check(mock_conn)

        assert passed is True

    def test_table_is_empty_fails_when_has_rows(self):
        """TableIsEmpty should fail when table has rows."""
        mock_conn = create_mock_connection({"COUNT(*)": [5]})
        precondition = TableIsEmpty("temp_data")

        passed, message = precondition.check(mock_conn)

        assert passed is False


# =============================================================================
# CustomSQL Precondition Tests
# =============================================================================


class TestCustomSQL:
    """Tests for CustomSQL precondition."""

    def test_custom_sql_passes_when_true(self):
        """CustomSQL should pass when SQL returns true."""
        mock_conn = create_mock_connection({"pending": [True]})
        precondition = CustomSQL(
            sql="SELECT COUNT(*) = 0 FROM users WHERE status = 'pending'",
            description="No pending users",
        )

        passed, message = precondition.check(mock_conn)

        assert passed is True
        assert message == "No pending users"

    def test_custom_sql_fails_when_false(self):
        """CustomSQL should fail when SQL returns false."""
        mock_conn = create_mock_connection({"pending": [False]})
        precondition = CustomSQL(
            sql="SELECT COUNT(*) = 0 FROM users WHERE status = 'pending'",
            description="No pending users",
        )

        passed, message = precondition.check(mock_conn)

        assert passed is False

    def test_custom_sql_with_params(self):
        """CustomSQL should support parameterized queries."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = [True]
        mock_cursor.__enter__ = Mock(return_value=mock_cursor)
        mock_cursor.__exit__ = Mock(return_value=None)
        mock_conn.cursor.return_value = mock_cursor

        precondition = CustomSQL(
            sql="SELECT COUNT(*) > %s FROM users",
            description="Users count above threshold",
            params=(5,),
        )

        passed, message = precondition.check(mock_conn)

        assert passed is True
        mock_cursor.execute.assert_called_once_with(
            "SELECT COUNT(*) > %s FROM users", (5,)
        )


# =============================================================================
# PreconditionValidator Tests
# =============================================================================


class TestPreconditionValidator:
    """Tests for the PreconditionValidator class."""

    def test_check_returns_all_passed_when_all_pass(self):
        """Validator check() should return (True, []) when all pass."""
        mock_conn = create_mock_connection({
            "information_schema.tables": [True],
            "information_schema.columns": [True],
        })
        validator = PreconditionValidator(mock_conn)

        preconditions = [
            TableExists("users"),
            ColumnExists("users", "email"),
        ]

        all_passed, failures = validator.check(preconditions)

        assert all_passed is True
        assert failures == []

    def test_check_returns_failures_when_some_fail(self):
        """Validator check() should return failures when some fail."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()

        # First call passes (TableExists), second fails (ColumnExists)
        mock_cursor.fetchone.side_effect = [[True], [False]]
        mock_cursor.__enter__ = Mock(return_value=mock_cursor)
        mock_cursor.__exit__ = Mock(return_value=None)
        mock_conn.cursor.return_value = mock_cursor

        validator = PreconditionValidator(mock_conn)

        preconditions = [
            TableExists("users"),
            ColumnExists("users", "nonexistent"),
        ]

        all_passed, failures = validator.check(preconditions)

        assert all_passed is False
        assert len(failures) == 1
        assert isinstance(failures[0][0], ColumnExists)

    def test_validate_raises_on_failure(self):
        """Validator validate() should raise PreconditionValidationError."""
        mock_conn = create_mock_connection({"information_schema.tables": [False]})
        validator = PreconditionValidator(mock_conn)

        preconditions = [TableExists("nonexistent_table")]

        with pytest.raises(PreconditionValidationError) as exc_info:
            validator.validate(
                preconditions, migration_version="003", migration_name="test"
            )

        assert "preconditions failed" in str(exc_info.value).lower()
        assert len(exc_info.value.failures) == 1

    def test_validate_passes_silently_on_success(self):
        """Validator validate() should not raise when all pass."""
        mock_conn = create_mock_connection({"information_schema.tables": [True]})
        validator = PreconditionValidator(mock_conn)

        preconditions = [TableExists("users")]

        # Should not raise
        validator.validate(preconditions)

    def test_validate_single_raises_precondition_error(self):
        """Validator validate_single() should raise PreconditionError."""
        mock_conn = create_mock_connection({"information_schema.tables": [False]})
        validator = PreconditionValidator(mock_conn)

        precondition = TableExists("nonexistent")

        with pytest.raises(PreconditionError) as exc_info:
            validator.validate_single(precondition)

        assert exc_info.value.precondition is precondition

    def test_empty_preconditions_list_passes(self):
        """Validator should pass with empty preconditions list."""
        mock_conn = MagicMock()
        validator = PreconditionValidator(mock_conn)

        all_passed, failures = validator.check([])

        assert all_passed is True
        assert failures == []


# =============================================================================
# Integration with Migration Class Tests
# =============================================================================


class TestMigrationPreconditions:
    """Tests for preconditions on Migration class."""

    def test_migration_has_precondition_attributes(self):
        """Migration class should have up_preconditions and down_preconditions."""
        from confiture.models.migration import Migration

        class TestMigration(Migration):
            version = "001"
            name = "test"
            up_preconditions = [TableExists("users")]
            down_preconditions = [TableNotExists("users")]

            def up(self):
                pass

            def down(self):
                pass

        # Verify class attributes
        assert hasattr(TestMigration, "up_preconditions")
        assert hasattr(TestMigration, "down_preconditions")
        assert len(TestMigration.up_preconditions) == 1
        assert len(TestMigration.down_preconditions) == 1

    def test_migration_default_preconditions_are_empty(self):
        """Migration should have empty preconditions by default."""
        from confiture.models.migration import Migration

        class SimpleMigration(Migration):
            version = "001"
            name = "simple"

            def up(self):
                pass

            def down(self):
                pass

        assert SimpleMigration.up_preconditions == []
        assert SimpleMigration.down_preconditions == []
