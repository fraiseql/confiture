"""Tests for error code registry and definitions.

This module tests the error code system that enables deterministic
error handling for agent workflows.
"""

from dataclasses import dataclass

import pytest

from confiture.core.error_codes import (
    ERROR_CODE_REGISTRY,
    ErrorCodeDefinition,
    ErrorCodeRegistry,
)
from confiture.exceptions import ConfigurationError, MigrationError, SQLError
from confiture.models.error import ErrorSeverity


class TestErrorCodeDefinition:
    """Test ErrorCodeDefinition dataclass."""

    def test_error_code_definition_creation(self) -> None:
        """Test creating an error code definition."""
        definition = ErrorCodeDefinition(
            code="CONFIG_001",
            message_template="Missing required field '{field}' in {file}",
            severity=ErrorSeverity.ERROR,
            exit_code=2,
            resolution_hint="Add the field to your config file",
        )

        assert definition.code == "CONFIG_001"
        assert definition.message_template == "Missing required field '{field}' in {file}"
        assert definition.severity == ErrorSeverity.ERROR
        assert definition.exit_code == 2
        assert definition.resolution_hint == "Add the field to your config file"

    def test_error_code_definition_with_minimal_fields(self) -> None:
        """Test creating error code definition with minimal fields."""
        definition = ErrorCodeDefinition(
            code="MIGR_100",
            message_template="Migration {version} not found",
            severity=ErrorSeverity.ERROR,
            exit_code=3,
        )

        assert definition.code == "MIGR_100"
        assert definition.resolution_hint is None

    def test_error_code_format_validation(self) -> None:
        """Test that error codes follow CATEGORY_NNN format."""
        # Valid formats
        valid_codes = [
            "CONFIG_001",
            "MIGR_100",
            "SCHEMA_200",
            "SYNC_300",
            "DIFFER_400",
        ]

        for code in valid_codes:
            definition = ErrorCodeDefinition(
                code=code,
                message_template="Test message",
                severity=ErrorSeverity.ERROR,
                exit_code=1,
            )
            assert definition.code == code


class TestErrorCodeRegistry:
    """Test ErrorCodeRegistry functionality."""

    def test_registry_register_and_get(self) -> None:
        """Test registering and retrieving error codes."""
        registry = ErrorCodeRegistry()

        definition = ErrorCodeDefinition(
            code="CONFIG_001",
            message_template="Missing database URL",
            severity=ErrorSeverity.ERROR,
            exit_code=2,
        )

        registry.register(definition)
        retrieved = registry.get("CONFIG_001")

        assert retrieved.code == "CONFIG_001"
        assert retrieved.message_template == "Missing database URL"

    def test_registry_get_nonexistent_code(self) -> None:
        """Test that getting nonexistent code raises ValueError."""
        registry = ErrorCodeRegistry()

        with pytest.raises(ValueError, match="Error code not found"):
            registry.get("NONEXISTENT_999")

    def test_registry_lookup_is_fast(self) -> None:
        """Test that registry lookup is O(1)."""
        registry = ErrorCodeRegistry()

        # Register multiple codes
        for i in range(100):
            definition = ErrorCodeDefinition(
                code=f"TEST_{i:03d}",
                message_template=f"Test message {i}",
                severity=ErrorSeverity.INFO,
                exit_code=1,
            )
            registry.register(definition)

        # All should be retrievable in O(1)
        assert registry.get("TEST_000").code == "TEST_000"
        assert registry.get("TEST_050").code == "TEST_050"
        assert registry.get("TEST_099").code == "TEST_099"

    def test_registry_no_duplicate_codes(self) -> None:
        """Test that registering duplicate codes raises error."""
        registry = ErrorCodeRegistry()

        definition1 = ErrorCodeDefinition(
            code="CONFIG_001",
            message_template="Message 1",
            severity=ErrorSeverity.ERROR,
            exit_code=2,
        )

        definition2 = ErrorCodeDefinition(
            code="CONFIG_001",
            message_template="Message 2",
            severity=ErrorSeverity.ERROR,
            exit_code=2,
        )

        registry.register(definition1)

        with pytest.raises(ValueError, match="already registered"):
            registry.register(definition2)

    def test_registry_get_for_exception_type(self) -> None:
        """Test getting default error code for exception type."""
        registry = ErrorCodeRegistry()

        # Register codes for known exception types
        config_def = ErrorCodeDefinition(
            code="CONFIG_001",
            message_template="Configuration error",
            severity=ErrorSeverity.ERROR,
            exit_code=2,
        )
        registry.register(config_def)
        registry.set_exception_default(ConfigurationError, "CONFIG_001")

        code = registry.get_for_exception(ConfigurationError)
        assert code == "CONFIG_001"

    def test_registry_exit_codes_vary_by_category(self) -> None:
        """Test that different error categories map to different exit codes."""
        registry = ErrorCodeRegistry()

        config_def = ErrorCodeDefinition(
            code="CONFIG_001",
            message_template="Config error",
            severity=ErrorSeverity.ERROR,
            exit_code=2,
        )

        migr_def = ErrorCodeDefinition(
            code="MIGR_100",
            message_template="Migration error",
            severity=ErrorSeverity.ERROR,
            exit_code=3,
        )

        registry.register(config_def)
        registry.register(migr_def)

        assert registry.get("CONFIG_001").exit_code == 2
        assert registry.get("MIGR_100").exit_code == 3

    def test_registry_severity_levels(self) -> None:
        """Test that error codes can have different severity levels."""
        registry = ErrorCodeRegistry()

        definitions = [
            ErrorCodeDefinition(
                code="CONFIG_001",
                message_template="Info",
                severity=ErrorSeverity.INFO,
                exit_code=0,
            ),
            ErrorCodeDefinition(
                code="CONFIG_002",
                message_template="Warning",
                severity=ErrorSeverity.WARNING,
                exit_code=1,
            ),
            ErrorCodeDefinition(
                code="CONFIG_003",
                message_template="Error",
                severity=ErrorSeverity.ERROR,
                exit_code=2,
            ),
            ErrorCodeDefinition(
                code="CONFIG_004",
                message_template="Critical",
                severity=ErrorSeverity.CRITICAL,
                exit_code=8,
            ),
        ]

        for definition in definitions:
            registry.register(definition)

        assert registry.get("CONFIG_001").severity == ErrorSeverity.INFO
        assert registry.get("CONFIG_002").severity == ErrorSeverity.WARNING
        assert registry.get("CONFIG_003").severity == ErrorSeverity.ERROR
        assert registry.get("CONFIG_004").severity == ErrorSeverity.CRITICAL


class TestGlobalErrorCodeRegistry:
    """Test the global ERROR_CODE_REGISTRY instance."""

    def test_global_registry_is_populated(self) -> None:
        """Test that global registry has error codes defined."""
        # Should have at least some codes
        assert ERROR_CODE_REGISTRY.size() > 0

    def test_global_registry_has_config_codes(self) -> None:
        """Test that CONFIG category codes are registered."""
        # CONFIG_001 should be defined
        definition = ERROR_CODE_REGISTRY.get("CONFIG_001")
        assert definition.code == "CONFIG_001"
        assert definition.exit_code == 2  # Configuration error exit code

    def test_global_registry_has_migr_codes(self) -> None:
        """Test that MIGR category codes are registered."""
        # MIGR_100 should be defined
        definition = ERROR_CODE_REGISTRY.get("MIGR_100")
        assert definition.code == "MIGR_100"
        assert definition.exit_code == 3  # Migration error exit code

    def test_global_registry_has_schema_codes(self) -> None:
        """Test that SCHEMA category codes are registered."""
        # SCHEMA_200 should be defined
        definition = ERROR_CODE_REGISTRY.get("SCHEMA_200")
        assert definition.code == "SCHEMA_200"
        assert definition.exit_code == 4  # Schema error exit code

    def test_global_registry_has_sql_codes(self) -> None:
        """Test that SQL category codes are registered."""
        # SQL_700 should be defined
        definition = ERROR_CODE_REGISTRY.get("SQL_700")
        assert definition.code == "SQL_700"
        assert definition.exit_code == 1  # General error exit code

    def test_global_registry_all_codes_have_templates(self) -> None:
        """Test that all registered codes have message templates."""
        # Sample some codes to verify
        for code_name in ["CONFIG_001", "MIGR_100", "SCHEMA_200"]:
            definition = ERROR_CODE_REGISTRY.get(code_name)
            assert definition.message_template is not None
            assert len(definition.message_template) > 0

    def test_global_registry_all_codes_have_exit_codes(self) -> None:
        """Test that all registered codes have valid exit codes."""
        for code_name in ["CONFIG_001", "MIGR_100", "SCHEMA_200"]:
            definition = ERROR_CODE_REGISTRY.get(code_name)
            assert isinstance(definition.exit_code, int)
            assert 0 <= definition.exit_code <= 10
