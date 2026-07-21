# COPY Format Loading - Practical Examples

## Real-World Scenarios

This guide shows practical examples for common seed loading situations.

## Scenario 1: Simple Project with Small Seeds

### Project Structure
```
myproject/
├── db/
│   ├── schema/
│   │   ├── 00_core/
│   │   │   └── types.sql
│   │   ├── 10_tables/
│   │   │   ├── users.sql
│   │   │   └── posts.sql
│   │   └── 20_constraints/
│   │       └── fk.sql
│   ├── seeds/
│   │   ├── 01_users.sql       (100 rows)
│   │   ├── 02_posts.sql       (200 rows)
│   │   └── 03_comments.sql    (150 rows)
│   └── environments/
│       └── local.yaml
```

### Seed Files
```sql
-- db/seeds/01_users.sql
INSERT INTO users (id, name, email) VALUES
  (1, 'Alice', 'alice@example.com'),
  (2, 'Bob', 'bob@example.com'),
  (3, 'Charlie', 'charlie@example.com');
```

### Commands
```bash
# Development: Just build and go
confiture build --database-url postgresql://localhost/myapp

# Testing: Add sequential for safety
confiture build --sequential --database-url postgresql://localhost/myapp

# With progress
confiture build --sequential --database-url postgresql://localhost/myapp -v
```

### Result
✅ Fast (< 1 second)
✅ Simple (no flags needed)
✅ Perfect for development

---

## Scenario 2: Growing Project with Large Seeds

### Project Structure
```
ecommerce/
├── db/
│   ├── schema/
│   │   ├── 00_core/
│   │   │   ├── types.sql
│   │   │   └── functions.sql
│   │   ├── 10_tables/
│   │   │   ├── users.sql
│   │   │   ├── products.sql
│   │   │   ├── orders.sql
│   │   │   └── order_items.sql
│   │   └── 20_constraints/
│   │       └── fk.sql
│   ├── seeds/
│   │   ├── 01_users.sql          (2,000 rows)
│   │   ├── 02_categories.sql     (500 rows)
│   │   ├── 03_products.sql       (15,000 rows)
│   │   ├── 04_orders.sql         (10,000 rows)
│   │   └── 05_order_items.sql    (50,000 rows)
│   └── environments/
│       ├── local.yaml
│       ├── test.yaml
│       └── staging.yaml
```

### Challenge
Old approach (concatenate) fails because some files exceed 650 rows

### Solution with Sequential + COPY
```bash
# Development (sequential solves 650+ limit)
confiture build --sequential \
  --database-url postgresql://localhost/ecommerce_dev

# Testing (add COPY for speed)
confiture build --sequential --copy-format \
  --database-url postgresql://localhost/ecommerce_test

# See performance improvement
confiture seed benchmark --seeds-dir db/seeds
# Output:
# COPY Format Performance Benchmark
# Total rows: 77,500
# VALUES: 12,345ms
# COPY: 1,234ms
# Speedup: 10x faster ✅
```

### Configuration
```yaml
# db/environments/test.yaml
name: test
database_url: postgresql://localhost/ecommerce_test

seed:
  execution_mode: sequential
  use_copy_format: true
  copy_threshold: 1000
  benchmark: true
```

### Makefile Integration
```makefile
.PHONY: db-setup db-seed db-reset

db-setup:
	confiture build --sequential --copy-format \
		--database-url postgresql://localhost/ecommerce_dev

db-seed:
	confiture seed apply --sequential --copy-format \
		--env local

db-reset:
	dropdb --if-exists ecommerce_dev
	createdb ecommerce_dev
	confiture build --sequential --copy-format \
		--database-url postgresql://localhost/ecommerce_dev
```

### Result
✅ Reliable (sequential handles > 650 rows)
✅ Fast (COPY format, 10x improvement)
✅ Easy development workflow

---

## Scenario 3: CI/CD Pipeline

### GitHub Actions Workflow
```yaml
name: Test Suite

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest

    services:
      postgres:
        image: postgres:16-alpine
        env:
          POSTGRES_PASSWORD: testpass
          POSTGRES_DB: myapp_test
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: |
          pip install fraiseql-confiture
          pip install -r requirements-test.txt

      - name: Build database with seeds
        run: |
          confiture build \
            --sequential \
            --copy-format \
            --continue-on-error \
            --database-url postgresql://postgres:testpass@localhost/myapp_test

      - name: Run tests
        run: pytest tests/ -v
```

### Performance
```
Building database...
✓ Schema created: 45 tables
✓ Seeds applied: 120,000 rows in 2.3s (COPY format)
✓ Ready for testing

Total time: 2.8s (vs 15-20s with VALUES format)
```

### Result
✅ Fast (2.8 seconds for full database)
✅ Reliable (sequential, continue-on-error)
✅ Safe (savepoint isolation)

---

## Scenario 4: Converting Existing Seeds

### Situation
You have large seed files as INSERT statements and want to convert to COPY format.

### Before
```sql
-- db/seeds/products.sql (15,000 rows)
INSERT INTO products (id, sku, name, price) VALUES
  (1, 'PROD-001', 'Laptop', 999.99),
  (2, 'PROD-002', 'Mouse', 29.99),
  (3, 'PROD-003', 'Keyboard', 79.99),
  ... (15,000 rows total)
```

### Convert
```bash
# Convert single file
confiture seed convert \
  --input db/seeds/products.sql \
  --output db/seeds/products_copy.sql

# Or convert entire directory
confiture seed convert \
  --input db/seeds \
  --batch \
  --output db/seeds_optimized

# View conversion report
Conversion Results
┌─────────────────┬────────────┬──────────┐
│ File            │ Status     │ Rows     │
├─────────────────┼────────────┼──────────┤
│ users.sql       │ ✓ Converted │ 2,000   │
│ categories.sql  │ ✓ Converted │ 500     │
│ products.sql    │ ✓ Converted │ 15,000  │
│ complex.sql     │ ⚠ Skipped   │ Has CTEs │
└─────────────────┴────────────┴──────────┘

Success rate: 75%
```

### After
```bash
# Use converted seeds for faster loading
confiture build \
  --sequential \
  --database-url postgresql://localhost/myapp

# Much faster (uses COPY format)
# 75% of seeds in COPY format
# 25% in original INSERT format (mixed seamlessly)
```

### Alternative: Store Both
```bash
# Keep original INSERT files for readability
git add db/seeds/

# Also commit optimized COPY versions
confiture seed convert --input db/seeds --batch --output db/seeds_copy
git add db/seeds_copy/

# Use optimized version in CI/CD
confiture build \
  --sequential \
  --database-url postgresql://localhost/myapp
```

### Result
✅ Conversion succeeded for 75% of files
✅ Unconvertible files stay as INSERT
✅ Automatic fallback (no configuration needed)

---

## Scenario 5: Production Database Initialization

### Challenge
Initialize production database with 500K+ rows of seed data as fast as possible

### Pre-conversion Strategy
```bash
# Step 1: Convert seeds locally (one-time)
confiture seed convert \
  --input db/seeds \
  --batch \
  --output db/seeds_production

# Step 2: Verify conversion succeeded
# Conversion Results
# Total: 12 files
# Converted: 11 (92%)
# Skipped: 1 (has stored procedure call)

# Step 3: Commit to git
git add db/seeds_production/
git commit -m "chore: add COPY-optimized seeds for production"

# Step 4: Tag for release
git tag -a v1.5.0-seeds -m "Production seed optimization"

# Step 5: In production deployment script
echo "Initializing production database..."
confiture build \
  --sequential \
  --database-url $PROD_DATABASE_URL \
  --progress

# Output:
# Initializing production database...
# Schema created: 45 tables (2.1s)
# Seeds applied: 500,000 rows (8.3s)
# ✓ Database ready (10.4s total)
```

### Deployment Script
```bash
#!/bin/bash
# scripts/initialize-prod-db.sh

set -e

echo "🚀 Production Database Initialization"
echo "======================================"

# Check database connectivity
echo "Checking database connection..."
psql "$DATABASE_URL" -c "\q" || exit 1

# Build database
echo "Building schema and seeds..."
confiture build \
  --sequential \
  --database-url "$DATABASE_URL" \
  --progress

# Verify
echo "Verifying schema..."
TABLE_COUNT=$(psql "$DATABASE_URL" -t -c "SELECT COUNT(*) FROM pg_tables WHERE schemaname='public'")
echo "✓ Tables created: $TABLE_COUNT"

# Check row counts
echo "Verifying seed data..."
psql "$DATABASE_URL" -c "SELECT 'Users' as table, COUNT(*) as rows FROM users
UNION ALL
SELECT 'Products', COUNT(*) FROM products
UNION ALL
SELECT 'Orders', COUNT(*) FROM orders;"

echo "✅ Production database initialized successfully"
```

### Result
✅ 500K rows loaded in < 10 seconds
✅ Pre-optimized seeds (zero conversion overhead)
✅ Reliable and reproducible
✅ Easy to verify and rollback

---

## Scenario 6: Handling Unconvertible Files

### Situation
Some seed files use SQL features that can't be converted to COPY format

### Mixed Format Example
```sql
-- db/seeds/01_users.sql (convertible)
INSERT INTO users (id, name, email) VALUES
  (1, 'Alice', 'alice@example.com'),
  (2, 'Bob', 'bob@example.com');

-- db/seeds/02_sequences.sql (unconvertible)
INSERT INTO sequences (name, next_value)
SELECT 'user_id', MAX(id) + 1 FROM users;

-- db/seeds/03_timestamps.sql (unconvertible)
INSERT INTO events (id, created_at)
VALUES (1, NOW()), (2, NOW());
```

### Conversion
```bash
# Attempt conversion
confiture seed convert --input db/seeds --batch --output db/seeds_copy

# Results:
Conversion Results
┌──────────────────────┬──────────┬───────────────────────────┐
│ File                 │ Status   │ Rows/Reason               │
├──────────────────────┼──────────┼───────────────────────────┤
│ 01_users.sql         │ ✓ Converted │ 2,000                │
│ 02_sequences.sql     │ ⚠ Skipped   │ Has SELECT subquery   │
│ 03_timestamps.sql    │ ⚠ Skipped   │ Has NOW() function    │
└──────────────────────┴──────────┘───────────────────────────┘

Summary:
  Converted: 1/3 (33%)
  Success rate: 33%
```

### How Confiture Handles This
```bash
# Graceful fallback: mix formats
confiture build --sequential --copy-format \
  --database-url postgresql://localhost/myapp

# Loading:
# ✓ 01_users.sql (COPY format) - 2,000 rows in 0.2s
# ✓ 02_sequences.sql (INSERT) - 1 row in 0.1s
# ✓ 03_timestamps.sql (INSERT) - 2 rows in 0.1s
# ✓ All seeds applied successfully
```

### Result
✅ Unconvertible files skipped gracefully
✅ Other files use COPY format
✅ No manual intervention needed
✅ Seamless mixed format loading

---

## Scenario 7: Docker Deployment

### Dockerfile
```dockerfile
FROM postgres:16-alpine AS builder

# Install Python and Confiture
RUN apk add --no-cache python3 py3-pip
RUN pip install fraiseql-confiture

# Copy schema and seeds
COPY db/schema /app/db/schema
COPY db/seeds /app/db/seeds

# Initialize database with schema and seeds
RUN mkdir -p /docker-entrypoint-initdb.d

# Create initialization script
RUN echo '#!/bin/bash' > /docker-entrypoint-initdb.d/000-init.sh && \
    echo 'cd /app' >> /docker-entrypoint-initdb.d/000-init.sh && \
    echo 'confiture build --sequential --copy-format --database-url postgresql://postgres@localhost/postgres' >> /docker-entrypoint-initdb.d/000-init.sh && \
    chmod +x /docker-entrypoint-initdb.d/000-init.sh

# Production image
FROM postgres:16-alpine

COPY --from=builder /docker-entrypoint-initdb.d /docker-entrypoint-initdb.d

ENV POSTGRES_PASSWORD=postgres
ENV POSTGRES_DB=myapp

EXPOSE 5432
```

### Usage
```bash
# Build image
docker build -t myapp-db:latest .

# Run container (auto-initializes)
docker run -d \
  -e POSTGRES_PASSWORD=mypassword \
  -e POSTGRES_DB=myapp \
  -p 5432:5432 \
  myapp-db:latest

# Database ready with schema + seeds
# Verified: docker logs myapp-db-container
# ✓ Schema created
# ✓ Seeds applied (COPY format)
```

### Result
✅ Self-contained image
✅ Automatic initialization
✅ Fast startup (COPY format)
✅ Perfect for development & testing

---

## Scenario 8: Large File Optimization

### Problem
Single seed file with 100K rows takes too long

### Analysis
```bash
# Check current performance
confiture seed benchmark --seeds-dir db/seeds

# Output:
# Seed Performance Analysis
# seeds/products.sql: 100,000 rows
#   VALUES format: 45.2s
#   COPY format:  4.8s
#   Speedup: 9.4x faster
```

### Solution: Split Files
```bash
# Split large file into smaller chunks
split -l 10000 db/seeds/products.sql db/seeds/products_

# Rename chunks
mv db/seeds/products_aa db/seeds/03_products_a.sql
mv db/seeds/products_ab db/seeds/03_products_b.sql
mv db/seeds/products_ac db/seeds/03_products_c.sql
# ... etc

# Now use with COPY format
confiture build --sequential --copy-format \
  --database-url postgresql://localhost/myapp

# Output:
# ✓ 03_products_a.sql (COPY) 10,000 rows - 1.1s
# ✓ 03_products_b.sql (COPY) 10,000 rows - 1.1s
# ✓ 03_products_c.sql (COPY) 10,000 rows - 1.0s
# Total: 100,000 rows in 3.2s (14x faster than original!)
```

### Result
✅ Better parallelization
✅ Faster execution
✅ Easier to manage
✅ Cleaner error isolation

---

## Performance Comparison Across Scenarios

| Scenario | Approach | Time | Speedup |
|----------|----------|------|---------|
| **Small Project** | Concatenate | 0.3s | Baseline |
| **Growing Project** | Sequential + COPY | 1.2s | 10x faster than VALUES |
| **CI/CD** | Sequential + COPY | 2.8s | 7x faster |
| **Production (500K)** | Pre-converted | 8.3s | 20x faster |
| **Large File** | Split + COPY | 3.2s | 14x faster |

---

## Troubleshooting Examples

### Issue: "Connection refused"
```bash
# Wrong: Default localhost
confiture build --sequential --copy-format

# Right: Explicit connection
confiture build --sequential --copy-format \
  --database-url postgresql://user:pass@host:5432/dbname
```

### Issue: "Cannot convert file"
```bash
# Cause: File uses SQL functions
# Solution: Keep that file as INSERT, convert others

confiture build --sequential --copy-format \
  --database-url postgresql://localhost/myapp

# File is skipped gracefully, no manual action needed
```

### Issue: "Slow performance"
```bash
# Check what format is being used
confiture seed benchmark --seeds-dir db/seeds

# If not fast enough, try higher threshold
confiture build --sequential --copy-format \
  --copy-threshold 500 \
  --database-url postgresql://localhost/myapp
```

---

## Summary

COPY format provides:
- ✅ 2-10x faster loading
- ✅ Automatic fallback for unconvertible patterns
- ✅ Seamless mixed format support
- ✅ Production-ready performance
- ✅ CI/CD friendly

Choose the scenario that matches your project and enjoy faster database initialization!
