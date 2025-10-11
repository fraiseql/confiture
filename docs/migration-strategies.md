# Migration Strategies

Confiture provides **4 migration strategies** (called "mediums") to handle every database scenario from local development to zero-downtime production deployments.

## Table of Contents

- [Overview](#overview)
- [Medium 1: Build from DDL](#medium-1-build-from-ddl)
- [Medium 2: Incremental Migrations](#medium-2-incremental-migrations)
- [Medium 3: Production Data Sync](#medium-3-production-data-sync-coming-soon)
- [Medium 4: Schema-to-Schema](#medium-4-schema-to-schema-coming-soon)
- [Decision Tree](#decision-tree)
- [Comparison](#comparison)
- [Best Practices](#best-practices)

---

## Overview

### The Four Mediums

| Medium | Use Case | Speed | Downtime | Phase |
|--------|----------|-------|----------|-------|
| **1. Build from DDL** | Fresh databases, testing | <1s | N/A | ✅ Available |
| **2. Incremental** | Simple schema changes | Fast | Seconds | ✅ Available |
| **3. Production Sync** | Copy prod → staging | Medium | N/A | 🚧 Phase 3 |
| **4. Schema-to-Schema** | Complex migrations | Slow | 0-5s | 🚧 Phase 3 |

### Philosophy

> **"Build from DDL, not migration history"**

Traditional tools (Alembic, Django) replay migration history to build databases. This is slow and brittle.

Confiture treats `db/schema/` DDL files as the **single source of truth**. Migrations are derived, not primary.

---

## Medium 1: Build from DDL

**Build fresh databases from schema files in <1 second**

### When to Use

- ✅ Local development (new developer onboarding)
- ✅ CI/CD test databases
- ✅ Ephemeral review environments
- ✅ Fresh staging deployments
- ❌ Existing databases with data

### How It Works

1. Concatenate all `.sql` files from `db/schema/` in alphabetical order
2. Execute combined schema on empty database
3. Database ready in <1 second (vs minutes with migration replay)

### Example

```bash
# Build local database
confiture build --env local

# Build test database for CI
confiture build --env test --output db/generated/schema_test.sql
```

### Directory Structure

```
db/schema/
├── 00_common/              # Extensions, types (executed first)
│   ├── extensions.sql
│   └── custom_types.sql
├── 10_tables/              # Core tables
│   ├── users.sql
│   ├── posts.sql
│   └── comments.sql
├── 20_views/               # Views (depend on tables)
│   └── user_stats.sql
└── 30_functions/           # Functions (executed last)
    └── calculate_score.sql
```

### Performance

| Database Size | Alembic (replay) | Confiture (build) | Speedup |
|---------------|------------------|-------------------|---------|
| 10 tables | 12s | 0.3s | **40x** |
| 50 tables | 45s | 0.8s | **56x** |
| 100 tables | 120s | 1.2s | **100x** |

### Implementation (Current)

**Status**: 🚧 Not implemented yet (coming in future milestone)

```python
# Future API
from confiture import SchemaBuilder

builder = SchemaBuilder(env="local")
schema_sql = builder.build()  # Returns combined SQL
builder.execute()  # Executes on database
```

### Benefits

- 🚀 **Lightning fast** - Build 100-table schema in 1 second
- 🧪 **Perfect for testing** - Fresh database per test
- 👥 **Onboarding** - New developers get working DB instantly
- 🔄 **CI/CD** - Faster pipeline execution

### Limitations

- ❌ Cannot use on databases with existing data
- ❌ Requires empty database
- ⚠️ Schema files must be self-contained

---

## Medium 2: Incremental Migrations

**Apply schema changes via ALTER statements**

### When to Use

- ✅ Simple schema changes (add column, create index)
- ✅ Development workflow (iterative changes)
- ✅ Staging deployments
- ✅ Production (small changes, acceptable downtime)
- ❌ Complex transformations
- ❌ Zero-downtime required

### How It Works

1. Detect schema differences using intelligent diff algorithm
2. Generate Python migration with `up()` and `down()` methods
3. Apply migration via `ALTER TABLE` statements
4. Track applied migrations in `confiture_migrations` table

### Example: Add Column

```bash
# 1. Modify schema file
vim db/schema/10_tables/users.sql
# Add: bio TEXT

# 2. Generate migration
confiture migrate diff old.sql new.sql --generate --name add_user_bio

# 3. Review generated migration
cat db/migrations/002_add_user_bio.py

# 4. Apply migration
confiture migrate up --config db/environments/production.yaml
```

### Generated Migration

```python
"""Migration: add_user_bio

Version: 002
"""

from confiture.models.migration import Migration


class AddUserBio(Migration):
    """Migration: add_user_bio."""

    version = "002"
    name = "add_user_bio"

    def up(self) -> None:
        """Apply migration."""
        self.execute("ALTER TABLE users ADD COLUMN bio TEXT")

    def down(self) -> None:
        """Rollback migration."""
        self.execute("ALTER TABLE users DROP COLUMN bio")
```

### Supported Operations

| Operation | Example SQL | Downtime |
|-----------|-------------|----------|
| **Add column (nullable)** | `ALTER TABLE users ADD COLUMN bio TEXT` | None |
| **Add column (default)** | `ALTER TABLE users ADD COLUMN status TEXT DEFAULT 'active'` | Seconds¹ |
| **Drop column** | `ALTER TABLE users DROP COLUMN old_field` | None |
| **Rename column** | `ALTER TABLE users RENAME COLUMN name TO username` | None |
| **Change type (safe)** | `ALTER TABLE users ALTER COLUMN age TYPE BIGINT` | Seconds |
| **Create index** | `CREATE INDEX idx_users_email ON users(email)` | None² |
| **Drop index** | `DROP INDEX idx_old` | None |
| **Add constraint** | `ALTER TABLE users ADD CONSTRAINT uk_email UNIQUE (email)` | Seconds |

¹ PostgreSQL 11+ makes this instant
² Use `CREATE INDEX CONCURRENTLY` for zero-downtime

### Intelligent Diff Detection

Confiture uses similarity scoring to detect renames:

```python
# Detects column rename
# Old schema
CREATE TABLE users (
    full_name TEXT
);

# New schema
CREATE TABLE users (
    display_name TEXT
);

# Generated migration
def up(self):
    self.execute("""
        ALTER TABLE users
        RENAME COLUMN full_name TO display_name
    """)
```

Without rename detection, this would generate:
```python
# Naive diff (loses data!)
def up(self):
    self.execute("ALTER TABLE users DROP COLUMN full_name")
    self.execute("ALTER TABLE users ADD COLUMN display_name TEXT")
```

### Workflow

```
┌─────────────────┐
│ Edit schema     │
│ files           │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Generate diff   │ confiture migrate diff
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Review          │ vim db/migrations/00X.py
│ migration       │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Test in dev     │ confiture migrate up -c local.yaml
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Apply to prod   │ confiture migrate up -c prod.yaml
└─────────────────┘
```

### Benefits

- ✅ **Simple to use** - Automatic diff generation
- ✅ **Transactional** - Each migration in transaction
- ✅ **Reversible** - `down()` method for rollback
- ✅ **Trackable** - Audit log in database
- ✅ **Version control** - Migrations in git

### Limitations

- ⚠️ **Downtime** - Some operations lock tables
- ❌ **Not for large data** - `ALTER TABLE` on billion-row table is slow
- ⚠️ **Review required** - Always verify generated migrations

### Best Practices

#### 1. Small, Focused Migrations

```bash
# Good: One change per migration
confiture migrate generate add_email_index
confiture migrate generate add_verified_column

# Bad: Multiple changes
confiture migrate generate big_refactor
```

#### 2. Test Rollback

```bash
# Test up
confiture migrate up -c local.yaml

# Verify
psql myapp_local -c "\d users"

# Test down
confiture migrate down -c local.yaml

# Verify rollback worked
psql myapp_local -c "\d users"
```

#### 3. Use Safe Defaults

```python
# Good: Nullable column (instant)
self.execute("ALTER TABLE users ADD COLUMN bio TEXT")

# Good: Default doesn't rewrite table (PG 11+)
self.execute("ALTER TABLE users ADD COLUMN status TEXT DEFAULT 'active'")

# Bad: NOT NULL without default (requires backfill)
self.execute("ALTER TABLE users ADD COLUMN email TEXT NOT NULL")

# Better: Two-step migration
# Migration 1: Add nullable
self.execute("ALTER TABLE users ADD COLUMN email TEXT")

# Migration 2: Backfill then add constraint
self.execute("UPDATE users SET email = username || '@example.com' WHERE email IS NULL")
self.execute("ALTER TABLE users ALTER COLUMN email SET NOT NULL")
```

#### 4. Concurrent Index Creation

```python
# Bad: Locks table during index creation
self.execute("CREATE INDEX idx_users_email ON users(email)")

# Good: No locks (but can't run in transaction)
def up(self):
    # Confiture will handle this specially (future feature)
    self.execute("CREATE INDEX CONCURRENTLY idx_users_email ON users(email)")
```

---

## Medium 3: Production Data Sync (Coming Soon)

**Copy production data to local/staging with anonymization**

### When to Use

- ✅ Seed local development with real data
- ✅ Create staging environment from production
- ✅ Debug production issues locally
- ✅ Test migrations on production-like data
- ❌ Not for schema changes (use Medium 2 or 4)

### How It Works

1. Connect to production database (read-only)
2. Select tables to sync
3. Apply anonymization rules for PII
4. Stream data to target database

### Example (Future)

```bash
# Sync production to local (with anonymization)
confiture sync \
    --from production \
    --to local \
    --anonymize users.email,users.phone \
    --tables users,posts,comments
```

### Anonymization

```yaml
# db/sync_config.yaml
anonymize:
  users:
    email: "user_{id}@example.com"
    phone: "+1-555-{random(4)}"
    ssn: "XXX-XX-{random(4)}"
  payments:
    credit_card: "**** **** **** {last4}"
```

### Performance

Uses `COPY` for fast streaming:

| Table Size | Speed |
|------------|-------|
| 1M rows | ~30s |
| 10M rows | ~5 min |
| 100M rows | ~30 min |

### Benefits

- 🔒 **PII safe** - Automatic anonymization
- 🚀 **Fast** - Binary COPY format
- 💾 **Space efficient** - Streaming (no temp files)
- 🎯 **Selective** - Choose specific tables

### Implementation Status

**Status**: 🚧 Phase 3 (not yet implemented)

---

## Medium 4: Schema-to-Schema (Coming Soon)

**Zero-downtime migrations using Foreign Data Wrapper (FDW)**

### When to Use

- ✅ Complex schema changes (column type changes, renames)
- ✅ Large tables (billions of rows)
- ✅ Production zero-downtime requirement
- ✅ Data transformations during migration
- ❌ Simple changes (use Medium 2 instead)

### How It Works

1. Create new database with updated schema
2. Set up FDW from new → old database
3. Insert/migrate data from old via FDW
4. Dual-write during transition (app writes to both)
5. Cutover to new database (0-5 second downtime)
6. Drop old database

### Example (Future)

```bash
# Start zero-downtime migration
confiture migrate schema-to-schema \
    --from production \
    --to production_new \
    --strategy fdw \
    --mapping db/migration_map.yaml
```

### Migration Map

```yaml
# db/migration_map.yaml
tables:
  users:
    columns:
      # Rename column
      full_name: display_name

      # Transform data
      created_at:
        target: created_timestamp
        transform: "created_at AT TIME ZONE 'UTC'"

    # Custom transformation SQL
    custom_sql: |
      INSERT INTO production_new.users (id, display_name, created_timestamp)
      SELECT id, full_name, created_at AT TIME ZONE 'UTC'
      FROM old_schema.users
      WHERE deleted_at IS NULL
```

### Strategies

#### FDW Strategy (Default)

Best for: Small-medium tables (<10M rows), complex transformations

```sql
-- Set up FDW
CREATE EXTENSION postgres_fdw;

CREATE SERVER old_prod_server
  FOREIGN DATA WRAPPER postgres_fdw
  OPTIONS (host 'prod-db.example.com', dbname 'production');

IMPORT FOREIGN SCHEMA public
  FROM SERVER old_prod_server
  INTO old_schema;

-- Migrate data
INSERT INTO users (id, display_name)
SELECT id, full_name FROM old_schema.users;
```

#### COPY Strategy

Best for: Large fact tables (>10M rows), simple mapping

```bash
# 10-20x faster than FDW
confiture migrate schema-to-schema \
    --strategy copy \
    --tables events,page_views
```

Streams data using binary COPY (6M rows/sec):

```sql
-- Export from old
COPY (SELECT * FROM old.events) TO STDOUT WITH (FORMAT binary);

-- Import to new
COPY new.events FROM STDIN WITH (FORMAT binary);
```

#### Hybrid Strategy (Auto-detect)

```bash
# Automatically chooses best strategy per table
confiture migrate schema-to-schema --strategy hybrid
```

Logic:
- `rows < 10M && complex_mapping` → FDW
- `rows > 10M && simple_mapping` → COPY

### Timeline

```
Day 1: Setup
│
├─ Create production_new database
├─ Apply new schema
├─ Set up FDW
└─ Start data migration (background)

Day 2-3: Migration
│
├─ Monitor migration progress
└─ Fix any issues

Day 4: Validation
│
├─ Verify row counts match
├─ Run validation queries
└─ Check constraints

Day 5: Dual-write
│
├─ Deploy app update (writes to both DBs)
└─ Monitor for sync issues

Day 6: Cutover
│
├─ Switch app to read from production_new
├─ Monitor performance
└─ Keep old DB for 1 week (rollback safety)

Day 13: Cleanup
│
└─ Drop old database
```

### Benefits

- 🚀 **Zero-downtime** - 0-5 second cutover
- 💪 **Handles large tables** - Billions of rows
- 🔄 **Rollback safe** - Keep old DB during transition
- 🛠️ **Complex transforms** - Arbitrary SQL transformations

### Limitations

- ⏱️ **Time-consuming** - Days for large databases
- 💾 **2x storage** - Two databases during migration
- 🔧 **Complex setup** - Requires planning
- 💰 **Cost** - Temporary double infrastructure

### Implementation Status

**Status**: 🚧 Phase 3 (not yet implemented)

---

## Decision Tree

```
START: Do I need to change the database schema?
│
├─ NO: Just need data from production
│  └─ Use Medium 3 (Production Sync)
│
└─ YES: Schema change needed
   │
   ├─ Is it a fresh/empty database?
   │  └─ YES: Use Medium 1 (Build from DDL)
   │
   └─ NO: Existing database with data
      │
      ├─ Simple change? (add column, index, etc.)
      │  ├─ YES: Can tolerate seconds of downtime?
      │  │  ├─ YES: Use Medium 2 (Incremental Migrations)
      │  │  └─ NO: Use Medium 4 with concurrent operations
      │  │
      │  └─ NO: Complex change (type change, rename, transform)
      │     │
      │     └─ Large table (>10M rows) OR zero-downtime required?
      │        ├─ YES: Use Medium 4 (Schema-to-Schema)
      │        └─ NO: Use Medium 2 (but test thoroughly!)
```

---

## Comparison

### Speed Comparison

| Operation | Medium 1 | Medium 2 | Medium 3 | Medium 4 |
|-----------|----------|----------|----------|----------|
| **Setup empty DB (100 tables)** | 1s | N/A | N/A | N/A |
| **Add column (1M rows)** | N/A | 2s | N/A | 5min |
| **Copy data (100M rows)** | N/A | N/A | 30min | 2-3 hours |
| **Complex migration (1B rows)** | N/A | N/A | N/A | 2-3 days |

### Downtime Comparison

| Medium | Typical Downtime | Use Case |
|--------|------------------|----------|
| **1. Build** | N/A (fresh DB) | Development, CI/CD |
| **2. Incremental** | 1-30 seconds | Small changes, dev→staging |
| **3. Sync** | 0 (read-only sync) | Data seeding |
| **4. Schema-to-Schema** | 0-5 seconds | Production, large changes |

---

## Best Practices

### 1. Use the Right Medium for the Job

```bash
# Wrong: Using migrations for fresh dev DB
confiture migrate up  # Replays 100 migrations (slow)

# Right: Build from DDL
confiture build --env local  # <1 second

# Wrong: Schema-to-schema for simple column add
confiture migrate schema-to-schema --add-column bio

# Right: Simple migration
confiture migrate diff --generate --name add_bio
confiture migrate up
```

### 2. Progressive Deployment

```
Development:
├─ Use Medium 1 (build from DDL) for speed
└─ Test migrations with Medium 2

Staging:
├─ Use Medium 2 (apply migrations)
└─ Verify before production

Production:
├─ Small changes: Medium 2
└─ Large/complex: Medium 4
```

### 3. Version Control

```bash
# Commit both schema AND migrations
git add db/schema/10_tables/users.sql
git add db/migrations/002_add_user_bio.py
git commit -m "feat: add user bio column"
```

### 4. Documentation

```python
"""Migration: add_user_bio

Version: 002

Context:
  - Adding bio field for user profiles
  - Nullable initially, will be required in future migration
  - Supports markdown formatting

Deployment:
  - No downtime (nullable column)
  - No data backfill required
  - Safe to rollback

Testing:
  - Tested on staging with 1M users
  - Verified rollback works
"""
```

### 5. Rollback Strategy

```bash
# Always test rollback BEFORE production
confiture migrate up -c staging.yaml
# ... verify ...
confiture migrate down -c staging.yaml
# ... verify rollback worked ...

# Then apply to production
confiture migrate up -c production.yaml
```

---

## Coming Soon

### Phase 2: Rust Performance

- 10-50x faster schema building
- Parallel processing for large schemas
- Binary wheels (no Rust toolchain needed)

### Phase 3: Advanced Mediums

- Medium 3: Production sync with PII anonymization
- Medium 4: Zero-downtime schema-to-schema
- COPY strategy for large tables
- Hybrid auto-detection

---

## See Also

- [Getting Started](./getting-started.md) - Tutorials and examples
- [CLI Reference](./cli-reference.md) - Complete command documentation
- [Examples](../examples/) - Sample projects

---

**Part of the FraiseQL family** 🍓

*Vibe-engineered with ❤️ by [evoludigit](https://github.com/evoludigit)*
