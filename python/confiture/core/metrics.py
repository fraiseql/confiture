"""Error metrics collection and aggregation.

This module provides ErrorMetrics for tracking and analyzing error patterns,
frequency distributions, and statistics.
"""

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from confiture.exceptions import ConfiturError


class ErrorRecord:
    """A single recorded error with timestamp."""

    def __init__(self, error: Exception) -> None:
        """Initialize error record.

        Args:
            error: The exception that was recorded
        """
        self.error = error
        self.timestamp = datetime.utcnow()
        self.code = error.error_code if isinstance(error, ConfiturError) else None
        self.category = self.code.split("_")[0] if self.code else "UNKNOWN"
        self.severity = error.severity.value if isinstance(error, ConfiturError) else "error"


class ErrorMetrics:
    """Track and analyze error metrics.

    Maintains statistics on errors by code, category, severity, and time.

    Example:
        >>> metrics = ErrorMetrics()
        >>> error = ConfigurationError("Missing config", error_code="CONFIG_001")
        >>> metrics.record(error)
        >>> metrics.count_by_code("CONFIG_001")
        1
    """

    def __init__(self) -> None:
        """Initialize error metrics."""
        self.records: list[ErrorRecord] = []
        self._code_counts: dict[str, int] = defaultdict(int)
        self._category_counts: dict[str, int] = defaultdict(int)
        self._severity_counts: dict[str, int] = defaultdict(int)

    def record(self, error: Exception) -> None:
        """Record an error occurrence.

        Args:
            error: The exception to record
        """
        record = ErrorRecord(error)
        self.records.append(record)

        # Update counts
        if record.code:
            self._code_counts[record.code] += 1
        self._category_counts[record.category] += 1
        self._severity_counts[record.severity] += 1

    def total_count(self) -> int:
        """Get total number of recorded errors.

        Returns:
            Total error count
        """
        return len(self.records)

    def count_by_code(self, code: str) -> int:
        """Get count for a specific error code.

        Args:
            code: Error code (e.g., "CONFIG_001")

        Returns:
            Number of times this code was recorded
        """
        return self._code_counts.get(code, 0)

    def count_by_category(self, category: str) -> int:
        """Get count for a category.

        Args:
            category: Category name (e.g., "CONFIG", "MIGR")

        Returns:
            Number of errors in this category
        """
        return self._category_counts.get(category, 0)

    def count_by_severity(self, severity: str) -> int:
        """Get count for a severity level.

        Args:
            severity: Severity name (e.g., "error", "warning")

        Returns:
            Number of errors with this severity
        """
        return self._severity_counts.get(severity, 0)

    def count_since(
        self,
        time_window: timedelta,
        code: str | None = None,
        category: str | None = None,
    ) -> int:
        """Count errors recorded within a time window.

        Args:
            time_window: How far back to look (e.g., timedelta(hours=1))
            code: Optional specific code to filter by
            category: Optional specific category to filter by

        Returns:
            Count of errors matching criteria
        """
        cutoff = datetime.utcnow() - time_window
        count = 0

        for record in self.records:
            if record.timestamp < cutoff:
                continue

            if code and record.code != code:
                continue

            if category and record.category != category:
                continue

            count += 1

        return count

    def all_codes(self) -> list[str]:
        """Get list of all recorded error codes.

        Returns:
            List of unique error codes
        """
        return sorted(self._code_counts.keys())

    def histogram_by_code(self) -> dict[str, int]:
        """Get frequency distribution by code.

        Returns:
            Dict mapping code to count, sorted by frequency descending
        """
        return dict(sorted(self._code_counts.items(), key=lambda x: x[1], reverse=True))

    def histogram_by_category(self) -> dict[str, int]:
        """Get frequency distribution by category.

        Returns:
            Dict mapping category to count, sorted by frequency descending
        """
        return dict(
            sorted(
                self._category_counts.items(),
                key=lambda x: x[1],
                reverse=True,
            )
        )

    def histogram_by_severity(self) -> dict[str, int]:
        """Get frequency distribution by severity.

        Returns:
            Dict mapping severity to count
        """
        return dict(sorted(self._severity_counts.items()))

    def top_errors(self, n: int = 10) -> list[tuple[str, int]]:
        """Get top N most frequent errors.

        Args:
            n: Number of top errors to return

        Returns:
            List of (code, count) tuples in descending frequency order
        """
        histogram = self.histogram_by_code()
        return list(histogram.items())[:n]

    def top_categories(self, n: int = 10) -> list[tuple[str, int]]:
        """Get top N most frequent categories.

        Args:
            n: Number of top categories to return

        Returns:
            List of (category, count) tuples in descending frequency order
        """
        histogram = self.histogram_by_category()
        return list(histogram.items())[:n]

    def summary(self) -> dict[str, Any]:
        """Get summary statistics.

        Returns:
            Dict with total count, top errors, top categories
        """
        return {
            "total": self.total_count(),
            "top_errors": self.top_errors(n=5),
            "top_categories": self.top_categories(n=5),
            "all_codes": len(self.all_codes()),
        }
