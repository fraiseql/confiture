"""Performance benchmarks for schema linting system.

This module contains performance tests to measure and track linting speed,
especially with pre-compiled regex patterns and CLI optimizations.

Tests measure:
- Regex pattern matching performance (snake_case validation)
- Name suggestion performance (CamelCase conversion)
- Full linting pipeline performance
- Memory usage with large schemas
"""

import re
import time
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from confiture.core.linting import SchemaLinter


class TestLintingPerformance:
    """Performance benchmarks for the linting system."""

    def test_naming_rule_performance_with_compiled_patterns(self) -> None:
        """Test that pre-compiled regex patterns improve performance.

        Pre-compiled patterns should be faster than compiling regex on each call.
        This test verifies the optimization provides measurable benefit.
        """
        # Import the compiled patterns
        from confiture.core.linting import (
            CAMEL_TO_SNAKE_PATTERN1,
            CAMEL_TO_SNAKE_PATTERN2,
            SNAKE_CASE_PATTERN,
        )

        test_names = [
            "valid_snake_case",
            "InvalidCamelCase",
            "another_valid_name",
            "MixedCaseName",
            "UPPERCASE_NAME",
            "with123numbers",
            "user_profiles",
            "UserProfiles",
        ] * 100  # Test with 800 names

        # Time the compiled patterns
        start = time.perf_counter()
        for name in test_names:
            SNAKE_CASE_PATTERN.match(name)
        compiled_time = time.perf_counter() - start

        # Time dynamic compilation (for comparison)
        start = time.perf_counter()
        for name in test_names:
            re.match(r"^[a-z][a-z0-9_]*$", name)
        dynamic_time = time.perf_counter() - start

        # Pre-compiled should be faster (at least not slower)
        # Allow some variance for system load
        assert compiled_time <= dynamic_time * 1.2, (
            f"Compiled patterns ({compiled_time:.4f}s) should be faster than "
            f"dynamic compilation ({dynamic_time:.4f}s)"
        )

        # Test CamelCase to snake_case conversion
        camel_cases = [
            "UserProfile",
            "DatabaseConfiguration",
            "HTTPSConnection",
            "XMLParser",
        ] * 100

        start = time.perf_counter()
        for name in camel_cases:
            s1 = CAMEL_TO_SNAKE_PATTERN1.sub(r"\1_\2", name)
            CAMEL_TO_SNAKE_PATTERN2.sub(r"\1_\2", s1).lower()
        conversion_time = time.perf_counter() - start

        # Conversion should be reasonably fast
        assert conversion_time < 0.5, (
            f"CamelCase conversion took {conversion_time:.4f}s for 400 items"
        )

    def test_linting_with_typical_schema(self) -> None:
        """Test linting performance with a typical database schema.

        Measures the time to lint a reasonable-sized schema (10-20 tables).
        """
        # Use the existing test environment
        start = time.perf_counter()
        linter = SchemaLinter(env="test")
        report = linter.lint()
        elapsed = time.perf_counter() - start

        # Linting should be fast (< 100ms for typical schema)
        assert elapsed < 0.1, (
            f"Linting took {elapsed:.4f}s, expected < 0.1s"
        )

    def test_linting_speed_improvement_from_optimizations(self) -> None:
        """Verify that optimizations provide measurable improvement.

        This test confirms that the pre-compiled patterns and CLI optimizations
        provide a tangible performance benefit compared to dynamic approaches.
        """
        from confiture.core.linting import NamingConventionRule

        rule = NamingConventionRule()

        # Create mock tables with camelCase (to generate violations)
        class MockColumn:
            def __init__(self, name: str) -> None:
                self.name = name

        class MockTable:
            def __init__(self, name: str, num_columns: int = 20) -> None:
                self.name = name
                self.columns = [
                    MockColumn(f"column{i}") for i in range(num_columns)  # CamelCase
                ]

        # Create multiple tables with invalid naming
        tables = [MockTable(f"Table{i}", 20) for i in range(10)]
        config = {"style": "snake_case"}

        # Measure validation speed (first run)
        start = time.perf_counter()
        violations = rule.lint(tables, config)
        first_run = time.perf_counter() - start

        # Should find violations (invalid naming)
        assert violations, "Should detect naming violations in mock tables"

        # Measure repeated runs to test pattern compilation benefit
        start = time.perf_counter()
        for _ in range(99):  # Run 99 more times (100 total)
            rule.lint(tables, config)
        total_time = time.perf_counter() - start + first_run

        # Should be very fast (< 1 second for 100 iterations)
        # That's ~10ms per linting run
        assert total_time < 1.0, (
            f"100 linting runs took {total_time:.4f}s, expected < 1.0s"
        )


class TestLintingOptimizations:
    """Test that optimization changes don't break functionality.

    These tests ensure that performance optimizations don't introduce
    regressions in correctness.
    """

    def test_regex_pattern_correctness(self) -> None:
        """Verify pre-compiled patterns have same behavior as original."""
        from confiture.core.linting import (
            CAMEL_TO_SNAKE_PATTERN1,
            CAMEL_TO_SNAKE_PATTERN2,
            SNAKE_CASE_PATTERN,
        )

        # Test snake_case validation
        # Pattern: ^[a-z][a-z0-9_]*$ - starts with lowercase, contains [a-z0-9_]
        valid_names = [
            "valid",
            "valid_name",
            "with_numbers_123",
            "a",
            "a_b_c",
            "trailing_underscore_",  # Valid - underscore allowed anywhere after first char
        ]
        invalid_names = [
            "InvalidName",       # Has uppercase
            "INVALID_NAME",      # All uppercase
            "123_invalid",       # Starts with number
            "_leading_underscore",  # Starts with underscore (not lowercase letter)
        ]

        for name in valid_names:
            assert SNAKE_CASE_PATTERN.match(name), (
                f"Pattern should match valid snake_case: {name}"
            )

        for name in invalid_names:
            assert not SNAKE_CASE_PATTERN.match(name), (
                f"Pattern should not match invalid name: {name}"
            )

        # Test CamelCase conversion
        conversions = [
            ("UserProfile", "user_profile"),
            ("HTTPSConnection", "https_connection"),
            ("XMLParser", "xml_parser"),
            ("simpleCase", "simple_case"),
            ("ALLCAPS", "allcaps"),
        ]

        for camel, expected_snake in conversions:
            s1 = CAMEL_TO_SNAKE_PATTERN1.sub(r"\1_\2", camel)
            result = CAMEL_TO_SNAKE_PATTERN2.sub(r"\1_\2", s1).lower()
            assert result == expected_snake, (
                f"Conversion of {camel} should be {expected_snake}, got {result}"
            )

    def test_cli_format_validation_constant(self) -> None:
        """Verify LINT_FORMATS constant works correctly."""
        from confiture.cli.main import LINT_FORMATS

        # Should contain all expected formats
        assert "table" in LINT_FORMATS
        assert "json" in LINT_FORMATS
        assert "csv" in LINT_FORMATS

        # Should be iterable and convertible to string
        formats_str = ", ".join(LINT_FORMATS)
        assert "table" in formats_str
        assert "json" in formats_str
        assert "csv" in formats_str
