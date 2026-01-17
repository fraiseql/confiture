# Build from DDL

[← Back to Guides](../index.md) · [Migration Decision Tree →](migration-decision-tree.md)

**Build fresh PostgreSQL databases from DDL files in <1 second**

---

## Overview

Build from DDL is Confiture's fastest way to create a database. Instead of replaying migration history, Confiture concatenates your schema files and executes them directly.

> **"DDL files are the source of truth, not migration history"**

```
Traditional: Migration 001 → 002 → 003 → ... → 100 (slow)
Confiture:   db/schema/*.sql → Concatenate → Execute (fast)
```

### When to Use

| Use Case | Build from DDL |
|----------|---------------|
| Local development | Perfect |
| CI/CD pipelines | Perfect |
| Fresh staging | Perfect |
| Existing databases with data | Use Medium 2 |
| Production deployments | Use Medium 2 or 4 |

---

## Quick Start

```bash
# Build default environment
confiture build

# Build specific environment
confiture build --env production

# Dry run (show SQL, don't execute)
confiture build --env test --dry-run
```

---

## Directory Structure

```
db/
├── schema/
│   ├── 00_common/           # Extensions, types (first)
│   │   └── extensions.sql
│   ├── 10_tables/           # Core tables
│   │   └── users.sql
│   ├── 20_views/            # Views (depend on tables)
│   │   └── user_stats.sql
│   ├── 30_indexes/          # Indexes
│   │   └── users_indexes.sql
│   └── 40_constraints/      # Foreign keys (last)
│       └── foreign_keys.sql
├── seeds/                   # Test data
│   ├── common/
│   └── development/
└── environments/
    ├── local.yaml
    └── production.yaml
```

**Files are processed alphabetically.** Use numbered directories (00_, 10_, 20_) to control order.

---

## Environment Configuration

```yaml
# db/environments/local.yaml
name: local
database:
  host: localhost
  port: 5432
  database: myapp_local
  user: postgres
  password: postgres

include_dirs:
  - db/schema
  - db/seeds/common
  - db/seeds/development

exclude_dirs:
  - db/schema/deprecated
```

---

## Example Schema File

```sql
-- db/schema/10_tables/users.sql
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE users IS 'User accounts and profiles';
```

---

## Python API

```python
from confiture.core.builder import SchemaBuilder

builder = SchemaBuilder(env="local")
schema = builder.build()

# Compute schema hash for version tracking
schema_hash = builder.compute_hash()
```

---

## Best Practices

1. **Use numbered directories** - `00_common/`, `10_tables/`, `20_views/`
2. **Include `IF NOT EXISTS`** - Makes rebuilds idempotent
3. **Keep files self-contained** - Each file should work independently
4. **Separate schema from seeds** - DDL in `schema/`, DML in `seeds/`
5. **Use comments** - Document tables and columns

---

## Common Issues

### "No SQL files found"
Check `include_dirs` in your environment config matches your directory structure.

### "Relation already exists"
Add `IF NOT EXISTS` to all CREATE statements.

### Build slow (>5s)
Rust extension may not be installed. Reinstall with: `pip install confiture`

---

## See Also

- [Incremental Migrations](./02-incremental-migrations.md) - For existing databases
- [Migration Decision Tree](./migration-decision-tree.md) - Choose the right approach
- [CLI Reference](../reference/cli.md) - All build commands
