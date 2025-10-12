# Migrator API

The `Migrator` class implements Medium 2: Incremental Migrations.

## Overview

The Migrator executes database migrations and tracks their state in the `confiture_migrations` table. It ensures migrations run exactly once and provides rollback capabilities.

## Quick Example

```python
import psycopg
from confiture.core.migrator import Migrator

# Connect to database
conn = psycopg.connect("postgresql://localhost/mydb")

# Initialize migrator
migrator = Migrator(connection=conn)
migrator.initialize()

# Apply a migration
from my_migrations import AddUserBio

migration = AddUserBio(connection=conn)
migrator.apply(migration)

# Check applied versions
applied = migrator.get_applied_versions()
print(f"Applied migrations: {applied}")

# Rollback if needed
migrator.rollback(migration)
```

## API Reference

::: confiture.core.migrator.Migrator
    options:
      show_source: true
      members:
        - __init__
        - initialize
        - apply
        - rollback
        - get_applied_versions
        - find_migration_files
        - find_pending

## Migration Tracking

Confiture uses an identity trinity pattern for migration tracking:

```sql
CREATE TABLE confiture_migrations (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    pk_migration UUID NOT NULL DEFAULT uuid_generate_v4() UNIQUE,
    slug TEXT NOT NULL UNIQUE,
    version VARCHAR(255) NOT NULL UNIQUE,
    name VARCHAR(255) NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    execution_time_ms INTEGER,
    checksum VARCHAR(64)
);
```

- **id**: Auto-increment (internal)
- **pk_migration**: UUID (stable identifier for external APIs)
- **slug**: Human-readable (`migration_name_YYYYMMDD_HHMMSS`)
- **version**: Migration version (e.g., "001", "002")

## See Also

- [Medium 2: Incremental Migrations Guide](../guides/medium-2-incremental-migrations.md)
- [Migration Base Class](../api/migration.md)
- [CLI Reference: migrate commands](../reference/cli.md#migrate)
