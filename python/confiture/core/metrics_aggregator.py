"""Metrics aggregation and query API.

Provides MetricsAggregator for querying, filtering, and exporting
error metrics with support for time windows and statistical analysis.
"""

import json
from datetime import datetime, timedelta
from typing import Any

from confiture.core.metrics import ErrorMetrics


class MetricsAggregator:
    """Query and aggregate error metrics.

    Builds on ErrorMetrics to provide filtering, time-windowing,
    and export capabilities.

    Example:
        >>> metrics = ErrorMetrics()
        >>> metrics.record(error)
        >>> agg = MetricsAggregator(metrics)
        >>> top_5 = agg.top_by_code(n=5)
    """

    def __init__(self, metrics: ErrorMetrics) -> None:
        """Initialize aggregator with metrics.

        Args:
            metrics: ErrorMetrics instance to query
        """
        self.metrics = metrics

    def query(
        self,
        code: str | None = None,
        category: str | None = None,
        severity: str | None = None,
        time_window: timedelta | None = None,
    ) -> dict[str, Any]:
        """Query metrics with filters.

        Args:
            code: Filter by error code
            category: Filter by category
            severity: Filter by severity
            time_window: Filter by time (last N time)

        Returns:
            Dict with matching error counts
        """
        result: dict[str, Any] = {
            "filters": {
                "code": code,
                "category": category,
                "severity": severity,
                "time_window": str(time_window) if time_window else None,
            },
            "results": {},
        }

        # Simple filter implementation
        if time_window:
            count = self.metrics.count_since(
                time_window, code=code, category=category
            )
            result["results"]["count"] = count
        else:
            if code:
                result["results"]["count"] = self.metrics.count_by_code(code)
            elif category:
                result["results"]["count"] = self.metrics.count_by_category(category)
            elif severity:
                result["results"]["count"] = self.metrics.count_by_severity(severity)
            else:
                result["results"]["count"] = self.metrics.total_count()

        return result

    def top_by_code(self, n: int = 10) -> list[tuple[str, int]]:
        """Get top N codes by frequency.

        Args:
            n: Number of results

        Returns:
            List of (code, count) tuples
        """
        return self.metrics.top_errors(n=n)

    def top_by_category(self, n: int = 10) -> list[tuple[str, int]]:
        """Get top N categories by frequency.

        Args:
            n: Number of results

        Returns:
            List of (category, count) tuples
        """
        return self.metrics.top_categories(n=n)

    def percentiles(self, *percentiles: int) -> dict[int, int]:
        """Get error counts at percentiles.

        This is a simplified version - in production would use
        proper percentile calculation.

        Args:
            percentiles: Percentile values (e.g., 50, 95, 99)

        Returns:
            Dict mapping percentile to count
        """
        total = self.metrics.total_count()
        result = {}

        for p in percentiles:
            # Simplified: percentile count
            result[p] = int(total * (p / 100))

        return result

    def time_series(self, interval: timedelta) -> dict[str, int]:
        """Get time series of error counts.

        Args:
            interval: Time interval for bucketing

        Returns:
            Dict with timestamp -> count
        """
        # Simplified implementation
        current = datetime.utcnow()
        cutoff = current - (interval * 10)  # Last 10 intervals

        counts_by_period: dict[str, int] = {}

        for record in self.metrics.records:
            if record.timestamp < cutoff:
                continue

            # Bucket by interval
            period = (record.timestamp - cutoff).total_seconds() / interval.total_seconds()
            period_key = f"period_{int(period)}"

            counts_by_period[period_key] = counts_by_period.get(period_key, 0) + 1

        return counts_by_period

    def export_json(self) -> str:
        """Export metrics as JSON.

        Returns:
            JSON string with metrics summary
        """
        export = {
            "summary": self.metrics.summary(),
            "top_errors": self.top_by_code(n=10),
            "top_categories": self.top_by_category(n=10),
            "severity_distribution": self.metrics.histogram_by_severity(),
        }
        return json.dumps(export, indent=2)

    def export_csv(self) -> str:
        """Export metrics as CSV.

        Returns:
            CSV string with error codes and counts
        """
        lines = ["code,count"]

        for code, count in self.top_by_code(n=1000):
            lines.append(f'"{code}",{count}')

        return "\n".join(lines)
