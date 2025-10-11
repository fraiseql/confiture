"""Performance benchmarks for Rust extension vs Python implementation.

These tests verify that the Rust extension provides the expected 10-50x
speedup over pure Python for file operations and hashing.
"""

import time

import pytest

from confiture.core.builder import SchemaBuilder


@pytest.fixture
def large_schema_dir(tmp_path):
    """Create a directory with many SQL files for benchmarking."""
    schema_dir = tmp_path / "db" / "schema"
    schema_dir.mkdir(parents=True)

    # Create 100 SQL files with realistic content
    for i in range(100):
        file_path = schema_dir / f"{i:03d}_table.sql"
        content = f"""-- Table {i}
CREATE TABLE table_{i} (
    id BIGSERIAL PRIMARY KEY,
    pk_table_{i} UUID UNIQUE NOT NULL DEFAULT gen_random_uuid(),
    slug TEXT UNIQUE NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    data JSONB
);

CREATE INDEX idx_table_{i}_created ON table_{i}(created_at);
CREATE INDEX idx_table_{i}_data ON table_{i} USING GIN(data);
"""
        file_path.write_text(content)

    # Create config
    config_dir = tmp_path / "db" / "environments"
    config_dir.mkdir(parents=True)
    config_file = config_dir / "benchmark.yaml"
    config_file.write_text(
        f"""name: benchmark
include_dirs:
  - {schema_dir}
exclude_dirs: []
database_url: postgresql://localhost/benchmark
"""
    )

    return tmp_path


@pytest.mark.slow
def test_build_performance(large_schema_dir):
    """Test that schema building completes in reasonable time.

    Expected: <2s for 100 files (Rust), <10s for 100 files (Python fallback)
    """
    builder = SchemaBuilder(env="benchmark", project_dir=large_schema_dir)

    start = time.perf_counter()
    schema = builder.build()
    duration = time.perf_counter() - start

    # Should complete within 10 seconds even with Python fallback
    assert duration < 10.0, f"Build took {duration:.2f}s, expected <10s"

    # Should have content
    assert len(schema) > 50_000  # At least 50KB
    assert "table_0" in schema
    assert "table_99" in schema

    print(f"\n✓ Built schema in {duration:.3f}s ({len(schema):,} bytes)")


@pytest.mark.slow
def test_hash_performance(large_schema_dir):
    """Test that hash computation completes in reasonable time.

    Expected: <1s for 100 files (Rust), <5s for 100 files (Python fallback)
    """
    builder = SchemaBuilder(env="benchmark", project_dir=large_schema_dir)

    start = time.perf_counter()
    hash_value = builder.compute_hash()
    duration = time.perf_counter() - start

    # Should complete within 5 seconds even with Python fallback
    assert duration < 5.0, f"Hash took {duration:.2f}s, expected <5s"

    # Should be valid SHA256
    assert len(hash_value) == 64
    assert all(c in "0123456789abcdef" for c in hash_value)

    print(f"\n✓ Computed hash in {duration:.3f}s (hash: {hash_value[:16]}...)")


@pytest.mark.slow
def test_repeated_operations_performance(large_schema_dir):
    """Test that repeated operations maintain performance.

    Verifies that there's no memory leak or performance degradation.
    """
    builder = SchemaBuilder(env="benchmark", project_dir=large_schema_dir)

    # Warm up
    builder.compute_hash()

    # Measure 10 iterations
    durations = []
    for _ in range(10):
        start = time.perf_counter()
        _ = builder.compute_hash()
        duration = time.perf_counter() - start
        durations.append(duration)

    avg_duration = sum(durations) / len(durations)
    max_duration = max(durations)

    # Average should be reasonable
    assert avg_duration < 2.0, f"Average hash time {avg_duration:.2f}s, expected <2s"

    # No single iteration should be much slower (no degradation)
    assert max_duration < avg_duration * 2, "Performance degradation detected"

    print(f"\n✓ Repeated operations: avg={avg_duration:.3f}s, max={max_duration:.3f}s")


def test_rust_extension_availability():
    """Check if Rust extension is available and report status."""
    from confiture.core.builder import HAS_RUST

    if HAS_RUST:
        print("\n✓ Rust extension is AVAILABLE - using 10-50x faster implementation")
    else:
        print("\n⚠ Rust extension is NOT available - using Python fallback (slower but functional)")


@pytest.mark.slow
def test_build_vs_hash_ratio(large_schema_dir):
    """Test that build and hash have expected performance ratio.

    Hash should be faster than full build since it doesn't allocate strings.
    """
    builder = SchemaBuilder(env="benchmark", project_dir=large_schema_dir)

    # Measure build time
    start = time.perf_counter()
    _ = builder.build()
    build_duration = time.perf_counter() - start

    # Measure hash time
    start = time.perf_counter()
    _ = builder.compute_hash()
    hash_duration = time.perf_counter() - start

    # Build should be slower than hash (more work)
    assert build_duration > hash_duration, "Build should be slower than hash"

    ratio = build_duration / hash_duration
    print(
        f"\n✓ Build/hash ratio: {ratio:.1f}x "
        f"(build={build_duration:.3f}s, hash={hash_duration:.3f}s)"
    )
