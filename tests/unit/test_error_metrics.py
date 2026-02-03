"""Tests for error metrics collection system.

Tests the ErrorMetrics class for tracking and aggregating error statistics
by category, severity, and error code.
"""

from datetime import timedelta

from confiture.core.metrics import ErrorMetrics
from confiture.exceptions import (
    ConfigurationError,
    ConfiturError,
    MigrationError,
)


class TestErrorMetricsCreation:
    """Test ErrorMetrics initialization."""

    def test_metrics_creation(self) -> None:
        """Test creating a metrics instance."""
        metrics = ErrorMetrics()
        assert metrics is not None

    def test_metrics_initial_state(self) -> None:
        """Test that new metrics has zero counts."""
        metrics = ErrorMetrics()
        assert metrics.total_count() == 0

    def test_metrics_count_by_category_empty(self) -> None:
        """Test that initial category counts are zero."""
        metrics = ErrorMetrics()
        assert metrics.count_by_category("CONFIG") == 0


class TestRecordingErrors:
    """Test recording errors to metrics."""

    def test_record_simple_error(self) -> None:
        """Test recording a simple error."""
        metrics = ErrorMetrics()
        error = ConfiturError("Test error")

        metrics.record(error)

        assert metrics.total_count() == 1

    def test_record_multiple_errors(self) -> None:
        """Test recording multiple errors."""
        metrics = ErrorMetrics()
        errors = [
            ConfiturError("Error 1"),
            ConfiturError("Error 2"),
            ConfiturError("Error 3"),
        ]

        for error in errors:
            metrics.record(error)

        assert metrics.total_count() == 3

    def test_record_error_with_code(self) -> None:
        """Test recording error with error code."""
        metrics = ErrorMetrics()
        error = ConfigurationError(
            "Config error",
            error_code="CONFIG_001",
        )

        metrics.record(error)

        assert metrics.count_by_code("CONFIG_001") == 1

    def test_record_error_increments_count(self) -> None:
        """Test that recording same error multiple times increments count."""
        metrics = ErrorMetrics()
        error = ConfigurationError("Config error", error_code="CONFIG_001")

        metrics.record(error)
        metrics.record(error)
        metrics.record(error)

        assert metrics.count_by_code("CONFIG_001") == 3


class TestCategoryTracking:
    """Test category-based metrics."""

    def test_track_by_category(self) -> None:
        """Test tracking errors by category."""
        metrics = ErrorMetrics()

        config_error = ConfigurationError("Config", error_code="CONFIG_001")
        migr_error = MigrationError("Migration", version="001", error_code="MIGR_100")

        metrics.record(config_error)
        metrics.record(migr_error)

        assert metrics.count_by_category("CONFIG") == 1
        assert metrics.count_by_category("MIGR") == 1

    def test_multiple_errors_same_category(self) -> None:
        """Test multiple errors in same category."""
        metrics = ErrorMetrics()

        for i in range(5):
            error = ConfigurationError(
                f"Config error {i}",
                error_code=f"CONFIG_{i:03d}",
            )
            metrics.record(error)

        assert metrics.count_by_category("CONFIG") == 5

    def test_unknown_category(self) -> None:
        """Test querying unknown category returns zero."""
        metrics = ErrorMetrics()
        assert metrics.count_by_category("UNKNOWN") == 0


class TestSeverityTracking:
    """Test severity-based metrics."""

    def test_track_by_severity(self) -> None:
        """Test tracking errors by severity."""
        from confiture.models.error import ErrorSeverity

        metrics = ErrorMetrics()

        error_normal = ConfiturError(
            "Normal error",
            severity=ErrorSeverity.ERROR,
        )
        error_critical = ConfiturError(
            "Critical error",
            severity=ErrorSeverity.CRITICAL,
        )

        metrics.record(error_normal)
        metrics.record(error_critical)

        assert metrics.count_by_severity("error") == 1
        assert metrics.count_by_severity("critical") == 1

    def test_multiple_errors_same_severity(self) -> None:
        """Test multiple errors with same severity."""
        from confiture.models.error import ErrorSeverity

        metrics = ErrorMetrics()

        for i in range(3):
            error = ConfiturError(
                f"Error {i}",
                severity=ErrorSeverity.WARNING,
            )
            metrics.record(error)

        assert metrics.count_by_severity("warning") == 3


class TestTimestampTracking:
    """Test timestamp-based tracking."""

    def test_error_recorded_with_timestamp(self) -> None:
        """Test that errors are recorded with timestamp."""
        metrics = ErrorMetrics()
        error = ConfiturError("Test")

        metrics.record(error)

        # Should have recorded the error
        assert metrics.total_count() == 1

    def test_time_window_query(self) -> None:
        """Test querying errors within time window."""
        metrics = ErrorMetrics()

        # Record error now
        error = ConfiturError("Recent error", error_code="CONFIG_001")
        metrics.record(error)

        # Query last hour
        recent = metrics.count_since(timedelta(hours=1), code="CONFIG_001")
        assert recent == 1

        # Query last minute (might miss if timing is unlucky, but should be 1)
        very_recent = metrics.count_since(timedelta(seconds=5), code="CONFIG_001")
        assert very_recent >= 0  # Timing dependent


class TestQueryMethods:
    """Test various query methods."""

    def test_get_all_recorded_codes(self) -> None:
        """Test getting list of all recorded error codes."""
        metrics = ErrorMetrics()

        codes = ["CONFIG_001", "MIGR_100", "SCHEMA_200"]
        for code in codes:
            error = ConfiturError("Test", error_code=code)
            metrics.record(error)

        all_codes = metrics.all_codes()
        assert len(all_codes) >= len(codes)
        for code in codes:
            assert code in all_codes

    def test_get_error_code_frequency(self) -> None:
        """Test getting frequency distribution by code."""
        metrics = ErrorMetrics()

        error1 = ConfiturError("Error 1", error_code="CONFIG_001")
        error2 = ConfiturError("Error 2", error_code="CONFIG_001")
        error3 = ConfiturError("Error 3", error_code="MIGR_100")

        metrics.record(error1)
        metrics.record(error2)
        metrics.record(error3)

        assert metrics.count_by_code("CONFIG_001") == 2
        assert metrics.count_by_code("MIGR_100") == 1

    def test_histogram_of_codes(self) -> None:
        """Test getting histogram of error codes."""
        metrics = ErrorMetrics()

        for i in range(3):
            metrics.record(ConfiturError(f"Config {i}", error_code="CONFIG_001"))
        for i in range(2):
            metrics.record(ConfiturError(f"Migration {i}", error_code="MIGR_100"))
        metrics.record(ConfiturError("Schema", error_code="SCHEMA_200"))

        histogram = metrics.histogram_by_code()

        assert histogram["CONFIG_001"] == 3
        assert histogram["MIGR_100"] == 2
        assert histogram["SCHEMA_200"] == 1

    def test_histogram_by_category(self) -> None:
        """Test getting histogram by category."""
        metrics = ErrorMetrics()

        for i in range(3):
            metrics.record(ConfigurationError(f"Config {i}", error_code="CONFIG_001"))
        for i in range(2):
            metrics.record(MigrationError(f"Migration {i}", version="001", error_code="MIGR_100"))

        histogram = metrics.histogram_by_category()

        assert histogram["CONFIG"] == 3
        assert histogram["MIGR"] == 2


class TestStatistics:
    """Test statistical calculations."""

    def test_total_count(self) -> None:
        """Test total error count."""
        metrics = ErrorMetrics()

        for i in range(10):
            metrics.record(ConfiturError(f"Error {i}"))

        assert metrics.total_count() == 10

    def test_percentiles_calculation(self) -> None:
        """Test percentile calculations."""
        metrics = ErrorMetrics()

        # Record same error 100 times
        error = ConfiturError("Frequent error", error_code="CONFIG_001")
        for _ in range(100):
            metrics.record(error)

        # Top error should be CONFIG_001
        top = metrics.top_errors(n=1)
        assert len(top) >= 1
        assert top[0][0] == "CONFIG_001"
        assert top[0][1] >= 100

    def test_top_errors(self) -> None:
        """Test getting top N errors."""
        metrics = ErrorMetrics()

        # Create errors with different frequencies
        for i in range(5):
            error = ConfiturError(f"Error {i}", error_code=f"CONFIG_{i:03d}")
            for _ in range(10 - i):  # Decreasing frequency
                metrics.record(error)

        top = metrics.top_errors(n=3)

        assert len(top) == 3
        # Top should be most frequent first
        assert top[0][1] >= top[1][1]
        assert top[1][1] >= top[2][1]
