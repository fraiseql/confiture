# Performance Benchmarks

This directory contains performance benchmarks for Confiture's core components.

## 📊 Running Benchmarks

### Quick Start

Run all performance benchmarks:

```bash
uv run pytest tests/performance/ -v -s
```

Run specific benchmark:

```bash
uv run pytest tests/performance/test_syncer_benchmarks.py::test_baseline_copy_performance -v -s
```

### Requirements

- PostgreSQL server running locally
- Two test databases:
  - `confiture_source_test`
  - `confiture_target_test`

Create databases:

```bash
createdb confiture_source_test
createdb confiture_target_test
```

Or use custom URLs:

```bash
export CONFITURE_SOURCE_DB_URL="postgresql://localhost/my_source_db"
export CONFITURE_TARGET_DB_URL="postgresql://localhost/my_target_db"
```

## 📈 Benchmark Suites

### 1. Syncer Benchmarks (`test_syncer_benchmarks.py`)

Tests ProductionSyncer performance:

#### `test_baseline_copy_performance`
- Measures COPY throughput (no anonymization)
- Expected: >50,000 rows/sec
- **Current: ~70,000 rows/sec** ✅

#### `test_baseline_anonymization_performance`
- Measures anonymization throughput (3 columns)
- Expected: >5,000 rows/sec
- **Current: ~6,500 rows/sec** ✅

#### `test_batch_size_impact`
- Finds optimal batch size for anonymization
- Tests: 1K, 5K, 10K, 20K rows/batch
- **Optimal: 5,000 rows/batch**

#### `test_connection_overhead`
- Measures database connection creation time
- Expected: <100ms
- **Current: ~29ms** ✅

#### `test_multi_table_sync_performance`
- Realistic multi-table sync scenario
- Mixed workload (COPY + anonymization)
- **Current: ~10,600 rows/sec overall** ✅

#### `test_memory_usage_estimate`
- Estimates memory usage by batch size
- Ensures bounded memory usage
- **Current: ~1MB for 5K batch** ✅

#### `test_checkpoint_overhead`
- Measures resume functionality overhead
- Expected: <20% overhead
- **Current: ~10% overhead** ✅

#### `test_performance_consistency`
- Validates performance stability
- Runs 3 iterations, measures variance
- **Current: 41% variance** ⚠️ (acceptable)

### 2. Builder Benchmarks (`test_rust_speedup.py`)

Tests SchemaBuilder performance:

- `test_build_performance`: Schema concatenation speed
- `test_hash_performance`: Hash computation speed
- `test_repeated_operations_performance`: Memory leak detection
- `test_rust_extension_availability`: Rust extension check

## 🎯 Benchmark Results Summary

### Current Performance (v0.2.0-alpha)

| Benchmark | Result | Status |
|-----------|--------|--------|
| COPY throughput | 70,396 rows/sec | ✅ Excellent |
| Anonymization (3 cols) | 6,515 rows/sec | ✅ Good |
| Optimal batch size | 5,000 rows | ✅ Optimized |
| Connection overhead | 29ms | ✅ Low |
| Multi-table sync | 10,645 rows/sec | ✅ Good |
| Memory usage (5K batch) | ~1 MB | ✅ Bounded |
| Checkpoint overhead | 9.7% | ✅ Low |
| Performance variance | 41.2% | ⚠️ Acceptable |

## 🔬 Interpreting Results

### Throughput Metrics

**Rows per second** is the primary metric:
- **>50K r/s**: Excellent (COPY path)
- **5K-10K r/s**: Good (anonymization path)
- **<2K r/s**: Poor (investigate bottlenecks)

### Variance

**Performance variance** measures consistency across runs:
- **<20%**: Excellent consistency
- **20-50%**: Acceptable (real-world conditions)
- **>50%**: High variance (investigate external factors)

Common causes of variance:
- Background processes
- Database load
- Network conditions
- System caching

### Memory Usage

**Peak memory** should remain bounded:
- **<10 MB**: Excellent
- **10-100 MB**: Good
- **>100 MB**: Consider streaming for large tables

## 🛠️ Customizing Benchmarks

### Change Test Data Size

Edit `benchmark_databases` fixture in `test_syncer_benchmarks.py`:

```python
# Current: 10K users, 20K products
cursor.execute("""
    INSERT INTO users (...)
    FROM generate_series(1, 10000) AS i  -- Change this number
""")
```

### Add New Benchmark

Follow TDD methodology:

```python
@pytest.mark.benchmark
@pytest.mark.slow
def test_my_new_benchmark(benchmark_databases):
    """Test description and expected results."""
    source_config, target_config = benchmark_databases

    with ProductionSyncer(source_config, target_config) as syncer:
        start = time.perf_counter()
        # ... your benchmark code ...
        duration = time.perf_counter() - start

        print(f"\n📊 My Benchmark:")
        print(f"  Duration: {duration:.3f}s")

        assert duration < 5.0, "Should complete in <5s"
```

### Profile CPU Usage

Use cProfile:

```python
import cProfile
cProfile.run('syncer.sync_table("users")', 'profile_output.prof')

# Analyze results
python -m pstats profile_output.prof
```

### Profile Memory Usage

Use memory_profiler:

```bash
pip install memory-profiler
python -m memory_profiler python/confiture/core/syncer.py
```

## 📊 Benchmark History

Track performance over time in `docs/performance.md`.

### October 2025 - Milestone 3.6

**Optimizations**:
1. ✅ Changed default batch size from 10,000 → 5,000 rows
   - Improvement: ~19% faster anonymization
2. ✅ Analyzed connection pooling (not beneficial currently)
3. ✅ Validated memory usage is bounded

**Results**:
- COPY: 70K rows/sec (baseline established)
- Anonymization: 6.5K rows/sec (improved from 5.5K)
- Batch size: 5K optimal (empirically determined)

## 🎯 Performance Goals

### Short Term (Phase 3)

- [x] Establish baseline metrics
- [x] Optimize batch size
- [x] Document performance characteristics
- [ ] Reduce variance to <30%

### Long Term (Phase 4+)

- [ ] Rust-based anonymization (10-50x faster)
- [ ] Parallel table sync
- [ ] Connection pooling for high-frequency syncs
- [ ] Streaming for very large tables (>10M rows)

## 🐛 Troubleshooting

### Tests Fail with "PostgreSQL not available"

Ensure PostgreSQL is running:

```bash
pg_isready
# Should return: /tmp:5432 - accepting connections
```

Create test databases:

```bash
createdb confiture_source_test
createdb confiture_target_test
```

### Slow Test Execution

Benchmarks are marked `@pytest.mark.slow` - skip them for quick tests:

```bash
pytest -m "not slow"
```

### Inconsistent Results

Performance can vary based on:
- System load (close other applications)
- Database caching (first run may be slower)
- Network conditions (use local PostgreSQL)

Run multiple iterations for stable average:

```bash
for i in {1..5}; do
  pytest tests/performance/test_syncer_benchmarks.py::test_baseline_copy_performance
done
```

## 📚 Resources

- [Performance Guide](../../docs/performance.md) - Complete performance documentation
- [Production Sync Guide](../../docs/production-sync.md) - Production usage guide
- [psycopg3 Documentation](https://www.psycopg.org/psycopg3/docs/) - Database driver details

---

**Maintained By**: Confiture Core Team
**Last Updated**: October 2025
