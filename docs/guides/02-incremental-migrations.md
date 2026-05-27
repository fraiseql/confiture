# Incremental Migrations

[← Back to Guides](../index.md) · [Build from DDL](01-build-from-ddl.md) · [Production Sync →](03-production-sync.md)

**Apply schema changes to existing databases using ALTER statements**

---

## Use this guide if you're a migration-only project

`confiture build` (Medium 1) requires a `db/schema/` directory. **Every
other command in this guide does not.** `migrate up`, `migrate down`,
`migrate status`, `migrate baseline`, and `migrate preflight --against`
all operate on a pure migration chain — no canonical DDL required.

If your project is laid out as `db/migrations/001_*.sql … 005_*.sql` with
no `db/schema/` directory, this guide is your entry point. Skip the
build-from-DDL strategy entirely; the rest of confiture works.

---

## Overview

Incremental migrations apply targeted changes (ALTER TABLE, CREATE INDEX) to existing databases while preserving data.

> **"Track changes over time, modify schema incrementally"**

Each migration has two methods:
- `up()` - Apply the change
- `down()` - Reverse the change

### When to Use

| Use Case | Incremental Migrations |
|----------|----------------------|
| Add/drop columns | Perfect |
| Create indexes | Perfect |
| Fresh databases | Use Medium 1 |
| Zero-downtime required | Use Medium 4 |
| Large table refactoring | Use Medium 4 |

---

## Quick Start

```bash
# Apply all pending migrations
confiture migrate up

# Rollback last migration
confiture migrate down

# Check status
confiture migrate status

# Dry run
confiture migrate up --dry-run
```

---

## Creating Migrations

### Naming Requirements

Confiture has strict naming conventions for migration files. All migration filenames must follow one of these patterns:

```
{NNN}_{name}.py             # Python migrations
{NNN}_{name}.up.sql         # Forward migrations (SQL)
{NNN}_{name}.down.sql       # Rollback migrations (SQL)
```

**Important**: Files like `20260403120115_add_email.sql` (without `.up.sql`) are **silently ignored**!

**Examples**:
```
20260403120000_create_users.py         ✅ Correct
20260403120115_add_email.up.sql        ✅ Correct
20260403120115_add_email.down.sql      ✅ Correct
20260403120230_add_phone.sql           ❌ WRONG - missing .up suffix!
```

**See** [Migration Naming Best Practices](migration-naming-best-practices.md) for complete guidelines.

### Python Migrations

```python
# db/migrations/20260403120115_add_user_bio.py
"""Add bio column to users table"""

from confiture.models.migration import Migration

class AddUserBio(Migration):
    version = "20260403120115"
    name = "add_user_bio"

    def up(self) -> None:
        self.execute("""
            ALTER TABLE users ADD COLUMN bio TEXT
        """)

    def down(self) -> None:
        self.execute("""
            ALTER TABLE users DROP COLUMN bio
        """)
```

### SQL Migrations

```sql
-- db/migrations/20260403120115_add_user_bio.up.sql
-- Add bio column to users table

ALTER TABLE users ADD COLUMN bio TEXT;
```

```sql
-- db/migrations/20260403120115_add_user_bio.down.sql
-- Remove bio column from users table

ALTER TABLE users DROP COLUMN IF EXISTS bio;
```

**Note**: Both `.up.sql` and `.down.sql` files are needed for reversible migrations.

---

## Generating Migration Files

Use `confiture migrate generate` to create a new migration template with auto-incrementing version numbers:

```bash
# Basic usage - creates timestamp-based migration file
confiture migrate generate add_users

# Preview before creating (dry-run mode)
confiture migrate generate add_users_table --dry-run

# Show version calculation details
confiture migrate generate add_email_column --verbose

# JSON output for automation/agents
confiture migrate generate add_phone --format json
```

### Version Numbering

The command automatically:
- Scans existing migrations to find the highest version
- Increments by 1 and zero-pads to 3 digits (001, 002, ..., 999)
- Preserves gaps in numbering (001, 003, 005 → next is 006)

### Advanced Options

#### Dry-Run Mode

Preview the migration without creating any files:

```bash
confiture migrate generate add_users --dry-run
# Output:
# 🔍 Dry-run mode - no files will be created
#
# Would create migration:
#   Version: 20260403120000
#   Name: add_users
#   Class: AddUsers
#   File: /path/to/db/migrations/20260403120000_add_users.py
#
# [Template preview...]
```

#### Verbose Mode

Show directory scanning and version calculation:

```bash
confiture migrate generate add_email --verbose
# Output:
# 🔍 Scanning migrations directory...
#   Directory: /path/to/db/migrations
#   Found 2 migration files:
#     - 20260403120000_add_users.py (version: 20260403120000)
#     - 20260403120115_add_posts.py (version: 20260403120115)
#   Next version: 20260403120230 (current timestamp)
#   Target file: 20260403120230_add_email.py
```

#### JSON Output (for Automation)

Output structured JSON for parsing by scripts or CI/CD:

```bash
confiture migrate generate add_email --format json
```

Returns:
```json
{
  "status": "success",
  "version": "20260403120230",
  "name": "add_email",
  "filepath": "/path/to/db/migrations/20260403120230_add_email.py",
  "class_name": "AddEmail",
  "migrations_dir": "/path/to/db/migrations",
  "warnings": [],
  "next_available_version": "20260403120230"
}
```

### Safety Features

Confiture validates migration generation for safety:

1. **Duplicate Version Detection** - Warns if multiple files have same version
2. **Name Conflict Detection** - Warns if same name exists in different versions
3. **Concurrent Generation Protection** - File locking prevents race conditions in CI/CD

Example with warnings:

```bash
$ confiture migrate generate add_users
⚠️  Warning: Migration name 'add_users' already exists in other versions
    - 20260403120000_add_users.py
    - 20260403120115_add_users.py
✅ Migration generated successfully!
```

---

## Validating Migration Names

Use `confiture migrate validate` to check that all migration files are properly named:

```bash
# Check for orphaned files
confiture migrate validate

# Auto-fix naming issues
confiture migrate validate --fix-naming

# Preview without making changes
confiture migrate validate --fix-naming --dry-run
```

This catches common mistakes like:
- Missing `.up.sql` suffix: `20260403120000_schema.sql`
- Wrong suffix: `20260403120000_schema.sql` instead of `.up.sql`
- Inconsistent timestamps: `20260403120115_add_email.up.sql` and `20260403120230_add_email.down.sql`

---

## Common Operations

### Add Column (Fast)

```python
def up(self):
    # Nullable column - instant
    self.execute("ALTER TABLE users ADD COLUMN bio TEXT")

    # With default (PostgreSQL 11+) - instant
    self.execute("ALTER TABLE users ADD COLUMN status TEXT DEFAULT 'active'")
```

### Create Index (Use CONCURRENTLY)

```python
def up(self):
    # No locks with CONCURRENTLY
    self.execute("CREATE INDEX CONCURRENTLY idx_users_email ON users(email)")

def down(self):
    self.execute("DROP INDEX CONCURRENTLY idx_users_email")
```

### Two-Step NOT NULL

For adding NOT NULL columns to tables with existing data:

**Migration 1: Add nullable column**
```python
def up(self):
    self.execute("ALTER TABLE users ADD COLUMN email TEXT")
```

**Migration 2: Backfill and add constraint**
```python
def up(self):
    self.execute("UPDATE users SET email = username || '@example.com' WHERE email IS NULL")
    self.execute("ALTER TABLE users ALTER COLUMN email SET NOT NULL")
```

---

## Migration Tracking

Confiture records applied migrations in **`tb_confiture`** (default name, configurable per environment). See [the tracking-table reference](../reference/tracking-table.md) for the column shape.

```sql
SELECT version, name, applied_at, execution_time_ms
FROM tb_confiture
ORDER BY applied_at DESC
LIMIT 20;
```

Prefer the CLI for day-to-day queries:

```bash
confiture migrate status              # human-readable
confiture migrate status --format json | jq '.applied[-5:]'
```

---

## Rollback

### Rolling back the most recent migration

```bash
$ confiture migrate down

Rolling back: 20260520143015_add_user_bio
  ▸ Executing db/migrations/20260520143015_add_user_bio.down.sql
  ▸ Removing tb_confiture row for version 20260520143015
✓ Rolled back in 18 ms

$ confiture migrate status
Tracking table: tb_confiture (8 rows)
Applied:        8 migrations
Pending:        1 migration
  • 20260520143015_add_user_bio.up.sql  (un-applied — ready for `migrate up`)
```

### Rolling back to a specific version

`migrate down --target` runs each `down.sql` in reverse order until the target version is the newest applied row:

```bash
$ confiture migrate down --target 20260518090000

Will roll back 3 migrations:
  ◂ 20260520143015_add_user_bio
  ◂ 20260519140000_add_orders_table
  ◂ 20260518120000_alter_users_email_index
Continue? [y/N] y

✓ Rolled back 3 migrations in 142 ms
```

### Production rollback safety

- Confiture acquires the same advisory lock for `down` as it does for `up` — concurrent rollbacks are serialised.
- If a `down.sql` is missing or empty, `migrate down` fails before touching the database. There is no "best effort" rollback.
- For migrations that mark themselves `transactional: false` (e.g. `CREATE INDEX CONCURRENTLY` and its inverse), the rollback runs outside a transaction. Plan a forward-fix migration if anything goes wrong mid-rollback.
- `migrate preflight --against <db>` against a copy of production replays the `down` + `up` pair end-to-end before you touch real data. See [the dry-run guide](dry-run.md).

---

## Best Practices

1. **Small, focused migrations** - One change per file
2. **Test rollback** - Always verify `down()` works
3. **Use transactions** - Default behavior, atomic changes
4. **Document complex changes** - Add context in docstrings
5. **Update schema files** - Keep `db/schema/` in sync with migrations
6. **Use CONCURRENTLY** - For indexes on production tables
7. **Version numbering** - Zero-padded, sequential (001, 002, 003)

---

## Performance Guide

| Operation | 1M rows | 10M rows |
|-----------|---------|----------|
| ADD COLUMN (nullable) | 0.1s | 0.5s |
| DROP COLUMN | 0.1s | 0.5s |
| CREATE INDEX | 5s | 30s |
| CREATE INDEX CONCURRENTLY | 10s | 1min |
| ALTER TYPE (cast) | 30s | 5min |

---

## Common Issues

### Forgetting down() method
Always implement rollback logic.

### Mixing transactional operations
`CREATE INDEX CONCURRENTLY` can't run in transactions. Use separate migrations.

### Schema drift
Always update both `db/schema/` files and migrations together.

---

## See Also

- [Build from DDL](./01-build-from-ddl.md) - For fresh databases
- [Schema-to-Schema](./04-schema-to-schema.md) - For zero-downtime
- [ACL Coverage](./acl-coverage.md) - Catch tables that ship without `GRANT`s
- [Dry-Run Guide](./dry-run.md) - Test migrations safely
- [CLI Reference](../reference/cli.md) - All migrate commands
