"""Tests for error recovery workflows by category.

Tests recovery strategies for each error code category.
"""

import pytest

from confiture.workflows.recovery import (
    RecoveryHandler,
    RecoveryAction,
    get_recovery_handler,
)
from confiture.exceptions import ConfigurationError, MigrationError


class TestRecoveryAction:
    """Test RecoveryAction enum."""

    def test_recovery_actions_exist(self) -> None:
        """Test that recovery actions are defined."""
        assert hasattr(RecoveryAction, "RETRY")
        assert hasattr(RecoveryAction, "ABORT")
        assert hasattr(RecoveryAction, "MANUAL")
        assert hasattr(RecoveryAction, "HEAL")


class TestRecoveryHandler:
    """Test RecoveryHandler base class."""

    def test_handler_creation(self) -> None:
        """Test creating recovery handler."""
        handler = RecoveryHandler("CONFIG_001")
        assert handler.error_code == "CONFIG_001"

    def test_handler_decide(self) -> None:
        """Test deciding recovery action."""
        handler = RecoveryHandler("CONFIG_001")
        action = handler.decide()
        assert action in RecoveryAction


class TestConfigurationErrorRecovery:
    """Test recovery for configuration errors."""

    def test_recover_from_missing_config(self) -> None:
        """Test recovery from CONFIG_001."""
        error = ConfigurationError("Missing config", error_code="CONFIG_001")
        handler = get_recovery_handler(error)

        assert handler is not None
        action = handler.decide()
        assert action in [RecoveryAction.MANUAL, RecoveryAction.RETRY]

    def test_recover_from_invalid_yaml(self) -> None:
        """Test recovery from CONFIG_002."""
        error = ConfigurationError("Invalid YAML", error_code="CONFIG_002")
        handler = get_recovery_handler(error)

        assert handler is not None
        assert handler.error_code == "CONFIG_002"


class TestMigrationErrorRecovery:
    """Test recovery for migration errors."""

    def test_recover_from_migration_locked(self) -> None:
        """Test recovery from MIGR_104."""
        error = MigrationError(
            "Migration locked",
            version="001",
            error_code="MIGR_104",
        )
        handler = get_recovery_handler(error)

        assert handler is not None
        action = handler.decide()
        assert action in [RecoveryAction.RETRY, RecoveryAction.MANUAL]

    def test_recover_from_migration_not_found(self) -> None:
        """Test recovery from MIGR_100."""
        error = MigrationError(
            "Migration not found",
            version="999",
            error_code="MIGR_100",
        )
        handler = get_recovery_handler(error)

        assert handler is not None
        assert handler.error_code == "MIGR_100"


class TestRecoveryRegistry:
    """Test recovery handler registry."""

    def test_get_handler_for_known_code(self) -> None:
        """Test getting handler for known error code."""
        error = ConfigurationError("test", error_code="CONFIG_001")
        handler = get_recovery_handler(error)

        assert handler is not None

    def test_handler_without_code_returns_default(self) -> None:
        """Test getting handler for error without code."""
        error = ConfigurationError("test")
        handler = get_recovery_handler(error)

        # Should get default handler
        assert handler is not None
