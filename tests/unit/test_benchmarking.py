"""Unit tests for benchmarking and performance tracking modules.

Tests:
- BenchmarkResult dataclass formatting and statistics
- Benchmarker strategy and batch benchmarking
- Performance comparison and regression detection
- PerformanceTracker timing recording and statistics
- ScalabilityTester scaling analysis and complexity detection
"""

from confiture.core.anonymization.benchmarking import (
    Benchmarker,
    BenchmarkResult,
    ComparativeResult,
    PerformanceTracker,
    ScalabilityTester,
)
from confiture.core.anonymization.strategies.hash import DeterministicHashStrategy


class TestBenchmarkResult:
    """Test BenchmarkResult dataclass."""

    def test_benchmark_result_creation(self):
        """Test creating a BenchmarkResult."""
        result = BenchmarkResult(
            operation="TestOp",
            iterations=1000,
            total_time_ms=100.0,
            avg_time_ms=0.1,
            min_time_ms=0.05,
            max_time_ms=0.2,
            ops_per_second=10000.0,
            memory_estimate_kb=1024.0,
        )

        assert result.operation == "TestOp"
        assert result.iterations == 1000
        assert result.avg_time_ms == 0.1

    def test_benchmark_result_str_format(self):
        """Test BenchmarkResult string formatting."""
        result = BenchmarkResult(
            operation="TestOperation",
            iterations=500,
            total_time_ms=50.0,
            avg_time_ms=0.1,
            min_time_ms=0.05,
            max_time_ms=0.15,
            ops_per_second=10000.0,
            memory_estimate_kb=512.0,
        )

        output = str(result)
        assert "TestOperation" in output
        assert "500" in output
        assert "0.1000" in output


class TestComparativeResult:
    """Test ComparativeResult dataclass."""

    def test_comparative_result_improvement(self):
        """Test ComparativeResult with performance improvement."""
        baseline = BenchmarkResult(
            operation="Op1",
            iterations=100,
            total_time_ms=100.0,
            avg_time_ms=1.0,
            min_time_ms=0.8,
            max_time_ms=1.2,
            ops_per_second=1000.0,
            memory_estimate_kb=1024.0,
        )
        candidate = BenchmarkResult(
            operation="Op1",
            iterations=100,
            total_time_ms=50.0,
            avg_time_ms=0.5,
            min_time_ms=0.4,
            max_time_ms=0.6,
            ops_per_second=2000.0,
            memory_estimate_kb=1024.0,
        )

        result = ComparativeResult(
            operation="Op1",
            baseline=baseline,
            candidate=candidate,
            speedup=2.0,
            regression=False,
        )

        assert result.speedup == 2.0
        assert result.regression is False
        assert "IMPROVEMENT" in str(result)

    def test_comparative_result_regression(self):
        """Test ComparativeResult with performance regression."""
        baseline = BenchmarkResult(
            operation="Op1",
            iterations=100,
            total_time_ms=50.0,
            avg_time_ms=0.5,
            min_time_ms=0.4,
            max_time_ms=0.6,
            ops_per_second=2000.0,
            memory_estimate_kb=1024.0,
        )
        candidate = BenchmarkResult(
            operation="Op1",
            iterations=100,
            total_time_ms=100.0,
            avg_time_ms=1.0,
            min_time_ms=0.8,
            max_time_ms=1.2,
            ops_per_second=1000.0,
            memory_estimate_kb=1024.0,
        )

        result = ComparativeResult(
            operation="Op1",
            baseline=baseline,
            candidate=candidate,
            speedup=0.5,
            regression=True,
        )

        assert result.speedup == 0.5
        assert result.regression is True
        assert "REGRESSION" in str(result)


class TestBenchmarker:
    """Test Benchmarker class."""

    def test_benchmarker_initialization(self):
        """Test Benchmarker initialization."""
        benchmarker = Benchmarker(verbose=False)
        assert benchmarker.verbose is False
        assert benchmarker.results == []

    def test_benchmarker_initialization_verbose(self):
        """Test Benchmarker initialization with verbose mode."""
        benchmarker = Benchmarker(verbose=True)
        assert benchmarker.verbose is True

    def test_benchmark_strategy(self):
        """Test benchmarking a strategy."""
        benchmarker = Benchmarker(verbose=False)
        strategy = DeterministicHashStrategy()
        test_values = ["test1", "test2", "test3"]

        result = benchmarker.benchmark_strategy(
            strategy, test_values, iterations=10
        )

        assert result.operation == "DeterministicHashStrategy"
        assert result.iterations > 0
        assert result.avg_time_ms > 0
        assert result.ops_per_second > 0
        assert len(benchmarker.results) == 1

    def test_benchmark_strategy_multiple(self):
        """Test benchmarking multiple strategies."""
        benchmarker = Benchmarker(verbose=False)
        strategy1 = DeterministicHashStrategy()
        strategy2 = DeterministicHashStrategy()
        test_values = ["value1", "value2"]

        result1 = benchmarker.benchmark_strategy(strategy1, test_values, iterations=5)
        result2 = benchmarker.benchmark_strategy(strategy2, test_values, iterations=5)

        assert len(benchmarker.results) == 2
        assert result1.operation == "DeterministicHashStrategy"
        assert result2.operation == "DeterministicHashStrategy"

    def test_benchmark_batch_anonymization(self):
        """Test batch anonymization benchmarking."""
        benchmarker = Benchmarker(verbose=False)

        def mock_anonymize(data):
            return [{"id": item["id"], "name": "REDACTED"} for item in data]

        results = benchmarker.benchmark_batch_anonymization(mock_anonymize, [10, 20])

        assert 10 in results
        assert 20 in results
        assert results[10].avg_time_ms > 0
        assert results[20].avg_time_ms > 0

    def test_benchmark_batch_single_size(self):
        """Test batch anonymization with single batch size."""
        benchmarker = Benchmarker(verbose=False)

        def mock_anonymize(data):
            return data

        results = benchmarker.benchmark_batch_anonymization(mock_anonymize, [5])

        assert len(results) == 1
        assert 5 in results

    def test_compare_performance_improvement(self):
        """Test performance comparison showing improvement."""
        benchmarker = Benchmarker()
        baseline = BenchmarkResult(
            operation="Op",
            iterations=100,
            total_time_ms=100.0,
            avg_time_ms=1.0,
            min_time_ms=0.8,
            max_time_ms=1.2,
            ops_per_second=1000.0,
            memory_estimate_kb=1024.0,
        )
        candidate = BenchmarkResult(
            operation="Op",
            iterations=100,
            total_time_ms=50.0,
            avg_time_ms=0.5,
            min_time_ms=0.4,
            max_time_ms=0.6,
            ops_per_second=2000.0,
            memory_estimate_kb=1024.0,
        )

        result = benchmarker.compare_performance(baseline, candidate)

        assert result.speedup == 2.0
        assert result.regression is False

    def test_compare_performance_regression(self):
        """Test performance comparison showing regression."""
        benchmarker = Benchmarker()
        baseline = BenchmarkResult(
            operation="Op",
            iterations=100,
            total_time_ms=100.0,
            avg_time_ms=1.0,
            min_time_ms=0.8,
            max_time_ms=1.2,
            ops_per_second=1000.0,
            memory_estimate_kb=1024.0,
        )
        candidate = BenchmarkResult(
            operation="Op",
            iterations=100,
            total_time_ms=120.0,
            avg_time_ms=1.2,
            min_time_ms=1.0,
            max_time_ms=1.4,
            ops_per_second=833.0,
            memory_estimate_kb=1024.0,
        )

        result = benchmarker.compare_performance(baseline, candidate)

        assert result.speedup < 1.0
        assert result.regression is True

    def test_compare_performance_threshold(self):
        """Test performance comparison with custom regression threshold."""
        benchmarker = Benchmarker()
        baseline = BenchmarkResult(
            operation="Op",
            iterations=100,
            total_time_ms=100.0,
            avg_time_ms=1.0,
            min_time_ms=0.8,
            max_time_ms=1.2,
            ops_per_second=1000.0,
            memory_estimate_kb=1024.0,
        )
        candidate = BenchmarkResult(
            operation="Op",
            iterations=100,
            total_time_ms=80.0,
            avg_time_ms=0.8,
            min_time_ms=0.6,
            max_time_ms=1.0,
            ops_per_second=1250.0,
            memory_estimate_kb=1024.0,
        )

        result = benchmarker.compare_performance(
            baseline, candidate, regression_threshold=1.1
        )

        assert result.speedup > 1.0
        assert result.regression is False

    def test_get_summary_empty(self):
        """Test summary with no results."""
        benchmarker = Benchmarker()
        summary = benchmarker.get_summary()
        assert "No results to summarize" in summary

    def test_get_summary_with_results(self):
        """Test summary with multiple results."""
        benchmarker = Benchmarker()
        benchmarker.results = [
            BenchmarkResult(
                operation="FastOp",
                iterations=100,
                total_time_ms=50.0,
                avg_time_ms=0.5,
                min_time_ms=0.4,
                max_time_ms=0.6,
                ops_per_second=2000.0,
                memory_estimate_kb=512.0,
            ),
            BenchmarkResult(
                operation="SlowOp",
                iterations=100,
                total_time_ms=200.0,
                avg_time_ms=2.0,
                min_time_ms=1.8,
                max_time_ms=2.2,
                ops_per_second=500.0,
                memory_estimate_kb=1024.0,
            ),
        ]

        summary = benchmarker.get_summary()

        assert "BENCHMARK SUMMARY" in summary
        assert "FastOp" in summary
        assert "SlowOp" in summary
        assert "Fastest:" in summary
        assert "Slowest:" in summary
        assert "Ratio:" in summary


class TestPerformanceTracker:
    """Test PerformanceTracker class."""

    def test_tracker_initialization(self):
        """Test PerformanceTracker initialization."""
        tracker = PerformanceTracker()
        assert tracker.timings == {}

    def test_record_single_timing(self):
        """Test recording a single timing."""
        tracker = PerformanceTracker()
        tracker.record("operation1", 10.5)

        assert "operation1" in tracker.timings
        assert tracker.timings["operation1"] == [10.5]

    def test_record_multiple_timings(self):
        """Test recording multiple timings for same operation."""
        tracker = PerformanceTracker()
        tracker.record("operation1", 10.0)
        tracker.record("operation1", 20.0)
        tracker.record("operation1", 15.0)

        assert len(tracker.timings["operation1"]) == 3
        assert tracker.timings["operation1"] == [10.0, 20.0, 15.0]

    def test_record_different_operations(self):
        """Test recording timings for different operations."""
        tracker = PerformanceTracker()
        tracker.record("op1", 10.0)
        tracker.record("op2", 20.0)
        tracker.record("op1", 15.0)

        assert len(tracker.timings["op1"]) == 2
        assert len(tracker.timings["op2"]) == 1

    def test_get_stats_nonexistent(self):
        """Test getting stats for operation with no recordings."""
        tracker = PerformanceTracker()
        stats = tracker.get_stats("nonexistent")
        assert stats == {}

    def test_get_stats_single_value(self):
        """Test getting stats with single value."""
        tracker = PerformanceTracker()
        tracker.record("op", 10.0)

        stats = tracker.get_stats("op")

        assert stats["count"] == 1
        assert stats["total_ms"] == 10.0
        assert stats["avg_ms"] == 10.0
        assert stats["min_ms"] == 10.0
        assert stats["max_ms"] == 10.0

    def test_get_stats_multiple_values(self):
        """Test getting stats with multiple values."""
        tracker = PerformanceTracker()
        tracker.record("op", 10.0)
        tracker.record("op", 20.0)
        tracker.record("op", 30.0)

        stats = tracker.get_stats("op")

        assert stats["count"] == 3
        assert stats["total_ms"] == 60.0
        assert stats["avg_ms"] == 20.0
        assert stats["min_ms"] == 10.0
        assert stats["max_ms"] == 30.0

    def test_get_report_empty(self):
        """Test report with no timings."""
        tracker = PerformanceTracker()
        report = tracker.get_report()

        assert "PERFORMANCE REPORT" in report
        assert "=" in report

    def test_get_report_with_timings(self):
        """Test report with recorded timings."""
        tracker = PerformanceTracker()
        tracker.record("operation1", 10.0)
        tracker.record("operation1", 20.0)
        tracker.record("operation2", 15.0)

        report = tracker.get_report()

        assert "PERFORMANCE REPORT" in report
        assert "operation1" in report
        assert "operation2" in report
        assert "Count" in report
        assert "Total (ms)" in report


class TestScalabilityTester:
    """Test ScalabilityTester class."""

    def test_scalability_tester_initialization(self):
        """Test ScalabilityTester initialization."""

        def dummy_func(record):
            return record

        tester = ScalabilityTester(dummy_func)
        assert tester.anonymize_func == dummy_func

    def test_test_scaling_linear_performance(self):
        """Test scaling with linear performance."""

        def dummy_func(record):
            return {k: f"anon_{v}" for k, v in record.items()}

        tester = ScalabilityTester(dummy_func)
        results = tester.test_scaling((10, 30), step=10)

        assert 10 in results
        assert 20 in results
        assert 30 in results
        assert len(results) == 3

    def test_test_scaling_single_point(self):
        """Test scaling with single point."""

        def dummy_func(record):
            return record

        tester = ScalabilityTester(dummy_func)
        results = tester.test_scaling((10, 10), step=5)

        assert 10 in results

    def test_test_scaling_values_positive(self):
        """Test that scaling results are positive."""

        def dummy_func(record):
            return record

        tester = ScalabilityTester(dummy_func)
        results = tester.test_scaling((5, 25), step=5)

        for _field_count, time_ms in results.items():
            assert time_ms > 0

    def test_analyze_complexity_insufficient_data(self):
        """Test complexity analysis with insufficient data."""

        def dummy_func(record):
            return record

        tester = ScalabilityTester(dummy_func)
        analysis = tester.analyze_complexity({10: 1.0})

        assert "Insufficient data" in analysis

    def test_analyze_complexity_constant_time(self):
        """Test complexity analysis detecting O(1) complexity."""

        def dummy_func(record):
            return record

        tester = ScalabilityTester(dummy_func)
        # Constant time: same time regardless of field count
        results = {
            10: 1.0,
            20: 1.0,
            30: 1.0,
            40: 1.0,
        }

        analysis = tester.analyze_complexity(results)

        assert "O(1) - Constant" in analysis
        assert "Field Count" in analysis

    def test_analyze_complexity_linear_time(self):
        """Test complexity analysis detecting O(n) complexity."""

        def dummy_func(record):
            return record

        tester = ScalabilityTester(dummy_func)
        # Linear time: proportional to field count (with some noise)
        results = {
            10: 10.5,
            20: 21.0,
            30: 31.5,
            40: 42.0,
        }

        analysis = tester.analyze_complexity(results)

        assert "Estimated Complexity" in analysis
        assert "Average Growth Ratio" in analysis

    def test_analyze_complexity_quadratic_time(self):
        """Test complexity analysis detecting O(n²) complexity."""

        def dummy_func(record):
            return record

        tester = ScalabilityTester(dummy_func)
        # Quadratic time: proportional to field count squared
        results = {
            10: 100.0,
            20: 400.0,
            30: 900.0,
        }

        analysis = tester.analyze_complexity(results)

        assert "Estimated Complexity" in analysis
        assert "Average Growth Ratio" in analysis

    def test_analyze_complexity_format(self):
        """Test complexity analysis output format."""

        def dummy_func(record):
            return record

        tester = ScalabilityTester(dummy_func)
        results = {10: 5.0, 20: 10.0, 30: 15.0}

        analysis = tester.analyze_complexity(results)

        assert "Complexity Analysis" in analysis
        assert "Field Count" in analysis
        assert "Time (ms)" in analysis
        assert "Trend" in analysis
