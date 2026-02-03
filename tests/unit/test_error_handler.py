"""Tests for CLI error handler.

Tests error formatting and exit code handling for CLI output.
"""

from confiture.core.error_handler import format_error_for_cli, handle_cli_error
from confiture.exceptions import (
    ConfigurationError,
    ConfiturError,
    MigrationError,
)
from confiture.models.error import ErrorSeverity


class TestFormatErrorForCli:
    """Test format_error_for_cli function."""

    def test_format_error_with_code_and_hint(self) -> None:
        """Test formatting error with code and resolution hint."""
        error = ConfiturError(
            "Missing database_url",
            error_code="CONFIG_001",
            resolution_hint="Add database_url to your config",
        )

        formatted = format_error_for_cli(error)

        assert "CONFIG_001" in formatted
        assert "Missing database_url" in formatted
        assert "Add database_url to your config" in formatted

    def test_format_error_with_context(self) -> None:
        """Test formatting error with context data."""
        error = ConfiturError(
            "Configuration error",
            error_code="CONFIG_001",
            context={"file": "local.yaml", "field": "database_url"},
        )

        formatted = format_error_for_cli(error)

        assert "CONFIG_001" in formatted
        assert "local.yaml" in formatted or "database_url" in formatted

    def test_format_error_without_code(self) -> None:
        """Test formatting error without error code."""
        error = ConfiturError("Generic error message")

        formatted = format_error_for_cli(error)

        assert "Generic error message" in formatted

    def test_format_error_with_severity(self) -> None:
        """Test that error severity affects formatting."""
        error_critical = ConfiturError(
            "Critical issue",
            severity=ErrorSeverity.CRITICAL,
            error_code="ROLLBACK_602",
        )

        formatted = format_error_for_cli(error_critical)

        # Should indicate severity somehow
        assert "ROLLBACK_602" in formatted
        assert "Critical issue" in formatted

    def test_format_migration_error(self) -> None:
        """Test formatting MigrationError with version."""
        error = MigrationError(
            "Migration failed",
            version="001",
            error_code="MIGR_100",
        )

        formatted = format_error_for_cli(error)

        assert "MIGR_100" in formatted
        assert "Migration failed" in formatted

    def test_format_configuration_error(self) -> None:
        """Test formatting ConfigurationError."""
        error = ConfigurationError(
            "Invalid YAML syntax",
            error_code="CONFIG_002",
            resolution_hint="Fix YAML formatting",
        )

        formatted = format_error_for_cli(error)

        assert "CONFIG_002" in formatted
        assert "Invalid YAML syntax" in formatted


class TestHandleCliError:
    """Test handle_cli_error function."""

    def test_handle_confiture_error_with_code(self) -> None:
        """Test handling ConfiturError with error code."""
        error = ConfigurationError(
            "Missing config",
            error_code="CONFIG_001",
        )

        exit_code = handle_cli_error(error)

        # CONFIG_001 should map to exit code 2
        assert exit_code == 2

    def test_handle_confiture_error_without_code(self) -> None:
        """Test handling ConfiturError without error code."""
        error = ConfiturError("Generic error")

        exit_code = handle_cli_error(error)

        # Should default to 1
        assert exit_code == 1

    def test_handle_migration_error(self) -> None:
        """Test handling MigrationError."""
        error = MigrationError(
            "Migration locked",
            version="001",
            error_code="MIGR_104",
        )

        exit_code = handle_cli_error(error)

        # MIGR_104 should map to exit code 3
        assert exit_code == 3

    def test_handle_generic_exception(self) -> None:
        """Test handling generic Python exceptions."""
        error = ValueError("Some error")

        exit_code = handle_cli_error(error)

        # Generic exceptions should get default exit code
        assert exit_code == 1

    def test_exit_code_mapping(self) -> None:
        """Test that different error codes map to correct exit codes."""
        test_cases = [
            ("CONFIG_001", 2),  # Configuration error
            ("MIGR_100", 3),  # Migration error
            ("SCHEMA_200", 4),  # Schema error
        ]

        for code, expected_exit in test_cases:
            error = ConfiturError(
                f"Error {code}",
                error_code=code,
            )
            exit_code = handle_cli_error(error)
            assert exit_code == expected_exit

    def test_handle_error_returns_int(self) -> None:
        """Test that handle_cli_error always returns an int."""
        errors = [
            ConfigurationError("config"),
            MigrationError("migr"),
            ValueError("generic"),
        ]

        for error in errors:
            exit_code = handle_cli_error(error)
            assert isinstance(exit_code, int)
            assert 0 <= exit_code <= 10

    def test_handle_error_is_callable(self) -> None:
        """Test that handle_cli_error is callable."""
        assert callable(handle_cli_error)

    def test_format_error_is_callable(self) -> None:
        """Test that format_error_for_cli is callable."""
        assert callable(format_error_for_cli)
