# Medium 4: Schema-to-Schema Migration

**Zero-downtime migrations for major schema refactoring using Foreign Data Wrapper**

## What is Schema-to-Schema Migration?

Schema-to-Schema migration enables zero-downtime database migrations for major schema changes by running old and new schemas side-by-side, then seamlessly cutting over. It uses PostgreSQL's Foreign Data Wrapper (FDW) to connect the new schema to the old schema, allowing data migration while the old schema remains operational.

### Key Concept

> **"Two schemas, zero downtime"**

Confiture creates a new database with the new schema while keeping the old database running. Data migrates in the background using FDW or COPY strategies, then you cutover when ready. No downtime required.

---

## When to Use Schema-to-Schema Migration

### Perfect For

- **Major refactoring** - Breaking schema changes (renaming columns, changing types)
- **Large tables** - Multi-million row tables requiring hours to migrate
- **Zero-downtime requirements** - Production systems that can't afford downtime
- **Complex transformations** - Column mappings, data transformations during migration
- **High-traffic databases** - Can't lock tables for ALTER TABLE operations
- **Table splits/merges** - Breaking one table into multiple, or merging multiple into one

### Not For

- **Simple changes** - Use Medium 2 (Incremental) for simple ALTER TABLE operations
- **Fresh database** - Use Medium 1 (Build from DDL) for new environments
- **Data copying only** - Use Medium 3 (Production Sync) for copying data without schema changes
- **Emergency hotfixes** - Too complex for urgent production fixes

### When Breaking Changes Require Zero-Downtime

| Change Type | Medium 2 (Incremental) | Medium 4 (Schema-to-Schema) |
|-------------|----------------------|---------------------------|
| Add column | ✅ Simple ALTER | ❌ Overkill |
| Drop column | ✅ Simple ALTER | ❌ Overkill |
| Rename column | ⚠️ Requires app downtime | ✅ Zero downtime |
| Change column type | ⚠️ Locks table | ✅ Zero downtime |
| Large table (>10M rows) | ⚠️ Long locks | ✅ Background migration |
| Split/merge tables | ❌ Complex, risky | ✅ Safe, controlled |

---

## How Schema-to-Schema Migration Works

### The Migration Architecture

```
┌─────────────────────┐
│  Old Database       │  ← Application still running
│  (Source)           │     Reading/writing here
│                     │
│  old_users table    │
│  - full_name        │
│  - email            │
└─────────────────────┘
         │
         │ FDW Connection
         │ (Read-only access)
         ↓
┌─────────────────────┐
│  New Database       │  ← New schema ready
│  (Target)           │     Being populated in background
│                     │
│  Foreign Schema:    │
│  ├─ old_schema.     │  ← FDW views of old tables
│  │   old_users      │
│  │                  │
│  New Schema:        │
│  ├─ public.users    │  ← New schema structure
│      - display_name │     (renamed from full_name)
│      - email        │
└─────────────────────┘
```

### Migration Process

```
1. Setup Phase
   ↓
   Create new database with new schema (Medium 1: Build from DDL)

2. FDW Setup
   ↓
   Configure Foreign Data Wrapper to connect to old database

3. Strategy Selection
   ↓
   Auto-analyze tables, choose optimal strategy:
   - FDW Strategy: <10M rows (500K rows/sec)
   - COPY Strategy: ≥10M rows (6M rows/sec, 10-20x faster)

4. Data Migration
   ↓
   For each table, migrate data with column mapping:
   old_schema.old_users.full_name → public.users.display_name

5. Verification
   ↓
   Compare row counts, verify data integrity

6. Cutover
   ↓
   Switch application to new database (DNS/config change)
   Zero downtime!

7. Cleanup
   ↓
   Monitor new database, decommission old when confident
```

---

## The Two Migration Strategies

Confiture automatically selects the optimal strategy based on table size:

### Strategy 1: FDW (Foreign Data Wrapper)

**Best for**: Small-medium tables (<10M rows), complex transformations

**How it works**:
```sql
-- Uses INSERT ... SELECT through FDW
INSERT INTO public.users (display_name, email)
SELECT full_name AS display_name, email
FROM old_schema.old_users;
```

**Performance**: 500,000 rows/sec

**Pros**:
- Simple SQL-based transformations
- Works across databases/hosts
- Good for tables with complex logic

**Cons**:
- Slower than COPY
- More network round-trips
- Higher overhead for large tables

---

### Strategy 2: COPY

**Best for**: Large tables (≥10M rows), maximum speed

**How it works**:
```sql
-- Uses COPY ... TO STDOUT + COPY ... FROM STDIN
COPY (SELECT full_name, email FROM old_schema.old_users) TO STDOUT
↓ (streaming buffer)
COPY public.users (display_name, email) FROM STDIN
```

**Performance**: 6,000,000 rows/sec (10-20x faster than FDW!)

**Pros**:
- Maximum throughput
- Minimal memory usage
- Streaming architecture
- Optimal for bulk data

**Cons**:
- Limited transformations (column mapping only)
- Requires FDW setup first

---

### Strategy Comparison

| Metric | FDW Strategy | COPY Strategy |
|--------|-------------|--------------|
| **Throughput** | 500K rows/sec | 6M rows/sec ⚡ |
| **Best for** | <10M rows | ≥10M rows |
| **1M rows** | ~2 seconds | ~0.17 seconds |
| **10M rows** | ~20 seconds | ~1.7 seconds |
| **100M rows** | ~3.3 minutes | ~17 seconds |
| **Transformations** | Complex SQL | Column mapping |
| **Memory** | Medium | Low (streaming) |
| **Network** | Higher overhead | Optimized |

**Auto-selection threshold**: 10,000,000 rows

---

## Commands

### Full Migration Workflow

```bash
# 1. Create new database with new schema
confiture build --env new_production --from-ddl

# 2. Setup FDW connection to old database
confiture migrate schema-to-schema setup \
    --source old_production \
    --target new_production

# 3. Analyze tables and recommend strategies
confiture migrate schema-to-schema analyze \
    --target new_production

# Output:
# Table Analysis:
# ┌──────────────┬──────────┬──────────────┬────────────────────┐
# │ Table        │ Rows     │ Strategy     │ Est. Time          │
# ├──────────────┼──────────┼──────────────┼────────────────────┤
# │ users        │ 100K     │ fdw          │ 0.2s               │
# │ posts        │ 5M       │ fdw          │ 10s                │
# │ events       │ 50M      │ copy ⚡      │ 8.3s               │
# │ logs         │ 200M     │ copy ⚡      │ 33.3s              │
# └──────────────┴──────────┴──────────────┴────────────────────┘

# 4. Migrate tables with column mapping
confiture migrate schema-to-schema migrate \
    --target new_production \
    --mapping db/migration/column_mapping.yaml

# 5. Verify migration
confiture migrate schema-to-schema verify \
    --target new_production

# 6. Cutover (manual DNS/config change)
# Update application config to point to new_production

# 7. Cleanup FDW (after monitoring period)
confiture migrate schema-to-schema cleanup \
    --target new_production
```

---

### Individual Commands

**Setup FDW**:
```bash
confiture migrate schema-to-schema setup \
    --source old_production \
    --target new_production \
    --foreign-schema old_schema
```

**Analyze tables**:
```bash
confiture migrate schema-to-schema analyze \
    --target new_production \
    --schema public
```

**Migrate single table**:
```bash
confiture migrate schema-to-schema migrate-table \
    --target new_production \
    --source-table old_users \
    --target-table users \
    --mapping "full_name:display_name,email:email"
```

**Migrate all tables**:
```bash
confiture migrate schema-to-schema migrate \
    --target new_production \
    --mapping db/migration/column_mapping.yaml \
    --auto-strategy  # Let Confiture choose FDW vs COPY
```

**Manual strategy override**:
```bash
confiture migrate schema-to-schema migrate \
    --target new_production \
    --mapping db/migration/column_mapping.yaml \
    --force-strategy copy  # Force COPY for all tables
```

**Verify migration**:
```bash
confiture migrate schema-to-schema verify \
    --target new_production \
    --tables users,posts,comments
```

**Cleanup**:
```bash
confiture migrate schema-to-schema cleanup \
    --target new_production
```

---

## Configuration

### Environment Configuration

**db/environments/old_production.yaml** (source):
```yaml
name: old_production
database:
  host: old-db.example.com
  port: 5432
  database: myapp_production
  user: postgres
  password: ${OLD_DB_PASSWORD}
```

**db/environments/new_production.yaml** (target):
```yaml
name: new_production
database:
  host: new-db.example.com
  port: 5432
  database: myapp_production_v2
  user: postgres
  password: ${NEW_DB_PASSWORD}
```

### Column Mapping Configuration

**db/migration/column_mapping.yaml**:
```yaml
# Maps: source_table.source_column → target_table.target_column

users:
  source_table: old_users
  target_table: users
  columns:
    full_name: display_name  # Renamed
    email: email             # Same
    created_at: created_at   # Same

posts:
  source_table: blog_posts
  target_table: posts
  columns:
    post_title: title        # Renamed
    post_body: content       # Renamed
    author_id: user_id       # Renamed
    publish_date: published_at  # Renamed

# Table split example
orders:
  source_table: orders
  target_table: orders
  columns:
    id: id
    user_id: user_id
    total: total

order_items:
  source_table: orders
  target_table: order_items
  columns:
    id: order_id
    # Additional logic needed for splitting (manual SQL)
```

---

## Column Mapping and Transformations

### Simple Column Rename

**Old schema**:
```sql
CREATE TABLE old_users (
    id SERIAL PRIMARY KEY,
    full_name TEXT,
    email TEXT
);
```

**New schema**:
```sql
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    display_name TEXT,  -- Renamed from full_name
    email TEXT
);
```

**Mapping**:
```yaml
users:
  source_table: old_users
  target_table: users
  columns:
    full_name: display_name
    email: email
```

**Resulting migration SQL**:
```sql
-- FDW Strategy
INSERT INTO users (display_name, email)
SELECT full_name AS display_name, email
FROM old_schema.old_users;

-- COPY Strategy (for large tables)
COPY (SELECT full_name, email FROM old_schema.old_users) TO STDOUT
-- ↓ streaming
COPY users (display_name, email) FROM STDIN
```

---

### Type Change

**Old schema**:
```sql
CREATE TABLE products (
    id SERIAL PRIMARY KEY,
    price INTEGER  -- Cents
);
```

**New schema**:
```sql
CREATE TABLE products (
    id SERIAL PRIMARY KEY,
    price NUMERIC(10,2)  -- Dollars
);
```

**Note**: Type conversions beyond column mapping require custom SQL transformations (outside column mapping):

```sql
-- Manual migration with transformation
INSERT INTO products (id, price)
SELECT id, price::NUMERIC / 100.0  -- Convert cents to dollars
FROM old_schema.products;
```

**Current limitation**: Complex transformations not yet supported in column mapping. For now, use manual SQL or write custom migration script.

---

### Table Merge

**Old schema**:
```sql
CREATE TABLE user_profiles (
    user_id INTEGER PRIMARY KEY,
    bio TEXT
);

CREATE TABLE user_settings (
    user_id INTEGER PRIMARY KEY,
    theme TEXT
);
```

**New schema**:
```sql
CREATE TABLE users (
    id INTEGER PRIMARY KEY,
    bio TEXT,
    theme TEXT
);
```

**Migration** (requires multiple steps):
```sql
-- Step 1: Migrate from user_profiles
INSERT INTO users (id, bio)
SELECT user_id, bio FROM old_schema.user_profiles;

-- Step 2: Update from user_settings
UPDATE users
SET theme = old_schema.user_settings.theme
FROM old_schema.user_settings
WHERE users.id = old_schema.user_settings.user_id;
```

**Current limitation**: Table merges require manual SQL. Use column mapping for 1-to-1 table migrations only.

---

## Strategy Selection

### Auto-Detection (Recommended)

Confiture automatically selects the optimal strategy based on table size:

```bash
# Analyze tables and see recommendations
confiture migrate schema-to-schema analyze \
    --target new_production

# Output:
# ┌──────────────┬──────────┬──────────────┬────────────────────┐
# │ Table        │ Rows     │ Strategy     │ Est. Time          │
# ├──────────────┼──────────┼──────────────┼────────────────────┤
# │ users        │ 100K     │ fdw          │ 0.2s               │
# │ posts        │ 5M       │ fdw          │ 10s                │
# │ events       │ 50M      │ copy ⚡      │ 8.3s (5x faster)   │
# └──────────────┴──────────┴──────────────┴────────────────────┘

# Use auto-selected strategies
confiture migrate schema-to-schema migrate \
    --target new_production \
    --mapping column_mapping.yaml \
    --auto-strategy
```

**Selection logic**:
```python
if row_count >= 10_000_000:
    strategy = "copy"  # 6M rows/sec
else:
    strategy = "fdw"   # 500K rows/sec
```

---

### Manual Override

Force specific strategy for all tables:

```bash
# Force FDW (even for large tables)
confiture migrate schema-to-schema migrate \
    --target new_production \
    --mapping column_mapping.yaml \
    --force-strategy fdw

# Force COPY (even for small tables)
confiture migrate schema-to-schema migrate \
    --target new_production \
    --mapping column_mapping.yaml \
    --force-strategy copy
```

**When to override**:
- **Force FDW**: Complex transformations needed, network is fast
- **Force COPY**: Maximum speed required, simple column mapping only

---

### Per-Table Strategy Override

**db/migration/column_mapping.yaml**:
```yaml
users:
  source_table: old_users
  target_table: users
  strategy: fdw  # Override: force FDW for this table
  columns:
    full_name: display_name
    email: email

events:
  source_table: old_events
  target_table: events
  strategy: copy  # Override: force COPY for this table
  columns:
    event_type: type
    event_data: data
```

---

## Verification and Testing

### Pre-Migration Verification

**1. Verify FDW setup**:
```bash
# Test FDW connection
psql new_production -c "SELECT COUNT(*) FROM old_schema.old_users"

# Expected: Row count from old database
```

**2. Verify schema compatibility**:
```bash
# Compare schemas
confiture diff \
    --from old_production \
    --to new_production

# Check for missing columns in mapping
```

**3. Test migration on single table**:
```bash
# Migrate small table first
confiture migrate schema-to-schema migrate-table \
    --target new_production \
    --source-table old_users \
    --target-table users_test \
    --mapping "full_name:display_name,email:email"

# Verify data
psql new_production -c "SELECT * FROM users_test LIMIT 10"
```

---

### Post-Migration Verification

**1. Row count comparison**:
```bash
confiture migrate schema-to-schema verify \
    --target new_production \
    --tables users,posts,comments

# Output:
# Verification Results:
# ┌──────────┬──────────────┬──────────────┬────────┬────────────┐
# │ Table    │ Source Count │ Target Count │ Match  │ Difference │
# ├──────────┼──────────────┼──────────────┼────────┼────────────┤
# │ users    │ 1,234,567    │ 1,234,567    │ ✅ Yes │ 0          │
# │ posts    │ 9,876,543    │ 9,876,543    │ ✅ Yes │ 0          │
# │ comments │ 50,000,000   │ 49,999,999   │ ❌ No  │ -1         │
# └──────────┴──────────────┴──────────────┴────────┴────────────┘
```

**2. Data integrity checks**:
```sql
-- Check for NULL values in required columns
SELECT COUNT(*) FROM users WHERE display_name IS NULL;
-- Expected: 0

-- Check foreign key integrity
SELECT COUNT(*)
FROM posts p
LEFT JOIN users u ON p.user_id = u.id
WHERE u.id IS NULL;
-- Expected: 0 (no orphaned posts)

-- Check data ranges
SELECT MIN(created_at), MAX(created_at) FROM users;
-- Verify dates make sense
```

**3. Sampling verification**:
```sql
-- Compare sample data
SELECT id, display_name, email
FROM old_schema.old_users
WHERE id IN (1, 100, 1000, 10000)
ORDER BY id;

SELECT id, display_name, email
FROM public.users
WHERE id IN (1, 100, 1000, 10000)
ORDER BY id;

-- Verify display_name = old full_name
```

---

## Zero-Downtime Cutover Process

### The Cutover Plan

```
Phase 1: Preparation (Days before)
↓
- New database fully migrated
- Verification complete
- Monitoring in place
- Rollback plan ready

Phase 2: Read-Write Split (Optional)
↓
- New database: Read traffic
- Old database: Write traffic
- Catch-up synchronization

Phase 3: Final Cutover (Minutes)
↓
- DNS/config change
- Application restarts
- Traffic moves to new database

Phase 4: Monitoring (Hours after)
↓
- Watch error rates
- Monitor query performance
- Keep old database warm

Phase 5: Decommission (Days/weeks later)
↓
- Cleanup FDW
- Archive old database
- Remove old config
```

---

### Cutover Strategies

**Strategy A: Blue-Green Deployment** (Recommended)

```bash
# 1. New database ready (green)
# 2. All traffic on old database (blue)

# 3. Cutover: Update DNS/config
# OLD:
DATABASE_URL=postgresql://old-db.example.com/myapp

# NEW:
DATABASE_URL=postgresql://new-db.example.com/myapp_v2

# 4. Rolling restart application servers
kubectl rollout restart deployment/app

# 5. Monitor
# - Error rates should be unchanged
# - Response times should be similar or better

# 6. Rollback if needed (change DNS back)
```

---

**Strategy B: Read-Write Split** (Advanced)

```bash
# Phase 1: Reads to new, writes to old
# Configure application:
READ_DATABASE_URL=postgresql://new-db.example.com/myapp_v2
WRITE_DATABASE_URL=postgresql://old-db.example.com/myapp

# Deploy application with read-write split
kubectl apply -f k8s/app-split-config.yaml

# Run catch-up synchronization
confiture sync \
    --from old_production \
    --to new_production \
    --tables users,posts \
    --incremental  # Only new/updated rows

# Phase 2: Monitor read traffic on new database
# Verify performance, error rates

# Phase 3: Cutover writes
WRITE_DATABASE_URL=postgresql://new-db.example.com/myapp_v2

# Deploy write cutover
kubectl apply -f k8s/app-unified-config.yaml
```

---

**Strategy C: Feature Flag** (Gradual)

```python
# Application code with feature flag
if feature_flags.get("use_new_database"):
    db = new_database_connection
else:
    db = old_database_connection

# Gradual rollout:
# 1% traffic → 10% → 50% → 100%
```

---

### Rollback Procedures

**Immediate rollback** (within minutes):
```bash
# 1. Revert DNS/config
DATABASE_URL=postgresql://old-db.example.com/myapp

# 2. Rolling restart
kubectl rollout restart deployment/app

# 3. Old database still warm, no data loss
```

**Data rollback** (if new database modified):
```bash
# 1. Stop writes to new database
# 2. Re-sync from old to new
confiture sync --from old_production --to new_production

# 3. Retry cutover after fixing issues
```

---

## Best Practices

### 1. Test the Migration First

**Bad**: Migrate production directly

```bash
# ❌ DANGEROUS
confiture migrate schema-to-schema migrate \
    --source production \
    --target new_production
```

**Good**: Test on staging first

```bash
# ✅ SAFE

# 1. Test on staging
confiture migrate schema-to-schema migrate \
    --source staging \
    --target new_staging

# 2. Verify staging works
# Run integration tests
# Manual QA testing

# 3. Time the migration
# Estimate production migration time

# 4. Then migrate production
confiture migrate schema-to-schema migrate \
    --source production \
    --target new_production
```

---

### 2. Use Read-Only Source Connection

**Production database (source)**:
```yaml
# db/environments/old_production.yaml
database:
  host: old-db.example.com
  user: readonly_user  # ✅ Read-only
  password: ${OLD_DB_PASSWORD}
```

**Create read-only user**:
```sql
-- On old production database
CREATE USER readonly_user WITH PASSWORD 'secure_password';
GRANT CONNECT ON DATABASE myapp_production TO readonly_user;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO readonly_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO readonly_user;
```

**Why**: Prevents accidental writes to production during migration

---

### 3. Migrate During Low-Traffic Period

```bash
# Schedule migration during maintenance window
# Example: Sunday 2 AM - 6 AM

# 1. Notify users of maintenance window
# 2. Reduce traffic (optional: enable read-only mode)
# 3. Run migration
confiture migrate schema-to-schema migrate \
    --source production \
    --target new_production

# 4. Verify
# 5. Cutover
```

---

### 4. Monitor Throughout Migration

```bash
# Terminal 1: Run migration
confiture migrate schema-to-schema migrate \
    --source production \
    --target new_production \
    --show-progress

# Terminal 2: Monitor old database
watch -n 5 'psql old_production -c "
    SELECT COUNT(*) as active_connections
    FROM pg_stat_activity
    WHERE datname = current_database()
"'

# Terminal 3: Monitor new database
watch -n 5 'psql new_production -c "
    SELECT
        schemaname,
        tablename,
        n_live_tup as row_count
    FROM pg_stat_user_tables
    ORDER BY n_live_tup DESC
"'
```

---

### 5. Keep Old Database Warm

```bash
# After cutover, don't immediately drop old database
# Keep for 1-2 weeks as rollback safety net

# Monitor both databases
# Compare query patterns
# Watch for anomalies

# Only after confidence period:
confiture migrate schema-to-schema cleanup \
    --target new_production

# Archive old database (don't delete!)
pg_dump old_production > old_production_final_backup.sql
```

---

### 6. Document Column Mappings

```yaml
# db/migration/column_mapping.yaml
# Add comments explaining renames

users:
  source_table: old_users
  target_table: users
  columns:
    full_name: display_name  # Renamed for clarity (JIRA-123)
    email: email
    created_at: created_at

posts:
  source_table: blog_posts
  target_table: posts
  columns:
    post_title: title  # Simplified naming (JIRA-456)
    post_body: content # Standardized across all content tables
    author_id: user_id # FK consistency (JIRA-789)
```

---

## Common Use Cases

### Use Case 1: Column Rename

**Scenario**: Rename `full_name` to `display_name` in `users` table (10M rows)

**Old schema**:
```sql
CREATE TABLE old_users (
    id SERIAL PRIMARY KEY,
    full_name TEXT,
    email TEXT UNIQUE
);
```

**New schema**:
```sql
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    display_name TEXT,
    email TEXT UNIQUE
);
```

**Solution**:
```bash
# 1. Create new database with new schema
confiture build --env new_production --from-ddl

# 2. Setup FDW
confiture migrate schema-to-schema setup \
    --source old_production \
    --target new_production

# 3. Analyze (10M rows → COPY strategy auto-selected)
confiture migrate schema-to-schema analyze \
    --target new_production
# Output: users: 10M rows, COPY strategy, ~1.7s

# 4. Migrate with column mapping
confiture migrate schema-to-schema migrate-table \
    --target new_production \
    --source-table old_users \
    --target-table users \
    --mapping "full_name:display_name,email:email"
# Completed in 1.7 seconds (COPY strategy)

# 5. Verify
confiture migrate schema-to-schema verify \
    --target new_production \
    --tables users
# ✅ Match: 10,000,000 rows

# 6. Cutover (update app config)
DATABASE_URL=postgresql://new-db.example.com/myapp_v2

# Zero downtime achieved!
```

---

### Use Case 2: Type Change

**Scenario**: Change `price` from INTEGER (cents) to NUMERIC (dollars)

**Old schema**:
```sql
CREATE TABLE products (
    id SERIAL PRIMARY KEY,
    name TEXT,
    price INTEGER  -- Cents: 1999 = $19.99
);
```

**New schema**:
```sql
CREATE TABLE products (
    id SERIAL PRIMARY KEY,
    name TEXT,
    price NUMERIC(10,2)  -- Dollars: 19.99
);
```

**Solution**:
```bash
# Column mapping doesn't support type conversion
# Use custom SQL migration

confiture migrate schema-to-schema setup \
    --source old_production \
    --target new_production

# Manual migration with transformation
psql new_production <<SQL
INSERT INTO products (id, name, price)
SELECT
    id,
    name,
    (price::NUMERIC / 100.0)::NUMERIC(10,2)  -- Convert cents to dollars
FROM old_schema.products;
SQL

# Verify conversion
psql new_production -c "
SELECT
    p_old.id,
    p_old.price as old_price_cents,
    p_new.price as new_price_dollars
FROM old_schema.products p_old
JOIN public.products p_new ON p_old.id = p_new.id
LIMIT 10
"
```

---

### Use Case 3: Table Rename

**Scenario**: Rename `blog_posts` to `posts`

**Old schema**:
```sql
CREATE TABLE blog_posts (
    id SERIAL PRIMARY KEY,
    title TEXT,
    content TEXT
);
```

**New schema**:
```sql
CREATE TABLE posts (
    id SERIAL PRIMARY KEY,
    title TEXT,
    content TEXT
);
```

**Solution**:
```bash
# Column names same, just table rename
confiture migrate schema-to-schema migrate-table \
    --target new_production \
    --source-table blog_posts \
    --target-table posts \
    --mapping "title:title,content:content,id:id"

# Or use wildcard mapping (future feature)
# --mapping "*:*"  # Map all columns with same names
```

---

### Use Case 4: Large Table Migration

**Scenario**: Migrate `events` table with 200M rows

**Solution**:
```bash
# 1. Analyze
confiture migrate schema-to-schema analyze \
    --target new_production

# Output:
# events: 200M rows, COPY strategy ⚡, ~33.3 seconds

# 2. Migrate (automatically uses COPY)
confiture migrate schema-to-schema migrate \
    --target new_production \
    --mapping column_mapping.yaml \
    --auto-strategy

# Migration uses COPY strategy:
# - 6M rows/sec throughput
# - Streaming (low memory)
# - Completed in ~33 seconds

# If using FDW instead:
# - 500K rows/sec
# - Would take ~400 seconds (6.7 minutes)
# - COPY is 12x faster!
```

---

## Performance Characteristics

### Throughput Comparison

Based on production benchmarks:

| Table Size | FDW Time | COPY Time | Speedup |
|------------|----------|-----------|---------|
| 1M rows | 2.0s | 0.17s | 11.8x |
| 10M rows | 20.0s | 1.7s | 11.8x |
| 50M rows | 100.0s | 8.3s | 12.0x |
| 100M rows | 200.0s | 16.7s | 12.0x |
| 200M rows | 400.0s | 33.3s | 12.0x |

**COPY strategy is consistently 10-20x faster** for large tables.

---

### Strategy Selection Impact

**Example**: 5-table database

| Table | Rows | Auto Strategy | Time | Manual FDW | Time |
|-------|------|--------------|------|------------|------|
| users | 100K | FDW | 0.2s | FDW | 0.2s |
| posts | 5M | FDW | 10.0s | FDW | 10.0s |
| comments | 20M | COPY ⚡ | 3.3s | FDW | 40.0s |
| events | 50M | COPY ⚡ | 8.3s | FDW | 100.0s |
| logs | 200M | COPY ⚡ | 33.3s | FDW | 400.0s |
| **TOTAL** | **275.1M** | **Mixed** | **55.1s** | **All FDW** | **550.2s** |

**Auto-strategy is 10x faster** (55s vs 550s) by using COPY for large tables!

---

### Memory Usage

| Strategy | Batch Size | Memory per Batch | Total Memory |
|----------|-----------|------------------|--------------|
| FDW | N/A | ~50MB | ~50MB |
| COPY | Streaming | ~10-20MB buffer | ~20MB |

**COPY uses less memory** due to streaming architecture.

---

### Network Overhead

```
FDW Strategy:
┌─────────┐     SELECT * FROM old_schema.users      ┌──────────┐
│  Source │ ←───────────────────────────────────── │  Target  │
│    DB   │ ─→ Row 1                                │    DB    │
│         │ ─→ Row 2                                │          │
│         │ ... (many round-trips)                  │          │
│         │ ─→ Row N                                │          │
└─────────┘                                          └──────────┘
Network round-trips: High

COPY Strategy:
┌─────────┐     COPY ... TO STDOUT                  ┌──────────┐
│  Source │ ═══════════════════════════════════════>│  Target  │
│    DB   │ ═══ Streaming buffer (bulk transfer) ═══│    DB    │
│         │                                          │          │
└─────────┘                                          └──────────┘
Network round-trips: Minimal (streaming)
```

**COPY minimizes network overhead** with bulk streaming.

---

## Troubleshooting

### FDW Setup Fails: "extension postgres_fdw does not exist"

**Cause**: postgres_fdw extension not available

**Solution**:
```sql
-- On target database
CREATE EXTENSION postgres_fdw;

-- If still fails, install PostgreSQL contrib package
-- Ubuntu/Debian:
sudo apt-get install postgresql-contrib

-- RHEL/CentOS:
sudo yum install postgresql-contrib
```

---

### FDW Connection Fails: "could not connect to server"

**Cause**: Network/firewall issue between databases

**Solution**:
```bash
# Test connection from target to source
psql -h old-db.example.com -U postgres -d myapp_production

# Check firewall rules
# Ensure target can reach source on port 5432

# Check pg_hba.conf on source database
# Add entry for target database IP:
# host    all    postgres    10.0.1.50/32    md5
```

---

### Migration Fails: "column does not exist"

**Cause**: Column mapping mismatch

**Solution**:
```bash
# Verify columns exist in source table
psql old_production -c "\d old_users"

# Verify columns exist in target table
psql new_production -c "\d users"

# Fix column_mapping.yaml
# Ensure source columns match source table
# Ensure target columns match target table
```

---

### Verification Fails: "row count mismatch"

**Cause**: Data changed during migration, or migration incomplete

**Solution**:
```bash
# Check for partial migration
psql new_production -c "SELECT COUNT(*) FROM users"
psql old_production -c "SELECT COUNT(*) FROM old_users"

# If mismatch:
# 1. Truncate target table
psql new_production -c "TRUNCATE users"

# 2. Re-migrate
confiture migrate schema-to-schema migrate-table \
    --target new_production \
    --source-table old_users \
    --target-table users \
    --mapping "full_name:display_name,email:email"
```

---

### COPY Strategy Slow

**Cause**: Network latency, disk I/O bottleneck

**Solution**:
```bash
# Check network latency
ping old-db.example.com

# Use same region/VPC
# Ensure both databases in same AWS region/Azure region

# Check disk I/O on target
iostat -x 5

# Ensure fast SSD storage
# Use provisioned IOPS (AWS RDS)
```

---

### Memory Issues During COPY

**Cause**: Extremely large rows (rare)

**Solution**:
```bash
# COPY uses streaming, should not cause memory issues
# If still problematic, use FDW instead
confiture migrate schema-to-schema migrate \
    --target new_production \
    --mapping column_mapping.yaml \
    --force-strategy fdw
```

---

## See Also

- [Migration Decision Tree](./migration-decision-tree.md) - When to use Medium 4
- [Medium 1: Build from DDL](./medium-1-build-from-ddl.md) - Creating new database
- [Medium 2: Incremental Migrations](./medium-2-incremental-migrations.md) - For simple changes
- [Example: Zero-Downtime Migration](../../examples/05-schema-to-schema-migration/) - Complete example
- [Performance Guide](../performance.md) - Detailed benchmarks
- [CLI Reference](../reference/cli.md) - All schema-to-schema commands

---

## Quick Reference

### Commands
```bash
# Setup
confiture migrate schema-to-schema setup --source old_prod --target new_prod

# Analyze
confiture migrate schema-to-schema analyze --target new_prod

# Migrate all
confiture migrate schema-to-schema migrate --target new_prod --mapping mapping.yaml

# Migrate single table
confiture migrate schema-to-schema migrate-table \
    --target new_prod \
    --source-table old_users \
    --target-table users \
    --mapping "full_name:display_name,email:email"

# Verify
confiture migrate schema-to-schema verify --target new_prod --tables users,posts

# Cleanup
confiture migrate schema-to-schema cleanup --target new_prod
```

### Strategies
| Strategy | Throughput | Best For |
|----------|-----------|----------|
| **FDW** | 500K rows/sec | <10M rows, complex SQL |
| **COPY** | 6M rows/sec ⚡ | ≥10M rows, bulk data |

**Auto-selection threshold**: 10,000,000 rows

### Performance
- **1M rows** (COPY): ~0.17 seconds
- **10M rows** (COPY): ~1.7 seconds
- **100M rows** (COPY): ~16.7 seconds
- **COPY is 10-20x faster** than FDW for large tables

### Best Practices
- ✅ Test migration on staging first
- ✅ Use read-only source credentials
- ✅ Migrate during low-traffic period
- ✅ Monitor throughout migration
- ✅ Keep old database warm (1-2 weeks)
- ✅ Use auto-strategy selection (optimal performance)
- ✅ Verify row counts before cutover
- ✅ Document column mappings

### Cutover Strategies
- **Blue-Green**: DNS/config change (simplest)
- **Read-Write Split**: Gradual migration (advanced)
- **Feature Flag**: Percentage rollout (gradual)

---

**Part of the Confiture documentation** 🍓

*Zero downtime, major refactoring*
