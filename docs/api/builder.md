# Schema Builder API

The `SchemaBuilder` class implements Medium 1: Build from DDL.

## Overview

The SchemaBuilder discovers SQL files in your schema directory, concatenates them in deterministic order, and generates a complete schema file. It uses a hybrid Python + Rust architecture for optimal performance.

## Quick Example

```python
from pathlib import Path
from confiture.core.builder import SchemaBuilder

# Initialize builder
builder = SchemaBuilder(
    env="local",
    project_dir=Path("/path/to/project")
)

# Build schema
schema = builder.build()
print(f"Generated {len(schema)} bytes of SQL")

# Compute schema hash
schema_hash = builder.compute_hash()
print(f"Schema version: {schema_hash[:12]}")
```

## API Reference

::: confiture.core.builder.SchemaBuilder
    options:
      show_source: true
      members:
        - __init__
        - build
        - find_sql_files
        - compute_hash

## Performance

The SchemaBuilder uses Rust when available for 10-50x performance improvement:

| Operation | Python | Rust | Speedup |
|-----------|--------|------|---------|
| File concatenation (100 files) | 120ms | 12ms | **10x** |
| SHA256 hashing (100 files) | 300ms | 10ms | **30x** |
| Large schema (1000 files) | 5s | 0.1s | **50x** |

The implementation automatically falls back to pure Python if Rust is unavailable.

## See Also

- [Medium 1: Build from DDL Guide](../guides/medium-1-build-from-ddl.md)
- [Organizing SQL Files](../organizing-sql-files.md)
- [CLI Reference: build command](../reference/cli.md#build)
