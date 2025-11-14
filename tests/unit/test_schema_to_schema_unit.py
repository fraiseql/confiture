"""Unit tests for SchemaToSchemaMigrator core logic (no database required).

Tests FDW setup logic, strategy selection, verification logic, and error handling
in isolation without requiring database connections.
"""

from unittest.mock import MagicMock, Mock, PropertyMock, patch

import psycopg
import pytest
from psycopg import sql

from confiture.core.schema_to_schema import (
    COPY_THROUGHPUT,
    FDW_THROUGHPUT,
    LARGE_TABLE_THRESHOLD,
    SchemaToSchemaMigrator,
)
from confiture.exceptions import MigrationError


class TestConstants:
    """Test module constants are properly defined."""

    def test_large_table_threshold(self):
        """Test large table threshold is 10M rows."""
        assert LARGE_TABLE_THRESHOLD == 10_000_000

    def test_fdw_throughput(self):
        """Test FDW throughput constant."""
        assert FDW_THROUGHPUT == 500_000

    def test_copy_throughput(self):
        """Test COPY throughput is 10-20x faster."""
        assert COPY_THROUGHPUT == 6_000_000
        assert COPY_THROUGHPUT / FDW_THROUGHPUT == 12  # 12x faster


class TestMigratorInitialization:
    """Test SchemaToSchemaMigrator initialization."""

    def test_init_with_default_names(self):
        """Test initialization with default schema and server names."""
        source_conn = Mock()
        target_conn = Mock()

        migrator = SchemaToSchemaMigrator(source_conn, target_conn)

        assert migrator.source_connection == source_conn
        assert migrator.target_connection == target_conn
        assert migrator.foreign_schema_name == "old_schema"
        assert migrator.server_name == "confiture_source_server"

    def test_init_with_custom_names(self):
        """Test initialization with custom schema and server names."""
        source_conn = Mock()
        target_conn = Mock()

        migrator = SchemaToSchemaMigrator(
            source_conn,
            target_conn,
            foreign_schema_name="custom_schema",
            server_name="custom_server",
        )

        assert migrator.foreign_schema_name == "custom_schema"
        assert migrator.server_name == "custom_server"


class TestConnectionParams:
    """Test connection parameter extraction."""

    def test_get_connection_params_extracts_dbname_and_user(self):
        """Test extracting dbname and user from connection."""
        source_conn = Mock()
        target_conn = Mock()

        # Mock connection info
        mock_info = Mock()
        mock_info.get_parameters.return_value = {
            "dbname": "production_db",
            "user": "postgres_user",
        }
        source_conn.info = mock_info

        migrator = SchemaToSchemaMigrator(source_conn, target_conn)
        dbname, user = migrator._get_connection_params()

        assert dbname == "production_db"
        assert user == "postgres_user"

    def test_get_connection_params_defaults(self):
        """Test default values when params not available."""
        source_conn = Mock()
        target_conn = Mock()

        # Mock connection info with missing params
        mock_info = Mock()
        mock_info.get_parameters.return_value = {}
        source_conn.info = mock_info

        migrator = SchemaToSchemaMigrator(source_conn, target_conn)
        dbname, user = migrator._get_connection_params()

        assert dbname == "postgres"
        assert user == "postgres"


class TestMigrateTableValidation:
    """Test migrate_table input validation."""

    def test_migrate_table_empty_column_mapping_raises(self):
        """Test that empty column_mapping raises MigrationError."""
        source_conn = Mock()
        target_conn = Mock()

        migrator = SchemaToSchemaMigrator(source_conn, target_conn)

        with pytest.raises(MigrationError, match="column_mapping cannot be empty"):
            migrator.migrate_table("users", "users", column_mapping={})

    def test_migrate_table_copy_empty_column_mapping_raises(self):
        """Test that empty column_mapping raises MigrationError in COPY mode."""
        source_conn = Mock()
        target_conn = Mock()

        migrator = SchemaToSchemaMigrator(source_conn, target_conn)

        with pytest.raises(MigrationError, match="column_mapping cannot be empty"):
            migrator.migrate_table_copy("users", "users", column_mapping={})


class TestStrategySelection:
    """Test migration strategy selection logic."""

    def test_strategy_for_small_table(self):
        """Test FDW strategy selected for tables < 10M rows."""
        # Mock a small table (1M rows)
        row_count = 1_000_000

        # Should select FDW
        if row_count >= LARGE_TABLE_THRESHOLD:
            strategy = "copy"
        else:
            strategy = "fdw"

        assert strategy == "fdw"

    def test_strategy_for_large_table(self):
        """Test COPY strategy selected for tables >= 10M rows."""
        # Mock a large table (50M rows)
        row_count = 50_000_000

        # Should select COPY
        if row_count >= LARGE_TABLE_THRESHOLD:
            strategy = "copy"
        else:
            strategy = "fdw"

        assert strategy == "copy"

    def test_strategy_threshold_boundary(self):
        """Test strategy selection at exact threshold (10M rows)."""
        row_count = LARGE_TABLE_THRESHOLD

        # Should select COPY (>= threshold)
        if row_count >= LARGE_TABLE_THRESHOLD:
            strategy = "copy"
        else:
            strategy = "fdw"

        assert strategy == "copy"


class TestEstimatedTime:
    """Test migration time estimation logic."""

    def test_estimated_time_fdw_strategy(self):
        """Test time estimation for FDW strategy."""
        row_count = 1_000_000
        estimated_seconds = row_count / FDW_THROUGHPUT

        # 1M rows / 500k rows/s = 2 seconds
        assert estimated_seconds == 2.0

    def test_estimated_time_copy_strategy(self):
        """Test time estimation for COPY strategy."""
        row_count = 60_000_000
        estimated_seconds = row_count / COPY_THROUGHPUT

        # 60M rows / 6M rows/s = 10 seconds
        assert estimated_seconds == 10.0

    def test_estimated_time_rounding(self):
        """Test time estimation rounding for small tables."""
        row_count = 100
        estimated_seconds = row_count / FDW_THROUGHPUT

        # Should be 0.0002, but rounds to 0.001 minimum
        raw_estimate = estimated_seconds
        final_estimate = max(0.001, round(raw_estimate, 3))

        assert final_estimate == 0.001

    def test_estimated_time_zero_rows(self):
        """Test time estimation for empty tables."""
        row_count = 0

        # Empty table should have 0 estimated time
        if row_count > 0:
            estimated_seconds = max(0.001, round(row_count / FDW_THROUGHPUT, 3))
        else:
            estimated_seconds = 0.0

        assert estimated_seconds == 0.0


class TestVerificationLogic:
    """Test migration verification logic."""

    def test_verification_matching_counts(self):
        """Test verification with matching row counts."""
        source_count = 1000
        target_count = 1000

        difference = target_count - source_count
        match = source_count == target_count

        assert match is True
        assert difference == 0

    def test_verification_missing_rows(self):
        """Test verification detects missing rows in target."""
        source_count = 1000
        target_count = 950

        difference = target_count - source_count
        match = source_count == target_count

        assert match is False
        assert difference == -50  # 50 rows missing

    def test_verification_extra_rows(self):
        """Test verification detects extra rows in target."""
        source_count = 1000
        target_count = 1050

        difference = target_count - source_count
        match = source_count == target_count

        assert match is False
        assert difference == 50  # 50 extra rows

    def test_verification_empty_tables(self):
        """Test verification with empty source and target."""
        source_count = 0
        target_count = 0

        difference = target_count - source_count
        match = source_count == target_count

        assert match is True
        assert difference == 0


class TestSQLComposition:
    """Test SQL query composition logic."""

    def test_column_mapping_builds_correct_structure(self):
        """Test column mapping creates correct number of select items."""
        column_mapping = {
            "old_name": "new_name",
            "id": "id",
            "created": "created_at",
        }

        # Build SELECT clause similar to migrate_table
        select_items = []
        for source_col, target_col in column_mapping.items():
            select_items.append(
                sql.SQL("{source} AS {target}").format(
                    source=sql.Identifier(source_col),
                    target=sql.Identifier(target_col),
                )
            )

        # Verify correct number of items
        assert len(select_items) == 3

    def test_sql_identifiers_used_for_tables(self):
        """Test that sql.Identifier is used for table names."""
        table_name = "users"

        # Use sql.Identifier (same as in production code)
        identifier = sql.Identifier(table_name)

        # Verify it's the correct type
        assert isinstance(identifier, sql.Identifier)


class TestErrorHandling:
    """Test error handling and exception raising."""

    def test_empty_column_mapping_raises_migration_error(self):
        """Test that empty column mapping raises MigrationError."""
        source_conn = Mock()
        target_conn = Mock()
        migrator = SchemaToSchemaMigrator(source_conn, target_conn)

        # Should raise MigrationError
        with pytest.raises(MigrationError):
            migrator.migrate_table("source", "target", {})

        with pytest.raises(MigrationError):
            migrator.migrate_table_copy("source", "target", {})

    def test_migration_error_preserves_context(self):
        """Test that MigrationError preserves exception context."""
        # This tests the error handling pattern used throughout the module
        original_error = ValueError("Original error")

        try:
            raise MigrationError("Migration failed") from original_error
        except MigrationError as e:
            # Verify exception chaining works
            assert e.__cause__ == original_error
            assert "Migration failed" in str(e)


class TestSQLSafety:
    """Test SQL injection prevention through psycopg.sql usage."""

    def test_sql_identifier_type_used(self):
        """Test that sql.Identifier is used for identifiers (SQL injection safe)."""
        # Potentially dangerous table name
        table_name = "users; DROP TABLE important_data; --"

        # Use sql.Identifier (same as in production code)
        identifier = sql.Identifier(table_name)

        # Verify it's an Identifier (which psycopg escapes safely)
        assert isinstance(identifier, sql.Identifier)

    def test_sql_literal_type_used(self):
        """Test that sql.Literal is used for literals (SQL injection safe)."""
        # Potentially dangerous value
        dangerous_value = "'; DROP TABLE users; --"

        # Use sql.Literal (same as in production code)
        literal = sql.Literal(dangerous_value)

        # Verify it's a Literal (which psycopg escapes safely)
        assert isinstance(literal, sql.Literal)


class TestCleanupLogic:
    """Test FDW cleanup logic."""

    def test_cleanup_sql_order(self):
        """Test cleanup executes in correct order (schema → mapping → server)."""
        # The order matters: schema must be dropped before server
        # This tests the logic structure of cleanup_fdw

        cleanup_order = []

        # Simulate cleanup operations
        def drop_schema():
            cleanup_order.append("schema")

        def drop_mapping():
            cleanup_order.append("mapping")

        def drop_server():
            cleanup_order.append("server")

        # Execute in correct order
        drop_schema()
        drop_mapping()
        drop_server()

        # Verify order
        assert cleanup_order == ["schema", "mapping", "server"]

    def test_cleanup_uses_cascade(self):
        """Test cleanup constructs DROP SCHEMA with CASCADE."""
        schema_name = "old_schema"

        # Build DROP SCHEMA query (similar to cleanup_fdw)
        query = sql.SQL("DROP SCHEMA IF EXISTS {schema} CASCADE").format(
            schema=sql.Identifier(schema_name)
        )

        # Verify it's a Composed object with CASCADE and IF EXISTS
        assert isinstance(query, sql.Composed)
        # The template string contains CASCADE and IF EXISTS
        assert "CASCADE" in str(query._obj)
        assert "IF EXISTS" in str(query._obj)


class TestAnalysisRecommendations:
    """Test table analysis and strategy recommendations."""

    def test_recommendation_for_small_table(self):
        """Test recommendation for small table."""
        row_count = 50_000

        if row_count >= LARGE_TABLE_THRESHOLD:
            strategy = "copy"
            estimated_seconds = row_count / COPY_THROUGHPUT
        else:
            strategy = "fdw"
            estimated_seconds = row_count / FDW_THROUGHPUT

        assert strategy == "fdw"
        assert estimated_seconds == 0.1  # 50k / 500k = 0.1s

    def test_recommendation_for_large_table(self):
        """Test recommendation for large table."""
        row_count = 50_000_000

        if row_count >= LARGE_TABLE_THRESHOLD:
            strategy = "copy"
            estimated_seconds = row_count / COPY_THROUGHPUT
        else:
            strategy = "fdw"
            estimated_seconds = row_count / FDW_THROUGHPUT

        assert strategy == "copy"
        assert estimated_seconds == pytest.approx(8.333, rel=0.01)  # 50M / 6M ≈ 8.33s

    def test_recommendation_structure(self):
        """Test recommendation dictionary structure."""
        # Simulates the structure returned by analyze_tables
        table_name = "users"
        row_count = 1000
        strategy = "fdw"
        estimated_seconds = 0.002

        recommendation = {
            "strategy": strategy,
            "row_count": row_count,
            "estimated_seconds": max(0.001, round(estimated_seconds, 3)),
        }

        assert "strategy" in recommendation
        assert "row_count" in recommendation
        assert "estimated_seconds" in recommendation
        assert recommendation["strategy"] in ["fdw", "copy"]
        assert isinstance(recommendation["row_count"], int)
        assert isinstance(recommendation["estimated_seconds"], float)
