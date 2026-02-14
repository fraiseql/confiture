# Seed Loading Strategy Decision Tree

## Quick Decision Guide

Use this flowchart to choose the optimal seed loading strategy for your situation:

```
START: Seed Loading Strategy Decision
│
├─ Question 1: How many rows total across all seeds?
│  │
│  ├─ < 5,000 total
│  │  └─→ Strategy A: Simple Concatenation
│  │
│  ├─ 5,000 - 50,000 total
│  │  └─→ Strategy B: Sequential (if any file > 650 rows)
│  │
│  └─ > 50,000 total
│     └─→ Strategy C: Sequential + COPY Format ⭐
│
└─ (See detailed strategies below)
```

## Strategy A: Simple Concatenation

### When to Use
- ✅ Total seed data < 5,000 rows
- ✅ No individual seed file > 650 rows
- ✅ All seed patterns are basic INSERT statements
- ✅ Quick iteration, testing, development

### Command
```bash
confiture seed apply --env local
# or
confiture build --database-url postgresql://localhost/myapp
```

### Pros
- ✅ Simplest approach
- ✅ Fastest to set up
- ✅ Good for development
- ✅ Minimal configuration

### Cons
- ❌ Fails with 650+ rows per file
- ❌ Slower for large datasets
- ❌ Not ideal for CI/CD

### Example
```bash
# Perfect for small projects
confiture build --database-url postgresql://localhost/myapp

# Small seed files work great
# 01_users.sql - 100 rows ✓
# 02_posts.sql - 200 rows ✓
# 03_comments.sql - 150 rows ✓
# Total: 450 rows - Fast and reliable
```

---

## Strategy B: Sequential Execution

### When to Use
- ✅ Any seed file with 650+ rows
- ✅ Need per-file error isolation
- ✅ Want clean error messages
- ✅ CI/CD pipelines
- ✅ Development + testing

### Command
```bash
confiture seed apply --sequential --env local
# or
confiture build --sequential --database-url postgresql://localhost/myapp
```

### Pros
- ✅ Solves 650+ row parser limit
- ✅ Per-file error isolation
- ✅ Clean error messages
- ✅ Continue-on-error support
- ✅ Better for CI/CD

### Cons
- ❌ Slightly slower than concatenation (for small files)
- ❌ More round-trips to database

### Example
```bash
# Handles large seed files reliably
confiture build --sequential \
  --database-url postgresql://localhost/myapp

# Large seed files work perfectly
# 01_users.sql - 1,000 rows ✓
# 02_products.sql - 2,500 rows ✓
# 03_categories.sql - 500 rows ✓
# Total: 4,000 rows - Reliable and fast
```

### Configuration
```yaml
# db/environments/local.yaml
seed:
  execution_mode: sequential
  continue_on_error: false
```

---

## Strategy C: Sequential + COPY Format ⭐ **Recommended for Large Data**

### When to Use
- ✅ **Total seed data > 50,000 rows** (⭐ BEST CHOICE)
- ✅ Need maximum speed for CI/CD
- ✅ Fresh database initialization
- ✅ Performance-critical pipelines
- ✅ Production-like environments

### Command
```bash
confiture seed apply --sequential --copy-format --env local
# or (recommended)
confiture build --sequential --copy-format \
  --database-url postgresql://localhost/myapp
```

### Pros
- ✅ **2-10x faster** loading (maximum speed)
- ✅ Solves 650+ row limit
- ✅ Per-file isolation
- ✅ Best for CI/CD
- ✅ See performance improvement

### Cons
- ❌ Some SQL patterns must stay as INSERT (graceful fallback)
- ❌ Conversion overhead (minimal, usually negligible)

### Example
```bash
# Maximum speed for large datasets
confiture build --sequential --copy-format \
  --benchmark \
  --database-url postgresql://localhost/myapp

# Output:
# Schema created: 45 tables
# Seeds applied: 120,000 rows in 2.3 seconds (COPY format)
# Speedup: 8.5x vs VALUES format
# Time saved: 15.2 seconds per build

# Compare with Strategy B (Sequential only):
# Same 120,000 rows would take ~18.5 seconds
# 8.5x faster = 16.2 second improvement!
```

### Performance Tiers

| Data Size | Strategy | Speed | Use Case |
|-----------|----------|-------|----------|
| < 5KB | Concatenate | Baseline | Dev/test |
| 5-50KB | Sequential | Baseline | Dev/test + safety |
| 50KB-1MB | Sequential + COPY | 3-5x faster | Production |
| 1-10MB | Sequential + COPY | 5-8x faster | Large systems |
| > 10MB | Sequential + COPY | 8-10x faster | Data warehouses |

### Configuration
```yaml
# db/environments/local.yaml
seed:
  execution_mode: sequential
  use_copy_format: true
  copy_threshold: 1000      # Auto-select for tables > 1000 rows
  benchmark: true           # Show performance metrics
```

---

## Strategy D: Pre-converted COPY Format Files

### When to Use
- ✅ Want to commit optimized seed files to git
- ✅ Very large static seed data
- ✅ Frequently re-initialize databases
- ✅ Performance critical

### Setup
```bash
# 1. Convert all seeds to COPY format
confiture seed convert --input db/seeds --batch --output db/seeds_copy

# 2. Review conversion results
# 3. Commit converted files to git
git add db/seeds_copy
git commit -m "chore: add COPY format optimized seeds"

# 4. Use in build
confiture build --sequential --database-url postgresql://localhost/myapp
```

### Pros
- ✅ Maximum speed (no conversion overhead)
- ✅ Reproducible (files in git)
- ✅ No conversion needed at runtime
- ✅ Great for monorepos

### Cons
- ❌ Less readable than INSERT
- ❌ Harder to edit/review
- ❌ Requires git discipline
- ❌ Mixed formats if some files unconvertible

### Example
```bash
# Setup once
confiture seed convert \
  --input db/seeds \
  --batch \
  --output db/seeds_copy

# View conversion results
Conversion Results
┌─────────────────┬───────────┬──────────┐
│ File            │ Status    │ Rows     │
├─────────────────┼───────────┼──────────┤
│ users.sql       │ ✓ Converted │ 10,000 │
│ posts.sql       │ ✓ Converted │ 25,000 │
│ comments.sql    │ ✓ Converted │ 85,000 │
│ complex.sql     │ ⚠ Skipped   │ Has CTEs │
└─────────────────┴───────────┴──────────┘

Summary:
  Total: 4 files
  Converted: 3 (75%)
  Skipped: 1 (due to CTEs)
  Success rate: 75%

# Now use converted seeds
git add db/seeds_copy/
git commit -m "chore: add COPY-optimized seeds"

# Future builds use optimized files automatically
confiture build --sequential --database-url postgresql://localhost/myapp
```

---

## Choosing Your Strategy: Decision Matrix

| Scenario | Total Rows | Max File | Strategy |
|----------|-----------|----------|----------|
| Development | < 5K | < 500 | A: Concatenate |
| Development | < 5K | 500-1000 | B: Sequential |
| Development | > 5K | < 650 | B: Sequential |
| Development | > 5K | > 650 | C: Sequential + COPY |
| **Testing** | **< 5K** | **< 500** | **A: Concatenate** |
| **Testing** | **< 5K** | **500-1000** | **B: Sequential** |
| **Testing** | **> 5K** | **Any** | **C: Sequential + COPY** |
| **CI/CD (Quick)** | < 50K | < 650 | B: Sequential |
| **CI/CD (Fast)** | > 50K | Any | C: Sequential + COPY ⭐ |
| **Production Init** | > 100K | Any | D: Pre-converted COPY |

---

## Quick Recommendation Guide

### For Different Projects

#### **Microservice / Small API**
```bash
# Most microservices have < 5K seed rows
confiture build --sequential --database-url postgresql://localhost/myapp

# Files:
# seeds/users.sql - 200 rows
# seeds/roles.sql - 50 rows
# seeds/permissions.sql - 100 rows
```

#### **Web Application**
```bash
# Typical web app has 10-50K rows
confiture build --sequential --copy-format \
  --benchmark \
  --database-url postgresql://localhost/myapp

# Files:
# seeds/users.sql - 5,000 rows
# seeds/posts.sql - 15,000 rows
# seeds/comments.sql - 20,000 rows
```

#### **Data Platform / Warehouse**
```bash
# Large systems need maximum speed
# Pre-convert and commit optimized seeds
confiture seed convert --input db/seeds --batch --output db/seeds_copy
git add db/seeds_copy/

# Then use in production builds:
confiture build --sequential --database-url $DATABASE_URL

# Files:
# seeds_copy/events.sql - 500K rows
# seeds_copy/metrics.sql - 250K rows
```

#### **Testing Suite**
```bash
# CI/CD needs fast, reliable setup
confiture build --sequential --copy-format \
  --continue-on-error \
  --database-url postgresql://localhost/test_db

# Handles any seed file size, any format
```

---

## Migration Path

If you're currently using Strategy A and growing:

### Step 1: Add Sequential (when hitting parser limit)
```bash
# If seeing "syntax error" with large files:
confiture build --sequential --database-url postgresql://localhost/myapp
```

### Step 2: Add COPY Format (when speed matters)
```bash
# If builds are slow:
confiture build --sequential --copy-format --benchmark \
  --database-url postgresql://localhost/myapp
```

### Step 3: Pre-convert (if very large)
```bash
# If > 100K rows and frequent rebuilds:
confiture seed convert --input db/seeds --batch --output db/seeds_copy
git add db/seeds_copy/
confiture build --sequential --database-url postgresql://localhost/myapp
```

---

## Performance Expectations

### Build Times (Example Dataset: 50,000 rows)

| Strategy | Time | Notes |
|----------|------|-------|
| **A: Concatenate** | 4.5s | Baseline, fails > 650 rows/file |
| **B: Sequential** | 4.3s | Slightly faster (less overhead) |
| **C: Sequential + COPY** | 0.6s | **7.2x faster** ⭐ |
| **D: Pre-converted COPY** | 0.5s | **9x faster** (no conversion) |

### Theoretical Speedup

```
Data Size:     50,000 rows
Concatenate:   4.5s
Sequential:    4.3s (same as concatenate for small files)
Sequential+:   0.6s (7.2x faster)
Pre-converted: 0.5s (9x faster)

Time saved per build: 4.0 seconds
Per month (100 builds): 400 seconds (6+ minutes)
Per year (1200 builds): 1 hour 20 minutes saved
```

---

## Troubleshooting by Strategy

### Strategy A Issues
```
Error: "syntax error at or near ";"
```
→ **Solution:** Switch to Strategy B (sequential)
```bash
confiture build --sequential --database-url postgresql://localhost/myapp
```

### Strategy B Issues
```
Error: "Cannot connect to database"
```
→ **Solution:** Check database URL
```bash
confiture build --sequential \
  --database-url postgresql://user:pass@host/db
```

### Strategy C Issues
```
Error: "Cannot convert db/seeds/complex.sql"
Reason: Detected NOW() function in VALUES clause
```
→ **Solution:** That file stays as INSERT (automatic), others convert
```bash
# Just continue - graceful fallback is automatic
confiture build --sequential --copy-format \
  --database-url postgresql://localhost/myapp
```

---

## See Also

- [COPY Format Loading Guide](copy-format-loading.md) - Detailed COPY format documentation
- [Sequential Seed Execution](sequential-seed-execution.md) - Deep dive into sequential mode
- [Seed Validation](seed-validation.md) - Ensure data quality before loading
- [Build from DDL](01-build-from-ddl.md) - Schema initialization guide
