"""Unit tests for strategy sandbox security."""

from unittest.mock import patch

import pytest

from confiture.core.anonymization.plugins.sandbox import (
    SandboxResult,
    SandboxViolationError,
    execute_sandboxed,
    load_strategy,
)
from confiture.core.anonymization.strategy import AnonymizationStrategy
from confiture.exceptions import ConfiturError


class TestStrategySandbox:
    """Test suite for strategy loading and execution sandbox."""

    def test_load_strategy_valid_file(self, tmp_path):
        """load_strategy() should successfully load a valid strategy file."""
        # Create a valid strategy file
        strategy_file = tmp_path / "valid_strategy.py"
        strategy_file.write_text("""
from confiture.core.anonymization.strategy import AnonymizationStrategy

class TestStrategy(AnonymizationStrategy):
    def anonymize(self, value):
        return f"anonymized_{value}"

    def validate(self, value):
        return isinstance(value, str)
""")

        # Load the strategy
        strategy_class = load_strategy(strategy_file)

        # Verify it's the right class
        assert strategy_class.__name__ == "TestStrategy"
        assert issubclass(strategy_class, AnonymizationStrategy)

        # Test instantiation and execution
        strategy = strategy_class()
        result = strategy.anonymize("test")
        assert result == "anonymized_test"

    def test_load_strategy_blocks_dangerous_imports(self, tmp_path):
        """load_strategy() should reject files with blocked imports."""
        # Create a strategy file with blocked import
        strategy_file = tmp_path / "dangerous_strategy.py"
        strategy_file.write_text("""
import os
from confiture.core.anonymization.strategy import AnonymizationStrategy

class DangerousStrategy(AnonymizationStrategy):
    def anonymize(self, value):
        return os.path.basename(value)
""")

        # Should raise SandboxViolationError
        with pytest.raises(SandboxViolationError) as exc_info:
            load_strategy(strategy_file)

        error = exc_info.value
        assert "os" in str(error)
        assert len(error.violations) == 1
        assert error.violations[0].module == "os"

    def test_load_strategy_requires_single_strategy_class(self, tmp_path):
        """load_strategy() should require exactly one strategy class per file."""
        # File with no strategy class
        empty_file = tmp_path / "empty.py"
        empty_file.write_text("import hashlib")

        with pytest.raises(ConfiturError):
            load_strategy(empty_file)

        # File with multiple strategy classes
        multi_file = tmp_path / "multi.py"
        multi_file.write_text("""
from confiture.core.anonymization.strategy import AnonymizationStrategy

class Strategy1(AnonymizationStrategy):
    def anonymize(self, value): return value

class Strategy2(AnonymizationStrategy):
    def anonymize(self, value): return value
""")

        with pytest.raises(ConfiturError):
            load_strategy(multi_file)

    def test_execute_sandboxed_captures_timing(self):
        """execute_sandboxed() should capture execution timing."""
        from confiture.core.anonymization.strategies.preserve import PreserveStrategy

        strategy = PreserveStrategy()
        result = execute_sandboxed(strategy, "test_value")

        assert isinstance(result, SandboxResult)
        assert result.value == "test_value"  # Preserve returns unchanged
        assert result.duration_ms >= 0
        assert result.strategy_name == "PreserveStrategy"

    def test_execute_sandboxed_logs_exceptions(self, caplog):
        """execute_sandboxed() should log exceptions during execution."""
        from confiture.core.anonymization.strategy import AnonymizationStrategy

        class FailingStrategy(AnonymizationStrategy):
            def anonymize(self, value):
                raise ValueError("Test error")

            def validate(self, value):
                return True

        strategy = FailingStrategy()

        with pytest.raises(ValueError, match="Test error"):
            execute_sandboxed(strategy, "test")

        # Check that warning was logged
        assert "failed after" in caplog.text
        assert "FailingStrategy" in caplog.text

    def test_execute_sandboxed_timeout_logging(self):
        """execute_sandboxed() should log when execution exceeds timeout."""
        from confiture.core.anonymization.strategy import AnonymizationStrategy

        class SlowStrategy(AnonymizationStrategy):
            def anonymize(self, value):
                import time

                time.sleep(0.01)  # 10ms, over default 5ms timeout
                return value

            def validate(self, value):
                return True

        strategy = SlowStrategy()

        with patch("confiture.core.anonymization.plugins.sandbox.logger") as mock_logger:
            execute_sandboxed(strategy, "test", timeout_s=0.005)  # 5ms timeout

            # Should log warning about timeout
            mock_logger.warning.assert_called_once()
            call_args = mock_logger.warning.call_args[0]
            assert "exceeded timeout" in call_args[0]
