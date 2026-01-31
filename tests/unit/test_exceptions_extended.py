"""Tests for extended ConfiturError with error code support.

Tests backward compatibility and new error code functionality.
"""

import pytest

from confiture.exceptions import (
    ConfigurationError,
    ConfiturError,
    MigrationError,
    SQLError,
)
from confiture.models.error import ErrorSeverity


class TestConfiturErrorBackwardCompatibility:
    """Test that ConfiturError maintains backward compatibility."""

    def test_exception_raise_with_message(self) -> None:
        """Test raising exception with just a message."""
        with pytest.raises(ConfiturError, match="Test error"):
            raise ConfiturError("Test error")

    def test_exception_catch_by_type(self) -> None:
        """Test catching exception by type."""
        try:
            raise ConfigurationError("Config error")
        except ConfiturError as e:
            assert str(e) == "Config error"

    def test_exception_subclass_instantiation(self) -> None:
        """Test that all exception subclasses work."""
        errors = [
            ConfigurationError("config"),
            MigrationError("migration"),
            SQLError("SELECT 1", None, Exception("db error")),
        ]

        for error in errors:
            assert isinstance(error, ConfiturError)
            assert isinstance(error, Exception)


class TestConfiturErrorNewFunctionality:
    """Test new error code functionality."""

    def test_error_code_parameter(self) -> None:
        """Test setting error code via keyword parameter."""
        error = ConfiturError(
            "Test message",
            error_code="CONFIG_001",
        )

        assert error.error_code == "CONFIG_001"
        assert str(error) == "Test message"

    def test_severity_parameter(self) -> None:
        """Test setting severity via keyword parameter."""
        error = ConfiturError(
            "Test message",
            severity=ErrorSeverity.CRITICAL,
        )

        assert error.severity == ErrorSeverity.CRITICAL

    def test_context_parameter(self) -> None:
        """Test setting context via keyword parameter."""
        context = {"file": "config.yaml", "field": "database_url"}
        error = ConfiturError(
            "Test message",
            context=context,
        )

        assert error.context == context

    def test_resolution_hint_parameter(self) -> None:
        """Test setting resolution hint via keyword parameter."""
        error = ConfiturError(
            "Test message",
            resolution_hint="Add database_url to config",
        )

        assert error.resolution_hint == "Add database_url to config"

    def test_all_new_parameters(self) -> None:
        """Test setting all new parameters at once."""
        error = ConfiturError(
            "Complete error",
            error_code="CONFIG_001",
            severity=ErrorSeverity.ERROR,
            context={"file": "local.yaml"},
            resolution_hint="Fix the config",
        )

        assert error.error_code == "CONFIG_001"
        assert error.severity == ErrorSeverity.ERROR
        assert error.context == {"file": "local.yaml"}
        assert error.resolution_hint == "Fix the config"

    def test_default_severity(self) -> None:
        """Test that default severity is ERROR."""
        error = ConfiturError("Test")
        assert error.severity == ErrorSeverity.ERROR

    def test_default_context(self) -> None:
        """Test that default context is empty dict."""
        error = ConfiturError("Test")
        assert error.context == {}

    def test_default_error_code(self) -> None:
        """Test that default error code is None."""
        error = ConfiturError("Test")
        assert error.error_code is None

    def test_default_resolution_hint(self) -> None:
        """Test that default resolution hint is None."""
        error = ConfiturError("Test")
        assert error.resolution_hint is None


class TestConfiturErrorToDict:
    """Test to_dict() method for JSON serialization."""

    def test_to_dict_with_all_fields(self) -> None:
        """Test to_dict() with all fields populated."""
        error = ConfiturError(
            "Test error message",
            error_code="CONFIG_001",
            severity=ErrorSeverity.ERROR,
            context={"file": "config.yaml"},
            resolution_hint="Add missing field",
        )

        error_dict = error.to_dict()

        assert error_dict["error_code"] == "CONFIG_001"
        assert error_dict["severity"] == "error"
        assert error_dict["message"] == "Test error message"
        assert error_dict["context"] == {"file": "config.yaml"}
        assert error_dict["resolution_hint"] == "Add missing field"

    def test_to_dict_with_defaults(self) -> None:
        """Test to_dict() with default values."""
        error = ConfiturError("Test")

        error_dict = error.to_dict()

        assert error_dict["error_code"] is None
        assert error_dict["severity"] == "error"  # Default
        assert error_dict["message"] == "Test"
        assert error_dict["context"] == {}  # Default empty dict
        assert error_dict["resolution_hint"] is None


class TestMigrationErrorBackwardCompatibility:
    """Test that MigrationError maintains backward compatibility."""

    def test_migration_error_version_attribute(self) -> None:
        """Test that MigrationError.version is preserved."""
        error = MigrationError("Migration failed", version="001")
        assert error.version == "001"

    def test_migration_error_migration_name_attribute(self) -> None:
        """Test that MigrationError.migration_name is preserved."""
        error = MigrationError(
            "Migration failed",
            migration_name="add_users_table",
        )
        assert error.migration_name == "add_users_table"

    def test_migration_error_both_attributes(self) -> None:
        """Test that both version and migration_name work together."""
        error = MigrationError(
            "Migration failed",
            version="001",
            migration_name="add_users_table",
        )

        assert error.version == "001"
        assert error.migration_name == "add_users_table"

    def test_migration_error_with_error_code(self) -> None:
        """Test that MigrationError can also use error codes."""
        error = MigrationError(
            "Migration failed",
            version="001",
            error_code="MIGR_100",
        )

        assert error.version == "001"
        assert error.error_code == "MIGR_100"


class TestSQLErrorBackwardCompatibility:
    """Test that SQLError maintains backward compatibility."""

    def test_sql_error_attributes(self) -> None:
        """Test that SQLError attributes are preserved."""
        original_error = Exception("database error")
        error = SQLError(
            "SELECT * FROM users",
            ("param1", "param2"),
            original_error,
        )

        assert error.sql == "SELECT * FROM users"
        assert error.params == ("param1", "param2")
        assert error.original_error is original_error

    def test_sql_error_message_construction(self) -> None:
        """Test that SQLError constructs detailed message."""
        original_error = Exception("constraint violation")
        error = SQLError(
            "CREATE TABLE users (id INT PRIMARY KEY)",
            None,
            original_error,
        )

        # Message should contain SQL preview and error
        message = str(error)
        assert "SQL execution failed" in message
        assert "CREATE TABLE" in message
        assert "constraint violation" in message

    def test_sql_error_with_long_sql(self) -> None:
        """Test that long SQL statements are truncated in message."""
        long_sql = "SELECT " + ", ".join([f"col{i}" for i in range(50)])
        error = SQLError(long_sql, None, Exception("error"))

        message = str(error)
        assert len(message) < len(long_sql)  # Truncated
        assert "..." in message  # Shows it's truncated

    def test_sql_error_with_error_code(self) -> None:
        """Test that SQLError can use error codes."""
        error = SQLError(
            "SELECT 1",
            None,
            Exception("db error"),
            error_code="SQL_700",
        )

        assert error.sql == "SELECT 1"
        assert error.error_code == "SQL_700"
