# Medium 2: Incremental Migrations

**Apply schema changes to existing databases using ALTER statements**

## What are Incremental Migrations?

Incremental migrations are the traditional approach to database schema evolution. Instead of rebuilding the entire schema, you apply targeted changes (ALTER TABLE, CREATE INDEX, etc.) to existing databases.

### Key Concept

> **"Track changes over time, modify schema incrementally"**

Each migration is a Python file with two methods:
- `up()` - Apply the change (e.g., ADD COLUMN)
- `down()` - Reverse the change (e.g., DROP COLUMN)

Confiture tracks which migrations have been applied in the `confiture_migrations` table, ensuring each runs exactly once.

---

## When to Use Incremental Migrations

### ✅ Perfect For

- **Simple schema changes** - Add column, create index, add constraint
- **Development iteration** - Evolving schema during feature development
- **Staging deployments** - Testing changes before production
- **Production changes** - When 1-30 seconds downtime is acceptable
- **Collaborative work** - Team members can see migration history

### ❌ Not For

- **Fresh databases** - Use Medium 1 (Build from DDL) instead
- **Zero-downtime required** - Use Medium 4 (Schema-to-Schema)
- **Complex transformations** - Large tables with type changes
- **Production data sync** - Use Medium 3 instead

### Comparison with Medium 1 (Build from DDL)

| Scenario | Medium 1 (Build) | Medium 2 (Migrate) |
|----------|------------------|-------------------|
| Fresh database | ✅ <1s | ❌ Slower (replays history) |
| Existing database | ❌ Drops data | ✅ Preserves data |
| CI/CD tests | ✅ Fastest | ❌ Slower |
| Production | ❌ Can't use | ✅ Schema evolution |

---

## How Incremental Migrations Work

### Migration Lifecycle

```
1. Create Migration File
   ↓
   db/migrations/002_add_user_bio.py

2. Define up() and down()
   ↓
   up():   ALTER TABLE users ADD COLUMN bio TEXT
   down(): ALTER TABLE users DROP COLUMN bio

3. Apply Migration
   ↓
   confiture migrate up
   → Executes up() method
   → Records in confiture_migrations table

4. (If needed) Rollback
   ↓
   confiture migrate down
   → Executes down() method
   → Removes from confiture_migrations table
```

### Tracking Table

Confiture creates `confiture_migrations` to track applied migrations:

```sql
CREATE TABLE confiture_migrations (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    pk_migration UUID NOT NULL DEFAULT uuid_generate_v4() UNIQUE,
    slug TEXT NOT NULL UNIQUE,              -- human-readable: name_YYYYMMDD_HHMMSS
    version VARCHAR(255) NOT NULL UNIQUE,   -- e.g., "002"
    name VARCHAR(255) NOT NULL,             -- e.g., "add_user_bio"
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    execution_time_ms INTEGER,
    checksum VARCHAR(64)
);
```

**Identity Trinity Pattern**:
- `id`: Auto-increment (internal)
- `pk_migration`: UUID (stable, external APIs)
- `slug`: Human-readable (name + timestamp)

---

## Creating Migrations

### Manual Creation

Create migration file in `db/migrations/`:

**db/migrations/002_add_user_bio.py**:
```python
"""Add bio column to users table

Migration: 002_add_user_bio
Author: Your Name
Date: 2025-10-12

Description:
  Adds a bio TEXT column to the users table to store user biographies.
  Column is nullable to allow existing users without bio.

Rollback:
  Safe - drops bio column
"""

from confiture.models.migration import Migration


class AddUserBio(Migration):
    """Add bio column to users table."""

    version = "002"
    name = "add_user_bio"

    def up(self) -> None:
        """Apply migration: Add bio column."""
        self.execute("""
            ALTER TABLE users
            ADD COLUMN bio TEXT
        """)

        # Add column comment for documentation
        self.execute("""
            COMMENT ON COLUMN users.bio IS
            'User biography (markdown supported, max 5000 chars)'
        """)

    def down(self) -> None:
        """Rollback migration: Remove bio column."""
        self.execute("""
            ALTER TABLE users
            DROP COLUMN bio
        """)
```

### Auto-Generation (Future)

```bash
# Generate migration from schema diff (future feature)
confiture migrate generate --name add_user_bio

# Detects changes between current database and db/schema/*.sql
# Generates migration file automatically
```

---

## Migration Commands

### Apply Migrations

```bash
# Apply all pending migrations
confiture migrate up

# Apply up to specific version
confiture migrate up --target 005

# Dry run (show SQL without executing)
confiture migrate up --dry-run
```

### Rollback Migrations

```bash
# Rollback last migration
confiture migrate down

# Rollback to specific version
confiture migrate down --target 003

# Rollback all migrations
confiture migrate down --target 0
```

### Check Status

```bash
# Show migration status
confiture migrate status

# Example output:
# ✅ 001_create_users (applied 2025-10-01 10:30:00)
# ✅ 002_add_user_bio (applied 2025-10-05 14:22:00)
# ⏳ 003_add_posts (pending)
# ⏳ 004_add_indexes (pending)
```

### Migration History

```bash
# Show detailed history
confiture migrate history

# Example output:
# Version | Name            | Applied At          | Execution Time
# --------|-----------------|---------------------|---------------
# 002     | add_user_bio    | 2025-10-05 14:22:00 | 245ms
# 001     | create_users    | 2025-10-01 10:30:00 | 1.2s
```

---

## Supported Operations

### Add Column (Fast)

```python
def up(self):
    # Nullable column - instant operation
    self.execute("ALTER TABLE users ADD COLUMN bio TEXT")

    # With default (PostgreSQL 11+) - instant
    self.execute("ALTER TABLE users ADD COLUMN status TEXT DEFAULT 'active'")

    # NOT NULL requires backfill (use two-step migration)
```

**Downtime**: None (seconds for very large tables)

---

### Drop Column (Fast)

```python
def up(self):
    self.execute("ALTER TABLE users DROP COLUMN old_field")
```

**Downtime**: None (PostgreSQL doesn't rewrite table)

---

### Rename Column (Fast)

```python
def up(self):
    self.execute("ALTER TABLE users RENAME COLUMN full_name TO display_name")

def down(self):
    self.execute("ALTER TABLE users RENAME COLUMN display_name TO full_name")
```

**Downtime**: None (metadata-only change)

---

### Change Column Type (Variable)

```python
def up(self):
    # Compatible types - fast
    self.execute("ALTER TABLE users ALTER COLUMN age TYPE BIGINT")

    # Incompatible types - requires USING (slow, table rewrite)
    self.execute("""
        ALTER TABLE users
        ALTER COLUMN user_id TYPE BIGINT
        USING user_id::BIGINT
    """)
```

**Downtime**: Seconds to minutes (locks table during rewrite)

---

### Create Index (Use CONCURRENTLY)

```python
def up(self):
    # Bad: Locks table during index creation
    # self.execute("CREATE INDEX idx_users_email ON users(email)")

    # Good: No locks (but can't run in transaction)
    self.execute("CREATE INDEX CONCURRENTLY idx_users_email ON users(email)")

def down(self):
    self.execute("DROP INDEX CONCURRENTLY idx_users_email")
```

**Downtime**: None (with CONCURRENTLY)

---

### Add Constraint (Variable)

```python
def up(self):
    # Check constraint - fast if data valid
    self.execute("""
        ALTER TABLE users
        ADD CONSTRAINT check_age_positive CHECK (age > 0)
    """)

    # NOT NULL - requires all rows to have value
    self.execute("""
        ALTER TABLE users
        ALTER COLUMN email SET NOT NULL
    """)

    # Foreign key - validates all existing data
    self.execute("""
        ALTER TABLE posts
        ADD CONSTRAINT fk_posts_user
        FOREIGN KEY (user_id) REFERENCES users(id)
    """)
```

**Downtime**: Seconds (locks table during validation)

---

## Migration Patterns

### Two-Step Migration (NOT NULL)

**Problem**: Adding NOT NULL column to table with existing data

**Solution**: Split into two migrations

#### Migration 1: Add nullable column
```python
class AddEmailColumn(Migration):
    version = "003"
    name = "add_email_column"

    def up(self):
        self.execute("ALTER TABLE users ADD COLUMN email TEXT")

    def down(self):
        self.execute("ALTER TABLE users DROP COLUMN email")
```

#### Migration 2: Backfill and add constraint
```python
class MakeEmailRequired(Migration):
    version = "004"
    name = "make_email_required"

    def up(self):
        # Backfill existing records
        self.execute("""
            UPDATE users
            SET email = username || '@example.com'
            WHERE email IS NULL
        """)

        # Now add NOT NULL constraint
        self.execute("""
            ALTER TABLE users
            ALTER COLUMN email SET NOT NULL
        """)

    def down(self):
        self.execute("""
            ALTER TABLE users
            ALTER COLUMN email DROP NOT NULL
        """)
```

---

### Data Migration

**Problem**: Need to transform data during schema change

```python
class SplitFullName(Migration):
    version = "005"
    name = "split_full_name"

    def up(self):
        # Add new columns
        self.execute("ALTER TABLE users ADD COLUMN first_name TEXT")
        self.execute("ALTER TABLE users ADD COLUMN last_name TEXT")

        # Migrate data
        self.execute("""
            UPDATE users
            SET
                first_name = split_part(full_name, ' ', 1),
                last_name = split_part(full_name, ' ', 2)
            WHERE full_name IS NOT NULL
        """)

        # Drop old column
        self.execute("ALTER TABLE users DROP COLUMN full_name")

    def down(self):
        # Recreate old column
        self.execute("ALTER TABLE users ADD COLUMN full_name TEXT")

        # Reverse data migration
        self.execute("""
            UPDATE users
            SET full_name = first_name || ' ' || last_name
            WHERE first_name IS NOT NULL
        """)

        # Drop new columns
        self.execute("ALTER TABLE users DROP COLUMN first_name")
        self.execute("ALTER TABLE users DROP COLUMN last_name")
```

---

### Complex Index with Partial Condition

```python
class AddPartialIndex(Migration):
    version = "006"
    name = "add_active_users_index"

    def up(self):
        # Create partial index (only active users)
        self.execute("""
            CREATE INDEX CONCURRENTLY idx_users_active_email
            ON users(email)
            WHERE status = 'active'
        """)

        # Add comment
        self.execute("""
            COMMENT ON INDEX idx_users_active_email IS
            'Partial index for active users only (reduces index size by 70%)'
        """)

    def down(self):
        self.execute("DROP INDEX CONCURRENTLY idx_users_active_email")
```

---

## Best Practices

### 1. Small, Focused Migrations

```bash
# Good: One change per migration
002_add_user_bio.py
003_add_user_avatar.py
004_add_email_index.py

# Bad: Multiple unrelated changes
002_big_refactor.py  # Adds bio, avatar, index, and constraint
```

**Why**: Easier to review, test, and rollback

---

### 2. Test Rollback Before Production

```bash
# Local testing workflow
confiture migrate up -c local.yaml
# Verify migration worked
psql myapp_local -c "\d users"

# Test rollback
confiture migrate down -c local.yaml
# Verify rollback worked
psql myapp_local -c "\d users"

# Re-apply for deployment
confiture migrate up -c local.yaml
```

---

### 3. Use Transactions (Default)

Confiture runs migrations in transactions by default:

```python
def up(self):
    # Both succeed or both fail (atomic)
    self.execute("ALTER TABLE users ADD COLUMN bio TEXT")
    self.execute("ALTER TABLE users ADD COLUMN avatar TEXT")
```

**Exception**: `CREATE INDEX CONCURRENTLY` cannot run in transaction

---

### 4. Document Complex Migrations

```python
"""Split full_name into first_name and last_name

Migration: 005_split_full_name
Author: Alice Smith
Date: 2025-10-12

Context:
  - Marketing team needs first_name for personalization
  - Splitting "John Doe" → first_name="John", last_name="Doe"
  - Handles edge cases: single name, multiple spaces

Risks:
  - Data loss for complex names (e.g., "Mary Jane Watson")
  - Consider manual verification for important accounts

Rollback:
  - Safe: Concatenates first_name + last_name back to full_name
  - May lose formatting (extra spaces)

Testing:
  - Tested on staging with 1M users
  - Verified rollback works correctly
"""
```

---

### 5. Use Safe Defaults

```python
# Good: Nullable column (instant)
self.execute("ALTER TABLE users ADD COLUMN bio TEXT")

# Good: Default without NOT NULL (PostgreSQL 11+: instant)
self.execute("ALTER TABLE users ADD COLUMN status TEXT DEFAULT 'active'")

# Bad: NOT NULL without default (requires backfill)
self.execute("ALTER TABLE users ADD COLUMN email TEXT NOT NULL")  # ❌ Fails on existing rows

# Better: Two-step migration (see pattern above)
```

---

### 6. Version Numbering

```bash
# Good: Sequential, zero-padded
001_create_users.py
002_add_user_bio.py
003_add_posts.py
...
042_add_comments.py

# Bad: Non-sequential or no padding
1_users.py
5_bio.py
42_comments.py  # Sorts incorrectly
```

---

## Common Pitfalls

### ❌ Pitfall 1: Forgetting down() Method

```python
# Bad: No rollback
def up(self):
    self.execute("ALTER TABLE users ADD COLUMN bio TEXT")

# Missing down() method!
```

**Solution**: Always implement down()
```python
def down(self):
    self.execute("ALTER TABLE users DROP COLUMN bio")
```

---

### ❌ Pitfall 2: Non-Transactional Operations

```python
# Bad: Mix of transactional and non-transactional
def up(self):
    self.execute("ALTER TABLE users ADD COLUMN bio TEXT")  # Transactional
    self.execute("CREATE INDEX CONCURRENTLY idx_bio ON users(bio)")  # Non-transactional
    # ❌ If index creation fails, column still added
```

**Solution**: Separate migrations
```python
# Migration 1: Add column (transactional)
def up(self):
    self.execute("ALTER TABLE users ADD COLUMN bio TEXT")

# Migration 2: Add index (non-transactional)
def up(self):
    self.execute("CREATE INDEX CONCURRENTLY idx_bio ON users(bio)")
```

---

### ❌ Pitfall 3: Data Loss on Rollback

```python
# Bad: down() doesn't preserve data
def up(self):
    self.execute("ALTER TABLE users RENAME COLUMN name TO full_name")
    self.execute("ALTER TABLE users ADD COLUMN first_name TEXT")
    self.execute("UPDATE users SET first_name = split_part(full_name, ' ', 1)")

def down(self):
    self.execute("ALTER TABLE users DROP COLUMN first_name")
    self.execute("ALTER TABLE users RENAME COLUMN full_name TO name")
    # ❌ Lost first_name transformation
```

**Solution**: Reversible transformations
```python
def down(self):
    # Reconstruct original if needed
    self.execute("UPDATE users SET full_name = first_name || ' ' || last_name")
    self.execute("ALTER TABLE users DROP COLUMN first_name")
    self.execute("ALTER TABLE users RENAME COLUMN full_name TO name")
```

---

### ❌ Pitfall 4: Forgetting to Update Schema Files

**Problem**: Migration applied but db/schema/*.sql not updated

```bash
# Applied migration
confiture migrate up  # Adds bio column

# But schema file still missing bio
cat db/schema/10_tables/users.sql  # No bio column!
```

**Solution**: Always update both
```bash
# 1. Update schema file
vim db/schema/10_tables/users.sql  # Add bio column

# 2. Create migration
vim db/migrations/002_add_user_bio.py

# 3. Commit both together
git add db/schema/10_tables/users.sql db/migrations/002_add_user_bio.py
git commit -m "feat: add user bio column"
```

---

## Workflow Integration

### Development Workflow

```bash
# 1. Update schema file
vim db/schema/10_tables/users.sql
# Add: bio TEXT

# 2. Create migration
vim db/migrations/002_add_user_bio.py

# 3. Test locally
confiture migrate up -c local.yaml
psql myapp_local -c "SELECT * FROM users LIMIT 1"

# 4. Test rollback
confiture migrate down -c local.yaml
psql myapp_local -c "\d users"

# 5. Re-apply
confiture migrate up -c local.yaml

# 6. Commit
git add db/schema/10_tables/users.sql db/migrations/002_add_user_bio.py
git commit -m "feat: add user bio column"
```

---

### Deployment Workflow

```bash
# Staging deployment
ssh staging
git pull
confiture migrate up -c staging.yaml

# Verify
psql myapp_staging -c "\d users"

# Production deployment (after staging verification)
ssh production
git pull
confiture migrate up -c production.yaml --dry-run  # Review first
confiture migrate up -c production.yaml             # Execute
```

---

### CI/CD Integration

```yaml
# .github/workflows/test.yml
name: Test

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest

    services:
      postgres:
        image: postgres:16
        env:
          POSTGRES_DB: myapp_test
          POSTGRES_USER: postgres
          POSTGRES_PASSWORD: postgres
        options: >-
          --health-cmd pg_isready
          --health-interval 10s

    steps:
      - uses: actions/checkout@v3

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: pip install confiture

      - name: Run migrations
        run: confiture migrate up -c test.yaml

      - name: Run tests
        run: pytest tests/
```

---

## Performance Considerations

### Operation Timing (Approximate)

| Operation | 1M rows | 10M rows | 100M rows |
|-----------|---------|----------|-----------|
| ADD COLUMN (nullable) | 0.1s | 0.5s | 2s |
| ADD COLUMN (default) | 0.1s | 0.5s | 2s |
| DROP COLUMN | 0.1s | 0.5s | 2s |
| ALTER TYPE (compatible) | 10s | 1min | 10min |
| ALTER TYPE (cast) | 30s | 5min | 1hour |
| CREATE INDEX | 5s | 30s | 5min |
| CREATE INDEX CONCURRENTLY | 10s | 1min | 10min |

---

## See Also

- [Migration Decision Tree](./migration-decision-tree.md) - When to use Medium 2
- [Medium 1: Build from DDL](./medium-1-build-from-ddl.md) - For fresh databases
- [Medium 4: Schema-to-Schema](./medium-4-schema-to-schema.md) - For zero-downtime
- [Example: Basic Migration](../../examples/01-basic-migration/) - Complete tutorial
- [CLI Reference](../reference/cli.md) - All migrate commands

---

## Quick Reference

### Commands
```bash
confiture migrate up                    # Apply pending migrations
confiture migrate down                  # Rollback last migration
confiture migrate status                # Show migration status
confiture migrate up --target 005       # Apply up to version 005
confiture migrate down --target 003     # Rollback to version 003
```

### Migration Template
```python
from confiture.models.migration import Migration

class MyMigration(Migration):
    version = "00X"
    name = "my_migration"

    def up(self):
        self.execute("ALTER TABLE users ADD COLUMN bio TEXT")

    def down(self):
        self.execute("ALTER TABLE users DROP COLUMN bio")
```

### Best Practices
- ✅ Small, focused migrations (one change per file)
- ✅ Test rollback before production
- ✅ Use transactions (default)
- ✅ Document complex migrations
- ✅ Update both schema files and migrations
- ✅ Use CONCURRENTLY for indexes
- ✅ Two-step migrations for NOT NULL

---

**Part of the Confiture documentation** 🍓

*Evolving schemas, one migration at a time*
