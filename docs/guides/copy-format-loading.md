# COPY Format Loading Guide

## Overview

Confiture supports **PostgreSQL COPY format** for dramatically faster seed data loading. COPY is typically **2-10x faster** than traditional INSERT statements for bulk data loading.

### The Problem with INSERT Statements

When loading large seed files, traditional INSERT statements have limitations:

```sql
-- Slow: Individual row insertion (typical seed file)
INSERT INTO users (id, name, email) VALUES
  (1, 'Alice', 'alice@example.com'),
  (2, 'Bob', 'bob@example.com'),
  (3, 'Charlie', 'charlie@example.com'),
  -- ...1000+ more rows...
  (1000, 'Zoe', 'zoe@example.com');
```

**Issues:**
- ❌ Parser overhead for each row
- ❌ Inefficient for large datasets (650+ rows)
- ❌ Network round-trip per batch
- ❌ Slower than PostgreSQL's native COPY protocol

### The Solution: COPY Format

COPY format is PostgreSQL's **native bulk data format** designed for high-performance data loading:

```
COPY users (id, name, email) FROM stdin;
1	Alice	alice@example.com
2	Bob	bob@example.com
3	Charlie	charlie@example.com
\.
```

**Benefits:**
- ✅ **2-10x faster** for large datasets
- ✅ **Native PostgreSQL protocol** (optimized)
- ✅ **Less network overhead** (binary format option)
- ✅ **Better parser performance** (streaming)
- ✅ **Ideal for CI/CD** (fresh database initialization)

## Quick Start

### 1. Automatic Format Selection (Recommended)

Let Confiture automatically choose the best format based on dataset size:

```bash
# Apply seeds with automatic format selection
confiture seed apply --sequential --copy-format

# Configure threshold (default: 1000 rows)
confiture seed apply --sequential --copy-format --copy-threshold 500
```

**How it works:**
- Tables with ≤ 1000 rows: Uses VALUES (faster for small data)
- Tables with > 1000 rows: Uses COPY (dramatically faster)

### 2. Convert INSERT to COPY Format

Transform existing INSERT files to COPY format:

```bash
# Convert single file
confiture seed convert --input seeds.sql --output seeds_copy.sql

# Convert entire directory
confiture seed convert --input db/seeds --batch --output db/seeds_copy

# Preview conversion
confiture seed convert --input seeds.sql
```

### 3. Benchmark Performance

See how much faster COPY is for your data:

```bash
# Compare VALUES vs COPY performance
confiture seed benchmark --seeds-dir db/seeds

# Output:
# COPY Format Performance Benchmark
# ════════════════════════════════════
# Total rows: 45,230
# VALUES format: 2,345ms
# COPY format:   245ms
# Speedup:       9.6x faster
# Time saved:    2,100ms
```

### 4. Full Integration with Build

Use COPY format when building fresh databases:

```bash
# Build schema and apply seeds with COPY format
confiture build --sequential --copy-format

# With performance metrics
confiture build --sequential --copy-format --benchmark

# Custom threshold
confiture build --sequential --copy-format --copy-threshold 500
```

## Decision Tree: When to Use COPY

```
┌─ How many rows in seed table? ─────┐
│                                    │
├─ < 500 rows ─────→ VALUES (fast)   │
│                                    │
├─ 500-1000 rows ──→ VALUES (fine)   │
│                                    │
├─ 1000-10K rows ──→ COPY (2-3x)     │
│                                    │
├─ 10K-100K rows ──→ COPY (5-7x)     │
│                                    │
└─ > 100K rows ────→ COPY (10x)      │
```

**Default behavior:**
- Confiture's automatic selection uses **1000 rows as threshold**
- Adjustable via `--copy-threshold` flag

## How It Works

### Format Conversion

When you use `--copy-format`, Confiture:

1. **Parses INSERT statements** using SQLglot AST parser
2. **Validates data compatibility** (detects functions, subqueries, etc.)
3. **Converts to COPY format** with proper escaping
4. **Applies via native protocol** for maximum speed

### Escaping Rules

COPY format uses tab-delimited values with special characters escaped:

| Value Type | Representation | Example |
|-----------|----------------|---------|
| String | Literal text | `Alice` |
| NULL | Backslash-N | `\N` |
| Newline in string | Literal newline | `Alice\nBob` |
| Tab in string | Literal tab | `Name\tExt` |
| Backslash | Escaped | `Path\\to\\file` |
| Pipe | Literal pipe | `A\|B` (if not delimiter) |

### Transaction Safety

All COPY operations use PostgreSQL **savepoints** for safety:

```
BEGIN TRANSACTION
  SAVEPOINT sp_users
    COPY users FROM stdin
    [data...]
    \.
  RELEASE SAVEPOINT sp_users
COMMIT
```

**Benefits:**
- ✅ Atomic per-table (all rows or none)
- ✅ Automatic rollback on error
- ✅ Safe parallel execution
- ✅ Compatible with `--sequential` mode

## Use Cases

### 1. Fresh Database Initialization (⭐ Recommended)

```bash
# Build fresh database with COPY format (fastest)
confiture build \
  --sequential \
  --copy-format \
  --database-url postgresql://localhost/myapp_fresh
```

**Why:**
- Fastest possible fresh database
- No risk of parser limits
- Complete with schema + seed data
- Perfect for CI/CD pipelines

### 2. Large Seed Files (650+ rows)

```bash
# Combine --sequential (parser limits) with --copy-format (speed)
confiture seed apply \
  --sequential \
  --copy-format \
  --env production
```

**Why:**
- Solves PostgreSQL 650+ row parser limits
- Dramatically faster loading (5-10x)
- Reliable batch processing

### 3. CI/CD Pipeline

```bash
# Fast, reliable seed loading for testing
confiture build \
  --sequential \
  --copy-format \
  --continue-on-error \
  --database-url $DATABASE_URL
```

**Features:**
- Fast (COPY format)
- Reliable (sequential execution)
- Flexible (continue-on-error)
- Tracked (JSON output available)

### 4. Performance Analysis

```bash
# Compare current vs optimized approach
confiture seed benchmark --seeds-dir db/seeds

# If showing < 5x speedup, increase threshold
confiture seed apply \
  --sequential \
  --copy-format \
  --copy-threshold 2000 \
  --benchmark
```

### 5. Format Conversion Pipeline

```bash
# Convert all seed files to COPY format
confiture seed convert \
  --input db/seeds \
  --batch \
  --output db/seeds_optimized

# Then use optimized seeds
confiture build \
  --sequential \
  --database-url postgresql://localhost/myapp
```

## Advanced Configuration

### Environment Configuration

Add to `db/environments/local.yaml`:

```yaml
name: local
database_url: postgresql://localhost/myapp_local

# Seed loading configuration
seed:
  # Execution mode: "concatenate" | "sequential"
  execution_mode: sequential

  # Use COPY format for large tables
  use_copy_format: true

  # Row threshold for auto COPY selection
  copy_threshold: 1000

  # Show performance metrics
  benchmark: true

  # Continue on error (sequential only)
  continue_on_error: false
```

### CLI Options Reference

```bash
confiture seed apply --sequential --copy-format [OPTIONS]

--copy-format          # Enable COPY format conversion
--copy-threshold N     # Row threshold for auto COPY (default: 1000)
--benchmark            # Show VALUES vs COPY comparison
--sequential           # Required for COPY format
--continue-on-error    # Skip failed files and continue
--env ENV              # Environment name
--database-url URL     # Explicit database URL
```

## Converting INSERT to COPY

### Single File Conversion

```bash
# Before
cat db/seeds/users.sql
INSERT INTO users (id, name, email) VALUES
  (1, 'Alice', 'alice@example.com'),
  (2, 'Bob', 'bob@example.com'),
  ...

# Convert
confiture seed convert --input db/seeds/users.sql --output db/seeds/users_copy.sql

# After
cat db/seeds/users_copy.sql
COPY users (id, name, email) FROM stdin;
1	Alice	alice@example.com
2	Bob	bob@example.com
...
\.
```

### Batch Directory Conversion

```bash
# Convert all .sql files in directory
confiture seed convert \
  --input db/seeds \
  --batch \
  --output db/seeds_copy

# Output shows results
┏━━━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━━┓
┃ File         ┃ Status     ┃ Rows/Reason ┃
┡━━━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━━┩
│ users.sql    │ ✓ Converted │ 1,234      │
│ posts.sql    │ ✓ Converted │ 5,678      │
│ complex.sql  │ ⚠ Skipped   │ Has CTEs   │
└──────────────┴────────────┴────────────┘
```

### Handling Unconvertible Patterns

Some SQL patterns cannot be converted to COPY format:

```sql
-- ❌ Functions in VALUES
INSERT INTO users (created_at) VALUES (NOW());
-- Reason: Cannot convert functions to COPY format

-- ❌ Subqueries
INSERT INTO posts (user_id) VALUES ((SELECT user_id FROM users LIMIT 1));
-- Reason: Subqueries in VALUES cannot be converted

-- ❌ Common Table Expressions (CTEs)
WITH user_ids AS (SELECT id FROM users)
INSERT INTO posts (user_id) SELECT id FROM user_ids;
-- Reason: CTEs require complex SQL execution

-- ✅ Graceful fallback: File is skipped with descriptive reason
```

**Solution:** Confiture gracefully skips unconvertible files and continues with others.

## Troubleshooting

### Issue: "Cannot convert functions in VALUES"

```
⚠ Cannot convert db/seeds/users.sql
  Reason: Detected NOW() function in VALUES clause
  Tip: This INSERT statement uses SQL features that cannot be
       converted to COPY format. You can still use the original
       INSERT format for this file.
```

**Solution:**
- Keep this file as INSERT (compatible)
- Use COPY format for other files
- Mix both formats in same project (safe)

### Issue: "COPY format is not faster"

**Causes:**
- Small dataset (< 500 rows) - VALUES is fine
- Disk I/O bottleneck (not SQL parsing)
- Network latency (improve connection)

**Solution:**
```bash
# Check what format is being used
confiture seed benchmark --seeds-dir db/seeds

# If no speedup, stick with VALUES
confiture seed apply --sequential --env local
```

### Issue: "Unsupported data type in COPY"

COPY supports all PostgreSQL data types. If you see errors:

1. Check data type compatibility
2. Verify escaping rules for special characters
3. Test with smaller dataset first

```bash
# Test conversion first
confiture seed convert --input small_test.sql
# Then apply if successful
confiture seed apply --sequential --copy-format
```

## Performance Tuning

### Optimize for Maximum Speed

```bash
# 1. Use COPY format
# 2. Use sequential execution (isolates parser state)
# 3. Adjust threshold based on your data

confiture build \
  --sequential \
  --copy-format \
  --copy-threshold 500 \
  --benchmark \
  --database-url postgresql://localhost/myapp_fresh
```

### Monitor Performance

```bash
# Before optimization
confiture seed benchmark --seeds-dir db/seeds
# OUTPUT: COPY 3.2x faster

# Adjust threshold to catch more tables
confiture seed apply \
  --sequential \
  --copy-format \
  --copy-threshold 500 \
  --benchmark
# OUTPUT: COPY 7.5x faster

# Measure improvement
```

### Batch Size Tuning

Confiture automatically tunes batch sizes for optimal performance:
- Small tables (< 1KB): Batch with other tables
- Medium tables (1-10KB): Single batch
- Large tables (> 10KB): Streamed directly

## Integration Examples

### With Makefile

```makefile
.PHONY: db-setup db-seed

db-setup:
	confiture build \
		--sequential \
		--copy-format \
		--database-url postgresql://localhost/myapp

db-seed:
	confiture seed apply \
		--sequential \
		--copy-format \
		--env local
```

### With Docker

```dockerfile
FROM postgres:16-alpine

COPY db/schema /schema
COPY db/seeds /seeds

CMD confiture build \
      --sequential \
      --copy-format \
      --database-url postgresql://postgres@localhost/myapp
```

### With GitHub Actions

```yaml
name: Setup Test Database

jobs:
  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16
        env:
          POSTGRES_PASSWORD: test
          POSTGRES_DB: myapp_test

    steps:
      - uses: actions/checkout@v4

      - name: Install Confiture
        run: pip install confiture

      - name: Build and seed database
        run: |
          confiture build \
            --sequential \
            --copy-format \
            --benchmark \
            --database-url postgresql://postgres:test@localhost/myapp_test
```

## Comparison: VALUES vs COPY

| Aspect | VALUES | COPY |
|--------|--------|------|
| **Speed** | Baseline | 2-10x faster |
| **Parser overhead** | High | Low (streaming) |
| **Network overhead** | Per-row batches | Single stream |
| **Best for** | Small data (< 500 rows) | Large data (> 1000 rows) |
| **Compatibility** | All SQL features | Limited (basic values only) |
| **Escaping** | SQL syntax | Tab-delimited format |
| **PostgreSQL native** | Yes (INSERT) | Yes (COPY) |
| **Transaction safety** | Full ACID | Full ACID (savepoint) |

## Related Commands

- **`confiture seed apply`** - Load seeds with optional COPY format
- **`confiture seed convert`** - Transform INSERT to COPY format
- **`confiture seed benchmark`** - Compare VALUES vs COPY performance
- **`confiture seed validate`** - Check seed data quality
- **`confiture build`** - Build schema and apply seeds with COPY support

## FAQ

### Q: Is COPY format safe?

**A:** Yes! COPY uses PostgreSQL's native protocol with full ACID guarantees. All operations are wrapped in savepoints for atomic execution.

### Q: Can I mix VALUES and COPY in the same project?

**A:** Yes! Confiture automatically selects the best format per table. Unconvertible files stay as INSERT (VALUES), others convert to COPY.

### Q: Will COPY format break my existing workflows?

**A:** No, COPY format is completely optional. Existing workflows continue to work. Enable with `--copy-format` flag.

### Q: How much faster is COPY?

**A:** Typically **2-10x faster** depending on:
- Data size (bigger = more improvement)
- Network latency (lower = more improvement)
- Row count (more rows = higher speedup)

### Q: Can I use COPY with functions (NOW(), uuid_generate(), etc)?

**A:** No, COPY format doesn't support computed values. Keep those as INSERT statements (Confiture handles mixed formats automatically).

### Q: What if conversion fails?

**A:** Confiture shows a clear reason and skips the file gracefully. Your workflow continues with original INSERT format (backward compatible).

### Q: Should I commit converted COPY files?

**A:** Optional. Benefits of each approach:
- **Store as COPY**: Fast on fresh builds, easier CI/CD
- **Store as INSERT**: More readable, easier to edit, convert on-demand
- **Mixed**: Store seed definitions as INSERT, convert during build

## See Also

- [Sequential Seed Execution](sequential-seed-execution.md) - Solves 650+ row parser limits
- [Seed Validation](seed-validation.md) - Check seed quality before loading
- [Build from DDL](01-build-from-ddl.md) - Fresh database initialization
