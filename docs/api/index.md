# API Reference

[← Back to Docs](../index.md)

**Confiture Python API** - Programmatic access to all migration strategies.

---

## Installation

```bash
# Install with pip
pip install confiture

# Install with uv (recommended)
uv add confiture

# With Rust acceleration (10-50x faster)
pip install confiture[rust]
```

---

## Quick Start

```python
import confiture

# Check version
print(confiture.__version__)  # "0.5.0"

# Initialize for a project
from confiture import Confiture

conf = Confiture(project_dir="/path/to/project")
conf.init()  # Creates db/ structure
```

---

## Core APIs

The four migration strategies ("mediums") each have a dedicated class:

| Class | Module | Strategy | Use Case |
|-------|--------|----------|----------|
| [`SchemaBuilder`](builder.md) | `confiture.core.builder` | Medium 1 | Build fresh databases from DDL |
| [`Migrator`](migrator.md) | `confiture.core.migrator` | Medium 2 | Apply incremental ALTER changes |
| [`ProductionSyncer`](syncer.md) | `confiture.core.syncer` | Medium 3 | Sync production data with anonymization |
| [`SchemaToSchemaMigrator`](schema-to-schema.md) | `confiture.core.schema_to_schema` | Medium 4 | Zero-downtime via FDW |

### Import Patterns

```python
# Individual imports (recommended)
from confiture.core.builder import SchemaBuilder
from confiture.core.migrator import Migrator
from confiture.core.syncer import ProductionSyncer
from confiture.core.schema_to_schema import SchemaToSchemaMigrator

# Convenience imports
from confiture import SchemaBuilder, Migrator, ProductionSyncer
```

---

## Quick Examples

### Medium 1: Build Schema

```python
from confiture.core.builder import SchemaBuilder

builder = SchemaBuilder(env="local")
schema = builder.build()

print(f"Generated {len(schema)} bytes")
print(f"Hash: {builder.compute_hash()[:12]}")
```

### Medium 2: Apply Migration

```python
from confiture.core.migrator import Migrator
import psycopg

with psycopg.connect("postgresql://localhost/mydb") as conn:
    migrator = Migrator(connection=conn)

    # Apply single migration
    migrator.apply("001_create_users")

    # Apply all pending
    migrator.apply_all()

    # Rollback
    migrator.rollback("001_create_users")
```

### Medium 3: Sync Production Data

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
        print(f"{table}: {stats['rows']} rows synced")
```

### Medium 4: Zero-Downtime Migration

```python
from confiture.core.schema_to_schema import SchemaToSchemaMigrator
import psycopg

source = psycopg.connect("postgresql://old_db")
target = psycopg.connect("postgresql://new_db")

migrator = SchemaToSchemaMigrator(
    source_connection=source,
    target_connection=target
)

# Setup Foreign Data Wrapper
migrator.setup_fdw()

# Migrate with column mapping
migrator.migrate_table(
    source_table="users",
    target_table="users",
    column_mapping={
        "id": "id",
        "full_name": "display_name",  # Rename
        "email": "email"
    }
)

# Verify before cutover
results = migrator.verify_migration(["users"])
if all(r["match"] for r in results.values()):
    print("✅ Ready for cutover")

# Cleanup
migrator.cleanup_fdw()
```

---

## Extension APIs

| API | Module | Description |
|-----|--------|-------------|
| [Hooks](hooks.md) | `confiture.hooks` | Lifecycle callbacks for migrations |
| [Anonymization](anonymization.md) | `confiture.anonymization` | Custom data masking strategies |
| [Linting](linting.md) | `confiture.linting` | Schema validation rules |
| [Wizard](wizard.md) | `confiture.wizard` | Interactive migration assistant |

### Hooks Example

```python
from confiture.hooks import register_hook, HookContext

@register_hook('post_execute')
def notify_team(context: HookContext) -> None:
    print(f"Migration {context.migration_name} completed")
    print(f"Duration: {context.duration}")
```

### Anonymization Example

```python
from confiture.anonymization import register_strategy
import hashlib

@register_strategy('email')
def anonymize_email(value: str | None, field_name: str, row_context: dict | None) -> str | None:
    if not value or '@' not in value:
        return None
    local, domain = value.rsplit('@', 1)
    hashed = hashlib.sha256(local.encode()).hexdigest()[:8]
    return f"user_{hashed}@{domain}"
```

---

## Error Handling

All Confiture APIs raise specific exceptions:

```python
from confiture.exceptions import (
    ConfitureError,          # Base exception
    ConfigurationError,      # Invalid configuration
    MigrationError,          # Migration execution failed
    ConnectionError,         # Database connection issues
    ValidationError,         # Schema validation failed
    SyncError,               # Production sync failed
)

try:
    migrator.apply("001_create_users")
except MigrationError as e:
    print(f"Migration failed: {e}")
    print(f"SQL: {e.sql}")
    print(f"Position: {e.position}")
except ConnectionError as e:
    print(f"Database connection failed: {e}")
```

---

## Async Support

All core APIs support async operations:

```python
import asyncio
from confiture.core.builder import SchemaBuilder
from confiture.core.migrator import Migrator

async def migrate():
    builder = SchemaBuilder(env="local")
    schema = await builder.build_async()

    async with Migrator.connect_async("postgresql://localhost/mydb") as migrator:
        await migrator.apply_async("001_create_users")

asyncio.run(migrate())
```

---

## Configuration

APIs read configuration from `confiture.yaml`:

```yaml
# confiture.yaml
version: 1

environments:
  local:
    database:
      host: localhost
      port: 5432
      database: myapp_local
      user: postgres
      password: postgres

    schema_dirs:
      - db/schema

    seed_dirs:
      - db/seeds/common
      - db/seeds/development

  production:
    database:
      url: ${DATABASE_URL}  # Environment variable

    schema_dirs:
      - db/schema
```

### Programmatic Configuration

```python
from confiture.config import Config

config = Config(
    env="local",
    database_url="postgresql://localhost/mydb",
    schema_dirs=["db/schema"],
    seed_dirs=["db/seeds"]
)

builder = SchemaBuilder(config=config)
```

---

## Type Hints

All APIs are fully typed for IDE support:

```python
from confiture.core.builder import SchemaBuilder
from confiture.core.migrator import Migrator, MigrationResult
from confiture.core.syncer import ProductionSyncer, SyncConfig, SyncResult
from confiture.core.schema_to_schema import SchemaToSchemaMigrator

# Type hints work throughout
def build_and_migrate(env: str) -> MigrationResult:
    builder: SchemaBuilder = SchemaBuilder(env=env)
    schema: str = builder.build()
    ...
```

---

## API Stability

> **Note**: "Stable API" means the interface won't have breaking changes. It does **not** mean production-tested. Confiture is Beta software.

| API | Interface | Since |
|-----|-----------|-------|
| SchemaBuilder | Stable | v0.1.0 |
| Migrator | Stable | v0.1.0 |
| ProductionSyncer | Stable | v0.2.0 |
| SchemaToSchemaMigrator | Stable | v0.3.0 |
| Hooks | Stable | v0.4.0 |
| Anonymization | Stable | v0.4.0 |
| Linting | Stable | v0.4.0 |
| Wizard | Stable | v0.4.0 |

**What "Stable" means:**
- No breaking changes without major version bump
- Does NOT mean "production-tested" or "battle-tested"

---

## Performance

### Rust Acceleration

When installed with `confiture[rust]`, these operations are 10-50x faster:

| Operation | Python | Rust | Speedup |
|-----------|--------|------|---------|
| Schema concatenation | 120ms | 12ms | **10x** |
| SHA256 hashing | 300ms | 10ms | **30x** |
| Large schema (1000 files) | 5s | 100ms | **50x** |
| SQL parsing | 500ms | 25ms | **20x** |

### Check if Rust is Available

```python
from confiture import has_rust_extension

if has_rust_extension():
    print("Rust acceleration enabled")
else:
    print("Using pure Python (slower)")
```

---

## See Also

- [CLI Reference](../reference/cli.md) - Command-line interface
- [Configuration Reference](../reference/configuration.md) - Full config options
- [Getting Started](../getting-started.md) - Tutorial
- [Troubleshooting](../troubleshooting.md) - Common issues

---

**Last Updated**: January 17, 2026
**Version**: 0.5.0
