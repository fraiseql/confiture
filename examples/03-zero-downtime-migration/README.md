# Zero-Downtime Migration: Splitting user.full_name

**Example**: Production-grade zero-downtime migration using Confiture's Schema-to-Schema migration (Medium 4)

**Scenario**: Split `users.full_name` into `users.first_name` and `users.last_name` without service interruption

**Difficulty**: Advanced

**Time Required**: 2-4 hours (mostly verification and monitoring)

---

## Table of Contents

- [Overview](#overview)
- [Problem Statement](#problem-statement)
- [Migration Strategy](#migration-strategy)
- [Prerequisites](#prerequisites)
- [Architecture](#architecture)
- [Step-by-Step Guide](#step-by-step-guide)
- [Verification Procedures](#verification-procedures)
- [Rollback Plan](#rollback-plan)
- [Monitoring and Observability](#monitoring-and-observability)
- [Performance Considerations](#performance-considerations)
- [Common Issues and Solutions](#common-issues-and-solutions)
- [Production Checklist](#production-checklist)

---

## Overview

This example demonstrates a **real-world zero-downtime migration** using Confiture's Foreign Data Wrapper (FDW) approach. We migrate from a single `full_name` column to separate `first_name` and `last_name` columns while keeping the application running.

### Key Features

- **Zero downtime**: Application remains available throughout migration
- **Bidirectional sync**: Changes in either schema propagate to the other
- **Data transformation**: Smart splitting of full names
- **Verification**: Comprehensive data integrity checks
- **Safe rollback**: Can revert at any stage before final cutover

### What You'll Learn

1. Setting up Foreign Data Wrapper for schema-to-schema sync
2. Implementing bidirectional triggers for data consistency
3. Handling data transformations during migration
4. Verifying data integrity at scale
5. Performing safe cutover with minimal risk
6. Rolling back if issues are detected

---

## Problem Statement

### Current Schema (Old)

```sql
CREATE TABLE users (
    id BIGSERIAL PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    full_name TEXT NOT NULL,
    bio TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_users_full_name ON users(full_name);
```

### Desired Schema (New)

```sql
CREATE TABLE users (
    id BIGSERIAL PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    bio TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_users_first_name ON users(first_name);
CREATE INDEX idx_users_last_name ON users(last_name);
CREATE INDEX idx_users_full_name ON users(first_name, last_name);
```

### Business Requirements

1. **Zero Downtime**: Application must remain available 24/7
2. **Data Integrity**: No data loss during migration
3. **Performance**: Migration must not degrade application performance
4. **Reversibility**: Ability to roll back if issues arise
5. **Audit Trail**: Complete logging of migration progress

### Technical Constraints

- **Database Size**: 10M+ user records
- **Write Traffic**: 1000 writes/second during peak hours
- **Read Traffic**: 10,000 reads/second during peak hours
- **Deployment Window**: None - must be done during normal operation
- **Team Availability**: On-call team during cutover only

---

## Migration Strategy

### Why Schema-to-Schema (Medium 4)?

We use Confiture's **Medium 4: Schema-to-Schema Migration** because:

1. **Zero Downtime**: Old and new schemas coexist during migration
2. **Gradual Transition**: Can migrate data incrementally
3. **Bidirectional Sync**: Application can use either schema during transition
4. **Safe Rollback**: Easy to revert before final cutover
5. **Verification**: Extensive time to verify data integrity

### Migration Phases

```
Phase 1: Setup (30 minutes)
├── Create new schema
├── Setup Foreign Data Wrapper
├── Configure column mappings
└── Deploy bidirectional triggers

Phase 2: Initial Data Migration (1-2 hours)
├── Copy existing data with transformation
├── Verify data integrity
└── Monitor replication lag

Phase 3: Dual-Write Period (variable - hours to days)
├── Both schemas active
├── Continuous verification
├── Performance monitoring
└── Application testing

Phase 4: Cutover (15 minutes)
├── Switch application to new schema
├── Monitor for issues
├── Verify all operations
└── Final data sync

Phase 5: Cleanup (30 minutes)
├── Remove FDW infrastructure
├── Drop old schema
├── Update documentation
└── Archive migration artifacts
```

---

## Prerequisites

### Required Knowledge

- PostgreSQL administration
- Confiture CLI basics
- Foreign Data Wrappers (FDW)
- Database replication concepts
- SQL and bash scripting

### Required Tools

```bash
# PostgreSQL with FDW support
psql --version  # >= 14

# Confiture
confiture --version  # >= 1.0.0

# System utilities
jq --version
bc --version
```

### Required Access

- Superuser access to production database
- Ability to create new schemas
- Permission to install FDW extensions
- SSH access to database server

### Environment Setup

```bash
# Clone example
cd examples/03-zero-downtime-migration

# Set database connection
export DATABASE_URL="postgresql://user:pass@localhost:5432/myapp_production"
export NEW_DATABASE_URL="postgresql://user:pass@localhost:5432/myapp_production_new"

# Set migration parameters
export BATCH_SIZE=10000
export THROTTLE_MS=100
export DRY_RUN=true  # Set to false for actual migration
```

---

## Architecture

### High-Level Overview

```
┌─────────────────────────────────────────────────────────────┐
│                     Application Layer                        │
│  ┌──────────────┐              ┌──────────────┐             │
│  │ Old API      │              │ New API      │             │
│  │ (full_name)  │              │ (first_name, │             │
│  │              │              │  last_name)  │             │
│  └──────┬───────┘              └──────┬───────┘             │
│         │                             │                      │
└─────────┼─────────────────────────────┼──────────────────────┘
          │                             │
          ▼                             ▼
┌─────────────────────────────────────────────────────────────┐
│                   PostgreSQL Database                        │
│                                                              │
│  ┌──────────────────────┐    ┌──────────────────────┐      │
│  │  Schema: public      │◄───┤  Schema: new_users   │      │
│  │  (Old Schema)        │ FDW│  (New Schema)        │      │
│  │                      │───►│                      │      │
│  │  Table: users        │    │  Table: users        │      │
│  │  - id                │    │  - id                │      │
│  │  - email             │    │  - email             │      │
│  │  - full_name         │    │  - first_name        │      │
│  │  - bio               │    │  - last_name         │      │
│  │  - timestamps        │    │  - bio               │      │
│  │                      │    │  - timestamps        │      │
│  └──────────────────────┘    └──────────────────────┘      │
│           │                            │                     │
│           ▼                            ▼                     │
│  ┌─────────────────┐         ┌─────────────────┐           │
│  │ Trigger: sync   │         │ Trigger: sync   │           │
│  │ to new_users    │         │ to public.users │           │
│  └─────────────────┘         └─────────────────┘           │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### Data Flow

**Phase 1: Initial State**
```
Application → public.users (full_name)
```

**Phase 2: Dual Write (FDW Active)**
```
Application → public.users (full_name) → Trigger → new_users.users (first_name, last_name)
Application → new_users.users (first_name, last_name) → Trigger → public.users (full_name)
```

**Phase 3: Final State**
```
Application → new_users.users (first_name, last_name)
```

### Column Mapping

```yaml
# migration_config.yaml
transformations:
  # Old → New (split full_name)
  old_to_new:
    full_name:
      target_columns: [first_name, last_name]
      function: split_full_name

  # New → Old (concatenate names)
  new_to_old:
    first_name:
      target_column: full_name
      function: concat_names
      depends_on: [last_name]
```

---

## Step-by-Step Guide

### Step 0: Pre-Migration Verification

**Verify current state**:

```bash
# Check database size
psql $DATABASE_URL -c "
SELECT
    schemaname,
    tablename,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size,
    n_live_tup as row_count
FROM pg_stat_user_tables
WHERE tablename = 'users';
"

# Check for blocking locks
psql $DATABASE_URL -c "
SELECT pid, usename, application_name, state, query
FROM pg_stat_activity
WHERE state = 'active' AND pid != pg_backend_pid();
"

# Verify index health
psql $DATABASE_URL -c "
SELECT schemaname, tablename, indexname, idx_scan, idx_tup_read, idx_tup_fetch
FROM pg_stat_user_indexes
WHERE tablename = 'users';
"
```

**Take backup**:

```bash
# Full backup before migration
pg_dump $DATABASE_URL -Fc -f backup_before_migration_$(date +%Y%m%d_%H%M%S).dump

# Verify backup
pg_restore --list backup_before_migration_*.dump | head -20
```

### Step 1: Setup New Schema (30 minutes)

**Create new schema structure**:

```bash
cd /home/lionel/code/confiture/examples/03-zero-downtime-migration

# Initialize Confiture for new schema
confiture init --schema-dir db/new_schema

# Review new schema files
cat db/new_schema/01_users_table.sql
```

**Build new schema in separate namespace**:

```bash
# Create new schema
psql $DATABASE_URL -c "CREATE SCHEMA IF NOT EXISTS new_users;"

# Build tables in new schema
psql $DATABASE_URL << 'EOF'
SET search_path TO new_users;

CREATE TABLE users (
    id BIGSERIAL PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    bio TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_users_first_name ON users(first_name);
CREATE INDEX idx_users_last_name ON users(last_name);
CREATE INDEX idx_users_full_name ON users(first_name, last_name);
EOF
```

**Verify new schema**:

```bash
psql $DATABASE_URL -c "
SELECT table_name, column_name, data_type
FROM information_schema.columns
WHERE table_schema = 'new_users' AND table_name = 'users'
ORDER BY ordinal_position;
"
```

### Step 2: Setup Foreign Data Wrapper (15 minutes)

**Install FDW extension**:

```bash
psql $DATABASE_URL -c "CREATE EXTENSION IF NOT EXISTS postgres_fdw;"
```

**Create FDW server**:

```bash
./scripts/1_setup_fdw.sh
```

This script:
1. Creates FDW server pointing to same database
2. Creates user mapping
3. Imports foreign tables
4. Sets up transformation functions

**Verify FDW setup**:

```bash
# Check foreign server
psql $DATABASE_URL -c "\des+"

# Check foreign tables
psql $DATABASE_URL -c "\det+ new_users.*"

# Test foreign table access
psql $DATABASE_URL -c "SELECT COUNT(*) FROM new_users.users;"
```

### Step 3: Create Transformation Functions (15 minutes)

**Deploy name splitting function**:

```sql
-- Function to split full_name into first_name and last_name
CREATE OR REPLACE FUNCTION split_full_name(full_name TEXT, OUT first_name TEXT, OUT last_name TEXT)
RETURNS RECORD AS $$
BEGIN
    -- Handle NULL
    IF full_name IS NULL THEN
        first_name := '';
        last_name := '';
        RETURN;
    END IF;

    -- Trim whitespace
    full_name := TRIM(full_name);

    -- Find last space (for last name)
    IF POSITION(' ' IN full_name) > 0 THEN
        first_name := SUBSTRING(full_name FROM 1 FOR POSITION(' ' IN full_name) - 1);
        last_name := SUBSTRING(full_name FROM POSITION(' ' IN full_name) + 1);
    ELSE
        -- No space - treat entire string as first name
        first_name := full_name;
        last_name := '';
    END IF;

    -- Handle multiple spaces (middle names go with first name)
    first_name := TRIM(first_name);
    last_name := TRIM(last_name);
END;
$$ LANGUAGE plpgsql IMMUTABLE;
```

**Deploy name concatenation function**:

```sql
-- Function to concatenate first_name and last_name
CREATE OR REPLACE FUNCTION concat_names(first_name TEXT, last_name TEXT)
RETURNS TEXT AS $$
BEGIN
    RETURN TRIM(CONCAT(COALESCE(first_name, ''), ' ', COALESCE(last_name, '')));
END;
$$ LANGUAGE plpgsql IMMUTABLE;
```

**Test transformation functions**:

```bash
psql $DATABASE_URL << 'EOF'
-- Test split_full_name
SELECT
    full_name,
    (split_full_name(full_name)).first_name,
    (split_full_name(full_name)).last_name
FROM (VALUES
    ('John Doe'),
    ('Mary Jane Watson'),
    ('Madonna'),
    ('  Spaced  Out  '),
    (NULL)
) AS t(full_name);

-- Test concat_names
SELECT
    first_name,
    last_name,
    concat_names(first_name, last_name) as full_name
FROM (VALUES
    ('John', 'Doe'),
    ('Mary', 'Watson'),
    ('Madonna', NULL),
    (NULL, 'Prince'),
    (NULL, NULL)
) AS t(first_name, last_name);
EOF
```

### Step 4: Setup Bidirectional Triggers (15 minutes)

**Create trigger: Old → New**:

```sql
-- Trigger function: Sync from public.users to new_users.users
CREATE OR REPLACE FUNCTION sync_to_new_users()
RETURNS TRIGGER AS $$
DECLARE
    name_parts RECORD;
BEGIN
    -- Split full_name
    name_parts := split_full_name(NEW.full_name);

    -- INSERT or UPDATE
    IF TG_OP = 'INSERT' THEN
        INSERT INTO new_users.users (id, email, first_name, last_name, bio, created_at, updated_at)
        VALUES (NEW.id, NEW.email, name_parts.first_name, name_parts.last_name, NEW.bio, NEW.created_at, NEW.updated_at)
        ON CONFLICT (id) DO UPDATE SET
            email = EXCLUDED.email,
            first_name = EXCLUDED.first_name,
            last_name = EXCLUDED.last_name,
            bio = EXCLUDED.bio,
            updated_at = EXCLUDED.updated_at;
    ELSIF TG_OP = 'UPDATE' THEN
        UPDATE new_users.users SET
            email = NEW.email,
            first_name = name_parts.first_name,
            last_name = name_parts.last_name,
            bio = NEW.bio,
            updated_at = NEW.updated_at
        WHERE id = NEW.id;
    ELSIF TG_OP = 'DELETE' THEN
        DELETE FROM new_users.users WHERE id = OLD.id;
        RETURN OLD;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create trigger
CREATE TRIGGER trigger_sync_to_new_users
    AFTER INSERT OR UPDATE OR DELETE ON public.users
    FOR EACH ROW
    EXECUTE FUNCTION sync_to_new_users();
```

**Create trigger: New → Old**:

```sql
-- Trigger function: Sync from new_users.users to public.users
CREATE OR REPLACE FUNCTION sync_to_old_users()
RETURNS TRIGGER AS $$
DECLARE
    full_name_value TEXT;
BEGIN
    -- Concatenate names
    full_name_value := concat_names(NEW.first_name, NEW.last_name);

    -- INSERT or UPDATE
    IF TG_OP = 'INSERT' THEN
        INSERT INTO public.users (id, email, full_name, bio, created_at, updated_at)
        VALUES (NEW.id, NEW.email, full_name_value, NEW.bio, NEW.created_at, NEW.updated_at)
        ON CONFLICT (id) DO UPDATE SET
            email = EXCLUDED.email,
            full_name = EXCLUDED.full_name,
            bio = EXCLUDED.bio,
            updated_at = EXCLUDED.updated_at;
    ELSIF TG_OP = 'UPDATE' THEN
        UPDATE public.users SET
            email = NEW.email,
            full_name = full_name_value,
            bio = NEW.bio,
            updated_at = NEW.updated_at
        WHERE id = NEW.id;
    ELSIF TG_OP = 'DELETE' THEN
        DELETE FROM public.users WHERE id = OLD.id;
        RETURN OLD;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create trigger
CREATE TRIGGER trigger_sync_to_old_users
    AFTER INSERT OR UPDATE OR DELETE ON new_users.users
    FOR EACH ROW
    EXECUTE FUNCTION sync_to_old_users();
```

**Test triggers**:

```bash
psql $DATABASE_URL << 'EOF'
-- Test: Insert into old schema
INSERT INTO public.users (email, full_name, bio)
VALUES ('test@example.com', 'Test User', 'Test bio')
RETURNING id;

-- Verify sync to new schema
SELECT id, email, first_name, last_name, bio
FROM new_users.users
WHERE email = 'test@example.com';

-- Test: Update in new schema
UPDATE new_users.users
SET first_name = 'Updated', last_name = 'Name'
WHERE email = 'test@example.com';

-- Verify sync to old schema
SELECT id, email, full_name, bio
FROM public.users
WHERE email = 'test@example.com';

-- Cleanup
DELETE FROM public.users WHERE email = 'test@example.com';
EOF
```

### Step 5: Initial Data Migration (1-2 hours)

**Run initial data copy**:

```bash
./scripts/2_migrate_data.sh
```

This script:
1. Copies data in batches (default: 10,000 rows)
2. Transforms `full_name` → `first_name`, `last_name`
3. Throttles to avoid overwhelming database
4. Provides progress updates
5. Verifies checksums

**Monitor progress**:

```bash
# In separate terminal
watch -n 5 'psql $DATABASE_URL -c "
SELECT
    (SELECT COUNT(*) FROM public.users) as old_count,
    (SELECT COUNT(*) FROM new_users.users) as new_count,
    (SELECT COUNT(*) FROM new_users.users) * 100.0 / NULLIF((SELECT COUNT(*) FROM public.users), 0) as percent_complete;
"'
```

**Expected output**:

```
Migrating users: public → new_users
Total rows: 10,234,567
Batch size: 10,000
Throttle: 100ms between batches

[=====>                    ] 25% (2,558,641 / 10,234,567) - ETA: 45 minutes
```

### Step 6: Verification (30 minutes)

**Run comprehensive verification**:

```bash
./scripts/3_verify.sh
```

**Verification checks**:

1. **Row count match**:
```sql
SELECT
    (SELECT COUNT(*) FROM public.users) as old_count,
    (SELECT COUNT(*) FROM new_users.users) as new_count,
    (SELECT COUNT(*) FROM public.users) = (SELECT COUNT(*) FROM new_users.users) as match;
```

2. **Data integrity check**:
```sql
-- Sample 1000 random rows for transformation accuracy
WITH sample AS (
    SELECT
        o.id,
        o.full_name,
        n.first_name,
        n.last_name,
        concat_names(n.first_name, n.last_name) as reconstructed
    FROM public.users o
    JOIN new_users.users n ON o.id = n.id
    ORDER BY RANDOM()
    LIMIT 1000
)
SELECT
    COUNT(*) as total_sampled,
    COUNT(*) FILTER (WHERE full_name = reconstructed) as exact_matches,
    COUNT(*) FILTER (WHERE TRIM(full_name) = TRIM(reconstructed)) as matches_trimmed,
    100.0 * COUNT(*) FILTER (WHERE full_name = reconstructed) / COUNT(*) as match_rate
FROM sample;
```

3. **Performance check**:
```sql
-- Verify indexes are used
EXPLAIN ANALYZE
SELECT * FROM new_users.users WHERE email = 'test@example.com';

EXPLAIN ANALYZE
SELECT * FROM new_users.users WHERE first_name = 'John' AND last_name = 'Doe';
```

4. **Trigger verification**:
```bash
# Insert 1000 test rows in old schema
# Verify they appear in new schema
# Measure replication lag
```

### Step 7: Dual-Write Period (Hours to Days)

**Enable application dual-write**:

In your application code, write to both schemas:

```python
# Example: Python application code
def create_user(email: str, first_name: str, last_name: str, bio: str):
    # Write to old schema
    old_conn.execute(
        "INSERT INTO users (email, full_name, bio) VALUES ($1, $2, $3)",
        email,
        f"{first_name} {last_name}",
        bio
    )

    # Write to new schema (via trigger or explicit)
    # Triggers handle this automatically in our case

# Read from old schema during transition
def get_user(user_id: int):
    return old_conn.fetchone("SELECT * FROM users WHERE id = $1", user_id)
```

**Monitor during dual-write period**:

```bash
# Run every 15 minutes
./scripts/3_verify.sh

# Check replication lag
psql $DATABASE_URL -c "
SELECT
    NOW() - MAX(updated_at) as max_lag
FROM (
    SELECT updated_at FROM public.users
    UNION ALL
    SELECT updated_at FROM new_users.users
) t;
"
```

**Typical dual-write period**: 24-72 hours

### Step 8: Cutover (15 minutes)

**Prerequisites**:
- [ ] All verification checks pass
- [ ] Replication lag < 1 second
- [ ] On-call team available
- [ ] Rollback plan tested
- [ ] Database backup completed

**Execute cutover**:

```bash
./scripts/4_cutover.sh
```

**Cutover steps**:

1. **Enable maintenance mode** (optional):
```bash
# In application
MAINTENANCE_MODE=true
```

2. **Final sync**:
```sql
-- Wait for final sync
SELECT pg_sleep(2);

-- Verify counts
SELECT
    (SELECT COUNT(*) FROM public.users) as old_count,
    (SELECT COUNT(*) FROM new_users.users) as new_count;
```

3. **Switch application connection**:
```bash
# Update application config
export DATABASE_SCHEMA="new_users"
export DATABASE_TABLE_PREFIX=""

# Restart application
kubectl rollout restart deployment/myapp
# OR: systemctl restart myapp
```

4. **Verify application health**:
```bash
# Check application logs
kubectl logs -f deployment/myapp | grep -i error

# Test API endpoints
curl https://api.example.com/health
curl https://api.example.com/users/me
```

5. **Disable old schema writes**:
```sql
-- Drop old → new trigger (keep new → old for safety)
DROP TRIGGER IF EXISTS trigger_sync_to_new_users ON public.users;
```

6. **Monitor for 30 minutes**:
```bash
# Watch error rates, latency, database load
# Verify all CRUD operations work
```

### Step 9: Cleanup (30 minutes)

**After 24-48 hours of stable operation**:

```bash
# 1. Drop reverse sync trigger
psql $DATABASE_URL -c "DROP TRIGGER IF EXISTS trigger_sync_to_old_users ON new_users.users;"

# 2. Rename new_users schema to public (or keep separate)
psql $DATABASE_URL << 'EOF'
-- Option A: Rename schemas
ALTER SCHEMA public RENAME TO old_users_deprecated;
ALTER SCHEMA new_users RENAME TO public;
EOF

# 3. Drop old schema (AFTER VERIFICATION)
psql $DATABASE_URL -c "DROP SCHEMA old_users_deprecated CASCADE;"

# 4. Vacuum and analyze
psql $DATABASE_URL -c "VACUUM ANALYZE public.users;"
```

---

## Verification Procedures

### Automated Verification Script

The `scripts/3_verify.sh` script performs these checks:

```bash
#!/bin/bash
# Comprehensive verification

echo "Running verification suite..."

# 1. Row count verification
echo "1. Checking row counts..."
psql $DATABASE_URL << 'EOF'
SELECT
    'Row Count Check' as test,
    (SELECT COUNT(*) FROM public.users) as old_count,
    (SELECT COUNT(*) FROM new_users.users) as new_count,
    CASE
        WHEN (SELECT COUNT(*) FROM public.users) = (SELECT COUNT(*) FROM new_users.users)
        THEN 'PASS'
        ELSE 'FAIL'
    END as status;
EOF

# 2. Data integrity verification
echo "2. Checking data integrity..."
psql $DATABASE_URL << 'EOF'
WITH sample AS (
    SELECT
        o.id,
        o.full_name,
        n.first_name,
        n.last_name,
        concat_names(n.first_name, n.last_name) as reconstructed
    FROM public.users o
    JOIN new_users.users n ON o.id = n.id
    ORDER BY RANDOM()
    LIMIT 10000
)
SELECT
    'Data Integrity Check' as test,
    COUNT(*) as sample_size,
    COUNT(*) FILTER (WHERE TRIM(full_name) = TRIM(reconstructed)) as matches,
    100.0 * COUNT(*) FILTER (WHERE TRIM(full_name) = TRIM(reconstructed)) / COUNT(*) as match_rate,
    CASE
        WHEN 100.0 * COUNT(*) FILTER (WHERE TRIM(full_name) = TRIM(reconstructed)) / COUNT(*) > 99.9
        THEN 'PASS'
        ELSE 'FAIL'
    END as status
FROM sample;
EOF

# 3. Trigger verification
echo "3. Testing triggers..."
# ... (see full script)

# 4. Performance verification
echo "4. Checking query performance..."
# ... (see full script)

echo "Verification complete."
```

### Manual Verification Checklist

- [ ] Row counts match between old and new schemas
- [ ] Sample data transformations are correct
- [ ] All indexes exist and are used by query planner
- [ ] Triggers fire correctly for INSERT/UPDATE/DELETE
- [ ] No orphaned records (data exists in one schema but not the other)
- [ ] Application can read from new schema
- [ ] Application can write to new schema
- [ ] No performance degradation
- [ ] Replication lag < 1 second

---

## Rollback Plan

### Rollback Scenarios

**Scenario 1: Issues during initial migration**
- **Action**: Stop migration script, drop new schema, start over
- **Data Loss**: None (old schema untouched)
- **Downtime**: None

**Scenario 2: Issues during dual-write period**
- **Action**: Keep using old schema, investigate issues, restart migration
- **Data Loss**: None (both schemas active)
- **Downtime**: None

**Scenario 3: Issues immediately after cutover**
- **Action**: Revert application to old schema, investigate
- **Data Loss**: Potential (writes to new schema may not sync back)
- **Downtime**: Minimal (seconds)

**Scenario 4: Issues hours after cutover**
- **Action**: Complex - may need manual data reconciliation
- **Data Loss**: Possible
- **Downtime**: Possible

### Rollback Procedure

**Quick rollback (< 1 hour after cutover)**:

```bash
./scripts/rollback.sh
```

**Manual rollback steps**:

```bash
# 1. Point application back to old schema
export DATABASE_SCHEMA="public"
kubectl rollout restart deployment/myapp

# 2. Re-enable bidirectional triggers (if dropped)
psql $DATABASE_URL < db/triggers/sync_to_new_users.sql
psql $DATABASE_URL < db/triggers/sync_to_old_users.sql

# 3. Sync any new data back to old schema
psql $DATABASE_URL << 'EOF'
INSERT INTO public.users (id, email, full_name, bio, created_at, updated_at)
SELECT
    id,
    email,
    concat_names(first_name, last_name),
    bio,
    created_at,
    updated_at
FROM new_users.users
WHERE id NOT IN (SELECT id FROM public.users)
ON CONFLICT (id) DO UPDATE SET
    email = EXCLUDED.email,
    full_name = EXCLUDED.full_name,
    bio = EXCLUDED.bio,
    updated_at = EXCLUDED.updated_at;
EOF

# 4. Verify old schema is current
./scripts/3_verify.sh

# 5. Investigate root cause
# ...
```

---

## Monitoring and Observability

### Key Metrics to Monitor

**Database Metrics**:
- Replication lag between schemas
- Query latency (p50, p95, p99)
- Connection pool usage
- Lock contention
- Disk I/O

**Application Metrics**:
- API latency
- Error rates (5xx errors)
- Success rates per endpoint
- User-facing errors

**Migration Metrics**:
- Rows migrated
- Migration speed (rows/second)
- Data transformation accuracy
- Verification failures

### Monitoring Queries

```sql
-- Replication lag
SELECT
    'Replication Lag' as metric,
    EXTRACT(EPOCH FROM (NOW() - MAX(updated_at))) as seconds
FROM (
    SELECT MAX(updated_at) as updated_at FROM public.users
    UNION ALL
    SELECT MAX(updated_at) as updated_at FROM new_users.users
) t;

-- Active connections
SELECT
    datname,
    count(*) as connections,
    count(*) FILTER (WHERE state = 'active') as active,
    count(*) FILTER (WHERE state = 'idle') as idle
FROM pg_stat_activity
WHERE datname = current_database()
GROUP BY datname;

-- Lock contention
SELECT
    locktype,
    relation::regclass,
    mode,
    transactionid,
    pid,
    granted
FROM pg_locks
WHERE NOT granted
ORDER BY relation;

-- Slow queries
SELECT
    pid,
    now() - pg_stat_activity.query_start AS duration,
    query,
    state
FROM pg_stat_activity
WHERE (now() - pg_stat_activity.query_start) > interval '5 seconds'
AND state = 'active'
ORDER BY duration DESC;
```

---

## Performance Considerations

### Expected Performance Impact

**During Migration**:
- CPU: +10-20% (transformation functions)
- Memory: +5-10% (trigger context)
- Disk I/O: +30-50% (writing to two schemas)
- Query latency: +5-10ms (trigger overhead)

**After Cutover**:
- Performance should match or exceed old schema
- Queries on `first_name`, `last_name` may be faster (better indexes)
- Disk usage: Same (old schema will be dropped)

### Optimization Tips

**Batch size tuning**:
```bash
# Adjust based on your database load
export BATCH_SIZE=5000   # Smaller = less impact, slower migration
export BATCH_SIZE=50000  # Larger = more impact, faster migration
```

**Throttling**:
```bash
# Add delays between batches
export THROTTLE_MS=200  # 200ms delay between batches
```

**Parallel migration**:
```bash
# Migrate different ID ranges in parallel (advanced)
./scripts/2_migrate_data.sh --min-id 0 --max-id 5000000 &
./scripts/2_migrate_data.sh --min-id 5000001 --max-id 10000000 &
```

**Index creation**:
```sql
-- Create indexes CONCURRENTLY to avoid locks
CREATE INDEX CONCURRENTLY idx_users_first_name ON new_users.users(first_name);
CREATE INDEX CONCURRENTLY idx_users_last_name ON new_users.users(last_name);
```

---

## Common Issues and Solutions

### Issue 1: Triggers Causing Infinite Loop

**Symptom**: Triggers fire recursively, database becomes unresponsive

**Cause**: Trigger on schema A updates schema B, which triggers update back to schema A

**Solution**: Use trigger guards

```sql
CREATE OR REPLACE FUNCTION sync_to_new_users()
RETURNS TRIGGER AS $$
BEGIN
    -- Guard: Don't sync if triggered by another sync
    IF current_setting('app.syncing', true) = 'true' THEN
        RETURN NEW;
    END IF;

    -- Set guard
    PERFORM set_config('app.syncing', 'true', true);

    -- ... sync logic ...

    -- Clear guard
    PERFORM set_config('app.syncing', 'false', true);

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
```

### Issue 2: Name Splitting Inaccuracies

**Symptom**: Names like "John van der Berg" split incorrectly

**Solution**: Improve splitting logic

```sql
CREATE OR REPLACE FUNCTION split_full_name(full_name TEXT, OUT first_name TEXT, OUT last_name TEXT)
RETURNS RECORD AS $$
BEGIN
    -- Handle prefixes: van, von, de, der, etc.
    -- Find LAST space for last name (keeps middle names with first)
    IF full_name ~ ' ' THEN
        first_name := SUBSTRING(full_name FROM '^(.+) [^ ]+$');
        last_name := SUBSTRING(full_name FROM '[^ ]+$');
    ELSE
        first_name := full_name;
        last_name := '';
    END IF;

    -- Fallback
    IF first_name IS NULL THEN
        first_name := full_name;
        last_name := '';
    END IF;
END;
$$ LANGUAGE plpgsql IMMUTABLE;
```

### Issue 3: Migration Too Slow

**Symptom**: Initial migration taking > 4 hours

**Solutions**:
1. Increase batch size
2. Disable triggers temporarily during initial load
3. Use `COPY` instead of `INSERT` for initial load
4. Parallelize migration

### Issue 4: High Replication Lag

**Symptom**: Replication lag > 10 seconds during high traffic

**Solutions**:
1. Reduce trigger complexity
2. Add connection pooling
3. Scale up database resources
4. Temporarily reduce application write traffic

---

## Production Checklist

### Pre-Migration

- [ ] Database backup completed
- [ ] Verification scripts tested
- [ ] Rollback procedure documented and tested
- [ ] On-call team briefed
- [ ] Monitoring dashboards configured
- [ ] Stakeholders notified of maintenance window
- [ ] Runbook reviewed by team
- [ ] Emergency contacts updated

### During Migration

- [ ] Initial setup completed successfully
- [ ] FDW configured and tested
- [ ] Transformation functions verified
- [ ] Triggers deployed and tested
- [ ] Initial data migration completed
- [ ] Verification checks pass (>99.9% accuracy)
- [ ] Performance impact acceptable
- [ ] Dual-write period stable

### Pre-Cutover

- [ ] All verification checks pass
- [ ] Replication lag < 1 second
- [ ] Application tested against new schema
- [ ] Rollback plan ready
- [ ] Team on standby

### Post-Cutover

- [ ] Application using new schema
- [ ] No errors in application logs
- [ ] API endpoints responding normally
- [ ] Database performance normal
- [ ] User-facing features working
- [ ] Monitoring shows healthy metrics

### Post-Migration (24-48 hours later)

- [ ] Old schema triggers dropped
- [ ] FDW infrastructure removed
- [ ] Old schema backed up
- [ ] Old schema dropped
- [ ] Documentation updated
- [ ] Post-mortem completed
- [ ] Lessons learned documented

---

## Conclusion

This zero-downtime migration example demonstrates Confiture's Schema-to-Schema migration capability (Medium 4). Key takeaways:

1. **Preparation is critical**: Thorough verification and testing prevent issues
2. **Bidirectional sync enables safety**: Ability to roll back at any point
3. **Monitoring is essential**: Watch metrics closely during cutover
4. **Incremental approach works**: Dual-write period gives confidence
5. **Testing catches issues**: Test transformations thoroughly before production

### Next Steps

- Review `SCENARIO.md` for detailed requirements analysis
- Examine SQL files in `db/old_schema/` and `db/new_schema/`
- Study `migration_config.yaml` for column mapping details
- Run scripts in `scripts/` directory to understand automation

### Related Examples

- **Example 01**: Basic migration workflow
- **Example 02**: FraiseQL integration
- **Example 04**: Production sync with PII anonymization

---

**Migration Strategy**: Schema-to-Schema (Medium 4)
**Estimated Duration**: 2-4 hours
**Risk Level**: Medium (with proper verification and rollback)
**Downtime**: Zero

**Last Updated**: October 12, 2025
