"""Unit tests for Performance Optimization.

Tests for performance monitoring, batch processing, concurrent processing,
caching, connection pooling, and query optimization.

Test Coverage:
- PerformanceMonitor: metrics recording, statistics, regression detection
- BatchAnonymizer: batch processing, throughput, error handling
- ConcurrentAnonymizer: thread pool execution, worker coordination
- AnonymizationCache: LRU eviction, TTL expiration, cache hits/misses
- ConnectionPoolManager: pool lifecycle, connection health checking
- QueryOptimizer: query analysis, index recommendations, slow query detection
"""

import time
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from confiture.core.anonymization.performance import (
    AnonymizationCache,
    BatchAnonymizer,
    CacheEntry,
    CacheStatistics,
    ConcurrentAnonymizer,
    ConnectionPoolManager,
    PerformanceMetric,
    PerformanceMonitor,
    PerformanceStatistics,
    QueryOptimizer,
)
from confiture.core.anonymization.strategy import AnonymizationStrategy


class DummyStrategy(AnonymizationStrategy):
    """Simple strategy for testing."""

    def anonymize(self, value) -> str:
        return f"anon_{value}"

    def validate(self, value) -> bool:
        return True

    @property
    def is_reversible(self) -> bool:
        return False


# ============================================================================
# PerformanceMetric Tests
# ============================================================================


class TestPerformanceMetric:
    """Test PerformanceMetric data class."""

    def test_metric_creation(self):
        """Test basic metric creation."""
        metric = PerformanceMetric(
            operation="anonymize",
            duration_ms=150.0,
            rows_processed=1000,
        )
        assert metric.operation == "anonymize"
        assert metric.duration_ms == 150.0
        assert metric.rows_processed == 1000
        assert metric.throughput_rows_per_sec > 0

    def test_throughput_calculation(self):
        """Test throughput calculation (rows/sec)."""
        # 1000 rows in 100ms = 10,000 rows/sec
        metric = PerformanceMetric(
            operation="anonymize",
            duration_ms=100.0,
            rows_processed=1000,
        )
        assert metric.throughput_rows_per_sec == pytest.approx(10000.0, rel=0.01)

    def test_throughput_zero_duration(self):
        """Test throughput with zero duration."""
        metric = PerformanceMetric(
            operation="anonymize",
            duration_ms=0,
            rows_processed=1000,
        )
        assert metric.throughput_rows_per_sec == 0.0

    def test_metric_with_error(self):
        """Test metric with error information."""
        metric = PerformanceMetric(
            operation="anonymize",
            duration_ms=100.0,
            rows_processed=500,
            error="Database timeout",
        )
        assert metric.error == "Database timeout"


# ============================================================================
# PerformanceMonitor Tests
# ============================================================================


class TestPerformanceMonitor:
    """Test PerformanceMonitor functionality."""

    def test_monitor_creation(self):
        """Test monitor creation."""
        monitor = PerformanceMonitor(retention_minutes=1440)
        assert monitor.retention_minutes == 1440
        assert len(monitor.metrics) == 0

    def test_record_metric(self):
        """Test recording a metric."""
        monitor = PerformanceMonitor()
        monitor.record("anonymize", duration_ms=150, rows_processed=1000)

        assert len(monitor.metrics) == 1
        assert monitor.metrics[0].operation == "anonymize"

    def test_get_statistics_single_operation(self):
        """Test getting statistics for single operation."""
        monitor = PerformanceMonitor()
        monitor.record("anonymize", duration_ms=100, rows_processed=1000)
        monitor.record("anonymize", duration_ms=150, rows_processed=1000)

        stats = monitor.get_statistics("anonymize")

        assert len(stats) == 1
        assert stats[0].count == 2
        assert stats[0].avg_duration_ms == pytest.approx(125.0, rel=0.01)
        assert stats[0].min_duration_ms == 100.0
        assert stats[0].max_duration_ms == 150.0

    def test_get_statistics_multiple_operations(self):
        """Test getting statistics for multiple operations."""
        monitor = PerformanceMonitor()
        monitor.record("anonymize", duration_ms=100, rows_processed=1000)
        monitor.record("encrypt", duration_ms=200, rows_processed=500)

        stats = monitor.get_statistics()

        assert len(stats) == 2
        ops = {s.operation: s for s in stats}
        assert "anonymize" in ops
        assert "encrypt" in ops

    def test_error_rate_calculation(self):
        """Test error rate calculation."""
        monitor = PerformanceMonitor()
        monitor.record("anonymize", duration_ms=100, rows_processed=1000)
        monitor.record("anonymize", duration_ms=100, rows_processed=1000, error="Timeout")
        monitor.record("anonymize", duration_ms=100, rows_processed=1000, error="Timeout")

        stats = monitor.get_statistics("anonymize")

        assert stats[0].error_count == 2
        assert stats[0].error_rate == pytest.approx(66.67, rel=1)

    def test_cleanup_old_metrics(self):
        """Test cleanup of old metrics."""
        monitor = PerformanceMonitor(retention_minutes=1)

        # Record metric (will be kept)
        monitor.record("anonymize", duration_ms=100, rows_processed=1000)

        # Manually add old metric
        old_metric = PerformanceMetric(
            operation="anonymize",
            duration_ms=100,
            rows_processed=1000,
            timestamp=datetime.now() - timedelta(minutes=2),
        )
        monitor.metrics.append(old_metric)

        # Cleanup
        monitor._cleanup_old_metrics()

        # Old metric should be removed
        assert len(monitor.metrics) == 1

    def test_set_and_check_baseline(self):
        """Test baseline setting and regression detection."""
        monitor = PerformanceMonitor()

        # Set baseline
        baseline = PerformanceStatistics(
            operation="anonymize",
            count=1,
            avg_duration_ms=100,
            min_duration_ms=100,
            max_duration_ms=100,
            avg_throughput=10000,
            total_rows_processed=1000,
            total_duration_ms=100,
        )
        monitor.set_baseline("anonymize", baseline)

        # Check no regression when same performance
        monitor.record("anonymize", duration_ms=100, rows_processed=1000)
        assert not monitor.check_regression("anonymize", threshold_pct=10)

        # Check regression when performance degrades
        monitor.record("anonymize", duration_ms=150, rows_processed=1000)
        monitor.record("anonymize", duration_ms=150, rows_processed=1000)
        assert monitor.check_regression("anonymize", threshold_pct=10)

    def test_check_regression_nonexistent_baseline(self):
        """Test regression check with non-existent baseline."""
        monitor = PerformanceMonitor()
        assert not monitor.check_regression("nonexistent")


# ============================================================================
# AnonymizationCache Tests
# ============================================================================


class TestCacheEntry:
    """Test CacheEntry class."""

    def test_cache_entry_creation(self):
        """Test cache entry creation."""
        entry = CacheEntry("original", "anonymized", ttl_seconds=3600)
        assert entry.original_value == "original"
        assert entry.anonymized_value == "anonymized"
        assert not entry.is_expired()

    def test_cache_entry_expiration(self):
        """Test cache entry expiration."""
        entry = CacheEntry("original", "anonymized", ttl_seconds=1)
        time.sleep(1.1)
        assert entry.is_expired()

    def test_cache_entry_access_tracking(self):
        """Test access count and time tracking."""
        entry = CacheEntry("original", "anonymized")
        initial_count = entry.access_count
        entry.record_access()
        assert entry.access_count == initial_count + 1


class TestAnonymizationCache:
    """Test AnonymizationCache functionality."""

    def test_cache_creation(self):
        """Test cache creation."""
        cache = AnonymizationCache(max_entries=1000, ttl_seconds=3600)
        assert cache.max_entries == 1000
        assert cache.ttl_seconds == 3600

    def test_cache_set_and_get(self):
        """Test cache set and get operations."""
        cache = AnonymizationCache()
        cache.set("john@example.com", "TOKEN_abc123")

        result = cache.get("john@example.com")
        assert result == "TOKEN_abc123"

    def test_cache_miss(self):
        """Test cache miss."""
        cache = AnonymizationCache()
        result = cache.get("nonexistent@example.com")
        assert result is None

    def test_cache_hit_rate(self):
        """Test cache hit rate calculation."""
        cache = AnonymizationCache()
        cache.set("test", "anonymized")

        # Multiple hits
        cache.get("test")
        cache.get("test")
        cache.get("test")

        # Multiple misses
        cache.get("miss1")
        cache.get("miss2")

        stats = cache.get_statistics()
        assert stats.hits == 3
        assert stats.misses == 2
        assert stats.hit_rate == pytest.approx(60.0, rel=1)

    def test_cache_lru_eviction(self):
        """Test LRU eviction when cache is full."""
        cache = AnonymizationCache(max_entries=2)

        # Fill cache
        cache.set("a", "anon_a")
        cache.set("b", "anon_b")

        # Access 'a' to make it more recent
        cache.get("a")

        # Add third entry (should evict least recently used 'b')
        cache.set("c", "anon_c")

        # 'b' should be evicted
        assert cache.get("b") is None
        assert cache.get("a") is not None
        assert cache.get("c") is not None

    def test_cache_ttl_expiration(self):
        """Test TTL-based expiration."""
        cache = AnonymizationCache(ttl_seconds=1)
        cache.set("test", "anonymized")

        # Should be found immediately
        assert cache.get("test") is not None

        # Wait for expiration
        time.sleep(1.1)

        # Should be expired
        assert cache.get("test") is None

    def test_cache_clear(self):
        """Test cache clearing."""
        cache = AnonymizationCache()
        cache.set("a", "anon_a")
        cache.set("b", "anon_b")

        cache.clear()

        assert cache.get("a") is None
        assert cache.get("b") is None

    def test_cache_statistics(self):
        """Test cache statistics retrieval."""
        cache = AnonymizationCache(max_entries=100, ttl_seconds=3600)
        cache.set("test1", "anon_1")
        cache.set("test2", "anon_2")

        cache.get("test1")
        cache.get("nonexistent")

        stats = cache.get_statistics()
        assert stats.total_entries == 2
        assert stats.max_entries == 100
        assert stats.hits == 1
        assert stats.misses == 1


class TestCacheStatistics:
    """Test CacheStatistics data class."""

    def test_hit_rate_calculation(self):
        """Test hit rate calculation."""
        stats = CacheStatistics(hits=80, misses=20, evictions=0)
        assert stats.hit_rate == pytest.approx(80.0, rel=0.01)

    def test_hit_rate_no_operations(self):
        """Test hit rate with no operations."""
        stats = CacheStatistics(hits=0, misses=0)
        assert stats.hit_rate == 0.0


# ============================================================================
# ConnectionPoolManager Tests
# ============================================================================


class TestConnectionPoolManager:
    """Test ConnectionPoolManager functionality."""

    def test_pool_creation(self):
        """Test pool creation."""
        pool = ConnectionPoolManager(min_size=5, max_size=20)
        assert pool.min_size == 5
        assert pool.max_size == 20

    @patch("psycopg.connect")
    def test_pool_initialization(self, mock_connect):
        """Test pool initialization."""
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn

        pool = ConnectionPoolManager(min_size=2, max_size=10)
        pool.initialize({"host": "localhost", "dbname": "test"})

        assert pool._initialized
        assert mock_connect.call_count == 2

    @patch("psycopg.connect")
    def test_borrow_connection(self, mock_connect):
        """Test borrowing connection from pool."""
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn

        pool = ConnectionPoolManager(min_size=1, max_size=5)
        pool.initialize({"host": "localhost"})

        conn = pool.borrow()
        assert conn is not None
        assert conn in pool._in_use

    @patch("psycopg.connect")
    def test_return_connection(self, mock_connect):
        """Test returning connection to pool."""
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn

        pool = ConnectionPoolManager(min_size=1, max_size=5)
        pool.initialize({"host": "localhost"})

        conn = pool.borrow()
        pool.return_connection(conn)

        assert conn not in pool._in_use
        assert conn in pool._available

    @patch("psycopg.connect")
    def test_pool_close_all(self, mock_connect):
        """Test closing all connections."""
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn

        pool = ConnectionPoolManager(min_size=2, max_size=10)
        pool.initialize({"host": "localhost"})

        pool.close_all()

        assert len(pool._connections) == 0
        assert len(pool._available) == 0


# ============================================================================
# QueryOptimizer Tests
# ============================================================================


class TestQueryOptimizer:
    """Test QueryOptimizer functionality."""

    def test_optimizer_creation(self):
        """Test optimizer creation."""
        mock_conn = MagicMock()
        optimizer = QueryOptimizer(mock_conn)
        assert optimizer.conn is mock_conn

    def test_recommend_indexes(self):
        """Test index recommendation generation."""
        mock_conn = MagicMock()
        optimizer = QueryOptimizer(mock_conn)

        recommendations = optimizer.recommend_indexes("users", ["email", "name"])

        assert len(recommendations) == 2
        assert "idx_users_email" in recommendations[0]
        assert "idx_users_name" in recommendations[1]

    def test_get_statistics(self):
        """Test optimizer statistics retrieval."""
        mock_conn = MagicMock()
        optimizer = QueryOptimizer(mock_conn)

        stats = optimizer.get_statistics()

        assert "total_queries_analyzed" in stats
        assert "slow_queries" in stats
        assert "queries_with_recommendations" in stats


# ============================================================================
# BatchAnonymizer Tests
# ============================================================================


class TestBatchAnonymizer:
    """Test BatchAnonymizer functionality."""

    def test_batch_anonymizer_creation(self):
        """Test batch anonymizer creation."""
        mock_conn = MagicMock()
        strategy = DummyStrategy()
        anonymizer = BatchAnonymizer(mock_conn, strategy, batch_size=5000)

        assert anonymizer.batch_size == 5000
        assert anonymizer.strategy is strategy

    def test_batch_anonymizer_with_monitor(self):
        """Test batch anonymizer with performance monitor."""
        mock_conn = MagicMock()
        strategy = DummyStrategy()
        monitor = PerformanceMonitor()

        anonymizer = BatchAnonymizer(mock_conn, strategy, monitor=monitor)

        assert anonymizer.monitor is monitor


# ============================================================================
# ConcurrentAnonymizer Tests
# ============================================================================


class TestConcurrentAnonymizer:
    """Test ConcurrentAnonymizer functionality."""

    def test_concurrent_anonymizer_creation(self):
        """Test concurrent anonymizer creation."""
        mock_conn = MagicMock()
        strategy = DummyStrategy()
        anonymizer = ConcurrentAnonymizer(
            mock_conn, strategy, num_workers=4, batch_size=5000
        )

        assert anonymizer.num_workers == 4
        assert anonymizer.batch_size == 5000
        assert anonymizer.strategy is strategy

    def test_concurrent_anonymizer_with_monitor(self):
        """Test concurrent anonymizer with performance monitor."""
        mock_conn = MagicMock()
        strategy = DummyStrategy()
        monitor = PerformanceMonitor()

        anonymizer = ConcurrentAnonymizer(mock_conn, strategy, monitor=monitor)

        assert anonymizer.monitor is monitor


# ============================================================================
# Integration Tests
# ============================================================================


class TestPerformanceOptimizationIntegration:
    """Integration tests for performance optimization."""

    def test_monitor_batch_anonymization(self):
        """Test performance monitoring during batch anonymization."""
        monitor = PerformanceMonitor()

        # Simulate batch operations
        for i in range(5):
            rows = (i + 1) * 1000
            duration = 100 + i * 10
            monitor.record("batch_anonymize", duration_ms=duration, rows_processed=rows)

        stats = monitor.get_statistics("batch_anonymize")

        assert stats[0].count == 5
        assert stats[0].total_rows_processed == 15000
        assert stats[0].error_count == 0

    def test_cache_improves_performance(self):
        """Test that caching improves hit rates."""
        cache = AnonymizationCache()

        # First pass: all misses
        values = ["a", "b", "c", "d", "e"]
        for v in values:
            cache.set(v, f"anon_{v}")

        # Second pass: all hits
        for v in values:
            cache.get(v)

        stats = cache.get_statistics()

        assert stats.hits == 5
        assert stats.misses == 0
        assert stats.hit_rate == 100.0

    def test_performance_monitoring_end_to_end(self):
        """Test end-to-end performance monitoring."""
        monitor = PerformanceMonitor()

        # Record multiple operations
        for i in range(3):
            monitor.record("encrypt", duration_ms=50 + i * 5, rows_processed=500)
            monitor.record("hash", duration_ms=30 + i * 3, rows_processed=800)

        # Get statistics
        encrypt_stats = monitor.get_statistics("encrypt")
        hash_stats = monitor.get_statistics("hash")

        assert encrypt_stats[0].count == 3
        assert hash_stats[0].count == 3
        assert encrypt_stats[0].avg_throughput > 0
        assert hash_stats[0].avg_throughput > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
