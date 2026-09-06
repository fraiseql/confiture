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


@pytest.fixture(autouse=True)
def _anonymization_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keyed strategies refuse to run without the per-deployment secret (D8)."""
    monkeypatch.setenv("ANONYMIZATION_SECRET", "benchmark-secret")


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
        assert rows_per_second > 10_000, (
            f"COPY performance too low: {rows_per_second:.0f} rows/sec (expected >10K)"
        )

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
        assert rows_per_second > 2_000, (
            f"Anonymization performance too low: {rows_per_second:.0f} rows/sec (expected >2K)"
        )

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
    assert avg_connection_time < 0.1, (
        f"Connection overhead too high: {avg_connection_time * 1000:.0f}ms"
    )


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


#: A checkpoint is one ``json.dump`` of a small dict. However slow the disk,
#: it does not cost a quarter of a second — that would mean a per-row or
#: per-batch flush, which is the regression this test exists to catch.
_MAX_CHECKPOINT_OVERHEAD_S = 0.25

#: Below this, a *ratio* of two sync durations measures scheduler jitter, not
#: checkpoint I/O: the whole sync is faster than the noise floor of the host.
_RATIO_NOISE_FLOOR_S = 0.025


@pytest.mark.benchmark
def test_checkpoint_overhead(benchmark_databases, tmp_path):
    """Measure checkpoint save overhead.

    This ensures resume functionality doesn't significantly impact performance.

    Timed like :func:`test_performance_consistency`, and for the same reason.
    Comparing *one* checkpointed sync against *one* plain sync measures which
    of the two ran first: the leader pays the cold page cache, uncached plans
    and whatever WAL the previous test file left postgres flushing. That
    difference is tens of milliseconds either way on a sync that itself takes
    tens of milliseconds, so the "overhead" swings from -50% to +150% run to
    run — it was reported *negative* about as often as positive, which is the
    tell that it was never measuring checkpoint I/O at all.

    Instead: warm up, then interleave the two configurations within each round
    so both meet the same host conditions, and compare medians. The assertion
    is on the absolute cost, because a JSON file write has an absolute budget;
    the ratio is only checked when the baseline clears the noise floor.
    """
    import statistics

    source_config, target_config = benchmark_databases
    checkpoint_file = tmp_path / "sync_checkpoint.json"

    # resume is False, so each run overwrites the checkpoint rather than
    # resuming from it — repeated rounds stay equivalent.
    config = SyncConfig(
        tables=TableSelection(include=["products"]),
        checkpoint_file=checkpoint_file,
    )
    config_no_checkpoint = SyncConfig(tables=TableSelection(include=["products"]))

    def _timed_sync(cfg: SyncConfig) -> float:
        with ProductionSyncer(source_config, target_config) as syncer:
            start = time.perf_counter()
            syncer.sync(cfg)
            return time.perf_counter() - start

    warmup_rounds = 2
    measured_rounds = 5
    with_checkpoint: list[float] = []
    without_checkpoint: list[float] = []

    for i in range(warmup_rounds + measured_rounds):
        d_with = _timed_sync(config)
        d_without = _timed_sync(config_no_checkpoint)
        if i < warmup_rounds:
            continue
        with_checkpoint.append(d_with)
        without_checkpoint.append(d_without)

    median_with = statistics.median(with_checkpoint)
    median_without = statistics.median(without_checkpoint)
    overhead = median_with - median_without

    print(f"\n📊 Checkpoint Overhead ({measured_rounds} rounds, {warmup_rounds} warmup):")
    print(f"  With checkpoint (median):    {median_with:.3f}s")
    print(f"  Without checkpoint (median): {median_without:.3f}s")
    print(f"  Overhead: {overhead:.3f}s")

    assert overhead < _MAX_CHECKPOINT_OVERHEAD_S, (
        f"Checkpoint overhead too high: {overhead * 1000:.0f}ms "
        f"(budget {_MAX_CHECKPOINT_OVERHEAD_S * 1000:.0f}ms)"
    )

    if median_without >= _RATIO_NOISE_FLOOR_S:
        overhead_pct = (overhead / median_without) * 100
        print(f"  Overhead: {overhead_pct:.1f}% of baseline")
        assert overhead_pct < 100, f"Checkpoint overhead too high: {overhead_pct:.1f}%"

    # Verify checkpoint file created
    assert checkpoint_file.exists()


@pytest.mark.benchmark
def test_performance_consistency(benchmark_databases):
    """Verify sync throughput is consistent across multiple runs.

    Measures coefficient of variation (stddev / mean) instead of
    ``(max - min) / mean`` — the latter is dominated by outliers that
    are routine on a contended developer laptop. The first few
    iterations are treated as warmup (caches cold, plans uncached,
    postgres still flushing WAL from prior test files) and discarded.

    The threshold is deliberately loose — the goal is to catch a
    catastrophic regression (e.g. 5–10× slowdown), not enforce
    millisecond stability that doesn't survive a busy host.
    """
    import math
    import statistics

    source_config, target_config = benchmark_databases

    warmup_iterations = 3
    measured_iterations = 10
    throughputs = []

    for i in range(warmup_iterations + measured_iterations):
        with ProductionSyncer(source_config, target_config) as syncer:
            start = time.perf_counter()
            rows_synced = syncer.sync_table("products")
            duration = time.perf_counter() - start
        if i < warmup_iterations:
            continue
        throughputs.append(rows_synced / duration)

    avg_throughput = statistics.fmean(throughputs)
    stddev = statistics.stdev(throughputs)
    cv_pct = (stddev / avg_throughput) * 100 if avg_throughput else math.inf

    print(
        f"\n📊 Performance Consistency "
        f"({measured_iterations} measured runs, {warmup_iterations} warmup):"
    )
    print(f"  Average: {avg_throughput:,.0f} rows/sec")
    print(f"  Min:     {min(throughputs):,.0f} rows/sec")
    print(f"  Max:     {max(throughputs):,.0f} rows/sec")
    print(f"  Stddev:  {stddev:,.0f} rows/sec")
    print(f"  CV:      {cv_pct:.1f}% (coefficient of variation)")

    # Loose desktop-friendly threshold. CV in isolation runs at 10–25%;
    # under sustained full-suite load (postgres still flushing WAL from
    # prior tests, page cache contended) it can spike to 60–80%. A
    # genuine regression here would manifest as 5–10× variance, not 2×.
    assert cv_pct < 150, f"Performance too inconsistent: CV={cv_pct:.1f}%"
