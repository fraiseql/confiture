"""Integration tests for Phase 2 M2 Enhanced Error Messages.

Tests error context detection and formatting with various exception types.
"""

import pytest

from confiture.core.error_context import (
    get_error_context,
    format_error_with_context,
    ERROR_CONTEXTS,
)
from confiture.core.error_handler import _detect_error_context, print_error_to_console
from confiture.exceptions import (
    ConfigurationError,
    MigrationConflictError,
    SchemaError,
    SeedError,
)


class TestErrorContextLookup:
    """Test error context retrieval by code."""

    def test_get_all_error_contexts(self):
        """Verify all 12 error contexts are defined."""
        expected_codes = {
            "DB_CONNECTION_FAILED",
            "DB_PERMISSION_DENIED",
            "SEEDS_DIR_NOT_FOUND",
            "MIGRATIONS_DIR_NOT_FOUND",
            "SCHEMA_DIR_NOT_FOUND",
            "MIGRATION_CONFLICT",
            "SEED_VALIDATION_FAILED",
            "SQL_SYNTAX_ERROR",
            "TABLE_ALREADY_EXISTS",
            "FOREIGN_KEY_CONSTRAINT",
            "INSUFFICIENT_DISK_SPACE",
            "LOCK_TIMEOUT",
        }
        assert set(ERROR_CONTEXTS.keys()) == expected_codes

    def test_get_error_context_returns_context(self):
        """Verify get_error_context returns ErrorContext for valid codes."""
        context = get_error_context("DB_CONNECTION_FAILED")
        assert context is not None
        assert context.error_code == "DB_CONNECTION_FAILED"
        assert context.cause  # Cause is not empty
        assert isinstance(context.cause, str)

    def test_get_error_context_returns_none_for_invalid_code(self):
        """Verify get_error_context returns None for invalid codes."""
        context = get_error_context("INVALID_ERROR_CODE")
        assert context is None

    def test_error_context_has_required_fields(self):
        """Verify all error contexts have required fields."""
        for code, context in ERROR_CONTEXTS.items():
            assert context.error_code == code
            assert context.message
            assert context.cause
            assert isinstance(context.solutions, list)
            assert len(context.solutions) > 0
            assert isinstance(context.examples, list)
            assert context.docs_url.startswith("https://")


class TestErrorContextDetection:
    """Test automatic error context detection from exceptions."""

    def test_detect_database_connection_error(self):
        """Detect database connection errors."""
        error = ConfigurationError("Cannot connect to PostgreSQL database at localhost")
        detected = _detect_error_context(error)
        assert detected == "DB_CONNECTION_FAILED"

    def test_detect_database_permission_error(self):
        """Detect database permission errors."""
        error = ConfigurationError("Database permission denied for user postgres")
        detected = _detect_error_context(error)
        assert detected == "DB_PERMISSION_DENIED"

    def test_detect_seeds_directory_not_found(self):
        """Detect missing seeds directory."""
        error = FileNotFoundError("Could not find seed directory at db/seeds")
        detected = _detect_error_context(error)
        assert detected == "SEEDS_DIR_NOT_FOUND"

    def test_detect_migrations_directory_not_found(self):
        """Detect missing migrations directory."""
        error = FileNotFoundError("Could not find migration directory")
        detected = _detect_error_context(error)
        assert detected == "MIGRATIONS_DIR_NOT_FOUND"

    def test_detect_schema_directory_not_found(self):
        """Detect missing schema directory."""
        error = SchemaError("Schema directory not found at db/schema")
        detected = _detect_error_context(error)
        assert detected == "SCHEMA_DIR_NOT_FOUND"

    def test_detect_migration_conflict_error(self):
        """Detect migration version conflicts."""
        error = MigrationConflictError("Multiple migrations with same version")
        detected = _detect_error_context(error)
        assert detected == "MIGRATION_CONFLICT"

    def test_detect_seed_validation_error(self):
        """Detect seed validation failures."""
        error = SeedError("Seed validation failed: invalid SQL")
        detected = _detect_error_context(error)
        assert detected == "SEED_VALIDATION_FAILED"

    def test_detect_sql_syntax_error(self):
        """Detect SQL syntax errors."""
        error = Exception("syntax error at ';'")
        detected = _detect_error_context(error)
        assert detected == "SQL_SYNTAX_ERROR"

    def test_detect_table_already_exists_error(self):
        """Detect table already exists errors."""
        error = Exception("Relation 'users' already exists")
        detected = _detect_error_context(error)
        assert detected == "TABLE_ALREADY_EXISTS"

    def test_detect_foreign_key_constraint_error(self):
        """Detect foreign key constraint violations."""
        error = Exception("Foreign key constraint violation")
        detected = _detect_error_context(error)
        assert detected == "FOREIGN_KEY_CONSTRAINT"

    def test_detect_disk_space_error(self):
        """Detect disk space exhaustion errors."""
        error = Exception("No space left on device")
        detected = _detect_error_context(error)
        assert detected == "INSUFFICIENT_DISK_SPACE"

    def test_detect_lock_timeout_error(self):
        """Detect lock timeout errors."""
        error = Exception("Lock timeout during migration")
        detected = _detect_error_context(error)
        assert detected == "LOCK_TIMEOUT"


class TestErrorContextFormatting:
    """Test error context formatting and output."""

    def test_format_error_with_context(self):
        """Verify error formatting includes all sections."""
        output = format_error_with_context("DB_CONNECTION_FAILED")
        assert "❌" in output
        assert "CAUSE:" in output
        assert "HOW TO FIX:" in output
        assert "EXAMPLES:" in output
        assert "LEARN MORE:" in output

    def test_format_error_includes_solutions(self):
        """Verify formatted error includes solutions."""
        output = format_error_with_context("DB_CONNECTION_FAILED")
        # Should include the actual solutions from the context
        assert "pg_isready" in output

    def test_format_error_includes_examples(self):
        """Verify formatted error includes examples."""
        output = format_error_with_context("DB_CONNECTION_FAILED")
        assert "confiture build" in output or "postgresql://" in output

    def test_format_error_includes_documentation_link(self):
        """Verify formatted error includes documentation link."""
        output = format_error_with_context("DB_CONNECTION_FAILED")
        assert "https://github.com/fraiseql/confiture/blob/main/docs/" in output

    def test_custom_message_override(self):
        """Test custom message override."""
        output = format_error_with_context(
            "DB_CONNECTION_FAILED",
            custom_message="Failed to connect to prod database"
        )
        assert "Failed to connect to prod database" in output
        assert "CAUSE:" in output

    def test_format_all_error_contexts(self):
        """Verify all error contexts can be formatted."""
        for code in ERROR_CONTEXTS.keys():
            output = format_error_with_context(code)
            assert "❌" in output
            assert "CAUSE:" in output
            assert "HOW TO FIX:" in output


class TestErrorContextIntegration:
    """Test integration of error context system."""

    def test_detect_and_format_pipeline(self):
        """Test full detect-and-format pipeline."""
        # Simulate a real error
        error = ConfigurationError("Cannot connect to PostgreSQL database")

        # Detect context
        context_code = _detect_error_context(error)
        assert context_code is not None

        # Format with context
        formatted = format_error_with_context(context_code, str(error))
        assert formatted
        assert "❌" in formatted
        assert "CAUSE:" in formatted

    def test_unknown_error_returns_none(self):
        """Verify unknown errors return None for context."""
        error = ValueError("Some random error")
        detected = _detect_error_context(error)
        assert detected is None

    def test_print_error_to_console_with_context(self, capsys):
        """Verify print_error_to_console integrates with error context."""
        # Note: This test verifies the function doesn't crash
        # In a real test we'd mock the console to verify output
        error = ConfigurationError("Cannot connect to PostgreSQL database")
        try:
            print_error_to_console(error)
        except Exception as e:
            pytest.fail(f"print_error_to_console raised: {e}")


class TestErrorContextCoverage:
    """Test coverage of common error scenarios."""

    def test_coverage_database_errors(self):
        """Verify database errors are covered."""
        errors_to_cover = [
            ("DB_CONNECTION_FAILED", "Cannot connect to database at PostgreSQL"),
            ("DB_PERMISSION_DENIED", "Database permission denied for user"),
        ]
        for expected_code, msg in errors_to_cover:
            error = ConfigurationError(msg)
            detected = _detect_error_context(error)
            assert detected == expected_code, f"Failed for: {msg}"

    def test_coverage_file_errors(self):
        """Verify file-related errors are covered."""
        errors_to_cover = [
            ("SEEDS_DIR_NOT_FOUND", "seed directory not found"),
            ("MIGRATIONS_DIR_NOT_FOUND", "migration directory"),
            ("SCHEMA_DIR_NOT_FOUND", "schema directory"),
        ]
        for expected_code, msg in errors_to_cover:
            error = FileNotFoundError(msg)
            detected = _detect_error_context(error)
            assert detected == expected_code, f"Failed for: {msg}"

    def test_coverage_migration_errors(self):
        """Verify migration-related errors are covered."""
        errors_to_cover = [
            ("MIGRATION_CONFLICT", "Multiple migrations"),
            ("SEED_VALIDATION_FAILED", "Seed validation"),
        ]
        for expected_code, msg in errors_to_cover:
            if expected_code == "MIGRATION_CONFLICT":
                error = MigrationConflictError(msg)
            else:
                error = SeedError(msg)
            detected = _detect_error_context(error)
            assert detected == expected_code, f"Failed for: {msg}"

    def test_coverage_sql_errors(self):
        """Verify SQL-related errors are covered."""
        errors_to_cover = [
            ("SQL_SYNTAX_ERROR", "syntax error"),
            ("TABLE_ALREADY_EXISTS", "table already exists"),
            ("FOREIGN_KEY_CONSTRAINT", "foreign key constraint"),
            ("INSUFFICIENT_DISK_SPACE", "no space left on device"),
            ("LOCK_TIMEOUT", "lock timeout"),
        ]
        for expected_code, msg in errors_to_cover:
            error = Exception(msg)
            detected = _detect_error_context(error)
            assert detected == expected_code, f"Failed for: {msg}"
