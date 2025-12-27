# Medium 1: Build from DDL

**Build fresh PostgreSQL databases from source DDL files in <1 second**

## What is Build from DDL?

Build from [DDL](../glossary.md#ddl) is Confiture's fastest way to create a PostgreSQL database. Instead of replaying migration history (like Alembic or Django migrations), Confiture concatenates your schema files and executes them directly.

### Key Concept

> **"[DDL](../glossary.md#ddl) files are the source of truth, not migration history"**

Traditional tools:
```
Migration 001 → Migration 002 → Migration 003 → ... → Migration 100
(Slow: replays entire history)
```

Confiture Build from DDL:
```
db/schema/*.sql → Concatenate → Execute
(Fast: one operation)
```

---

## When to Use Build from DDL

### ✅ Perfect For

- **Local development** - New developers get working DB instantly
- **CI/CD pipelines** - Fresh database for each test run (<1s)
- **Review environments** - Ephemeral databases per PR
- **Testing** - Clean state for integration tests
- **Staging setup** - Fresh staging environment matching production schema

### ❌ Not For

- **Existing databases with data** - Would drop all data
- **Production deployments** - Use Medium 2 or 4 for schema changes

### Use Case Examples

#### 1. New Developer Onboarding
```bash
# Clone repository
git clone https://github.com/yourcompany/yourapp.git
cd yourapp

# One command to get working database
confiture build --env local

# Database ready! Start coding immediately
```

**Time**: <1 second (vs 5-30 seconds replaying migrations)

#### 2. CI/CD Testing
```yaml
# .github/workflows/test.yml
- name: Setup PostgreSQL
  uses: ankane/setup-postgres@v1

- name: Build database schema
  run: confiture build --env ci

- name: Run tests
  run: pytest tests/

# Fast builds = faster CI/CD pipelines
```

#### 3. Integration Testing
```python
import pytest
from confiture.core.builder import SchemaBuilder

@pytest.fixture(scope="function")
def fresh_db():
    """Fresh database for each test"""
    builder = SchemaBuilder(env="test")
    builder.build()
    yield
    # Cleanup handled by test teardown
```

---

## How It Works

### The Build Process

```
1. Discovery
   ↓
   Find all *.sql files in db/schema/

2. Sorting
   ↓
   Sort files alphabetically (deterministic order)

3. Concatenation
   ↓
   Combine files with metadata headers

4. Execution
   ↓
   Execute combined SQL on empty database

5. Verification
   ↓
   Compute SHA256 hash for version tracking
```

### Performance

Confiture uses a **hybrid Python + Rust architecture**:

- **File discovery**: Python (flexible)
- **Concatenation**: Rust (10-50x faster)
- **Hashing**: Rust (30-60x faster)

| Database Size | Alembic (replay) | Confiture (build) | Speedup |
|---------------|------------------|-------------------|---------|
| 10 tables | 12s | 0.3s | **40x** |
| 50 tables | 45s | 0.8s | **56x** |
| 100 tables | 120s | 1.2s | **100x** |

---

## Directory Structure

### Recommended Organization

```
db/
├── schema/                    # DDL source files (CREATE, ALTER)
│   ├── 00_common/            # Extensions, types (load first)
│   │   ├── extensions.sql
│   │   ├── custom_types.sql
│   │   └── utility_functions.sql
│   │
│   ├── 10_tables/            # Core tables
│   │   ├── users.sql
│   │   ├── posts.sql
│   │   ├── comments.sql
│   │   └── tags.sql
│   │
│   ├── 20_views/             # Views (depend on tables)
│   │   ├── user_stats.sql
│   │   └── popular_posts.sql
│   │
│   ├── 30_indexes/           # Indexes (after tables)
│   │   ├── users_indexes.sql
│   │   └── posts_indexes.sql
│   │
│   ├── 40_constraints/       # Foreign keys, constraints
│   │   └── foreign_keys.sql
│   │
│   └── 50_functions/         # Stored procedures (load last)
│       ├── update_timestamps.sql
│       └── calculate_score.sql
│
├── seeds/                     # Test data (INSERT statements)
│   ├── common/               # Shared across envs
│   ├── development/          # Dev-only data
│   └── test/                 # Test fixtures
│
└── environments/              # Environment configs
    ├── local.yaml
    ├── test.yaml
    ├── ci.yaml
    └── production.yaml
```

### Ordering Strategy

**Files are processed alphabetically**. Use numbered directories to control execution order:

```
00_common/    → First  (extensions, types)
10_tables/    → Second (table definitions)
20_views/     → Third  (views depend on tables)
30_indexes/   → Fourth (indexes on tables)
40_constraints/ → Fifth (foreign keys)
50_functions/ → Last   (functions may reference everything)
```

### Example Schema File

**db/schema/10_tables/users.sql**:
```sql
-- Users table
-- Stores user account information

CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    bio TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Add comment for documentation
COMMENT ON TABLE users IS 'User accounts and profiles';
COMMENT ON COLUMN users.bio IS 'User biography (supports markdown)';
```

---

## Commands and Usage

### Basic Build Command

```bash
# Build default environment (usually 'local')
confiture build

# Build specific environment
confiture build --env production

# Build and save to file
confiture build --env local --output db/generated/schema.sql

# Dry run (just concatenate, don't execute)
confiture build --env test --dry-run
```

### Environment Configuration

**db/environments/local.yaml**:
```yaml
name: local
database:
  host: localhost
  port: 5432
  database: myapp_local
  user: postgres
  password: postgres

# Which directories to include when building
include_dirs:
  - db/schema
  - db/seeds/common
  - db/seeds/development

# Directories to exclude
exclude_dirs:
  - db/schema/experiments
  - db/schema/deprecated
```

### Programmatic API

```python
from pathlib import Path
from confiture.core.builder import SchemaBuilder

# Initialize builder
builder = SchemaBuilder(
    env="local",
    project_dir=Path("/path/to/project")
)

# Build schema
schema = builder.build()
print(f"Generated {len(schema)} bytes of SQL")

# Or build and save
builder.build(output_path=Path("db/generated/schema.sql"))

# Compute schema hash (for version tracking)
schema_hash = builder.compute_hash()
print(f"Schema version: {schema_hash[:12]}")
```

---

## Schema Versioning with Hashes

Confiture computes a **SHA256 hash** of your schema to detect changes.

### How Hashing Works

The hash includes:
- **File paths** (detects file renames/moves)
- **File content** (detects content changes)

```python
# Hash includes both structure and content
hash = SHA256(
    "db/schema/00_common/extensions.sql" + file_content +
    "db/schema/10_tables/users.sql" + file_content +
    ...
)
```

### Use Cases

#### 1. Detect Schema Changes

```bash
# Before changes
confiture build --env local
# Schema Hash: a1b2c3d4e5f6...

# After changes
vim db/schema/10_tables/users.sql
confiture build --env local
# Schema Hash: f6e5d4c3b2a1...  (different!)
```

#### 2. CI/CD Validation

```yaml
# .github/workflows/schema-check.yml
- name: Check for schema drift
  run: |
    EXPECTED_HASH=$(git show main:db/schema.hash)
    CURRENT_HASH=$(confiture hash --env production)

    if [ "$EXPECTED_HASH" != "$CURRENT_HASH" ]; then
      echo "Schema drift detected!"
      exit 1
    fi
```

#### 3. Database Metadata

Generated schema includes hash in header:
```sql
-- ============================================
-- PostgreSQL Schema for Confiture
-- ============================================
--
-- Environment: local
-- Generated: 2025-10-12T10:30:00
-- Schema Hash: a1b2c3d4e5f6789...
-- Files Included: 15
--
-- ============================================
```

---

## Best Practices

### 1. Use Numbered Directories

```
✅ Good: Explicit ordering
db/schema/
├── 00_common/
├── 10_tables/
└── 20_views/

❌ Bad: Ambiguous order
db/schema/
├── common/
├── tables/
└── views/
```

### 2. Keep Files Self-Contained

```sql
✅ Good: Includes IF NOT EXISTS
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ...
);

❌ Bad: Fails on re-run
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ...
);
```

### 3. Use Comments for Documentation

```sql
-- Users table
-- Stores user account information and authentication credentials
CREATE TABLE users (...);

-- Add detailed column comments
COMMENT ON COLUMN users.bio IS 'User biography (markdown supported, max 5000 chars)';
```

### 4. Separate Schema from Seeds

```
db/schema/        # DDL (CREATE TABLE, CREATE VIEW)
db/seeds/         # DML (INSERT, UPDATE)
```

Why? Seeds change frequently, schema is stable. Separate concerns.

### 5. Environment-Specific Configuration

```yaml
# local.yaml - includes dev seeds
include_dirs:
  - db/schema
  - db/seeds/common
  - db/seeds/development

# production.yaml - schema only
include_dirs:
  - db/schema
  - db/seeds/common
```

### 6. Version Control Generated Files

```bash
# .gitignore
db/generated/*.sql     # Don't commit generated schemas

# But do commit source files
db/schema/**/*.sql
db/seeds/**/*.sql
```

---

## Integration Patterns

### With Docker Compose

```yaml
# docker-compose.yml
services:
  db:
    image: postgres:16
    environment:
      POSTGRES_DB: myapp_local
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
    ports:
      - "5432:5432"

  db-setup:
    image: myapp:latest
    depends_on:
      - db
    command: confiture build --env local
```

### With Makefile

```makefile
# Makefile
.PHONY: db-build db-reset db-seed

db-build:
	confiture build --env local

db-reset:
	dropdb myapp_local || true
	createdb myapp_local
	confiture build --env local

db-seed:
	confiture build --env local
	python scripts/seed_data.py
```

### With pytest

```python
# conftest.py
import pytest
from confiture.core.builder import SchemaBuilder

@pytest.fixture(scope="session")
def db_schema():
    """Build schema once per test session"""
    builder = SchemaBuilder(env="test")
    builder.build()
    yield

@pytest.fixture(scope="function")
def db(db_schema):
    """Truncate tables before each test"""
    # Truncate all tables but keep schema
    pass
```

---

## Common Pitfalls

### ❌ Pitfall 1: Incorrect File Order

**Problem**: Views created before tables they depend on

```
db/schema/
├── views.sql     # ERROR: table "users" does not exist
└── users.sql
```

**Solution**: Use numbered directories
```
db/schema/
├── 10_tables/users.sql
└── 20_views/user_stats.sql
```

---

### ❌ Pitfall 2: Missing IF NOT EXISTS

**Problem**: Build fails on second run

```sql
CREATE TABLE users (...);  -- ERROR: relation "users" already exists
```

**Solution**: Always use IF NOT EXISTS
```sql
CREATE TABLE IF NOT EXISTS users (...);
```

---

### ❌ Pitfall 3: Circular Dependencies

**Problem**: Table A references Table B, Table B references Table A

**Solution**: Separate foreign keys into later stage
```
10_tables/
├── table_a.sql          # Table without FK
├── table_b.sql          # Table without FK
└── 40_constraints/
    └── foreign_keys.sql # Add FKs after tables exist
```

---

### ❌ Pitfall 4: Environment-Specific DDL

**Problem**: Different schemas for different environments

```
# local.yaml includes test-only tables
db/schema/
├── users.sql           # Production
└── debug_logs.sql      # Local only (ERROR in production!)
```

**Solution**: Use seeds for env-specific data, not schema
```
db/schema/              # Same for all environments
db/seeds/
├── development/        # Dev-only data
└── production/         # Prod-only data
```

---

## Performance Tuning

### Rust Extension

Confiture automatically uses Rust extension if available:

```bash
# Install with Rust support (default)
pip install confiture

# If Rust unavailable, falls back to Python
# (still works, just 10-50x slower)
```

### Parallel Processing (Future)

Large schemas (1000+ files) will support parallel processing:

```bash
# Future feature
confiture build --env local --parallel
```

### Caching (Future)

Skip unchanged files with incremental builds:

```bash
# Future feature
confiture build --env local --incremental
```

---

## Comparison with Other Tools

| Feature | Alembic | Confiture Build |
|---------|---------|-----------------|
| **Fresh DB setup** | 30-120s | <1s |
| **Philosophy** | Migration replay | Build from source |
| **Source of truth** | Migration files | DDL files |
| **Versioning** | Sequential numbers | Content hash |
| **Performance** | O(n) migrations | O(1) operation |

---

## Advanced Usage

### Multi-Schema Support

```yaml
# environments/production.yaml
include_dirs:
  - db/schema/public        # Public schema
  - db/schema/analytics     # Analytics schema
  - db/schema/audit         # Audit schema
```

### Custom File Extensions

```yaml
# Support .pgsql or .psql files
include_patterns:
  - "*.sql"
  - "*.pgsql"
  - "*.psql"
```

### Template Variables (Future)

```sql
-- db/schema/10_tables/users.sql
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ...
    shard_id INTEGER DEFAULT {{ SHARD_ID }}
);
```

```yaml
# environments/production.yaml
variables:
  SHARD_ID: 1
```

---

## Troubleshooting

### Build Fails: "No SQL files found"

**Cause**: Wrong directory structure

**Solution**: Check include_dirs in environment config
```yaml
# Fix path
include_dirs:
  - db/schema  # ✅ Correct
  # NOT: schema  # ❌ Wrong
```

### Build Fails: "Relation already exists"

**Cause**: Missing IF NOT EXISTS

**Solution**: Add to all CREATE statements
```sql
CREATE TABLE IF NOT EXISTS users (...);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
```

### Build Slow (>5 seconds)

**Cause**: Rust extension not installed

**Solution**: Reinstall with build support
```bash
pip uninstall confiture
pip install confiture --no-binary :all:
```

---

## See Also

- [Migration Decision Tree](./migration-decision-tree.md) - Choose the right medium
- [Organizing SQL Files](../organizing-sql-files.md) - Best practices for large schemas
- [Medium 2: Incremental Migrations](./medium-2-incremental-migrations.md) - For existing databases
- [Example: Basic Migration](../../examples/01-basic-migration/) - Complete tutorial
- [CLI Reference](../reference/cli.md) - All build commands

---

## Quick Reference

### Commands
```bash
confiture build                              # Build default env
confiture build --env production             # Build specific env
confiture build --output schema.sql          # Save to file
confiture build --dry-run                    # Don't execute
confiture hash --env local                   # Compute schema hash
```

### Directory Structure
```
db/schema/
├── 00_common/     # Extensions, types
├── 10_tables/     # Tables
├── 20_views/      # Views
├── 30_indexes/    # Indexes
└── 40_constraints/  # Foreign keys
```

### Best Practices
- ✅ Use numbered directories (00_, 10_, 20_)
- ✅ Include `IF NOT EXISTS` in all CREATE statements
- ✅ Keep files self-contained
- ✅ Separate schema (DDL) from seeds (DML)
- ✅ Use comments for documentation
- ✅ Version control source files, not generated

---

## 🎯 Next Steps

**Ready to use Medium 1?**
- ✅ You now understand: DDL-first philosophy, fast builds, file organization

**What to do next:**

1. **[Organizing SQL Files](../organizing-sql-files.md)** - Patterns for complex schemas with many tables and views

2. **[Quick Start Guide](../getting-started.md)** - Hands-on walkthrough with real code examples

3. **[Migration Decision Tree](./migration-decision-tree.md)** - When to use Medium 1 vs other mediums

4. **[Medium 2: Incremental Migrations](./medium-2-incremental-migrations.md)** - For making schema changes after initial build

5. **[Examples](../../examples/)** - See Medium 1 in action with working projects

**Got questions?**
- **[Glossary](../glossary.md)** - Terms explained
- **[Getting Started by Role](../getting-started-by-role.md)** - Find guides for your use case
- **[Troubleshooting](./troubleshooting.md)** - Common issues and solutions

---

**Part of the Confiture documentation** 🍓

*Building schemas at the speed of thought*
