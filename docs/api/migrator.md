# Migrator API

[← Back to API Reference](index.md)

The library entry point for **Medium 2: Incremental Migrations**. The public
surface is `Migrator.from_config()`, which returns a `MigratorSession` — a
context manager that owns the database connection and exposes the migration
operations.

---

## Overview

A `MigratorSession` applies and rolls back migrations and tracks their state in
the `tb_confiture` table (configurable via `migration.tracking_table`). It runs
each `up()` inside a single transaction and coordinates with PostgreSQL advisory
locks so concurrent runners can't apply migrations simultaneously.

**When to use**: applying `ALTER` changes to existing databases with data, from
Python rather than the CLI.

---

## Quick Example

```python
from confiture import Migrator

# from_config returns a MigratorSession; use it as a context manager so the
# database connection is always closed.
with Migrator.from_config("db/environments/production.yaml") as session:
    status = session.status()
    if status.has_pending:
        result = session.up()
        print(
            f"Applied {len(result.migrations_applied)} migrations "
            f"in {result.total_execution_time_ms} ms"
        )
```

---

## Creating a session

### `Migrator.from_config()`

```python
@classmethod
def from_config(
    cls,
    config: "Environment | Path | str",
    *,
    migrations_dir: "Path | str" = "db/migrations",
) -> "MigratorSession":
    """Create a managed MigratorSession from an environment config.

    Args:
        config: an ``Environment`` instance, or a ``Path``/``str`` to a YAML
                config file (e.g. ``"db/environments/prod.yaml"``).
        migrations_dir: directory containing migration files.

    Returns:
        A MigratorSession. Must be used as a context manager.

    Raises:
        ConfigurationError: if the config file is missing or invalid.
    """
```

The returned session must be entered with `with` — that is what opens (and
later closes) the connection.

---

## `MigratorSession` methods

### `status()`

```python
def status(self) -> "StatusResult":
    """Return applied/pending state for every known migration."""
```

```python
with Migrator.from_config("db/environments/local.yaml") as session:
    status = session.status()
    print(f"Applied: {len(status.applied)}  Pending: {len(status.pending)}")
    for version in status.pending:
        print(f"  pending: {version}")
```

### `current_revision()`

```python
def current_revision(self) -> "CurrentRevision | None":
    """Return the latest applied revision, or None if none are applied.

    Raises PreconditionError (PRECON_1001) if the tracking table is absent.
    """
```

### `up()`

```python
def up(
    self,
    *,
    target: str | None = None,
    dry_run: bool = False,
    dry_run_execute: bool = False,
    verify_checksums: bool = True,
    force: bool = False,
    lock_timeout: int = 30000,
    no_lock: bool = False,
    require_reversible: bool = False,
) -> "MigrateUpResult":
    """Apply pending migrations (atomically) up to an optional target."""
```

```python
with Migrator.from_config("db/environments/production.yaml") as session:
    # Apply everything pending
    result = session.up()

    # Apply up to a specific revision (YYYYMMDDHHMMSS)
    result = session.up(target="20260403120000")

    # Analyse without executing
    preview = session.up(dry_run=True)

    # Execute inside a SAVEPOINT, then roll back (catches real SQL errors)
    checked = session.up(dry_run_execute=True)
```

### `down()`

```python
def down(
    self,
    *,
    steps: int = 1,
    dry_run: bool = False,
    lock_timeout: int = 30000,
    no_lock: bool = False,
    command: str | None = None,
) -> "MigrateDownResult":
    """Roll back the most recently applied migrations, newest first."""
```

```python
with Migrator.from_config("db/environments/local.yaml") as session:
    session.down(steps=1)          # roll back the last migration
    session.down(steps=3)          # roll back the last three
```

### `down_to()`

```python
def down_to(
    self,
    target: str,
    *,
    dry_run: bool = False,
    lock_timeout: int = 30000,
    no_lock: bool = False,
    command: str | None = None,
) -> "DownToResult":
    """Roll back every migration newer than ``target`` (kept applied)."""
```

It validates up front that every required `.down.sql` exists, refusing
atomically (no partial rollback) if any is missing.

### Other operations

| Method | Purpose |
|--------|---------|
| `reinit(...)` | Rebuild the tracking table from the migration files on disk. |
| `rebuild(...)` | Drop and recreate the tracking table (recovery). |
| `preflight(...)` | Static safety checks on pending migrations (the `migrate preflight` engine). |
| `run_against(...)` | SAVEPOINT-replay pending migrations against a target database. |
| `is_locked()` | Whether the migration advisory lock is currently held. |
| `get_lock_holder()` | Details of the process holding the lock, or `None`. |

---

## Result objects

These are dataclasses from `confiture.models.results`.

### `StatusResult`

```python
from confiture.models.results import StatusResult

# Fields
#   migrations: list[MigrationInfo]   # per-file status
#   tracking_table_exists: bool
#   tracking_table: str
#   summary: dict[str, int]           # {"applied": N, "pending": N, "total": N}
# Properties
#   applied: list[str]                # applied versions
#   pending: list[str]                # pending versions
#   has_pending: bool
```

### `MigrateUpResult`

```python
from confiture.models.results import MigrateUpResult

# Fields
#   success: bool
#   migrations_applied: list[MigrationApplied]
#   total_execution_time_ms: int
#   checksums_verified: bool
#   dry_run: bool
#   dry_run_execute: bool
#   warnings: list[str]
#   skipped: list[str]
#   errors: list[str]
# Properties
#   has_errors: bool
#   error_summary: str | None
# to_dict() serialises migrations_applied as "applied" and
# total_execution_time_ms as "total_duration_ms".
```

### `MigrationApplied`

```python
from confiture.models.results import MigrationApplied

# Fields: version, name, execution_time_ms, rows_affected
```

### `CurrentRevision`

```python
from confiture.models.results import CurrentRevision

# Fields: version, name, applied_at, checksum
```

---

## Advanced: an existing connection

For callers that already hold a `psycopg` connection (and have loaded their
own config), construct the engine directly:

```python
import psycopg
from confiture.core.migrator import Migrator

with psycopg.connect("postgresql://localhost/mydb") as conn:
    migrator = Migrator(conn, migration_table="tb_confiture")
```

`from_config()` is preferred for application code — it wires the connection and
config for you and guarantees cleanup.

---

## Error Handling

```python
from confiture import Migrator
from confiture.exceptions import ConfigurationError, MigrationError

try:
    with Migrator.from_config("db/environments/production.yaml") as session:
        result = session.up()
        if not result.success:
            for message in result.errors:
                print(f"failed: {message}")
except ConfigurationError as exc:
    print(f"bad config: {exc}")
except MigrationError as exc:
    print(f"migration failed: {exc}")
```

All confiture exceptions inherit `confiture.exceptions.ConfiturError`, which
carries an `error_code` and maps to a semantic process exit code at the CLI.

---

## Migration Tracking

State is tracked in `tb_confiture` (an identity-trinity table: `id` / `pk_confiture`
/ `slug` plus `version`, `name`, `applied_at`, `execution_time_ms`, `checksum`).
See [Tracking Table](../reference/tracking-table.md) for the full schema and the
columns' meaning.

---

## See Also

- [Medium 2: Incremental Migrations Guide](../guides/02-incremental-migrations.md) — user guide
- [CLI Reference: migrate commands](../reference/cli.md#confiture-migrate) — CLI usage
- [Dry-Run Mode](../guides/dry-run.md) — test migrations safely
