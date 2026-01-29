# Getting Started with Confiture

> **⚠️ Beta Software**: Confiture has not yet been used in production. Use with caution for critical workloads.

**Confiture** is a PostgreSQL schema evolution framework with built-in multi-agent coordination. Whether you're a solo developer or part of a team with AI agents, Confiture provides safe schema evolution with automatic conflict detection.

## Choose Your Workflow

**Solo Developer?** Follow the [Quick Start](#quick-start-5-minutes) below for traditional migration workflow.

**Working with a team or AI agents?** Skip to [Multi-Agent Coordination](#multi-agent-coordination-workflow) for collaborative schema development.

Not sure? Multi-agent coordination is **optional but recommended** - it provides safety even for solo developers.

## Installation

Install Confiture using pip or uv:

```bash
# Using pip
pip install confiture

# Using uv (recommended)
uv add confiture
```

## Prerequisites

- Python 3.11+
- PostgreSQL 12+
- Basic understanding of SQL and database migrations

## Quick Start (5 minutes)

### 1. Initialize a Project

Create a new directory and initialize Confiture:

```bash
mkdir myapp
cd myapp
confiture init
```

This creates the following structure:

```
myapp/
├── db/
│   ├── schema/           # DDL: CREATE TABLE, CREATE VIEW, etc.
│   │   ├── 00_common/
│   │   │   └── extensions.sql
│   │   └── 10_tables/
│   │       └── example.sql
│   ├── seeds/            # Seed data: INSERT statements
│   │   ├── common/       # All non-production environments
│   │   ├── development/  # Development-specific
│   │   └── test/         # Test-specific
│   ├── migrations/       # Generated migration files
│   └── environments/     # Environment configurations
│       ├── local.yaml
│       ├── test.yaml
│       └── production.yaml
```

### 2. Configure Your Database

Edit `db/environments/local.yaml`:

```yaml
name: local

# Include schema DDL and seed data
includes:
  - ../schema           # All schema files
  - ../seeds/common     # Common seed data
  - ../seeds/development  # Development-specific seeds

database:
  host: localhost
  port: 5432
  database: myapp_local
  user: postgres
  password: postgres
```

**Production configuration** (`db/environments/production.yaml`) typically excludes seeds:

```yaml
name: production

# Only schema, no seed data!
includes:
  - ../schema

database:
  host: ${DB_HOST}
  port: ${DB_PORT}
  database: ${DB_NAME}
  user: ${DB_USER}
  password: ${DB_PASSWORD}
```

### 3. Create Your Schema

Edit `db/schema/10_tables/users.sql`:

```sql
-- Users table
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    email TEXT NOT NULL UNIQUE,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_users_username ON users(username);
CREATE INDEX idx_users_email ON users(email);
```

### 4. Generate Your First Migration

First, create an empty schema file to compare against:

```bash
echo "" > db/schema/empty.sql
```

Now generate a migration from the diff:

```bash
confiture migrate diff db/schema/empty.sql db/schema/10_tables/users.sql \
    --generate \
    --name create_users_table
```

This creates `db/migrations/001_create_users_table.py`:

```python
"""Migration: create_users_table

Version: 001
"""

from confiture.models.migration import Migration


class CreateUsersTable(Migration):
    """Migration: create_users_table."""

    version = "001"
    name = "create_users_table"

    def up(self) -> None:
        """Apply migration."""
        self.execute("""
            CREATE TABLE users (
                id SERIAL PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                email TEXT NOT NULL UNIQUE,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        self.execute("CREATE INDEX idx_users_username ON users(username)")
        self.execute("CREATE INDEX idx_users_email ON users(email)")

    def down(self) -> None:
        """Rollback migration."""
        self.execute("DROP TABLE users")
```

### 5. Check Migration Status

```bash
confiture migrate status --config db/environments/local.yaml
```

Output:
```
                    Migrations
┏━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┓
┃ Version ┃ Name               ┃ Status   ┃
┡━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━┩
│ 001     │ create_users_table │ ⏳ pending │
└─────────┴────────────────────┴──────────┘

📊 Total: 1 migrations (0 applied, 1 pending)
```

### 6. Apply the Migration

```bash
confiture migrate up --config db/environments/local.yaml
```

Output:
```
📦 Found 1 pending migration(s)

⚡ Applying 001_create_users_table... ✅

✅ Successfully applied 1 migration(s)!
```

### 7. Verify in Database

```bash
psql myapp_local -c "\dt"
```

You should see:
```
                List of relations
 Schema |        Name         | Type  |  Owner
--------+---------------------+-------+----------
 public | confiture_migrations| table | postgres
 public | users               | table | postgres
```

### 8. Make a Schema Change

Add a `bio` column to users. Edit `db/schema/10_tables/users.sql`:

```sql
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    email TEXT NOT NULL UNIQUE,
    bio TEXT,  -- NEW COLUMN
    created_at TIMESTAMP DEFAULT NOW()
);
```

### 9. Generate Migration for the Change

First, capture the current schema state:

```bash
# Get current schema from database
pg_dump myapp_local --schema-only > db/schema/current.sql
```

Generate migration for the change:

```bash
confiture migrate diff db/schema/current.sql db/schema/10_tables/users.sql \
    --generate \
    --name add_user_bio
```

This creates `db/migrations/002_add_user_bio.py`:

```python
def up(self) -> None:
    """Apply migration."""
    self.execute("ALTER TABLE users ADD COLUMN bio TEXT")

def down(self) -> None:
    """Rollback migration."""
    self.execute("ALTER TABLE users DROP COLUMN bio")
```

### 10. Apply the New Migration

```bash
confiture migrate up --config db/environments/local.yaml
```

Output:
```
📦 Found 1 pending migration(s)

⚡ Applying 002_add_user_bio... ✅

✅ Successfully applied 1 migration(s)!
```

### 11. Rollback (if needed)

If you need to undo the last migration:

```bash
confiture migrate down --config db/environments/local.yaml
```

Output:
```
📦 Rolling back 1 migration(s)

⚡ Rolling back 002_add_user_bio... ✅

✅ Successfully rolled back 1 migration(s)!
```

---

## Multi-Agent Coordination Workflow

When working with multiple agents or team members on schema changes, use Confiture's coordination system to prevent conflicts.

### When to Use Multi-Agent Coordination?

**Use coordination when:**
- 🤝 Multiple people/agents are working on the same database
- 🔄 Schema changes are happening in parallel
- 🛡️ You want safety checks before implementing changes
- 📋 You need an audit trail of who's working on what

**Skip coordination when:**
- 👤 Solo developer with full context
- 🔒 Exclusive lock on schema changes (no parallel work)

### Setup Coordination (One-Time)

Initialize the coordination database:

```bash
# Create coordination database
createdb confiture_coordination

# Initialize coordination tables
confiture coordinate init --db-url postgresql://localhost/confiture_coordination
```

### Coordination Workflow Example

**Agent Alice wants to add user profiles:**

```bash
# Step 1: Register intention BEFORE making changes
confiture coordinate register \
    --agent-id alice \
    --feature-name user_profiles \
    --tables-affected users,profiles \
    --schema-changes "ALTER TABLE users ADD COLUMN bio TEXT; CREATE TABLE profiles (...)" \
    --risk-level medium \
    --estimated-hours 3

# Output:
# ✅ Intent registered: int_abc123def456
# Branch allocated: feature/user_profiles_001
# Status: REGISTERED
```

**Agent Bob wants to modify users table too:**

```bash
# Step 2: Check for conflicts BEFORE implementing
confiture coordinate check \
    --agent-id bob \
    --tables-affected users

# Output:
# ⚠️ Conflict detected!
#   - alice is working on 'users' table (int_abc123def456)
#   - Suggestion: Coordinate with alice or work on different tables
```

**Viewing Active Work:**

```bash
# Check status of all active intentions
confiture coordinate status

# Output shows:
# ┌─────────────────┬────────────┬───────────────┬──────────────┐
# │ Intent ID       │ Agent      │ Feature       │ Status       │
# ├─────────────────┼────────────┼───────────────┼──────────────┤
# │ int_abc123...   │ alice      │ user_profiles │ IN_PROGRESS  │
# └─────────────────┴────────────┴───────────────┴──────────────┘

# Get JSON for CI/CD integration
confiture coordinate status --format json > status.json
```

**Completing Work:**

```bash
# Step 3: Mark intention as complete when done
confiture coordinate complete \
    --intent-id int_abc123def456 \
    --outcome success \
    --notes "User profiles implemented and tested"

# Output:
# ✅ Intent int_abc123def456 marked as COMPLETED
# No longer blocking other agents from 'users' table
```

**Abandoning Work:**

```bash
# If you need to abandon the work
confiture coordinate abandon \
    --intent-id int_abc123def456 \
    --reason "Requirements changed, feature no longer needed"
```

### Coordination Best Practices

1. **Register early** - Declare intentions before writing code
2. **Check often** - Run `confiture coordinate check` before major changes
3. **Keep updated** - Mark work as complete or abandoned promptly
4. **Use JSON output** - Integrate with CI/CD for automated conflict detection
5. **Review conflicts** - Don't ignore warnings, coordinate with other agents

### CI/CD Integration Example

```yaml
# .github/workflows/check-schema-conflicts.yml
name: Check Schema Conflicts

on: [pull_request]

jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Check for schema conflicts
        run: |
          confiture coordinate check \
            --agent-id github-ci \
            --tables-affected $(git diff --name-only | grep 'db/schema' | xargs) \
            --format json > conflicts.json

          # Fail if conflicts detected
          if jq -e '.conflicts | length > 0' conflicts.json; then
            echo "❌ Schema conflicts detected!"
            exit 1
          fi
```

**[→ Full Multi-Agent Coordination Guide](guides/multi-agent-coordination.md)**

---

## Common Workflows

### Adding a New Table

1. Create schema file: `db/schema/10_tables/posts.sql`
2. Generate migration: `confiture migrate diff current.sql posts.sql --generate --name add_posts`
3. Apply migration: `confiture migrate up --config db/environments/local.yaml`

### Modifying a Column

1. Update schema file with new column definition
2. Generate migration: `confiture migrate diff current.sql updated.sql --generate --name modify_column`
3. Review generated migration
4. Apply migration: `confiture migrate up`

### Creating an Index

1. Add index to schema file
2. Generate migration
3. Apply migration

### Complex Migrations

For complex transformations (data migrations, multi-step changes), create an empty migration:

```bash
confiture migrate generate migrate_user_data
```

Then edit the migration file manually:

```python
def up(self) -> None:
    """Apply migration."""
    # Step 1: Add new column
    self.execute("ALTER TABLE users ADD COLUMN full_name TEXT")

    # Step 2: Migrate data
    self.execute("""
        UPDATE users
        SET full_name = first_name || ' ' || last_name
    """)

    # Step 3: Drop old columns
    self.execute("ALTER TABLE users DROP COLUMN first_name")
    self.execute("ALTER TABLE users DROP COLUMN last_name")
```

## Configuration

### Environment Files

Create different environment configurations:

```
db/environments/
├── local.yaml       # Local development
├── staging.yaml     # Staging environment
└── production.yaml  # Production (credentials in environment variables)
```

Example `production.yaml`:

```yaml
name: production
include_dirs:
  - db/schema/00_common
  - db/schema/10_tables
  - db/schema/20_views

database:
  host: ${DB_HOST}
  port: ${DB_PORT}
  database: ${DB_NAME}
  user: ${DB_USER}
  password: ${DB_PASSWORD}
```

### Directory Organization

Organize schema files by category using **numbered prefixes**:

```
db/
├── schema/             # DDL (single source of truth)
│   ├── 00_common/      # Extensions, types (load first)
│   │   ├── extensions.sql
│   │   └── types.sql
│   ├── 10_tables/      # Core tables
│   │   ├── users.sql
│   │   ├── posts.sql
│   │   └── comments.sql
│   ├── 20_views/       # Views (depend on tables)
│   │   └── user_stats.sql
│   └── 30_functions/   # Stored procedures (load last)
│       └── calculate_score.sql
│
└── seeds/              # INSERT statements
    ├── common/         # All non-prod environments
    │   └── 00_users.sql
    ├── development/    # Dev-specific
    │   ├── 00_posts.sql
    │   └── 01_comments.sql
    └── test/           # Test-specific
        └── 00_posts.sql
```

**Key principle**: Files are processed in **alphabetical order**. Use numbered prefixes (00_, 10_, 20_) to control execution order.

**See [organizing-sql-files.md](./organizing-sql-files.md)** for detailed patterns and best practices.

## Best Practices

### 1. Always Test Migrations

Test migrations in a development/staging environment before production:

```bash
# Test on local
confiture migrate up --config db/environments/local.yaml

# Test on staging
confiture migrate up --config db/environments/staging.yaml

# Only then apply to production
confiture migrate up --config db/environments/production.yaml
```

### 2. Write Reversible Migrations

Always implement both `up()` and `down()` methods:

```python
def up(self) -> None:
    """Apply migration."""
    self.execute("ALTER TABLE users ADD COLUMN verified BOOLEAN DEFAULT FALSE")

def down(self) -> None:
    """Rollback migration."""
    self.execute("ALTER TABLE users DROP COLUMN verified")
```

### 3. Use Transactions

Confiture automatically wraps each migration in a transaction. Keep migrations atomic:

- ✅ Good: Single-purpose migrations (add column, create index)
- ❌ Bad: Complex multi-step migrations without proper error handling

### 4. Review Generated Migrations

Always review auto-generated migrations before applying:

```bash
# Generate migration
confiture migrate diff old.sql new.sql --generate --name my_migration

# Review the generated file
cat db/migrations/00X_my_migration.py

# Edit if needed
vim db/migrations/00X_my_migration.py

# Test in local environment
confiture migrate up --config db/environments/local.yaml
```

### 5. Version Control

Commit both schema files and migration files to git:

```bash
git add db/schema/ db/migrations/
git commit -m "feat: add user bio column"
```

### 6. Don't Modify Applied Migrations

Never modify a migration that has been applied to production. Instead, create a new migration.

## Troubleshooting

### "Migration already applied"

The migration was already run. Check status:

```bash
confiture migrate status --config db/environments/local.yaml
```

### "Database connection failed"

Check your configuration file and ensure PostgreSQL is running:

```bash
# Test connection manually
psql -h localhost -U postgres -d myapp_local

# Check configuration
cat db/environments/local.yaml
```

### "No Migration class found"

Ensure your migration file has a class that inherits from `Migration`:

```python
from confiture.models.migration import Migration

class MyMigration(Migration):  # Must inherit from Migration
    version = "001"
    name = "my_migration"
```

### "Table already exists"

The migration was partially applied. Either:
1. Manually fix the database state
2. Rollback and retry: `confiture migrate down && confiture migrate up`

## Working with Seed Data

Confiture supports **environment-specific seed data** for development and testing.

### Creating Seed Files

Create `db/seeds/common/00_users.sql`:

```sql
-- Common seed data: test users for all non-production environments
INSERT INTO users (id, username, email) VALUES
    ('00000000-0000-0000-0000-000000000001', 'admin', 'admin@example.com'),
    ('00000000-0000-0000-0000-000000000002', 'editor', 'editor@example.com'),
    ('00000000-0000-0000-0000-000000000003', 'reader', 'reader@example.com');
```

Create `db/seeds/development/00_posts.sql`:

```sql
-- Development seed data: sample posts for local work
INSERT INTO posts (id, author_id, title, content) VALUES
    (1, '00000000-0000-0000-0000-000000000001', 'Welcome Post', 'Welcome to the blog!'),
    (2, '00000000-0000-0000-0000-000000000002', 'Getting Started', 'Here is how to get started...');
```

### Building with Seeds

```bash
# Local: includes schema + common seeds + development seeds
confiture build --env local

# Test: includes schema + common seeds + test seeds
confiture build --env test

# Production: schema only, no seeds
confiture build --env production

# Override: build without seeds on any environment
confiture build --env local --schema-only
```

**Result**: Fresh databases come with data ready for immediate development!

## Next Steps

- **[Organizing SQL Files](organizing-sql-files.md)** - Patterns for complex schemas
- **[CLI Reference](reference/cli.md)** - Complete command documentation
- **[Migration Decision Tree](guides/migration-decision-tree.md)** - Choose the right approach
- **[Examples](../examples/)** - Sample projects

## Getting Help

- **Documentation**: https://github.com/fraiseql/confiture
- **Issues**: https://github.com/fraiseql/confiture/issues
- **FraiseQL**: https://github.com/fraiseql/fraiseql

## Part of FraiseQL Ecosystem

Confiture is the official migration tool for [FraiseQL](https://github.com/fraiseql/fraiseql), a modern GraphQL framework for Python with PostgreSQL.

While Confiture works standalone for any PostgreSQL project, it's designed to integrate seamlessly with FraiseQL's GraphQL-first approach.

---

**Part of the FraiseQL family** 🍓

*Vibe-engineered with ❤️ by [Lionel Hamayon](https://github.com/LionelHamayon)*
