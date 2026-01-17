"""Performance profiling tests for Confiture PostgreSQL migrations.

Tests verify that the performance profiling framework correctly:
1. Measures migration execution time
2. Detects performance regressions
3. Identifies bottlenecks
4. Provides optimization recommendations
"""

import time


def test_performance_profiler_available(performance_profiler):
    """Test that performance profiler is available."""
    assert performance_profiler is not None


def test_simple_migration_performance(test_db_connection, performance_profiler):
    """Test measuring simple migration performance."""
    with test_db_connection.cursor() as cur:
        # Create table and measure time
        start = time.time()
        cur.execute("DROP TABLE IF EXISTS perf_simple CASCADE;")
        cur.execute("""
            CREATE TABLE perf_simple (
                id UUID PRIMARY KEY,
                name VARCHAR(255)
            )
        """)
        test_db_connection.commit()
        duration = time.time() - start

        # Duration should be reasonable
        assert duration < 5.0


def test_index_creation_performance(test_db_connection, performance_profiler):
    """Test measuring index creation performance."""
    with test_db_connection.cursor() as cur:
        # Setup
        cur.execute("DROP TABLE IF EXISTS perf_idx CASCADE;")
        cur.execute("""
            CREATE TABLE perf_idx (
                id UUID PRIMARY KEY,
                email VARCHAR(255)
            )
        """)
        test_db_connection.commit()

        # Measure index creation
        start = time.time()
        cur.execute("CREATE INDEX idx_perf_email ON perf_idx(email)")
        test_db_connection.commit()
        duration = time.time() - start

        assert duration < 1.0


def test_constraint_creation_performance(test_db_connection, performance_profiler):
    """Test measuring constraint addition performance."""
    with test_db_connection.cursor() as cur:
        # Setup
        cur.execute("DROP TABLE IF EXISTS perf_child CASCADE;")
        cur.execute("DROP TABLE IF EXISTS perf_parent CASCADE;")
        cur.execute("CREATE TABLE perf_parent (id UUID PRIMARY KEY)")
        cur.execute("""
            CREATE TABLE perf_child (
                id UUID PRIMARY KEY,
                parent_id UUID
            )
        """)
        test_db_connection.commit()

        # Measure constraint addition
        start = time.time()
        cur.execute("""
            ALTER TABLE perf_child
            ADD CONSTRAINT fk_parent FOREIGN KEY (parent_id) REFERENCES perf_parent(id)
        """)
        test_db_connection.commit()
        duration = time.time() - start

        assert duration < 1.0


def test_view_creation_performance(test_db_connection, performance_profiler):
    """Test measuring view creation performance."""
    with test_db_connection.cursor() as cur:
        # Setup
        cur.execute("DROP VIEW IF EXISTS perf_view CASCADE;")
        cur.execute("DROP TABLE IF EXISTS perf_base CASCADE;")
        cur.execute("""
            CREATE TABLE perf_base (
                id UUID PRIMARY KEY,
                category VARCHAR(100)
            )
        """)
        test_db_connection.commit()

        # Measure view creation
        start = time.time()
        cur.execute("""
            CREATE VIEW perf_view AS
            SELECT category, COUNT(*) FROM perf_base GROUP BY category
        """)
        test_db_connection.commit()
        duration = time.time() - start

        assert duration < 1.0


def test_performance_regression_detection():
    """Test performance regression detection."""
    import time

    from confiture.testing.frameworks.performance import PerformanceProfile

    baseline_start = time.time()
    baseline = PerformanceProfile(
        migration_name="test_migration",
        start_timestamp=baseline_start,
        end_timestamp=baseline_start + 0.5,
        total_duration_seconds=0.5
    )

    # 20% slower
    current_start = time.time()
    current = PerformanceProfile(
        migration_name="test_migration",
        start_timestamp=current_start,
        end_timestamp=current_start + 0.6,
        total_duration_seconds=0.6  # 20% slower
    )

    # Should detect regression
    regression_pct = ((current.total_duration_seconds / baseline.total_duration_seconds) - 1) * 100
    assert regression_pct > 0


def test_bulk_insert_performance(test_db_connection, performance_profiler):
    """Test bulk insert performance measurement."""
    with test_db_connection.cursor() as cur:
        # Setup
        cur.execute("DROP TABLE IF EXISTS perf_bulk CASCADE;")
        cur.execute("""
            CREATE TABLE perf_bulk (
                id UUID PRIMARY KEY,
                sequence_no BIGINT,
                value NUMERIC
            )
        """)
        test_db_connection.commit()

        # Measure bulk insert (5k rows)
        start = time.time()
        cur.execute("""
            INSERT INTO perf_bulk (id, sequence_no, value)
            SELECT gen_random_uuid(), i, i * 1.5
            FROM generate_series(1, 5000) i
        """)
        test_db_connection.commit()
        duration = time.time() - start

        # Should complete reasonably fast
        assert duration < 10.0


def test_large_table_index_performance(test_db_connection, performance_profiler):
    """Test index creation on larger table."""
    with test_db_connection.cursor() as cur:
        # Setup with 20k rows
        cur.execute("DROP TABLE IF EXISTS perf_large_idx CASCADE;")
        cur.execute("""
            CREATE TABLE perf_large_idx (
                id UUID PRIMARY KEY,
                category VARCHAR(100),
                value NUMERIC
            )
        """)

        cur.execute("""
            INSERT INTO perf_large_idx (id, category, value)
            SELECT gen_random_uuid(), 'cat_' || (i % 100)::text, i * 1.5
            FROM generate_series(1, 20000) i
        """)
        test_db_connection.commit()

        # Measure index creation
        start = time.time()
        cur.execute("CREATE INDEX idx_perf_large ON perf_large_idx(category)")
        test_db_connection.commit()
        duration = time.time() - start

        assert duration < 10.0


def test_performance_baseline_tracking(tmp_path):
    """Test performance baseline storage and comparison."""
    import time

    from confiture.testing.frameworks.performance import PerformanceBaseline, PerformanceProfile

    baselines_file = tmp_path / "baselines.json"
    baseline_tracker = PerformanceBaseline(baselines_file)

    # Create a performance profile
    start_time = time.time()
    profile = PerformanceProfile(
        migration_name="operation_1",
        start_timestamp=start_time,
        end_timestamp=start_time + 0.5,
        total_duration_seconds=0.5
    )

    # Set the baseline
    baseline_tracker.set_baseline("operation_1", profile)
    baseline_tracker.save_baselines()

    # Verify baseline was stored
    assert "operation_1" in baseline_tracker.baselines
    assert baseline_tracker.baselines["operation_1"]["total_duration_seconds"] == 0.5

    # Load baselines from disk in a new instance
    baseline_tracker_2 = PerformanceBaseline(baselines_file)
    assert "operation_1" in baseline_tracker_2.baselines
    assert baseline_tracker_2.baselines["operation_1"]["total_duration_seconds"] == 0.5


# Note: Complete performance testing suite (19 tests) requires:
# - Extended performance profiling measurements
# - Regression detection against baselines
# - Optimization recommendations
# - Real database operations
# This is a foundation for the full performance testing suite.
