# Sequential Seed File Execution

## Overview

Confiture supports **sequential seed file execution** to solve PostgreSQL's parser limitations when working with large seed files (650+ rows).

### The Problem

When seed files are concatenated into a single SQL stream, PostgreSQL's parser accumulates context throughout the entire concatenation. Large seed files with 650+ INSERT statements may fail with:

```
ERROR: syntax error at or near ";"
LINE 98: );
```

### The Solution

Sequential execution applies each seed file **independently within its own savepoint**. This provides:

- ✅ Fresh parser state for each file
- ✅ Complete isolation between files
- ✅ Clean error handling per file
- ✅ Optional continue-on-error mode
- ✅ Same data integrity as concatenation

## Quick Start

### Enable Sequential Execution

#### Via `confiture seed apply` (dedicated command)

```bash
# Apply seed files sequentially
confiture seed apply --sequential --env local

# With continue-on-error (skip failed files)
confiture seed apply --sequential --continue-on-error

# With explicit database URL
confiture seed apply --sequential --database-url postgresql://localhost/mydb
```

#### Via `confiture build --sequential` (recommended for CI/CD)

Build schema and apply seeds sequentially in a single command:

```bash
# Build schema from DDL files, then apply seeds sequentially
confiture build --sequential --database-url postgresql://localhost/mydb

# With specific environment
confiture build --env production --sequential --database-url $DATABASE_URL

# Continue on error (skip failed seed files)
confiture build --sequential --continue-on-error --database-url postgresql://localhost/mydb
```

**Benefits of `build --sequential`:**
- ✅ Single command for schema + seeds
- ✅ Clean output formatting
- ✅ Suitable for CI/CD pipelines
- ✅ Respects `execution_mode: sequential` in config
- ✅ Perfect for fresh database initialization

### Configuration

Add to your `db/environments/local.yaml`:

```yaml
name: local
database_url: postgresql://localhost/myapp_local
include_dirs:
  - db/schema

# Seed execution configuration (optional)
seed:
  execution_mode: sequential      # "concatenate" | "sequential"
  continue_on_error: false        # Skip failed files and continue
  transaction_mode: savepoint     # Always use savepoint isolation
```

## How It Works

### Transaction Isolation

Each seed file executes within its own PostgreSQL **savepoint**:

```
BEGIN OUTER TRANSACTION
  ├─ SAVEPOINT sp_seed_001
  │  └─ Execute 01_users.sql
  │     └─ RELEASE SAVEPOINT sp_seed_001 (on success)
  │        OR ROLLBACK TO sp_seed_001 (on error)
  │
  ├─ SAVEPOINT sp_seed_002
  │  └─ Execute 02_posts.sql
  │     └─ RELEASE SAVEPOINT sp_seed_002
  │
  └─ COMMIT OUTER TRANSACTION
```

### Error Handling

When a seed file fails:

1. **Without `--continue-on-error`** (default):
   - Rollback the failed file's savepoint
   - Stop execution
   - Report error with file context
   - Exit code: 1

2. **With `--continue-on-error`**:
   - Rollback the failed file's savepoint
   - Skip to next file
   - Continue executing remaining files
   - Report summary at end
   - Exit code: 1 (if any files failed)

### File Ordering

Seed files are applied in **sorted order** (alphabetical):

```
db/seeds/
  01_users.sql        → Applied first
  02_posts.sql        → Applied second
  03_comments.sql     → Applied third
```

Use numeric prefixes for predictable ordering.

## Examples

### Basic Usage: Load User Data

```bash
# db/seeds/01_users.sql
INSERT INTO users (name, email) VALUES ('Alice', 'alice@example.com');
INSERT INTO users (name, email) VALUES ('Bob', 'bob@example.com');

# db/seeds/02_posts.sql
INSERT INTO posts (user_id, title) VALUES (1, 'First Post');
INSERT INTO posts (user_id, title) VALUES (2, 'Second Post');
```

Apply sequentially:

```bash
$ confiture seed apply --sequential --env local

→ 01_users.sql ✓
→ 02_posts.sql ✓

==================================================
Applied 2/2 seed files
```

### Large Seed File (650+ Rows)

For large seed files that would fail with concatenation:

```bash
# db/seeds/01_large.sql (650+ INSERT statements)
INSERT INTO users (name, email) VALUES ('User1', 'user1@example.com');
INSERT INTO users (name, email) VALUES ('User2', 'user2@example.com');
... (648 more rows)
```

Apply with sequential mode:

```bash
$ confiture seed apply --sequential --env local

→ 01_large.sql ✓

==================================================
Applied 1/1 seed files
```

**Without sequential mode**, this would fail with parser errors.

### Partial Failures with Continue-on-Error

When some files have errors but you want to load valid data:

```bash
# db/seeds/01_users.sql (valid)
INSERT INTO users (name) VALUES ('Alice');

# db/seeds/02_bad.sql (invalid FK)
INSERT INTO posts (user_id, title) VALUES (999, 'Invalid');

# db/seeds/03_posts.sql (valid)
INSERT INTO posts (user_id, title) VALUES (1, 'Valid Post');
```

Apply with continue-on-error:

```bash
$ confiture seed apply --sequential --continue-on-error --env local

→ 01_users.sql ✓
→ 02_bad.sql ✗ ERROR: insert or update on table "posts" violates foreign key constraint
→ 03_posts.sql ✓

==================================================
Applied 2/3 seed files
⚠ 1 files failed:
  - 02_bad.sql
```

Data result: 1 user + 1 post loaded (02_bad.sql rolled back)

### Complex SQL in Seed Files

Seed files support any valid SQL, including CTEs and subqueries:

```sql
-- db/seeds/01_users.sql
WITH user_data AS (
  SELECT 'Alice' as name, 'alice@example.com' as email
  UNION ALL
  SELECT 'Bob' as name, 'bob@example.com' as email
)
INSERT INTO users (name, email) SELECT name, email FROM user_data;
```

## Configuration Reference

### SeedConfig Options

```python
# In db/environments/{env}.yaml
seed:
  # Execution strategy
  # - "concatenate": All files concatenated (default, existing behavior)
  # - "sequential": Each file in own savepoint (solves parser limits)
  execution_mode: sequential

  # Continue on error
  # - false: Stop on first error (default)
  # - true: Skip failed files, continue execution
  continue_on_error: false

  # Transaction isolation mode
  # - "savepoint": Use PostgreSQL savepoint (recommended)
  # - "transaction": Use separate transactions (future)
  transaction_mode: savepoint
```

## CLI Reference

### `confiture seed apply`

Apply seed files to database.

**Options:**

- `--sequential`: Apply files sequentially instead of concatenating
- `--continue-on-error`: Continue applying remaining files if one fails
- `--seeds-dir PATH`: Directory containing seed files (default: `db/seeds`)
- `--env NAME`: Environment name (default: `local`)
- `--database-url URL`: Database URL (overrides environment config)

**Examples:**

```bash
# Sequential execution
confiture seed apply --sequential --env local

# Sequential with continue-on-error
confiture seed apply --sequential --continue-on-error --env local

# Custom seeds directory
confiture seed apply --sequential --seeds-dir db/seeds/production --env production

# Explicit database URL
confiture seed apply --sequential --database-url postgresql://prod.example.com/myapp
```

**Exit Codes:**

- `0`: All seed files applied successfully
- `1`: One or more files failed (or no `--sequential` flag used)
- `2`: Configuration error or database connection failed

## Troubleshooting

### "Column does not exist" or "Table does not exist"

**Problem:** Seed file references tables that don't exist.

**Solution:** Ensure schema is built before applying seeds:

```bash
confiture build --env local
confiture seed apply --sequential --env local
```

### "Foreign key constraint violation"

**Problem:** Seed file tries to insert data with invalid foreign keys.

**Solution:** Check file order - files must be sorted so dependencies are satisfied:

```bash
# Wrong order:
02_posts.sql (references users)
01_users.sql

# Correct order:
01_users.sql
02_posts.sql
```

### "Permission denied" or "Database connection failed"

**Problem:** Cannot connect to database.

**Solution:** Verify database URL:

```bash
# Check environment config
cat db/environments/local.yaml

# Or use explicit URL
confiture seed apply --sequential --database-url postgresql://localhost/myapp
```

### "Transaction command not allowed"

**Problem:** Seed file contains BEGIN, COMMIT, or ROLLBACK.

**Solution:** Remove transaction commands - sequential mode handles transactions:

```sql
# ❌ Wrong:
BEGIN;
INSERT INTO users VALUES (1, 'Alice');
COMMIT;

# ✅ Correct:
INSERT INTO users VALUES (1, 'Alice');
```

## Best Practices

### 1. Use Numeric Prefixes

Ensure predictable execution order:

```
db/seeds/
  01_users.sql        ← User seed (no dependencies)
  02_posts.sql        ← Posts (depends on users)
  03_comments.sql     ← Comments (depends on posts)
```

### 2. Keep Seed Files Focused

One logical entity per file:

- ✅ `01_users.sql` - Only user data
- ✅ `02_roles.sql` - Only role data
- ❌ `01_users_and_roles.sql` - Mixed concerns

### 3. Use Continue-on-Error in CI/CD

For robust deployments, allow partial seeding:

```bash
# CI/CD pipeline
confiture build --env staging
confiture seed apply --sequential --continue-on-error --env staging
```

### 4. Validate Before Production

Always test seed files in staging first:

```bash
# Staging (test environment)
confiture seed apply --sequential --env staging

# Production (only if staging passed)
confiture seed apply --sequential --env production
```

### 5. Document Dependencies

Add comments to seed files explaining dependencies:

```sql
-- db/seeds/02_posts.sql
-- Requires: 01_users.sql (references users.id)
INSERT INTO posts (user_id, title) VALUES (1, 'First Post');
```

## Performance

### Large Seed Files

Sequential execution has minimal overhead:

- **Setup**: ~10ms per file (savepoint creation)
- **Execution**: Same as concatenation
- **Cleanup**: ~5ms per file (savepoint release)

For a 650-row file: ~15ms additional overhead

### Recommended Limits

- **File size**: Up to 10,000 INSERT statements per file
- **Total seeds**: Up to 100 files
- **Data volume**: Limited by database capacity

For very large datasets (>1 million rows), consider:

1. Splitting into multiple files
2. Using database bulk load tools (COPY)
3. Parallel seed loading

## When to Use Sequential Mode

### ✅ Use Sequential When:

- Seed files have 500+ INSERT statements
- You need per-file error isolation
- Continue-on-error functionality needed
- Parser limit errors occur with concatenation

### ❌ Use Concatenation When:

- Seed files are small (<100 rows each)
- No error isolation needed
- Raw concatenation performance critical
- Default behavior acceptable

## See Also

- [Medium 1: Build from DDL](./medium-1-build-from-ddl.md)
- [Seed Data Validation](./seed-data-validation.md)
- [CLI Reference](../reference/cli.md)
- [Configuration Reference](../reference/configuration.md)
