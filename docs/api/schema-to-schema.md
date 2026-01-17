# SchemaToSchemaMigrator API

[← Back to API Reference](index.md)

The `SchemaToSchemaMigrator` class implements **Medium 4: Zero-downtime schema-to-schema migrations** using PostgreSQL Foreign Data Wrapper (FDW).

**When to use**: Major schema refactoring in production with zero downtime.

## Overview

The SchemaToSchemaMigrator enables zero-downtime migrations for major schema changes by:

1. Setting up FDW to access the old database
2. Migrating data using either FDW or COPY strategy
3. Verifying data integrity
4. Supporting zero-downtime cutover

## Quick Example

```python
import psycopg
from confiture.core.schema_to_schema import SchemaToSchemaMigrator

# Connect to both databases
source_conn = psycopg.connect("postgresql://localhost/old_db")
target_conn = psycopg.connect("postgresql://localhost/new_db")

# Initialize migrator
migrator = SchemaToSchemaMigrator(
    source_connection=source_conn,
    target_connection=target_conn,
    foreign_schema_name="old_schema"
)

# Setup FDW
migrator.setup_fdw()

# Migrate table with column mapping
migrator.migrate_table(
    source_table="users",
    target_table="users",
    column_mapping={
        "id": "id",
        "full_name": "display_name",  # Rename column
        "email": "email"
    }
)

# Verify migration
results = migrator.verify_migration(
    tables=["users"],
    source_schema="old_schema",
    target_schema="public"
)

for table, result in results.items():
    if result["match"]:
        print(f"✅ {table}: {result['source_count']} rows verified")
    else:
        print(f"❌ {table}: {result['difference']} rows missing!")

# Cleanup FDW resources
migrator.cleanup_fdw()
```

## API Reference

::: confiture.core.schema_to_schema.SchemaToSchemaMigrator
    options:
      show_source: true
      members:
        - __init__
        - setup_fdw
        - migrate_table
        - migrate_table_copy
        - analyze_tables
        - verify_migration
        - cleanup_fdw

## Strategy Selection

The migrator supports two strategies with automatic selection:

| Strategy | Throughput | Best For | Threshold |
|----------|------------|----------|-----------|
| **FDW** | 500K rows/sec | <10M rows, complex transformations | Default for small tables |
| **COPY** | 6M rows/sec | ≥10M rows, simple mappings | 10-20x faster for large tables |

### Auto-Detection Example

```python
# Analyze tables and get recommendations
recommendations = migrator.analyze_tables()

for table, info in recommendations.items():
    print(f"{table}:")
    print(f"  Strategy: {info['strategy']}")
    print(f"  Rows: {info['row_count']:,}")
    print(f"  Estimated time: {info['estimated_seconds']:.1f}s")

# Output:
# users:
#   Strategy: fdw
#   Rows: 50,000
#   Estimated time: 0.1s
#
# events:
#   Strategy: copy
#   Rows: 50,000,000
#   Estimated time: 8.3s
```

## Column Mapping

Column mapping supports:

- **Rename**: `{"old_name": "new_name"}`
- **Keep same**: `{"column": "column"}`
- **Subset**: Only specified columns are migrated

```python
column_mapping = {
    "id": "id",                    # Keep same
    "full_name": "display_name",   # Rename
    "email": "email",              # Keep same
    # created_at not in mapping = not migrated
}
```

## Verification

Always verify migration before cutover:

```python
verification = migrator.verify_migration(["users", "posts"])

all_match = all(r["match"] for r in verification.values())
if all_match:
    print("✅ All tables verified - safe to cutover")
else:
    print("❌ Verification failed - investigate before cutover")
    for table, result in verification.items():
        if not result["match"]:
            print(f"  {table}: {result['difference']} row difference")
```

## See Also

- [Medium 4: Schema-to-Schema Guide](../guides/04-schema-to-schema.md)
- [Zero-Downtime Migration Example](../../examples/03-zero-downtime-migration/)
- [CLI Reference](../reference/cli.md)
