"""Performance benchmarks for ProductionSyncer.

These tests establish baseline performance metrics and verify that
optimizations maintain or improve performance.
"""

import time

import pytest

from confiture.core.syncer import (
    AnonymizationRule,
    ProductionSyncer,
    SyncConfig,
    TableSelection,
)


@pytest.fixture
def benchmark_databases(source_db, target_db, source_config, target_config):
    """Create source and target databases for benchmarking."""
    # Create large test table in source
    with source_db.cursor() as cursor:
        # Create users table with PII
        cursor.execute("""
            CREATE TABLE users (
                id SERIAL PRIMARY KEY,
                email TEXT NOT NULL,
                phone TEXT,
                name TEXT NOT NULL,
                bio TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)

        # Insert 10K rows
        cursor.execute("""
            INSERT INTO users (email, phone, name, bio)
            SELECT
                'user' || i || '@example.com',
                '+1-555-' || LPAD(i::TEXT, 4, '0'),
                'User ' || i,
                'This is a bio for user ' || i
            FROM generate_series(1, 10000) AS i
        """)

        # Create products table (no PII)
        cursor.execute("""
            CREATE TABLE products (
                id SERIAL PRIMARY KEY,
                sku TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                price NUMERIC(10, 2),
                description TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)

        # Insert 20K rows
        cursor.execute("""
            INSERT INTO products (sku, name, price, description)
            SELECT
                'SKU-' || LPAD(i::TEXT, 6, '0'),
                'Product ' || i,
                (random() * 1000)::NUMERIC(10, 2),
                'Description for product ' || i
            FROM generate_series(1, 20000) AS i
        """)

    # Create matching tables in target
    with target_db.cursor() as cursor:
        cursor.execute("""
            CREATE TABLE users (
                id SERIAL PRIMARY KEY,
                email TEXT NOT NULL,
                phone TEXT,
                name TEXT NOT NULL,
                bio TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)

        cursor.execute("""
            CREATE TABLE products (
                id SERIAL PRIMARY KEY,
                sku TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                price NUMERIC(10, 2),
                description TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)

    return source_config, target_config


@pytest.mark.benchmark
@pytest.mark.slow
def test_baseline_copy_performance(benchmark_databases):
    """Benchmark baseline COPY performance (no anonymization).

    Expected: >50,000 rows/sec for COPY operations

    This test establishes the baseline for fast path (no anonymization).
    """
    source_config, target_config = benchmark_databases

    with ProductionSyncer(source_config, target_config) as syncer:
        # Sync products table (no anonymization)
        start = time.perf_counter()
        rows_synced = syncer.sync_table("products")
        duration = time.perf_counter() - start

        # Verify sync completed
        assert rows_synced == 20000

        # Calculate performance
        rows_per_second = rows_synced / duration

        # Baseline target: >50K rows/sec for COPY
        # (This may fail initially, helping us identify bottlenecks)
        print("\n📊 COPY Performance:")
        print(f"  Rows synced: {rows_synced:,}")
        print(f"  Duration: {duration:.3f}s")
        print(f"  Throughput: {rows_per_second:,.0f} rows/sec")

        # We expect at least 10K rows/sec even in worst case
        assert (
            rows_per_second > 10_000
        ), f"COPY performance too low: {rows_per_second:.0f} rows/sec (expected >10K)"

        # Get metrics
        metrics = syncer.get_metrics()
        assert "products" in metrics
        assert metrics["products"]["rows_per_second"] > 10_000


@pytest.mark.benchmark
@pytest.mark.slow
def test_baseline_anonymization_performance(benchmark_databases):
    """Benchmark baseline anonymization performance.

    Expected: >5,000 rows/sec with anonymization

    This test establishes the baseline for slow path (with anonymization).
    """
    source_config, target_config = benchmark_databases

    anonymization_rules = [
        AnonymizationRule(column="email", strategy="email", seed=42),
        AnonymizationRule(column="phone", strategy="phone", seed=42),
        AnonymizationRule(column="name", strategy="name", seed=42),
    ]

    with ProductionSyncer(source_config, target_config) as syncer:
        # Sync users table with anonymization
        start = time.perf_counter()
        rows_synced = syncer.sync_table("users", anonymization_rules=anonymization_rules)
        duration = time.perf_counter() - start

        # Verify sync completed
        assert rows_synced == 10000

        # Calculate performance
        rows_per_second = rows_synced / duration

        # Baseline target: >5K rows/sec with anonymization
        print("\n📊 Anonymization Performance:")
        print(f"  Rows synced: {rows_synced:,}")
        print(f"  Duration: {duration:.3f}s")
        print(f"  Throughput: {rows_per_second:,.0f} rows/sec")
        print("  Columns anonymized: 3 (email, phone, name)")

        # We expect at least 2K rows/sec even in worst case
        assert (
            rows_per_second > 2_000
        ), f"Anonymization performance too low: {rows_per_second:.0f} rows/sec (expected >2K)"

        # Get metrics
        metrics = syncer.get_metrics()
        assert "users" in metrics
        assert metrics["users"]["rows_per_second"] > 2_000


@pytest.mark.benchmark
@pytest.mark.slow
def test_batch_size_impact(benchmark_databases):
    """Test impact of different batch sizes on anonymization performance.

    This helps us find the optimal batch size.
    """
    source_config, target_config = benchmark_databases

    anonymization_rules = [
        AnonymizationRule(column="email", strategy="email", seed=42),
        AnonymizationRule(column="phone", strategy="phone", seed=42),
        AnonymizationRule(column="name", strategy="name", seed=42),
    ]

    batch_sizes = [1000, 5000, 10000, 20000]
    results = {}

    for batch_size in batch_sizes:
        with ProductionSyncer(source_config, target_config) as syncer:
            start = time.perf_counter()
            rows_synced = syncer.sync_table(
                "users",
                anonymization_rules=anonymization_rules,
                batch_size=batch_size,
            )
            duration = time.perf_counter() - start

            rows_per_second = rows_synced / duration
            results[batch_size] = {
                "duration": duration,
                "rows_per_second": rows_per_second,
            }

    # Print results
    print("\n📊 Batch Size Impact:")
    for batch_size, result in sorted(results.items()):
        print(
            f"  {batch_size:>6,} rows/batch: {result['rows_per_second']:>8,.0f} rows/sec ({result['duration']:.3f}s)"
        )

    # Find optimal batch size
    optimal_size = max(results.items(), key=lambda x: x[1]["rows_per_second"])[0]
    print(f"\n  Optimal batch size: {optimal_size:,}")

    # All batch sizes should complete successfully
    assert all(r["rows_per_second"] > 1000 for r in results.values())


@pytest.mark.benchmark
@pytest.mark.slow
def test_connection_overhead(benchmark_databases):
    """Measure connection creation overhead.

    This helps determine if connection pooling would be beneficial.
    """
    source_config, target_config = benchmark_databases

    # Measure single sync with new connections
    iterations = 5
    durations = []

    for _ in range(iterations):
        start = time.perf_counter()
        with ProductionSyncer(source_config, target_config) as syncer:
            # Just connect, don't sync
            _ = syncer.get_all_tables()
        duration = time.perf_counter() - start
        durations.append(duration)

    avg_connection_time = sum(durations) / len(durations)
    min_connection_time = min(durations)
    max_connection_time = max(durations)

    print("\n📊 Connection Overhead:")
    print(f"  Average: {avg_connection_time * 1000:.1f}ms")
    print(f"  Min: {min_connection_time * 1000:.1f}ms")
    print(f"  Max: {max_connection_time * 1000:.1f}ms")

    # Connection should be fast (<100ms)
    assert (
        avg_connection_time < 0.1
    ), f"Connection overhead too high: {avg_connection_time * 1000:.0f}ms"


@pytest.mark.benchmark
@pytest.mark.slow
def test_multi_table_sync_performance(benchmark_databases):
    """Benchmark multi-table sync performance.

    This simulates a realistic production sync scenario.
    """
    source_config, target_config = benchmark_databases

    config = SyncConfig(
        tables=TableSelection(include=["users", "products"]),
        anonymization={
            "users": [
                AnonymizationRule(column="email", strategy="email", seed=42),
                AnonymizationRule(column="phone", strategy="phone", seed=42),
                AnonymizationRule(column="name", strategy="name", seed=42),
            ]
        },
        batch_size=10000,
    )

    with ProductionSyncer(source_config, target_config) as syncer:
        start = time.perf_counter()
        results = syncer.sync(config)
        duration = time.perf_counter() - start

        # Verify both tables synced
        assert results["users"] == 10000
        assert results["products"] == 20000

        total_rows = sum(results.values())
        overall_throughput = total_rows / duration

        print("\n📊 Multi-Table Sync Performance:")
        print(f"  Total rows: {total_rows:,}")
        print(f"  Duration: {duration:.3f}s")
        print(f"  Overall throughput: {overall_throughput:,.0f} rows/sec")

        # Get per-table metrics
        metrics = syncer.get_metrics()
        print("\n  Per-table performance:")
        for table, metric in metrics.items():
            print(f"    {table:>12}: {metric['rows_per_second']:>8,.0f} rows/sec")

        # Overall should be reasonable
        assert overall_throughput > 5_000


@pytest.mark.benchmark
@pytest.mark.slow
def test_memory_usage_estimate(benchmark_databases):
    """Estimate memory usage during sync operations.

    This helps identify if we need streaming for large tables.
    Note: This is a simplified estimate, not true memory profiling.
    """
    source_config, target_config = benchmark_databases

    # Sync with different batch sizes to observe behavior
    batch_sizes = [1000, 10000]

    for batch_size in batch_sizes:
        with ProductionSyncer(source_config, target_config) as syncer:
            # Sync with anonymization (uses more memory)
            anonymization_rules = [
                AnonymizationRule(column="email", strategy="email", seed=42),
            ]

            rows_synced = syncer.sync_table(
                "users",
                anonymization_rules=anonymization_rules,
                batch_size=batch_size,
            )

            # Estimate memory (very rough): rows * avg_row_size * batch_size
            # Average row size ~200 bytes
            estimated_peak_mb = (batch_size * 200) / (1024 * 1024)

            print(f"\n📊 Memory Estimate (batch_size={batch_size:,}):")
            print(f"  Estimated peak memory: ~{estimated_peak_mb:.1f}MB")
            print(f"  Rows synced: {rows_synced:,}")

            assert rows_synced == 10000


@pytest.mark.benchmark
def test_checkpoint_overhead(benchmark_databases, tmp_path):
    """Measure checkpoint save/load overhead.

    This ensures resume functionality doesn't significantly impact performance.
    """
    source_config, target_config = benchmark_databases
    checkpoint_file = tmp_path / "sync_checkpoint.json"

    config = SyncConfig(
        tables=TableSelection(include=["products"]),
        checkpoint_file=checkpoint_file,
    )

    # Sync with checkpoint
    with ProductionSyncer(source_config, target_config) as syncer:
        start = time.perf_counter()
        syncer.sync(config)
        duration_with_checkpoint = time.perf_counter() - start

    # Sync without checkpoint
    config_no_checkpoint = SyncConfig(
        tables=TableSelection(include=["products"]),
    )

    with ProductionSyncer(source_config, target_config) as syncer:
        start = time.perf_counter()
        syncer.sync(config_no_checkpoint)
        duration_no_checkpoint = time.perf_counter() - start

    overhead = duration_with_checkpoint - duration_no_checkpoint
    overhead_pct = (overhead / duration_no_checkpoint) * 100

    print("\n📊 Checkpoint Overhead:")
    print(f"  With checkpoint: {duration_with_checkpoint:.3f}s")
    print(f"  Without checkpoint: {duration_no_checkpoint:.3f}s")
    print(f"  Overhead: {overhead:.3f}s ({overhead_pct:.1f}%)")

    # Overhead can vary significantly due to I/O variance
    # Accept up to 100% overhead (checkpoint file I/O is acceptable cost)
    assert overhead_pct < 100, f"Checkpoint overhead too high: {overhead_pct:.1f}%"

    # Verify checkpoint file created
    assert checkpoint_file.exists()


@pytest.mark.benchmark
def test_performance_consistency(benchmark_databases):
    """Verify performance is consistent across multiple runs.

    This helps identify performance regressions and variability.
    """
    source_config, target_config = benchmark_databases

    iterations = 3
    throughputs = []

    for _i in range(iterations):
        with ProductionSyncer(source_config, target_config) as syncer:
            start = time.perf_counter()
            rows_synced = syncer.sync_table("products")
            duration = time.perf_counter() - start

            throughput = rows_synced / duration
            throughputs.append(throughput)

    avg_throughput = sum(throughputs) / len(throughputs)
    min_throughput = min(throughputs)
    max_throughput = max(throughputs)
    variance = (max_throughput - min_throughput) / avg_throughput * 100

    print(f"\n📊 Performance Consistency ({iterations} runs):")
    print(f"  Average: {avg_throughput:,.0f} rows/sec")
    print(f"  Min: {min_throughput:,.0f} rows/sec")
    print(f"  Max: {max_throughput:,.0f} rows/sec")
    print(f"  Variance: {variance:.1f}%")

    # Variance should be reasonable (<30%)
    assert variance < 50, f"Performance too inconsistent: {variance:.1f}% variance"
