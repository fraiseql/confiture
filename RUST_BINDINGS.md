# Rust Bindings for Confiture

**Status**: Planned for Phase 2
**Target Performance**: 10-100x improvement for large schemas (1000+ files)

## Overview

Confiture is designed with a clean Python/Rust hybrid architecture. Phase 1 implements core functionality in pure Python. Phase 2 will optimize performance-critical operations using Rust with PyO3 bindings.

## Architecture

```
┌─────────────────────────────────────────────┐
│           Python Layer (CLI/API)            │
│  - Typer CLI interface                      │
│  - High-level workflow orchestration        │
│  - Configuration management                 │
└──────────────┬──────────────────────────────┘
               │
               │ Python API calls
               │
┌──────────────▼──────────────────────────────┐
│         Python Core (Current)               │
│  - SchemaBuilder.find_sql_files()           │
│  - SchemaBuilder.build()                    │
│  - SchemaBuilder.compute_hash()             │
│  - SchemaDiffer.compare()                   │
└──────────────┬──────────────────────────────┘
               │
               │ FFI boundary (future)
               │
┌──────────────▼──────────────────────────────┐
│         Rust Core (Phase 2)                 │
│  - Fast file discovery (walkdir)            │
│  - Parallel file reading (rayon)            │
│  - Fast hashing (sha2)                      │
│  - SQL parsing (sqlparser-rs)               │
└─────────────────────────────────────────────┘
```

## Performance-Critical Functions

### 1. File Discovery (`find_sql_files`)

**Current Implementation**: Python `pathlib.rglob()`
**Target**: Rust `walkdir` crate

```rust
// rust/src/file_discovery.rs
use pyo3::prelude::*;
use walkdir::WalkDir;

#[pyfunction]
fn find_sql_files_rust(
    include_dirs: Vec<String>,
    exclude_dirs: Vec<String>,
) -> PyResult<Vec<String>> {
    let mut files = Vec::new();

    for include_dir in include_dirs {
        for entry in WalkDir::new(include_dir)
            .follow_links(false)
            .into_iter()
            .filter_map(|e| e.ok())
            .filter(|e| {
                e.path()
                    .extension()
                    .map(|ext| ext == "sql")
                    .unwrap_or(false)
            })
        {
            let path = entry.path().display().to_string();

            // Check if in excluded directory
            let is_excluded = exclude_dirs.iter().any(|ex| path.starts_with(ex));

            if !is_excluded {
                files.push(path);
            }
        }
    }

    files.sort();
    Ok(files)
}
```

**Expected Speedup**: 5-10x for 1000+ files

### 2. Schema Concatenation (`build`)

**Current Implementation**: Python string concatenation
**Target**: Rust parallel file reading with `rayon`

```rust
// rust/src/schema_builder.rs
use pyo3::prelude::*;
use rayon::prelude::*;
use std::fs;

#[pyfunction]
fn build_schema_rust(
    file_paths: Vec<String>,
    env_name: String,
) -> PyResult<String> {
    // Read files in parallel
    let contents: Vec<(String, String)> = file_paths
        .par_iter()
        .map(|path| {
            let content = fs::read_to_string(path)
                .expect(&format!("Failed to read {}", path));
            (path.clone(), content)
        })
        .collect();

    // Concatenate with headers (sequential, order matters)
    let mut schema = generate_header(&env_name, contents.len());

    for (path, content) in contents {
        schema.push_str(&format!("\n-- File: {}\n", path));
        schema.push_str(&content);
    }

    Ok(schema)
}

fn generate_header(env: &str, file_count: usize) -> String {
    format!(
        "-- PostgreSQL Schema\n\
         -- Environment: {}\n\
         -- Files: {}\n",
        env, file_count
    )
}
```

**Expected Speedup**: 3-5x for large schemas (parallel I/O)

### 3. Hash Computation (`compute_hash`)

**Current Implementation**: Python `hashlib.sha256`
**Target**: Rust `sha2` crate with parallel processing

```rust
// rust/src/hasher.rs
use pyo3::prelude::*;
use rayon::prelude::*;
use sha2::{Sha256, Digest};
use std::fs;

#[pyfunction]
fn compute_hash_rust(file_paths: Vec<String>) -> PyResult<String> {
    // Compute individual file hashes in parallel
    let file_hashes: Vec<Vec<u8>> = file_paths
        .par_iter()
        .map(|path| {
            let content = fs::read(path).expect("Failed to read file");

            let mut hasher = Sha256::new();
            hasher.update(path.as_bytes());
            hasher.update(&[0u8]); // Separator
            hasher.update(&content);

            hasher.finalize().to_vec()
        })
        .collect();

    // Combine hashes sequentially (order matters)
    let mut final_hasher = Sha256::new();
    for file_hash in file_hashes {
        final_hasher.update(&file_hash);
    }

    let result = final_hasher.finalize();
    Ok(format!("{:x}", result))
}
```

**Expected Speedup**: 10-20x for 1000+ files (parallel file I/O + hashing)

### 4. SQL Parsing (`compare` in SchemaDiffer)

**Current Implementation**: Python `sqlparse`
**Target**: Rust `sqlparser-rs` crate

```rust
// rust/src/parser.rs
use pyo3::prelude::*;
use sqlparser::dialect::PostgreSqlDialect;
use sqlparser::parser::Parser;

#[pyfunction]
fn parse_sql_rust(sql: String) -> PyResult<Vec<String>> {
    let dialect = PostgreSqlDialect {};

    match Parser::parse_sql(&dialect, &sql) {
        Ok(statements) => {
            let parsed: Vec<String> = statements
                .iter()
                .map(|stmt| format!("{:?}", stmt))
                .collect();
            Ok(parsed)
        }
        Err(e) => Err(PyErr::new::<pyo3::exceptions::PyValueError, _>(
            format!("SQL parsing error: {}", e)
        )),
    }
}
```

**Expected Speedup**: 50-100x (sqlparser-rs is significantly faster than sqlparse)

## Integration Strategy

### Phase 2.1: Infrastructure Setup

1. **Add Rust toolchain**:
   ```toml
   # Cargo.toml
   [package]
   name = "confiture-core"
   version = "0.2.0"
   edition = "2021"

   [lib]
   name = "confiture_core"
   crate-type = ["cdylib"]

   [dependencies]
   pyo3 = { version = "0.22", features = ["extension-module"] }
   walkdir = "2.5"
   rayon = "1.10"
   sha2 = "0.10"
   sqlparser = "0.52"
   ```

2. **Add maturin for building**:
   ```toml
   # pyproject.toml
   [build-system]
   requires = ["maturin>=1.0,<2.0"]
   build-backend = "maturin"
   ```

3. **Create rust/ directory structure**:
   ```
   rust/
   ├── Cargo.toml
   ├── src/
   │   ├── lib.rs              # PyO3 module definition
   │   ├── file_discovery.rs   # Fast file finding
   │   ├── schema_builder.rs   # Parallel schema building
   │   ├── hasher.rs           # Fast hashing
   │   └── parser.rs           # SQL parsing
   └── tests/
       └── integration_tests.rs
   ```

### Phase 2.2: Gradual Migration

**Week 1-2**: File Discovery
- Implement `find_sql_files_rust()` in Rust
- Add fallback to Python if Rust unavailable
- Benchmark and validate

**Week 3-4**: Schema Building
- Implement `build_schema_rust()` with parallel I/O
- Maintain compatibility with Python version
- Add integration tests

**Week 5-6**: Hash Computation
- Implement `compute_hash_rust()` with parallelism
- Ensure deterministic results match Python
- Performance benchmarks

**Week 7-8**: SQL Parsing
- Integrate sqlparser-rs
- Update SchemaDiffer to use Rust parser
- Extensive SQL compatibility testing

### Phase 2.3: Python Fallback Pattern

```python
# python/confiture/core/builder.py

try:
    from confiture_core import find_sql_files_rust  # Rust implementation
    HAS_RUST = True
except ImportError:
    HAS_RUST = False

class SchemaBuilder:
    def find_sql_files(self) -> list[Path]:
        """Discover SQL files (uses Rust if available)"""

        if HAS_RUST:
            # Fast Rust implementation
            include_dirs = [str(d) for d in self.include_dirs]
            exclude_dirs = [str(d) for d in self.env_config.exclude_dirs]

            file_paths = find_sql_files_rust(include_dirs, exclude_dirs)
            return [Path(p) for p in file_paths]
        else:
            # Python fallback
            return self._find_sql_files_python()

    def _find_sql_files_python(self) -> list[Path]:
        """Pure Python implementation (current)"""
        # ... existing code ...
```

## Performance Targets

### Baseline (Phase 1 - Pure Python)

| Operation | 10 files | 100 files | 1000 files |
|-----------|----------|-----------|------------|
| File discovery | 5ms | 50ms | 500ms |
| Schema build | 10ms | 100ms | 1000ms |
| Hash computation | 8ms | 80ms | 800ms |
| Total | 23ms | 230ms | 2300ms |

### Target (Phase 2 - Rust Core)

| Operation | 10 files | 100 files | 1000 files |
|-----------|----------|-----------|------------|
| File discovery | 1ms | 5ms | 50ms |
| Schema build | 3ms | 20ms | 200ms |
| Hash computation | 2ms | 8ms | 80ms |
| Total | 6ms | 33ms | 330ms |

**Overall Speedup**: 3-7x depending on workload size

### Benchmark Suite

```rust
// rust/benches/schema_builder.rs
use criterion::{black_box, criterion_group, criterion_main, Criterion};
use confiture_core::*;

fn benchmark_file_discovery(c: &mut Criterion) {
    c.bench_function("find_sql_files_1000", |b| {
        b.iter(|| {
            find_sql_files_rust(
                black_box(vec!["db/schema".to_string()]),
                black_box(vec![]),
            )
        })
    });
}

fn benchmark_hash_computation(c: &mut Criterion) {
    let files = generate_test_files(1000);

    c.bench_function("compute_hash_1000", |b| {
        b.iter(|| {
            compute_hash_rust(black_box(files.clone()))
        })
    });
}

criterion_group!(benches, benchmark_file_discovery, benchmark_hash_computation);
criterion_main!(benches);
```

## Deployment Strategy

### Wheel Distribution

**Pure Python wheel** (Phase 1):
- Works on all platforms
- No compilation required
- Slower performance

**Rust-accelerated wheels** (Phase 2):
- Built for: `manylinux_2_28`, `macosx_11_0`, `win_amd64`
- Include compiled Rust extensions
- 10-100x faster
- Graceful fallback to Python if Rust unavailable

### CI/CD Pipeline

```yaml
# .github/workflows/release.yml
name: Build and Release

on:
  release:
    types: [published]

jobs:
  build-wheels:
    runs-on: ${{ matrix.os }}
    strategy:
      matrix:
        os: [ubuntu-latest, macos-latest, windows-latest]

    steps:
      - uses: actions/checkout@v4

      - name: Build wheels
        uses: PyO3/maturin-action@v1
        with:
          command: build
          args: --release --out dist

      - name: Upload wheels
        uses: actions/upload-artifact@v4
        with:
          name: wheels-${{ matrix.os }}
          path: dist/*.whl
```

## Testing Strategy

### Compatibility Tests

Ensure Python and Rust implementations produce **identical** results:

```python
# tests/test_rust_compat.py
import pytest
from confiture.core.builder import SchemaBuilder

def test_find_sql_files_rust_matches_python(tmp_path):
    """Rust and Python implementations must return identical results"""
    builder = SchemaBuilder(env="test", project_dir=tmp_path)

    # Get results from both implementations
    python_files = builder._find_sql_files_python()
    rust_files = builder._find_sql_files_rust()

    assert python_files == rust_files

def test_hash_computation_rust_matches_python(tmp_path):
    """Hashes must be deterministic across implementations"""
    builder = SchemaBuilder(env="test", project_dir=tmp_path)

    python_hash = builder._compute_hash_python()
    rust_hash = builder._compute_hash_rust()

    assert python_hash == rust_hash
```

### Performance Regression Tests

```python
# tests/test_performance.py
import time
import pytest

@pytest.mark.benchmark
def test_build_large_schema_performance(tmp_path):
    """Ensure build completes in reasonable time"""
    # Create 1000 table files
    create_large_schema(tmp_path, num_tables=1000)

    builder = SchemaBuilder(env="test", project_dir=tmp_path)

    start = time.perf_counter()
    schema = builder.build()
    duration = time.perf_counter() - start

    # Python: <2s, Rust: <500ms
    assert duration < 2.0  # Adjust based on implementation
```

## Migration Checklist

- [ ] Infrastructure Setup
  - [ ] Add Cargo.toml
  - [ ] Configure maturin in pyproject.toml
  - [ ] Create rust/ directory structure
  - [ ] Set up CI for wheel building

- [ ] File Discovery Migration
  - [ ] Implement find_sql_files_rust()
  - [ ] Add Python fallback logic
  - [ ] Write compatibility tests
  - [ ] Benchmark performance

- [ ] Schema Building Migration
  - [ ] Implement build_schema_rust() with rayon
  - [ ] Test parallel file reading
  - [ ] Validate output matches Python
  - [ ] Performance benchmarks

- [ ] Hash Computation Migration
  - [ ] Implement compute_hash_rust()
  - [ ] Ensure deterministic results
  - [ ] Test with large file sets
  - [ ] Benchmark parallel hashing

- [ ] SQL Parser Migration
  - [ ] Integrate sqlparser-rs
  - [ ] Update SchemaDiffer
  - [ ] PostgreSQL compatibility tests
  - [ ] Performance comparison

- [ ] Documentation
  - [ ] Update README with Rust benefits
  - [ ] Document installation (pip vs maturin)
  - [ ] Add performance benchmarks to docs
  - [ ] Migration guide for contributors

## Resources

- **PyO3**: https://pyo3.rs/
- **maturin**: https://www.maturin.rs/
- **sqlparser-rs**: https://github.com/sqlparser-rs/sqlparser-rs
- **walkdir**: https://docs.rs/walkdir/
- **rayon**: https://docs.rs/rayon/
- **sha2**: https://docs.rs/sha2/

## Timeline

- **Phase 1** (Current): Pure Python MVP - 4 weeks
- **Phase 2.1**: Rust infrastructure setup - 1 week
- **Phase 2.2**: Core optimizations (file discovery, hashing) - 3 weeks
- **Phase 2.3**: SQL parser integration - 2 weeks
- **Phase 2.4**: Benchmarking and polish - 1 week

**Total**: ~11 weeks for complete Rust integration

---

**Last Updated**: October 11, 2025
**Status**: Planning document - implementation starts after Phase 1 completion
**Author**: Lionel Hamayon (@evoludigit)
