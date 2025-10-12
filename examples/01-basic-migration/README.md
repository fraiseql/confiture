# Basic Migration Tutorial

**A complete beginner's guide to Confiture**

This example demonstrates the fundamental workflow of using Confiture for PostgreSQL migrations. You'll learn how to:

1. Initialize a Confiture project
2. Build a schema from DDL files (Medium 1)
3. Create and apply incremental migrations (Medium 2)
4. Manage multiple environments

**Time to complete**: 15 minutes

---

## Prerequisites

- Python 3.11 or higher
- PostgreSQL 14 or higher
- Confiture installed: `pip install confiture`

```bash
# Verify installation
confiture --version
# Should show: Confiture version X.X.X
```

---

## Project Structure

This example has the following structure:

```
01-basic-migration/
├── README.md                    # This file
├── db/
│   ├── schema/                  # DDL source files (CREATE TABLE, etc.)
│   │   ├── 00_common/
│   │   │   └── extensions.sql   # PostgreSQL extensions
│   │   ├── 10_tables/
│   │   │   └── users.sql        # Users table
│   │   └── 20_indexes/
│   │       └── users_indexes.sql # Indexes
│   │
│   ├── migrations/              # Incremental migrations
│   │   └── 001_add_user_bio.py  # Example migration
│   │
│   └── environments/            # Environment configurations
│       └── local.yaml           # Local development config
│
└── .gitignore
```

---

## Step 1: Set Up Database

Create a local PostgreSQL database for this tutorial:

```bash
# Create database
createdb confiture_tutorial

# Verify connection
psql confiture_tutorial -c "SELECT version()"
```

---

## Step 2: Explore the Schema Files

### 00_common/extensions.sql

This file enables PostgreSQL extensions needed for the project:

```sql
-- Enable UUID generation
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Enable timestamp functions
CREATE EXTENSION IF NOT EXISTS "btree_gist";
```

**Why numbered directories?**
Confiture processes files alphabetically. Using `00_`, `10_`, `20_` ensures correct execution order.

### 10_tables/users.sql

This defines the users table:

```sql
-- Users table
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Table comment
COMMENT ON TABLE users IS 'User accounts and profiles';
```

**Why `IF NOT EXISTS`?**
Allows the build command to be run multiple times safely.

### 20_indexes/users_indexes.sql

This creates performance indexes:

```sql
-- Email index for fast lookups
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);

-- Created date index for sorting
CREATE INDEX IF NOT EXISTS idx_users_created_at ON users(created_at DESC);
```

---

## Step 3: Build the Schema (Medium 1)

Build the database from DDL files:

```bash
# Build schema
confiture build --env local

# Expected output:
# Building schema for environment: local
# Found 3 SQL files
# Executing schema...
# ✅ Schema built successfully in 0.3s
```

**What happened?**
1. Confiture found all `.sql` files in `db/schema/`
2. Sorted them alphabetically (00_common → 10_tables → 20_indexes)
3. Concatenated them into a single script
4. Executed the script on your database

**Verify it worked:**

```bash
psql confiture_tutorial -c "\dt"

#  Schema |  Name  | Type  |  Owner
# --------+--------+-------+---------
#  public | users  | table | postgres
```

```bash
psql confiture_tutorial -c "SELECT * FROM users"

# id | email | display_name | created_at | updated_at
# ----+-------+--------------+------------+------------
# (0 rows)
```

---

## Step 4: Insert Test Data

Add some test users:

```bash
psql confiture_tutorial << EOF
INSERT INTO users (email, display_name)
VALUES
    ('alice@example.com', 'Alice'),
    ('bob@example.com', 'Bob'),
    ('charlie@example.com', 'Charlie');
EOF
```

**Verify:**

```bash
psql confiture_tutorial -c "SELECT email, display_name FROM users"

#        email        | display_name
# --------------------+--------------
#  alice@example.com  | Alice
#  bob@example.com    | Bob
#  charlie@example.com| Charlie
```

---

## Step 5: Create a Migration (Medium 2)

Now let's add a new column using an incremental migration.

### The Migration File

**db/migrations/001_add_user_bio.py**:

```python
"""Add bio column to users table

This migration adds a bio TEXT column for user biographies.
"""

from confiture.models.migration import Migration


class AddUserBio(Migration):
    """Add bio column to users table."""

    version = "001"
    name = "add_user_bio"

    def up(self) -> None:
        """Apply migration: Add bio column."""
        self.execute("""
            ALTER TABLE users
            ADD COLUMN bio TEXT
        """)

    def down(self) -> None:
        """Rollback migration: Remove bio column."""
        self.execute("""
            ALTER TABLE users
            DROP COLUMN bio
        """)
```

**Key points:**
- `version`: Unique migration identifier
- `name`: Human-readable name
- `up()`: Apply the change
- `down()`: Reverse the change (for rollback)

---

## Step 6: Apply the Migration

Apply the migration to add the bio column:

```bash
# Check migration status first
confiture migrate status --env local

# Expected output:
# ⏳ 001_add_user_bio (pending)

# Apply the migration
confiture migrate up --env local

# Expected output:
# Applying migration 001_add_user_bio...
# ✅ Migration 001_add_user_bio applied successfully (45ms)

# Check status again
confiture migrate status --env local

# Expected output:
# ✅ 001_add_user_bio (applied 2025-10-12 10:30:00)
```

**Verify the column was added:**

```bash
psql confiture_tutorial -c "\d users"

#                     Table "public.users"
#    Column     |           Type           | Nullable | Default
# --------------+--------------------------+----------+------------
#  id           | uuid                     | not null | uuid_generate_v4()
#  email        | text                     | not null |
#  display_name | text                     | not null |
#  created_at   | timestamp with time zone | not null | now()
#  updated_at   | timestamp with time zone | not null | now()
#  bio          | text                     |          |          ← New!
```

---

## Step 7: Test Rollback

Let's test rolling back the migration:

```bash
# Rollback the migration
confiture migrate down --env local

# Expected output:
# Rolling back migration 001_add_user_bio...
# ✅ Migration 001_add_user_bio rolled back successfully (32ms)

# Verify bio column is gone
psql confiture_tutorial -c "\d users"

# (bio column should be missing)

# Re-apply the migration
confiture migrate up --env local
```

**Why test rollback?**
Always test rollback in development before deploying to production. You need confidence that you can undo a migration if something goes wrong.

---

## Step 8: Update the Schema File

**Important**: After applying a migration, update the schema file to match.

Edit `db/schema/10_tables/users.sql` and add the bio column:

```sql
-- Users table
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    bio TEXT,  -- ← Add this line
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE users IS 'User accounts and profiles';
COMMENT ON COLUMN users.bio IS 'User biography (supports markdown)';  -- ← Add this
```

**Why update both?**
- Schema files = source of truth for fresh databases
- Migrations = how to evolve existing databases

Both should always be in sync.

---

## Step 9: Verify Fresh Build Still Works

Test that a fresh database can be built from schema files:

```bash
# Drop and recreate database
dropdb confiture_tutorial
createdb confiture_tutorial

# Build from schema files (should include bio column now)
confiture build --env local

# Verify bio column exists
psql confiture_tutorial -c "\d users"

# (bio column should be present without running migration)
```

**What this proves:**
New developers can get a working database with `confiture build` (without replaying migration history).

---

## Common Workflow

Here's the typical development workflow:

```bash
# 1. Make schema changes in db/schema/
vim db/schema/10_tables/users.sql

# 2. Create migration
vim db/migrations/002_next_change.py

# 3. Test migration locally
confiture migrate up --env local
psql confiture_tutorial -c "\d users"  # Verify

# 4. Test rollback
confiture migrate down --env local
psql confiture_tutorial -c "\d users"  # Verify

# 5. Re-apply
confiture migrate up --env local

# 6. Commit both schema and migration
git add db/schema/10_tables/users.sql
git add db/migrations/002_next_change.py
git commit -m "feat: add user avatar column"
```

---

## Environment Configuration

The `db/environments/local.yaml` file defines database connection settings:

```yaml
name: local
database:
  host: localhost
  port: 5432
  database: confiture_tutorial
  user: postgres
  password: postgres

include_dirs:
  - db/schema

exclude_dirs: []
```

**Multiple environments:**

```bash
# Local development
confiture build --env local

# CI/CD testing
confiture build --env ci

# Staging
confiture migrate up --env staging

# Production
confiture migrate up --env production
```

---

## Next Steps

### Try More Complex Migrations

1. **Add indexes**:
```python
def up(self):
    self.execute("CREATE INDEX idx_users_bio ON users(bio)")
```

2. **Add constraints**:
```python
def up(self):
    self.execute("ALTER TABLE users ADD CONSTRAINT email_format CHECK (email LIKE '%@%')")
```

3. **Data transformations**:
```python
def up(self):
    self.execute("UPDATE users SET bio = 'New user' WHERE bio IS NULL")
    self.execute("ALTER TABLE users ALTER COLUMN bio SET NOT NULL")
```

### Explore Other Examples

- **[02-fraiseql-integration](../02-fraiseql-integration/)** - GraphQL schema integration
- **[03-zero-downtime-migration](../03-zero-downtime-migration/)** - Production migrations
- **[04-production-sync-anonymization](../04-production-sync-anonymization/)** - Data syncing
- **[05-multi-environment-workflow](../05-multi-environment-workflow/)** - CI/CD setup

### Read the Guides

- **[Migration Decision Tree](../../docs/guides/migration-decision-tree.md)** - Which medium to use when
- **[Medium 1: Build from DDL](../../docs/guides/medium-1-build-from-ddl.md)** - Deep dive
- **[Medium 2: Incremental Migrations](../../docs/guides/medium-2-incremental-migrations.md)** - Advanced patterns

---

## Troubleshooting

### Build fails: "No SQL files found"

**Cause**: Wrong directory structure

**Solution**: Verify files are in `db/schema/` subdirectories
```bash
ls -R db/schema/
# Should show: 00_common/, 10_tables/, 20_indexes/
```

### Migration fails: "relation already exists"

**Cause**: Schema file missing `IF NOT EXISTS`

**Solution**: Add to all CREATE statements
```sql
CREATE TABLE IF NOT EXISTS users (...);
```

### Migration fails: "Not connected"

**Cause**: Wrong database credentials

**Solution**: Check `db/environments/local.yaml`
```bash
psql -h localhost -U postgres -d confiture_tutorial -c "SELECT 1"
```

---

## Clean Up

When done with this tutorial:

```bash
# Drop the tutorial database
dropdb confiture_tutorial
```

---

## Summary

You've learned:

- ✅ **Medium 1 (Build from DDL)**: Fast fresh database setup (`confiture build`)
- ✅ **Medium 2 (Incremental Migrations)**: Schema evolution (`confiture migrate up/down`)
- ✅ **Migration workflow**: Edit schema → Create migration → Test → Commit
- ✅ **Best practices**: Always test rollback, keep schema files in sync

**Key takeaway**: Confiture treats DDL files as the source of truth, making fresh database setup instant while still supporting incremental migrations for existing databases.

---

## Further Reading

- [Confiture Documentation](../../README.md)
- [CLI Reference](../../docs/reference/cli.md)
- [Organizing SQL Files](../../docs/organizing-sql-files.md)

---

**Part of the Confiture examples** 🍓

*Your first steps with Confiture migrations*
