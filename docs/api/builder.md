# SchemaBuilder API

[← Back to API Reference](index.md)

The `SchemaBuilder` class implements **Medium 1: Build from DDL**.

---

## Overview

SchemaBuilder discovers SQL files in your schema directory, concatenates them in deterministic order, and generates a complete schema. It uses a hybrid Python + Rust architecture for optimal performance.

**When to use**: Fresh database creation, local development, CI/CD pipelines.

---

## Quick Example

```python
from pathlib import Path
from confiture.core.builder import SchemaBuilder

# Initialize builder
builder = SchemaBuilder(env="local")

# Build schema
schema = builder.build()
print(f"Generated {len(schema)} bytes of SQL")

# Compute schema hash for version tracking
schema_hash = builder.compute_hash()
print(f"Schema version: {schema_hash[:12]}")
```

---

## Class Reference

### `SchemaBuilder`

```python
class SchemaBuilder:
    """Build database schema from DDL files."""

    def __init__(
        self,
        env: str = "local",
        project_dir: Path | str | None = None,
        config: Config | None = None,
    ) -> None:
        """
        Initialize schema builder.

        Args:
            env: Environment name (e.g., "local", "test", "production")
            project_dir: Project root directory. Defaults to current directory.
            config: Optional Config object. If provided, env and project_dir are ignored.

        Raises:
            ConfigurationError: If environment config not found.
        """
```

---

## Methods

### `build()`

Build complete schema from DDL files.

```python
def build(
    self,
    output_path: Path | str | None = None,
    include_seeds: bool = True,
) -> str:
    """
    Build schema by concatenating DDL files.

    Args:
        output_path: Optional path to write generated SQL.
            Defaults to db/generated/schema_{env}.sql
        include_seeds: Whether to include seed data files. Default True.

    Returns:
        Generated schema as SQL string.

    Raises:
        ConfigurationError: If schema directories not configured.
        FileNotFoundError: If schema directory doesn't exist.

    Example:
        >>> builder = SchemaBuilder(env="local")
        >>> schema = builder.build()
        >>> print(len(schema))
        15234
    """
```

**Example:**

```python
builder = SchemaBuilder(env="local")

# Build with defaults
schema = builder.build()

# Build to specific file without seeds
schema = builder.build(
    output_path="dist/schema.sql",
    include_seeds=False
)
```

---

### `build_async()`

Async version of `build()`.

```python
async def build_async(
    self,
    output_path: Path | str | None = None,
    include_seeds: bool = True,
) -> str:
    """
    Build schema asynchronously.

    Same parameters and behavior as build().
    """
```

**Example:**

```python
import asyncio

async def main():
    builder = SchemaBuilder(env="local")
    schema = await builder.build_async()
    print(f"Built {len(schema)} bytes")

asyncio.run(main())
```

---

### `find_sql_files()`

Discover SQL files in configured directories.

```python
def find_sql_files(
    self,
    directory: Path | str | None = None,
) -> list[Path]:
    """
    Find all SQL files in deterministic order.

    Files are sorted alphabetically. Use numbered prefixes
    (00_, 10_, 20_) to control execution order.

    Args:
        directory: Directory to search. Defaults to configured schema_dirs.

    Returns:
        List of Path objects to SQL files, sorted alphabetically.

    Example:
        >>> builder = SchemaBuilder(env="local")
        >>> files = builder.find_sql_files()
        >>> for f in files[:3]:
        ...     print(f.name)
        00_extensions.sql
        10_types.sql
        20_users.sql
    """
```

**Example:**

```python
builder = SchemaBuilder(env="local")
files = builder.find_sql_files()

print(f"Found {len(files)} SQL files:")
for f in files:
    print(f"  {f.relative_to(builder.project_dir)}")
```

---

### `compute_hash()`

Compute deterministic hash of schema content.

```python
def compute_hash(
    self,
    algorithm: str = "sha256",
) -> str:
    """
    Compute hash of schema for version tracking.

    The hash is deterministic: same files always produce same hash.
    Useful for detecting schema changes and versioning.

    Args:
        algorithm: Hash algorithm ("sha256", "md5", "sha1"). Default "sha256".

    Returns:
        Hexadecimal hash string.

    Example:
        >>> builder = SchemaBuilder(env="local")
        >>> hash = builder.compute_hash()
        >>> print(hash[:12])
        'a3b2c1d4e5f6'
    """
```

**Example:**

```python
builder = SchemaBuilder(env="local")

# Full hash
full_hash = builder.compute_hash()
print(f"Full: {full_hash}")

# Short version for display
short_hash = builder.compute_hash()[:12]
print(f"Version: {short_hash}")

# Different algorithm
md5_hash = builder.compute_hash(algorithm="md5")
```

---

### `validate()`

Validate schema syntax without executing.

```python
def validate(self) -> list[ValidationError]:
    """
    Validate schema SQL syntax.

    Parses all SQL files and checks for syntax errors without
    connecting to a database.

    Returns:
        List of ValidationError objects. Empty list if valid.

    Example:
        >>> builder = SchemaBuilder(env="local")
        >>> errors = builder.validate()
        >>> if errors:
        ...     for e in errors:
        ...         print(f"{e.file}:{e.line}: {e.message}")
    """
```

**Example:**

```python
builder = SchemaBuilder(env="local")
errors = builder.validate()

if errors:
    print("Schema has errors:")
    for err in errors:
        print(f"  {err.file}:{err.line}: {err.message}")
else:
    print("Schema is valid")
```

---

### `execute()`

Execute schema against a database.

```python
def execute(
    self,
    connection: psycopg.Connection | str,
    drop_existing: bool = False,
) -> ExecutionResult:
    """
    Execute schema against database.

    Args:
        connection: psycopg Connection or connection string.
        drop_existing: Drop existing objects before creating. Default False.

    Returns:
        ExecutionResult with timing and statistics.

    Raises:
        MigrationError: If execution fails.
        ConnectionError: If database connection fails.

    Example:
        >>> builder = SchemaBuilder(env="local")
        >>> result = builder.execute("postgresql://localhost/mydb")
        >>> print(f"Executed in {result.duration}")
    """
```

**Example:**

```python
import psycopg
from confiture.core.builder import SchemaBuilder

builder = SchemaBuilder(env="local")

# With connection string
result = builder.execute("postgresql://localhost/mydb")

# With existing connection
with psycopg.connect("postgresql://localhost/mydb") as conn:
    result = builder.execute(conn, drop_existing=True)

print(f"Duration: {result.duration}")
print(f"Tables created: {result.tables_created}")
```

---

## Data Classes

### `ExecutionResult`

```python
@dataclass
class ExecutionResult:
    """Result of schema execution."""

    duration: timedelta          # Total execution time
    tables_created: int          # Number of tables created
    indexes_created: int         # Number of indexes created
    views_created: int           # Number of views created
    functions_created: int       # Number of functions created
    bytes_executed: int          # Total SQL bytes executed
    warnings: list[str]          # Any warnings generated
```

### `ValidationError`

```python
@dataclass
class ValidationError:
    """Schema validation error."""

    file: Path                   # File containing error
    line: int                    # Line number
    column: int                  # Column number
    message: str                 # Error message
    severity: str                # "error" or "warning"
```

---

## Configuration

SchemaBuilder reads from environment config:

```yaml
# db/environments/local.yaml
name: local

database:
  host: localhost
  port: 5432
  database: myapp_local
  user: postgres
  password: postgres

# Directories to include (in order)
schema_dirs:
  - db/schema

# Seed data directories
seed_dirs:
  - db/seeds/common
  - db/seeds/development

# Directories to exclude
exclude_patterns:
  - "*.bak"
  - "*_deprecated*"
```

---

## Performance

SchemaBuilder uses Rust when available for significant performance improvements:

| Operation | Python | Rust | Speedup |
|-----------|--------|------|---------|
| File concatenation (100 files) | 120ms | 12ms | **10x** |
| SHA256 hashing (100 files) | 300ms | 10ms | **30x** |
| Large schema (1000 files) | 5s | 100ms | **50x** |

The implementation automatically falls back to pure Python if Rust is unavailable.

### Check Rust Status

```python
from confiture import has_rust_extension

if has_rust_extension():
    print("Using Rust acceleration")
else:
    print("Using pure Python")
```

---

## Error Handling

```python
from confiture.core.builder import SchemaBuilder
from confiture.exceptions import ConfigurationError, MigrationError

try:
    builder = SchemaBuilder(env="production")
    schema = builder.build()
except ConfigurationError as e:
    print(f"Config error: {e}")
except FileNotFoundError as e:
    print(f"Schema directory not found: {e}")

try:
    builder.execute("postgresql://localhost/mydb")
except MigrationError as e:
    print(f"Execution failed: {e}")
    print(f"Failed SQL: {e.sql[:100]}...")
```

---

## See Also

- [Medium 1: Build from DDL Guide](../guides/01-build-from-ddl.md) - User guide
- [Organizing SQL Files](../organizing-sql-files.md) - File structure patterns
- [CLI Reference: build command](../reference/cli.md#confiture-build) - CLI usage

---

**Last Updated**: January 17, 2026
