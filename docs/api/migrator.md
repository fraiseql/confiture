# Migrator API

[← Back to API Reference](index.md)

The `Migrator` class implements **Medium 2: Incremental Migrations**.

---

## Overview

The Migrator executes database migrations and tracks their state in the `confiture_migrations` table. It ensures migrations run exactly once and provides rollback capabilities.

**When to use**: Applying ALTER changes to existing databases with data.

---

## Quick Example

```python
import psycopg
from confiture.core.migrator import Migrator

# Connect to database
with psycopg.connect("postgresql://localhost/mydb") as conn:
    migrator = Migrator(connection=conn)

    # Apply all pending migrations
    results = migrator.apply_all()

    for result in results:
        print(f"Applied {result.name} in {result.duration}")
```

---

## Class Reference

### `Migrator`

```python
class Migrator:
    """Execute and track database migrations."""

    def __init__(
        self,
        connection: psycopg.Connection | str,
        migrations_dir: Path | str = "db/migrations",
        table_name: str = "confiture_migrations",
    ) -> None:
        """
        Initialize migrator.

        Args:
            connection: psycopg Connection or connection string.
            migrations_dir: Directory containing migration files.
            table_name: Name of migrations tracking table.

        Raises:
            ConnectionError: If database connection fails.
        """

    @classmethod
    async def connect_async(cls, connection_string: str) -> "Migrator":
        """
        Create migrator with async connection.

        Args:
            connection_string: PostgreSQL connection string.

        Returns:
            Migrator instance with async connection.
        """
```

---

## Methods

### `initialize()`

Create migrations tracking table.

```python
def initialize(self) -> None:
    """
    Create confiture_migrations table if not exists.

    Safe to call multiple times (idempotent).

    Example:
        >>> migrator = Migrator(connection=conn)
        >>> migrator.initialize()
        # Creates table if needed
    """
```

---

### `apply()`

Apply a single migration.

```python
def apply(
    self,
    migration: str | Migration,
    dry_run: bool = False,
) -> MigrationResult:
    """
    Apply a single migration.

    Args:
        migration: Migration name (e.g., "001_create_users") or Migration object.
        dry_run: If True, show SQL without executing.

    Returns:
        MigrationResult with execution details.

    Raises:
        MigrationError: If migration fails.
        MigrationAlreadyApplied: If migration was already applied.

    Example:
        >>> result = migrator.apply("001_create_users")
        >>> print(f"Applied in {result.duration}")
    """
```

**Example:**

```python
# Apply by name
result = migrator.apply("001_create_users")

# Apply with dry-run
result = migrator.apply("002_add_email", dry_run=True)
print(result.sql)  # Shows SQL without executing

# Apply Migration object
from db.migrations import CreateUsersTable
migration = CreateUsersTable()
result = migrator.apply(migration)
```

---

### `apply_all()`

Apply all pending migrations.

```python
def apply_all(
    self,
    target: str | None = None,
    dry_run: bool = False,
) -> list[MigrationResult]:
    """
    Apply all pending migrations up to target.

    Args:
        target: Stop at this migration (inclusive). None = apply all.
        dry_run: If True, show SQL without executing.

    Returns:
        List of MigrationResult for each applied migration.

    Example:
        >>> results = migrator.apply_all()
        >>> print(f"Applied {len(results)} migrations")
    """
```

**Example:**

```python
# Apply all pending
results = migrator.apply_all()
for r in results:
    print(f"  {r.name}: {r.duration}")

# Apply up to specific migration
results = migrator.apply_all(target="003_add_indexes")

# Dry-run all
results = migrator.apply_all(dry_run=True)
for r in results:
    print(f"Would apply: {r.name}")
    print(r.sql)
```

---

### `rollback()`

Rollback a migration.

```python
def rollback(
    self,
    migration: str | Migration,
    dry_run: bool = False,
) -> MigrationResult:
    """
    Rollback a migration by running its down() method.

    Args:
        migration: Migration name or Migration object.
        dry_run: If True, show SQL without executing.

    Returns:
        MigrationResult with rollback details.

    Raises:
        MigrationError: If rollback fails.
        MigrationNotApplied: If migration was not applied.

    Example:
        >>> result = migrator.rollback("002_add_email")
        >>> print(f"Rolled back in {result.duration}")
    """
```

**Example:**

```python
# Rollback last migration
result = migrator.rollback("003_add_indexes")

# Rollback with dry-run
result = migrator.rollback("002_add_email", dry_run=True)
print(result.sql)
```

---

### `rollback_to()`

Rollback to a specific migration.

```python
def rollback_to(
    self,
    target: str,
    dry_run: bool = False,
) -> list[MigrationResult]:
    """
    Rollback all migrations after target.

    Args:
        target: Keep this migration and earlier.
        dry_run: If True, show SQL without executing.

    Returns:
        List of MigrationResult for each rolled back migration.

    Example:
        >>> results = migrator.rollback_to("001_create_users")
        >>> print(f"Rolled back {len(results)} migrations")
    """
```

---

### `get_applied_versions()`

Get list of applied migrations.

```python
def get_applied_versions(self) -> list[AppliedMigration]:
    """
    Get all applied migrations.

    Returns:
        List of AppliedMigration objects, ordered by applied_at.

    Example:
        >>> applied = migrator.get_applied_versions()
        >>> for m in applied:
        ...     print(f"{m.version}: {m.name} ({m.applied_at})")
    """
```

---

### `find_pending()`

Find migrations not yet applied.

```python
def find_pending(self) -> list[Migration]:
    """
    Find migrations that haven't been applied yet.

    Returns:
        List of pending Migration objects.

    Example:
        >>> pending = migrator.find_pending()
        >>> print(f"{len(pending)} migrations pending")
    """
```

---

### `status()`

Get migration status summary.

```python
def status(self) -> MigrationStatus:
    """
    Get current migration status.

    Returns:
        MigrationStatus with counts and details.

    Example:
        >>> status = migrator.status()
        >>> print(f"Applied: {status.applied_count}")
        >>> print(f"Pending: {status.pending_count}")
    """
```

**Example:**

```python
status = migrator.status()

print(f"Applied: {status.applied_count}")
print(f"Pending: {status.pending_count}")
print(f"Last applied: {status.last_applied}")

if status.pending_count > 0:
    print("\nPending migrations:")
    for m in status.pending:
        print(f"  - {m.name}")
```

---

## Data Classes

### `MigrationResult`

```python
@dataclass
class MigrationResult:
    """Result of migration execution."""

    name: str                    # Migration name
    version: str                 # Migration version
    action: str                  # "applied" or "rolled_back"
    duration: timedelta          # Execution time
    sql: str                     # SQL that was executed
    rows_affected: int | None    # Rows affected (if applicable)
    success: bool                # Whether it succeeded
    error: str | None            # Error message if failed
```

### `AppliedMigration`

```python
@dataclass
class AppliedMigration:
    """Record of an applied migration."""

    id: int                      # Internal ID
    pk_migration: UUID           # Stable UUID
    slug: str                    # Human-readable slug
    version: str                 # Version number
    name: str                    # Migration name
    applied_at: datetime         # When applied
    execution_time_ms: int       # Execution time in ms
    checksum: str                # Migration file checksum
```

### `MigrationStatus`

```python
@dataclass
class MigrationStatus:
    """Current migration status."""

    applied_count: int           # Number of applied migrations
    pending_count: int           # Number of pending migrations
    applied: list[AppliedMigration]  # Applied migrations
    pending: list[Migration]     # Pending migrations
    last_applied: AppliedMigration | None  # Most recent
```

---

## Writing Migrations

### Migration Class

```python
from confiture.core.migrator import Migration

class AddUserEmail(Migration):
    """Add email column to users table."""

    version = "002"
    name = "add_user_email"

    def up(self) -> str:
        """Apply migration - returns SQL."""
        return """
            ALTER TABLE users
            ADD COLUMN email VARCHAR(255);

            CREATE UNIQUE INDEX users_email_idx ON users(email);
        """

    def down(self) -> str:
        """Rollback migration - returns SQL."""
        return """
            DROP INDEX IF EXISTS users_email_idx;
            ALTER TABLE users DROP COLUMN IF EXISTS email;
        """
```

### SQL File Migrations

```sql
-- db/migrations/002_add_user_email.sql

-- migrate:up
ALTER TABLE users ADD COLUMN email VARCHAR(255);
CREATE UNIQUE INDEX users_email_idx ON users(email);

-- migrate:down
DROP INDEX IF EXISTS users_email_idx;
ALTER TABLE users DROP COLUMN IF EXISTS email;
```

---

## Migration Tracking

Confiture uses an identity trinity pattern for migration tracking:

```sql
CREATE TABLE confiture_migrations (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    pk_migration UUID NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    slug TEXT NOT NULL UNIQUE,
    version VARCHAR(255) NOT NULL UNIQUE,
    name VARCHAR(255) NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    execution_time_ms INTEGER,
    checksum VARCHAR(64)
);
```

| Column | Purpose |
|--------|---------|
| `id` | Auto-increment (internal joins) |
| `pk_migration` | Stable UUID (external APIs) |
| `slug` | Human-readable (`add_email_20260117_143022`) |
| `version` | Sort order ("001", "002") |
| `checksum` | Detect if migration file changed |

---

## Advisory Locking

Migrator uses PostgreSQL advisory locks to prevent concurrent migrations:

```python
# Lock is automatically acquired
migrator.apply_all()  # Safe even if another process tries

# Or manually control locking
with migrator.lock():
    migrator.apply("001_create_users")
    migrator.apply("002_add_email")
```

---

## Error Handling

```python
from confiture.core.migrator import Migrator
from confiture.exceptions import (
    MigrationError,
    MigrationAlreadyApplied,
    MigrationNotApplied,
)

try:
    migrator.apply("001_create_users")
except MigrationAlreadyApplied:
    print("Migration already applied")
except MigrationError as e:
    print(f"Migration failed: {e}")
    print(f"SQL: {e.sql}")
    print(f"Position: {e.position}")

try:
    migrator.rollback("001_create_users")
except MigrationNotApplied:
    print("Cannot rollback - not applied")
```

---

## See Also

- [Medium 2: Incremental Migrations Guide](../guides/02-incremental-migrations.md) - User guide
- [CLI Reference: migrate commands](../reference/cli.md#confiture-migrate) - CLI usage
- [Dry-Run Mode](../guides/dry-run.md) - Test migrations safely

---

**Last Updated**: January 17, 2026
