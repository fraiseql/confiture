# ProductionSyncer API

[← Back to API Reference](index.md)

The `ProductionSyncer` class implements **Medium 3: Production Data Sync**.

---

## Overview

ProductionSyncer copies data from production to staging/local environments with built-in PII anonymization. It uses PostgreSQL's COPY protocol for high-performance streaming.

**When to use**: Getting realistic test data from production while protecting PII.

---

## Quick Example

```python
from confiture.core.syncer import ProductionSyncer

config = {
    "tables": ["users", "orders"],
    "anonymize": {
        "users": {"email": "email", "phone": "phone"}
    }
}

with ProductionSyncer(source="production", target="local") as syncer:
    results = syncer.sync(config)

    for table, stats in results.items():
        print(f"{table}: {stats['rows']} rows ({stats['duration']})")
```

---

## Class Reference

### `ProductionSyncer`

```python
class ProductionSyncer:
    """Sync production data with PII anonymization."""

    def __init__(
        self,
        source: str | psycopg.Connection,
        target: str | psycopg.Connection,
        config: Config | None = None,
    ) -> None:
        """
        Initialize production syncer.

        Args:
            source: Source environment name or connection.
            target: Target environment name or connection.
            config: Optional Config object.

        Raises:
            ConnectionError: If database connection fails.
            ConfigurationError: If environment not found.
        """

    def __enter__(self) -> "ProductionSyncer":
        """Context manager entry."""

    def __exit__(self, *args) -> None:
        """Context manager exit - closes connections."""
```

---

## Methods

### `sync()`

Sync all configured tables.

```python
def sync(
    self,
    config: SyncConfig | dict,
    resume: bool = False,
) -> dict[str, SyncResult]:
    """
    Sync tables from source to target.

    Args:
        config: SyncConfig object or dict with sync configuration.
        resume: Resume from last checkpoint if interrupted.

    Returns:
        Dict mapping table names to SyncResult objects.

    Raises:
        SyncError: If sync fails.
        AnonymizationError: If anonymization strategy fails.

    Example:
        >>> with ProductionSyncer("prod", "local") as syncer:
        ...     results = syncer.sync({"tables": ["users"]})
        ...     print(results["users"].rows)
    """
```

**Example:**

```python
config = {
    "tables": ["users", "orders", "products"],
    "anonymize": {
        "users": {
            "email": "email",
            "phone": "phone",
            "ssn": "redact"
        }
    },
    "batch_size": 5000,
    "show_progress": True
}

with ProductionSyncer("production", "local") as syncer:
    results = syncer.sync(config)

    for table, result in results.items():
        print(f"{table}:")
        print(f"  Rows: {result.rows:,}")
        print(f"  Duration: {result.duration}")
        print(f"  Rate: {result.rows_per_second:.0f} rows/sec")
```

---

### `sync_table()`

Sync a single table.

```python
def sync_table(
    self,
    table: str,
    anonymization: dict[str, str] | None = None,
    where: str | None = None,
    limit: int | None = None,
) -> SyncResult:
    """
    Sync a single table.

    Args:
        table: Table name to sync.
        anonymization: Column-to-strategy mapping.
        where: Optional WHERE clause filter.
        limit: Optional row limit.

    Returns:
        SyncResult with sync details.

    Example:
        >>> result = syncer.sync_table(
        ...     "users",
        ...     anonymization={"email": "email"},
        ...     where="created_at > '2025-01-01'",
        ...     limit=1000
        ... )
    """
```

**Example:**

```python
# Sync with filter
result = syncer.sync_table(
    "orders",
    where="status = 'completed' AND created_at > '2025-01-01'",
    limit=10000
)

# Sync with anonymization
result = syncer.sync_table(
    "users",
    anonymization={
        "email": "email",
        "phone": "phone",
        "password_hash": "redact"
    }
)

print(f"Synced {result.rows:,} rows in {result.duration}")
```

---

### `get_all_tables()`

List all tables in source database.

```python
def get_all_tables(
    self,
    schema: str = "public",
) -> list[TableInfo]:
    """
    Get all tables in source database.

    Args:
        schema: Schema to list tables from.

    Returns:
        List of TableInfo objects.

    Example:
        >>> tables = syncer.get_all_tables()
        >>> for t in tables:
        ...     print(f"{t.name}: {t.row_count:,} rows")
    """
```

---

### `select_tables()`

Select tables matching patterns.

```python
def select_tables(
    self,
    include: list[str] | None = None,
    exclude: list[str] | None = None,
) -> list[str]:
    """
    Select tables by include/exclude patterns.

    Args:
        include: Glob patterns to include (e.g., ["users*", "orders"]).
        exclude: Glob patterns to exclude (e.g., ["*_log", "*_archive"]).

    Returns:
        List of matching table names.

    Example:
        >>> tables = syncer.select_tables(
        ...     include=["users", "orders*"],
        ...     exclude=["*_archive"]
        ... )
    """
```

---

### `save_checkpoint()` / `load_checkpoint()`

Checkpoint support for resumable syncs.

```python
def save_checkpoint(
    self,
    file_path: Path | str = ".confiture_checkpoint.json",
) -> None:
    """Save current progress for resume."""

def load_checkpoint(
    self,
    file_path: Path | str = ".confiture_checkpoint.json",
) -> Checkpoint | None:
    """Load checkpoint if exists."""
```

**Example:**

```python
# Sync with checkpointing
with ProductionSyncer("prod", "local") as syncer:
    try:
        results = syncer.sync(config, resume=True)
    except KeyboardInterrupt:
        syncer.save_checkpoint()
        print("Progress saved - resume with resume=True")
```

---

### `get_metrics()`

Get sync performance metrics.

```python
def get_metrics(self) -> dict[str, TableMetrics]:
    """
    Get performance metrics for all synced tables.

    Returns:
        Dict mapping table names to TableMetrics.

    Example:
        >>> metrics = syncer.get_metrics()
        >>> for table, m in metrics.items():
        ...     print(f"{table}: {m.rows_per_second:.0f} rows/sec")
    """
```

---

## Data Classes

### `SyncConfig`

```python
@dataclass
class SyncConfig:
    """Configuration for sync operation."""

    tables: list[str] | TableSelection  # Tables to sync
    anonymization: dict[str, dict[str, str]]  # Table -> column -> strategy
    batch_size: int = 5000              # Rows per batch
    show_progress: bool = True          # Show progress bar
    parallel: int = 1                   # Parallel table syncs
    checkpoint_file: str | None = None  # Checkpoint file path
```

### `SyncResult`

```python
@dataclass
class SyncResult:
    """Result of table sync."""

    table: str                   # Table name
    rows: int                    # Rows synced
    duration: timedelta          # Total duration
    rows_per_second: float       # Throughput
    bytes_transferred: int       # Data volume
    anonymized_columns: list[str]  # Columns that were anonymized
```

### `TableInfo`

```python
@dataclass
class TableInfo:
    """Information about a source table."""

    name: str                    # Table name
    schema: str                  # Schema name
    row_count: int               # Approximate row count
    size_bytes: int              # Table size
    columns: list[ColumnInfo]    # Column details
    has_pii: bool                # Contains PII columns
```

---

## Anonymization Strategies

### Built-in Strategies

| Strategy | Input | Output | Use Case |
|----------|-------|--------|----------|
| `email` | `alice@example.com` | `user_a1b2@example.com` | Email addresses |
| `phone` | `+1-555-1234` | `+1-555-0000` | Phone numbers |
| `name` | `Alice Johnson` | `User_12345` | Names |
| `redact` | `123-45-6789` | `[REDACTED]` | SSN, credit cards |
| `hash` | `secret123` | `a1b2c3d4...` | Tokens, keys |
| `null` | `anything` | `NULL` | Remove value |
| `fake` | `John` | `Michael` | Realistic fake data |

### Configuration Example

```python
config = {
    "tables": ["users", "orders"],
    "anonymize": {
        "users": {
            "email": "email",           # Hash-based anonymization
            "phone": "phone",           # Phone format preserved
            "ssn": "redact",            # Replace with [REDACTED]
            "password_hash": "null",    # Set to NULL
            "first_name": "fake",       # Realistic fake name
        },
        "orders": {
            "credit_card": "redact",
            "billing_address": "redact"
        }
    }
}
```

### Custom Strategies

```python
from confiture.anonymization import register_strategy

@register_strategy('custom_email')
def my_email_anonymizer(value, field_name, row_context):
    if not value:
        return None
    return f"test_{row_context['id']}@test.local"
```

---

## Performance

### Benchmarks

| Mode | Throughput | Notes |
|------|------------|-------|
| COPY (no anonymization) | 70,396 rows/sec | Maximum speed |
| With 1 anonymized column | 25,000 rows/sec | Moderate impact |
| With 3 anonymized columns | 6,515 rows/sec | Per-row processing |

### Optimization Tips

```python
# Parallel sync for independent tables
config = SyncConfig(
    tables=["users", "orders", "products"],
    parallel=3  # Sync 3 tables simultaneously
)

# Optimal batch size (determined by benchmarking)
config = SyncConfig(
    batch_size=5000  # Best for most workloads
)

# Filter to reduce data volume
result = syncer.sync_table(
    "logs",
    where="created_at > NOW() - INTERVAL '30 days'"
)
```

---

## Error Handling

```python
from confiture.core.syncer import ProductionSyncer
from confiture.exceptions import (
    SyncError,
    AnonymizationError,
    ConnectionError,
)

try:
    with ProductionSyncer("prod", "local") as syncer:
        results = syncer.sync(config)
except ConnectionError as e:
    print(f"Connection failed: {e}")
except AnonymizationError as e:
    print(f"Anonymization failed for {e.column}: {e}")
except SyncError as e:
    print(f"Sync failed: {e}")
    print(f"Table: {e.table}")
    print(f"Rows synced before failure: {e.rows_synced}")
```

---

## See Also

- [Medium 3: Production Sync Guide](../guides/03-production-sync.md) - User guide
- [Anonymization Guide](../guides/anonymization.md) - Custom strategies
- [CLI Reference: sync command](../reference/cli.md#confiture-sync) - CLI usage

---

**Last Updated**: January 17, 2026
