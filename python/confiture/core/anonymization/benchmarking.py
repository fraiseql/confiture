"""Performance benchmarking and profiling for anonymization strategies.

Provides:
- Timing and memory profiling for strategies
- Batch operation benchmarking
- Comparative performance analysis
- Performance regression detection
"""

import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from confiture.core.anonymization.strategy import AnonymizationStrategy


@dataclass
class BenchmarkResult:
    """Results from a single benchmark run."""

    operation: str
    iterations: int
    total_time_ms: float
    avg_time_ms: float
    min_time_ms: float
    max_time_ms: float
    ops_per_second: float
    memory_estimate_kb: float

    def __str__(self) -> str:
        """Format as readable string."""
        return (
            f"{self.operation:30} | "
            f"Iterations: {self.iterations:5} | "
            f"Avg: {self.avg_time_ms:8.4f}ms | "
            f"Min: {self.min_time_ms:8.4f}ms | "
            f"Max: {self.max_time_ms:8.4f}ms | "
            f"Ops/sec: {self.ops_per_second:8.1f}"
        )


@dataclass
class ComparativeResult:
    """Comparison of benchmark results."""

    operation: str
    baseline: BenchmarkResult
    candidate: BenchmarkResult
    speedup: float
    regression: bool

    def __str__(self) -> str:
        """Format as readable string."""
        status = "🔴 REGRESSION" if self.regression else "🟢 IMPROVEMENT"
        return f"{self.operation:30} | {status:20} | Speedup: {self.speedup:6.2f}x"


class Benchmarker:
    """Performance benchmarking for anonymization operations."""

    def __init__(self, verbose: bool = False):
        """Initialize benchmarker.

        Args:
            verbose: Print detailed timing information.
        """
        self.verbose = verbose
        self.results: list[BenchmarkResult] = []

    def benchmark_strategy(
        self, strategy: AnonymizationStrategy, test_values: list[Any], iterations: int = 1000
    ) -> BenchmarkResult:
        """Benchmark a single strategy.

        Args:
            strategy: Strategy to benchmark.
            test_values: Sample values to anonymize.
            iterations: Number of iterations to run.

        Returns:
            BenchmarkResult with timing information.
        """
        times = []

        # Warmup
        for value in test_values[: min(10, len(test_values))]:
            _ = strategy.anonymize(value)

        # Benchmark
        for _ in range(iterations):
            for value in test_values:
                start = time.perf_counter()
                _ = strategy.anonymize(value)
                elapsed = (time.perf_counter() - start) * 1000  # Convert to ms
                times.append(elapsed)

        total_time_ms = sum(times)
        avg_time_ms = total_time_ms / len(times)
        min_time_ms = min(times)
        max_time_ms = max(times)
        ops_per_second = 1000.0 / avg_time_ms

        result = BenchmarkResult(
            operation=f"{strategy.__class__.__name__}",
            iterations=len(times),
            total_time_ms=total_time_ms,
            avg_time_ms=avg_time_ms,
            min_time_ms=min_time_ms,
            max_time_ms=max_time_ms,
            ops_per_second=ops_per_second,
            memory_estimate_kb=sys.getsizeof(strategy) / 1024.0,
        )

        self.results.append(result)

        if self.verbose:
            print(result)

        return result

    def benchmark_batch_anonymization(
        self, anonymize_func: Callable[[list[dict]], list[dict]], batch_sizes: list[int]
    ) -> dict[int, BenchmarkResult]:
        """Benchmark batch anonymization at different sizes.

        Args:
            anonymize_func: Function that takes list of dicts and returns anonymized list.
            batch_sizes: List of batch sizes to test.

        Returns:
            Dictionary mapping batch size to BenchmarkResult.
        """
        results = {}

        for batch_size in batch_sizes:
            # Create test data
            test_data = [
                {
                    "id": i,
                    "name": f"Person {i}",
                    "email": f"user{i}@example.com",
                    "age": 25 + (i % 50),
                }
                for i in range(batch_size)
            ]

            # Benchmark
            start = time.perf_counter()
            _ = anonymize_func(test_data)
            elapsed_ms = (time.perf_counter() - start) * 1000

            result = BenchmarkResult(
                operation=f"Batch Anonymization (size={batch_size})",
                iterations=1,
                total_time_ms=elapsed_ms,
                avg_time_ms=elapsed_ms,
                min_time_ms=elapsed_ms,
                max_time_ms=elapsed_ms,
                ops_per_second=1000.0 / elapsed_ms * batch_size,
                memory_estimate_kb=sys.getsizeof(test_data) / 1024.0,
            )

            results[batch_size] = result

            if self.verbose:
                print(result)

        return results

    def compare_performance(
        self,
        baseline: BenchmarkResult,
        candidate: BenchmarkResult,
        regression_threshold: float = 0.95,
    ) -> ComparativeResult:
        """Compare performance between two benchmark results.

        Args:
            baseline: Baseline benchmark result.
            candidate: Candidate benchmark result to compare.
            regression_threshold: Speedup threshold below which it's considered a regression.

        Returns:
            ComparativeResult with comparison analysis.
        """
        speedup = baseline.avg_time_ms / candidate.avg_time_ms
        regression = speedup < regression_threshold

        return ComparativeResult(
            operation=baseline.operation,
            baseline=baseline,
            candidate=candidate,
            speedup=speedup,
            regression=regression,
        )

    def get_summary(self) -> str:
        """Get summary of all benchmark results.

        Returns:
            Formatted summary string.
        """
        if not self.results:
            return "No results to summarize"

        summary = "BENCHMARK SUMMARY\n"
        summary += "=" * 120 + "\n"

        for result in sorted(self.results, key=lambda r: r.avg_time_ms, reverse=True):
            summary += str(result) + "\n"

        summary += "=" * 120 + "\n"

        fastest = min(self.results, key=lambda r: r.avg_time_ms)
        slowest = max(self.results, key=lambda r: r.avg_time_ms)

        summary += f"\nFastest: {fastest.operation:40} ({fastest.avg_time_ms:.4f}ms)\n"
        summary += f"Slowest: {slowest.operation:40} ({slowest.avg_time_ms:.4f}ms)\n"
        summary += f"Ratio:   {slowest.avg_time_ms / fastest.avg_time_ms:.2f}x\n"

        return summary


class PerformanceTracker:
    """Track and report performance metrics across multiple operations."""

    def __init__(self):
        """Initialize tracker."""
        self.timings: dict[str, list[float]] = {}

    def record(self, operation: str, elapsed_ms: float) -> None:
        """Record a timing measurement.

        Args:
            operation: Name of operation.
            elapsed_ms: Time elapsed in milliseconds.
        """
        if operation not in self.timings:
            self.timings[operation] = []
        self.timings[operation].append(elapsed_ms)

    def get_stats(self, operation: str) -> dict[str, float]:
        """Get statistics for an operation.

        Args:
            operation: Name of operation.

        Returns:
            Dictionary with timing statistics.
        """
        if operation not in self.timings:
            return {}

        times = self.timings[operation]
        return {
            "count": len(times),
            "total_ms": sum(times),
            "avg_ms": sum(times) / len(times),
            "min_ms": min(times),
            "max_ms": max(times),
        }

    def get_report(self) -> str:
        """Get performance report.

        Returns:
            Formatted performance report.
        """
        report = "PERFORMANCE REPORT\n"
        report += "=" * 100 + "\n"
        report += f"{'Operation':<40} {'Count':<10} {'Total (ms)':<15} {'Avg (ms)':<15} {'Min (ms)':<15}\n"
        report += "-" * 100 + "\n"

        for operation in sorted(self.timings.keys()):
            stats = self.get_stats(operation)
            report += (
                f"{operation:<40} "
                f"{stats['count']:<10} "
                f"{stats['total_ms']:<15.2f} "
                f"{stats['avg_ms']:<15.4f} "
                f"{stats['min_ms']:<15.4f}\n"
            )

        report += "=" * 100 + "\n"
        return report


class ScalabilityTester:
    """Test scalability and performance with varying data sizes."""

    def __init__(self, anonymize_func: Callable[[dict], dict]):
        """Initialize tester.

        Args:
            anonymize_func: Function that anonymizes a single record.
        """
        self.anonymize_func = anonymize_func

    def test_scaling(self, field_count_range: tuple[int, int], step: int = 10) -> dict[int, float]:
        """Test anonymization performance as number of fields increases.

        Args:
            field_count_range: (min_fields, max_fields) tuple.
            step: Step size for field count.

        Returns:
            Dictionary mapping field count to average time in ms.
        """
        results = {}

        for field_count in range(field_count_range[0], field_count_range[1] + 1, step):
            # Create test record with specified number of fields
            test_record = {f"field_{i}": f"value_{i}" for i in range(field_count)}

            # Measure time to anonymize
            start = time.perf_counter()
            for _ in range(100):
                _ = self.anonymize_func(test_record)
            elapsed_ms = (time.perf_counter() - start) * 10  # Convert to avg per call

            results[field_count] = elapsed_ms

        return results

    def analyze_complexity(self, scaling_results: dict[int, float]) -> str:
        """Analyze computational complexity from scaling results.

        Args:
            scaling_results: Results from test_scaling().

        Returns:
            Analysis string describing complexity pattern.
        """
        if len(scaling_results) < 2:
            return "Insufficient data for complexity analysis"

        items = sorted(scaling_results.items())
        ratios = []

        for i in range(1, len(items)):
            field_ratio = items[i][0] / items[i - 1][0]
            time_ratio = items[i][1] / items[i - 1][1]
            ratios.append(time_ratio / field_ratio if field_ratio > 0 else 0)

        avg_ratio = sum(ratios) / len(ratios) if ratios else 0

        # Classify complexity
        if avg_ratio < 1.05:
            complexity = "O(1) - Constant"
        elif avg_ratio < 1.15:
            complexity = "O(log n) - Logarithmic"
        elif avg_ratio < 1.3:
            complexity = "O(n) - Linear"
        elif avg_ratio < 1.5:
            complexity = "O(n log n) - Linearithmic"
        else:
            complexity = "O(n²) or higher - Quadratic or worse"

        analysis = "Complexity Analysis\n"
        analysis += f"{'Field Count':<15} {'Time (ms)':<15} {'Trend':<20}\n"
        analysis += "-" * 50 + "\n"

        for field_count, time_ms in items:
            analysis += f"{field_count:<15} {time_ms:<15.4f}\n"

        analysis += "-" * 50 + "\n"
        analysis += f"Estimated Complexity: {complexity}\n"
        analysis += f"Average Growth Ratio: {avg_ratio:.3f}x per field\n"

        return analysis
