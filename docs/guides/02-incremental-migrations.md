# Incremental Migrations

[← Back to Guides](../index.md) · [Build from DDL](01-build-from-ddl.md) · [Production Sync →](03-production-sync.md)

**Apply schema changes to existing databases using ALTER statements**

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

**Important**: Files like `001_add_email.sql` (without `.up.sql`) are **silently ignored**!

**Examples**:
```
001_create_users.py         ✅ Correct
002_add_email.up.sql        ✅ Correct
002_add_email.down.sql      ✅ Correct
003_add_phone.sql           ❌ WRONG - missing .up suffix!
```

**See** [Migration Naming Best Practices](migration-naming-best-practices.md) for complete guidelines.

### Python Migrations

```python
# db/migrations/002_add_user_bio.py
"""Add bio column to users table"""

from confiture.models.migration import Migration

class AddUserBio(Migration):
    version = "002"
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
-- db/migrations/002_add_user_bio.up.sql
-- Add bio column to users table

ALTER TABLE users ADD COLUMN bio TEXT;
```

```sql
-- db/migrations/002_add_user_bio.down.sql
-- Remove bio column from users table

ALTER TABLE users DROP COLUMN IF EXISTS bio;
```

**Note**: Both `.up.sql` and `.down.sql` files are needed for reversible migrations.

---

## Generating Migration Files

Use `confiture migrate generate` to create a new migration template with auto-incrementing version numbers:

```bash
# Basic usage - creates 001_add_users.py
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
#   Version: 001
#   Name: add_users
#   Class: AddUsers
#   File: /path/to/db/migrations/001_add_users.py
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
#     - 001_add_users.py (version: 001)
#     - 002_add_posts.py (version: 002)
#   Highest version: 002
#   Next version: 003
#   Target file: 003_add_email.py
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
  "version": "003",
  "name": "add_email",
  "filepath": "/path/to/db/migrations/003_add_email.py",
  "class_name": "AddEmail",
  "migrations_dir": "/path/to/db/migrations",
  "warnings": [],
  "next_available_version": "003"
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
⚠️  Warning: Duplicate versions detected: 003, 005
⚠️  Warning: Migration name 'add_users' already exists in other versions
    - 001_add_users.py
    - 002_add_users.py
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
- Missing `.up.sql` suffix: `001_schema.sql`
- Wrong suffix: `001_schema.sql` instead of `.up.sql`
- Inconsistent version numbers: `001_add_email.up.sql` and `002_add_email.down.sql`

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

Confiture tracks applied migrations in `confiture_migrations`:

```sql
SELECT version, name, applied_at FROM confiture_migrations ORDER BY applied_at;
```

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
- [Dry-Run Guide](./dry-run.md) - Test migrations safely
- [CLI Reference](../reference/cli.md) - All migrate commands
