"""Tests for PerformanceBenchmark - compare VALUES vs COPY performance."""

import pytest

from confiture.core.seed.performance_benchmark import (
    PerformanceBenchmark,
)


class TestBasicBenchmarking:
    """Test basic benchmarking functionality."""

    @pytest.mark.asyncio
    async def test_compares_values_and_copy_formats(self) -> None:
        """Test that benchmark compares both formats."""
        benchmark = PerformanceBenchmark()
        seed_data = {"users": [{"id": str(i), "name": f"User {i}"} for i in range(100)]}

        result = await benchmark.compare(seed_data)

        assert result.values_time_ms > 0
        assert result.copy_time_ms >= 0
        assert result.speedup_factor >= 1.0

    @pytest.mark.asyncio
    async def test_copy_is_faster_for_large_datasets(self) -> None:
        """Test that COPY is faster than VALUES for large datasets."""
        benchmark = PerformanceBenchmark()
        seed_data = {"users": [{"id": str(i), "name": f"User {i}"} for i in range(1000)]}

        result = await benchmark.compare(seed_data)

        # For large datasets, COPY should be faster
        assert result.speedup_factor > 1.0
        assert result.copy_time_ms < result.values_time_ms

    @pytest.mark.asyncio
    async def test_values_slower_for_all_datasets(self) -> None:
        """Test that VALUES is consistently slower than COPY."""
        benchmark = PerformanceBenchmark()
        seed_data = {"users": [{"id": str(i)} for i in range(10)]}

        result = await benchmark.compare(seed_data)

        # VALUES should always be slower, but relative overhead is smaller for tiny datasets
        assert result.speedup_factor >= 1.0
        assert result.values_time_ms >= result.copy_time_ms

    @pytest.mark.asyncio
    async def test_benchmarks_multiple_tables(self) -> None:
        """Test benchmarking multiple tables."""
        benchmark = PerformanceBenchmark()
        seed_data = {
            "users": [{"id": str(i)} for i in range(500)],
            "posts": [{"id": str(i)} for i in range(300)],
        }

        result = await benchmark.compare(seed_data)

        assert len(result.table_metrics) == 2
        assert "users" in result.table_metrics
        assert "posts" in result.table_metrics


class TestBenchmarkMetrics:
    """Test benchmark result metrics."""

    @pytest.mark.asyncio
    async def test_includes_execution_times(self) -> None:
        """Test that result includes timing information."""
        benchmark = PerformanceBenchmark()
        seed_data = {"users": [{"id": "1"}]}

        result = await benchmark.compare(seed_data)

        assert hasattr(result, "values_time_ms")
        assert hasattr(result, "copy_time_ms")
        assert hasattr(result, "speedup_factor")

    @pytest.mark.asyncio
    async def test_includes_row_count_metrics(self) -> None:
        """Test that result includes row count by table."""
        benchmark = PerformanceBenchmark()
        seed_data = {
            "users": [{"id": str(i)} for i in range(100)],
            "posts": [{"id": str(i)} for i in range(50)],
        }

        result = await benchmark.compare(seed_data)

        assert result.total_rows == 150
        assert result.table_metrics["users"]["rows"] == 100
        assert result.table_metrics["posts"]["rows"] == 50

    @pytest.mark.asyncio
    async def test_calculates_speedup_factor(self) -> None:
        """Test speedup factor calculation."""
        benchmark = PerformanceBenchmark()
        seed_data = {"users": [{"id": str(i)} for i in range(100)]}

        result = await benchmark.compare(seed_data)

        # Speedup = VALUES time / COPY time
        expected_speedup = result.values_time_ms / result.copy_time_ms
        assert abs(result.speedup_factor - expected_speedup) < 0.01


class TestBenchmarkAccuracy:
    """Test benchmark accuracy and reliability."""

    @pytest.mark.asyncio
    async def test_timing_is_positive(self) -> None:
        """Test that all timings are positive values."""
        benchmark = PerformanceBenchmark()
        seed_data = {"users": [{"id": str(i)} for i in range(100)]}

        result = await benchmark.compare(seed_data)

        assert result.values_time_ms >= 0
        assert result.copy_time_ms >= 0

    @pytest.mark.asyncio
    async def test_per_table_metrics_included(self) -> None:
        """Test that each table has performance metrics."""
        benchmark = PerformanceBenchmark()
        seed_data = {
            "users": [{"id": str(i)} for i in range(100)],
            "posts": [{"id": str(i)} for i in range(50)],
        }

        result = await benchmark.compare(seed_data)

        for _table, metrics in result.table_metrics.items():
            assert "rows" in metrics
            assert "values_time_ms" in metrics
            assert "copy_time_ms" in metrics

    @pytest.mark.asyncio
    async def test_benchmark_with_empty_table(self) -> None:
        """Test benchmarking with empty table."""
        benchmark = PerformanceBenchmark()
        seed_data = {"users": []}

        result = await benchmark.compare(seed_data)

        assert result.total_rows == 0
        assert result.speedup_factor >= 1.0


class TestBenchmarkReliability:
    """Test benchmark result reliability."""

    @pytest.mark.asyncio
    async def test_consistent_results_format(self) -> None:
        """Test that benchmark always produces consistent result format."""
        benchmark = PerformanceBenchmark()
        seed_data = {"users": [{"id": str(i), "name": f"User {i}"} for i in range(100)]}

        result = await benchmark.compare(seed_data)

        # Check all required fields exist
        assert hasattr(result, "values_time_ms")
        assert hasattr(result, "copy_time_ms")
        assert hasattr(result, "speedup_factor")
        assert hasattr(result, "total_rows")
        assert hasattr(result, "table_metrics")

    @pytest.mark.asyncio
    async def test_works_with_various_data_types(self) -> None:
        """Test benchmarking with various data types."""
        benchmark = PerformanceBenchmark()
        seed_data = {
            "mixed": [
                {
                    "id": str(i),
                    "name": f"Name {i}",
                    "active": "true" if i % 2 == 0 else "false",
                    "score": str(i * 10),
                    "email": None if i % 5 == 0 else f"user{i}@example.com",
                }
                for i in range(100)
            ]
        }

        result = await benchmark.compare(seed_data)

        assert result.total_rows == 100
        assert result.speedup_factor >= 1.0

    @pytest.mark.asyncio
    async def test_handles_large_dataset_benchmark(self) -> None:
        """Test benchmarking with larger dataset."""
        benchmark = PerformanceBenchmark()
        seed_data = {"users": [{"id": str(i), "name": f"User {i}"} for i in range(5000)]}

        result = await benchmark.compare(seed_data)

        assert result.total_rows == 5000
        # COPY should show clear advantage for large dataset
        assert result.speedup_factor > 1.5
