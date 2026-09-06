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
    on_checksum_mismatch: str = "fail",
    force: bool = False,
    lock_timeout: int = 30000,
    no_lock: bool = False,
    require_reversible: bool = False,
    strict_mode: bool | None = None,
    auto_baseline: Path | None = None,
    install_view_helpers: bool | None = None,
    on_event: Callable[[UpEvent], None] | None = None,
) -> "MigrateUpResult":
    """Apply pending migrations (atomically) up to an optional target."""
```

`up()` is the one apply loop: `confiture migrate up` and `Migrator.migrate_up()`
both run it. The lock is taken first; discovery and the ledger `CREATE TABLE IF NOT
EXISTS` happen under it; checksums are verified before anything is applied. A lock
that cannot be taken raises `LockAcquisitionError`; a failing migration is a
`success=False` result whose `failure` attribute holds the exception.

- `strict_mode`: fail on warnings/notices; `None` follows the environment's
  `migration.strict_mode`.
- `auto_baseline`: a snapshots directory — self-baseline a database whose ledger is
  missing (the CLI's `--auto-detect-baseline`). Refuses with `ConfigurationError`
  when a relation of the ledger's name exists in another schema, or when the
  directory is missing or empty.
- `install_view_helpers`: install the view helper functions first; `None` follows
  `migration.view_helpers: auto`.
- `on_event`: live progress. Each `UpEvent` has a `kind` (`lock_acquired`,
  `baseline_probe`, `baseline_detected`, `baseline_missed`, `view_helpers_installed`,
  `checksums_verified`, `pending`, `applying`, `applied`, `failed`, `superuser_halt`,
  `target_reached`), a `version`/`name` when one migration is concerned, a
  `message`, and `elapsed_ms` on `applied`.

`verify_checksums=True` (the default) checks every applied migration file —
`.py` and `.up.sql` — against the ledger before anything is applied, under the
migration lock. A modified file raises `confiture.core.checksum.ChecksumVerificationError`
(`.mismatches` lists the versions) under `on_checksum_mismatch="fail"`;
`"warn"` continues and reports each mismatch in `result.warnings`; `"ignore"`
continues silently. `force=True` skips the check. `result.checksums_verified` is
`True` only when the verifier ran and found no mismatch — never a copy of the flag.

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

### `apply_one()`

```python
def apply_one(
    self,
    version: str,
    *,
    applied_by: str | None = None,
    lock_timeout: int = 30000,
    no_lock: bool = False,
) -> "MigrationApplied":
    """Apply exactly one migration by version, under the migration lock."""
```

The engine behind `confiture migrate apply-as`: open a session on the privileged
role's URL, apply the migration `up()` halted on (`requires_superuser=True`), then
re-run `up()`. Raises `MigrationError` `MIGR_001` when the version is already
applied and `MIGR_100` when no file carries it.

### `MigratorSession.attached()`

```python
session = MigratorSession.attached(migrator, Path("db/migrations"))
result = session.up()
```

A session over an engine that already owns its connection — the connection is not
closed when the block ends. `Migrator.migrate_up()` is implemented this way.

### Other operations

| Method | Purpose |
|--------|---------|
| `reinit(...)` | Rebuild the tracking table from the migration files on disk. |
| `rebuild(...)` | Drop and recreate the tracking table (recovery). |
| `preflight(...)` | Static safety checks on pending migrations (the `migrate preflight` engine). On a database with no migration ledger it skips the checksum step and sets `checksum_verified=False` with a `checksum_skipped_reason`, rather than raising — consistent with `status()` and `current_revision()`. |
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
#   checksums_verified: bool   # the verifier ran and found no mismatch
#   skipped_superuser: list[SkippedMigration]
#   pending: list[str]        # versions not applied (dry run, or after a halt)
#   failure: BaseException | None   # the exception behind errors[0]; not serialized
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

`session.connection` is the live connection inside the `with` block — for a
read-only query alongside the session (the CLI uses it for the dry-run row
estimates). It raises `ConfigurationError` outside the block.

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

## Testing without a database — injected factories

`MigratorSession` takes what it needs to open a connection and to turn a
migration file into a class as parameters, so a test or an embedder injects
instead of patching a module:

```python
from confiture.core.migrator import Migrator, MigratorSession

session = MigratorSession(
    None,
    Path("db/migrations"),
    database_url_override="postgresql://localhost/test",
    connection_factory=my_pool.connection,      # called with the URL
    migration_loader=my_loader,                 # called with the migration file path
)
with Migrator.from_config("db/environments/test.yaml", connection_factory=fake) as m:
    m.status()
```

Without them a session reads the class-level defaults
`MigratorSession.default_connection_factory` and `default_migration_loader`
when it enters (they resolve to `confiture.core.connection`), so setting one
attribute changes every session in a test block. `confiture.core.migrator`
itself holds no patch seam.

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

### The resolution hint rides on `str(exc)`

Most raise sites also compute a `resolution_hint` — the actionable half of the
error. It is part of the string form, so a bare `print(exc)`, an f-string, a
`logging.error("%s", exc)` or an uncaught traceback all carry it:

```python
>>> print(exc)
Refusing to replace database 'proj_test_template': it exists and is not
confiture-managed — it carries no database COMMENT, and a template is
recognised only by a COMMENT starting with 'confiture:template:'.
Hint: If it is a foreign database, choose a different --template name. If it
is confiture's own template that lost its comment to an out-of-band recreate,
let confiture rebuild it: DROP DATABASE "proj_test_template" (or pass --force,
which drops and re-provisions it for you).
```

That matters most where confiture is embedded and nothing renders the error but
Python itself — a pytest fixture, orchestration code, a log line (#211).

Three attributes give you the pieces separately when you render your own:

| Attribute | Contents |
|-----------|----------|
| `exc.message` | The message alone, without the hint |
| `exc.resolution_hint` | The hint alone (`None` if the site set none) |
| `exc.error_code` | The symbolic code, e.g. `CONFIG_010` |

Use `exc.message`, not `str(exc)`, when you print the hint yourself or match on
the message text — `str(exc)` would render the hint a second time, or feed hint
prose to your matcher. `exc.to_dict()` already splits them.

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
