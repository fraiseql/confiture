"""Unit tests for registry plugin integration."""

import pytest

from confiture.core.anonymization.registry import StrategyRegistry


class TestRegistryPlugins:
    """Test suite for registry integration with sandboxed plugins."""

    def test_register_from_file_loads_and_registers_valid_strategy(self, tmp_path):
        """register_from_file() should load and register a valid strategy file."""
        # Create a valid strategy file
        strategy_file = tmp_path / "test_strategy.py"
        strategy_file.write_text("""
from confiture.core.anonymization.strategy import AnonymizationStrategy

class TestCustomStrategy(AnonymizationStrategy):
    def anonymize(self, value):
        return f"custom_{value}"

    def validate(self, value):
        return isinstance(value, str)
""")

        # Register from file
        name = StrategyRegistry.register_from_file(str(strategy_file))

        # Verify registration
        assert name == "TestCustomStrategy"
        assert StrategyRegistry.is_registered(name)

        # Verify strategy works
        strategy = StrategyRegistry.get(name)
        assert strategy.anonymize("test") == "custom_test"

    def test_register_from_file_rejects_file_with_blocked_imports(self, tmp_path):
        """register_from_file() should reject files with blocked imports."""
        # Create a strategy file with blocked import
        strategy_file = tmp_path / "dangerous_strategy.py"
        strategy_file.write_text("""
import os
from confiture.core.anonymization.strategy import AnonymizationStrategy

class DangerousStrategy(AnonymizationStrategy):
    def anonymize(self, value):
        return os.path.basename(value)

    def validate(self, value):
        return True
""")

        # Should raise SandboxViolationError
        from confiture.core.anonymization.plugins.sandbox import SandboxViolationError

        with pytest.raises(SandboxViolationError):
            StrategyRegistry.register_from_file(str(strategy_file))

    def test_register_from_file_requires_valid_strategy_class(self, tmp_path):
        """register_from_file() should require a valid strategy class."""
        # File with no strategy class
        empty_file = tmp_path / "empty.py"
        empty_file.write_text("import hashlib")

        from confiture.exceptions import ConfiturError

        with pytest.raises(ConfiturError):
            StrategyRegistry.register_from_file(str(empty_file))

    def setup_method(self):
        """Reset registry before each test."""
        StrategyRegistry.reset()

    def teardown_method(self):
        """Reset registry after each test."""
        StrategyRegistry.reset()
