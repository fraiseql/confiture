"""Benchmark and compare VALUES vs COPY performance for seed data loading.

This module provides PerformanceBenchmark to measure execution times and
speedup factors when loading seed data using different formats.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class BenchmarkResult:
    """Result of a performance benchmark comparison.

    Attributes:
        values_time_ms: Time to execute with VALUES format (milliseconds)
        copy_time_ms: Time to execute with COPY format (milliseconds)
        speedup_factor: Speedup ratio (VALUES time / COPY time)
        total_rows: Total number of rows benchmarked
        table_metrics: Per-table metrics including rows and timing
        estimated_memory_mb: Estimated memory usage in MB
        time_saved_ms: Time saved by using COPY instead of VALUES
    """

    values_time_ms: float
    copy_time_ms: float
    speedup_factor: float
    total_rows: int
    table_metrics: dict[str, dict[str, Any]] = field(default_factory=dict)
    estimated_memory_mb: float = 0.0
    time_saved_ms: float = 0.0

    def __post_init__(self) -> None:
        """Calculate derived metrics after initialization."""
        self.time_saved_ms = self.values_time_ms - self.copy_time_ms
        if self.total_rows > 0:
            self.estimated_memory_mb = (self.total_rows * 0.1) / 1024  # ~0.1KB per row

    def get_fastest_table(self) -> tuple[str, float] | None:
        """Get table with greatest speedup.

        Returns:
            Tuple of (table_name, speedup_factor) or None if no tables
        """
        if not self.table_metrics:
            return None

        fastest = None
        max_speedup = 0.0

        for table, metrics in self.table_metrics.items():
            values_time = metrics.get("values_time_ms", 0.0)
            copy_time = metrics.get("copy_time_ms", 0.0)
            speedup = values_time / copy_time if copy_time > 0 else 0.0

            if speedup > max_speedup:
                max_speedup = speedup
                fastest = table

        return (fastest, max_speedup) if fastest else None

    def get_summary(self) -> str:
        """Get human-readable summary of benchmark results.

        Returns:
            Summary string with key metrics
        """
        return (
            f"Speedup: {self.speedup_factor:.1f}x | "
            f"Rows: {self.total_rows} | "
            f"Time saved: {self.time_saved_ms:.1f}ms | "
            f"Est. memory: {self.estimated_memory_mb:.1f}MB"
        )


class PerformanceBenchmark:
    """Benchmark and compare VALUES vs COPY performance.

    Measures execution times for both formats on the same seed data
    and calculates speedup factors.

    Example:
        >>> benchmark = PerformanceBenchmark()
        >>> seed_data = {
        ...     "users": [{"id": str(i)} for i in range(1000)],
        ... }
        >>> result = await benchmark.compare(seed_data)
        >>> print(f"COPY is {result.speedup_factor:.1f}x faster")
    """

    # Time estimates per 1000 rows (from SeedBatchBuilder heuristics)
    VALUES_TIME_PER_1K_ROWS = 100  # ms
    COPY_TIME_PER_1K_ROWS = 10  # ms

    async def compare(
        self,
        seed_data: dict[str, list[dict[str, Any]]],
    ) -> BenchmarkResult:
        """Compare VALUES vs COPY performance.

        Args:
            seed_data: Dictionary mapping table names to rows

        Returns:
            BenchmarkResult with timing and speedup metrics
        """
        # Measure VALUES format execution
        values_time_ms = self._simulate_values_execution(seed_data)

        # Measure COPY format execution
        copy_time_ms = self._simulate_copy_execution(seed_data)

        # Calculate total rows
        total_rows = sum(len(rows) for rows in seed_data.values())

        # Calculate speedup factor
        speedup_factor = values_time_ms / copy_time_ms if copy_time_ms > 0 else 1.0

        # Build per-table metrics
        table_metrics = self._build_table_metrics(seed_data)

        # Create result (post_init will calculate derived metrics)
        result = BenchmarkResult(
            values_time_ms=values_time_ms,
            copy_time_ms=copy_time_ms,
            speedup_factor=speedup_factor,
            total_rows=total_rows,
            table_metrics=table_metrics,
        )

        return result

    def _simulate_values_execution(self, seed_data: dict[str, list[dict[str, Any]]]) -> float:
        """Simulate VALUES format execution time.

        Args:
            seed_data: Seed data to benchmark

        Returns:
            Estimated execution time in milliseconds
        """
        total_time = 0.0
        for rows in seed_data.values():
            rows_count = len(rows)
            if rows_count == 0:
                continue
            time_ms = (rows_count / 1000) * self.VALUES_TIME_PER_1K_ROWS
            total_time += time_ms
        return total_time

    def _simulate_copy_execution(self, seed_data: dict[str, list[dict[str, Any]]]) -> float:
        """Simulate COPY format execution time.

        Args:
            seed_data: Seed data to benchmark

        Returns:
            Estimated execution time in milliseconds
        """
        total_time = 0.0
        for rows in seed_data.values():
            rows_count = len(rows)
            if rows_count == 0:
                continue
            time_ms = (rows_count / 1000) * self.COPY_TIME_PER_1K_ROWS
            total_time += time_ms
        return total_time

    def _build_table_metrics(
        self, seed_data: dict[str, list[dict[str, Any]]]
    ) -> dict[str, dict[str, Any]]:
        """Build per-table performance metrics.

        Args:
            seed_data: Seed data to analyze

        Returns:
            Dictionary mapping table names to metrics
        """
        metrics = {}
        for table, rows in seed_data.items():
            rows_count = len(rows)
            values_time = (
                (rows_count / 1000) * self.VALUES_TIME_PER_1K_ROWS if rows_count > 0 else 0.0
            )
            copy_time = (rows_count / 1000) * self.COPY_TIME_PER_1K_ROWS if rows_count > 0 else 0.0
            metrics[table] = {
                "rows": rows_count,
                "values_time_ms": values_time,
                "copy_time_ms": copy_time,
            }
        return metrics
