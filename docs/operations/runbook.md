# Confiture Operations Runbook

This runbook provides day-to-day operational procedures for managing PostgreSQL migrations with Confiture.

## Table of Contents

- [Daily Operations](#daily-operations)
- [Common Operations](#common-operations)
- [Monitoring & Alerts](#monitoring--alerts)
- [Scheduled Tasks](#scheduled-tasks)
- [Emergency Procedures](#emergency-procedures)

---

## Daily Operations

### Check Migration Status

```bash
confiture migrate status
```

**Expected Output:**
```
Migration Status
================
Applied: 15
Pending: 0
Last Applied: 015_add_user_preferences (2024-01-15 10:30:00)

All migrations applied ✓
```

**Action if pending migrations:**
1. Review pending migrations in `db/migrations/`
2. Schedule migration window
3. Apply with appropriate safety checks

### Verify Database Health

```bash
confiture health check
```

**Checks performed:**
- Database connectivity
- Migration lock status
- Schema drift detection
- Replication lag (if configured)

**Expected Output:**
```
Health Check Results
====================
✓ Database connection: OK
✓ Migration lock: Available
✓ Schema drift: None detected
✓ Replication lag: 0ms

Overall: HEALTHY
```

### Verify Checksums

```bash
confiture migrate verify-checksums
```

**Expected Output:**
```
Checksum Verification
=====================
Verified: 15 migrations
Mismatches: 0

All checksums valid ✓
```

---

## Common Operations

### Applying Migrations

#### Development Environment

```bash
# Apply all pending migrations
confiture migrate up
```

#### Staging Environment

```bash
# Dry-run first
confiture migrate up --dry-run

# Apply with checksum verification
confiture migrate up --verify-checksums --lock-timeout 30000
```

#### Production Environment

```bash
# Step 1: Dry-run to see changes
confiture migrate up --dry-run --verify-checksums

# Step 2: Review output carefully

# Step 3: Apply with safety checks
confiture migrate up \
  --verify-checksums \
  --lock-timeout 60000 \
  --statement-timeout 300000
```

### Rolling Back Migrations

#### Single Migration Rollback

```bash
# Rollback the last migration
confiture migrate down --steps 1
```

#### Rollback to Specific Version

```bash
# Rollback to version 010
confiture migrate down --target 010_add_indexes
```

#### Emergency Rollback (Skip Checksums)

```bash
# Only use when checksums are corrupted
confiture migrate down --steps 1 --skip-checksums
```

### Schema Drift Detection

```bash
# Check for unauthorized schema changes
confiture migrate drift-detect
```

**If drift detected:**

1. **Investigate the change:**
   ```sql
   -- Find recent DDL changes
   SELECT * FROM pg_stat_user_tables
   WHERE schemaname = 'public'
   ORDER BY last_ddl_time DESC;
   ```

2. **Decision tree:**
   - If change should be kept → Create migration to codify it
   - If change was unauthorized → Rollback the change manually

3. **Create migration for legitimate changes:**
   ```bash
   confiture migrate create codify_manual_change
   # Edit the migration to include the change
   ```

### Linting Migrations

```bash
# Lint all migrations
confiture lint db/migrations/

# Lint specific migration
confiture lint db/migrations/015_add_user_preferences.py
```

**Common lint warnings:**
- Missing `down()` function
- Non-transactional DDL without explicit flag
- Large table operations without batching

---

## Monitoring & Alerts

### Alert: Migration Lock Timeout

**Symptoms:**
```
LockError: Could not acquire migration lock within 30000ms
```

**Cause:** Another migration is running or a lock wasn't released.

**Resolution:**

1. **Check for running migrations:**
   ```sql
   SELECT pid, query, state, query_start
   FROM pg_stat_activity
   WHERE query LIKE '%confiture%'
     AND state != 'idle';
   ```

2. **Check advisory locks:**
   ```sql
   SELECT l.pid, a.usename, a.query, l.granted
   FROM pg_locks l
   JOIN pg_stat_activity a ON l.pid = a.pid
   WHERE l.locktype = 'advisory'
     AND l.classid = 12345;  -- Confiture lock ID
   ```

3. **If stale lock (process crashed):**
   ```sql
   -- Verify the PID is actually dead
   SELECT pg_terminate_backend(<stale_pid>);

   -- Or force unlock (use with caution)
   SELECT pg_advisory_unlock(12345);
   ```

4. **Retry migration:**
   ```bash
   confiture migrate up --lock-timeout 60000
   ```

### Alert: Checksum Mismatch

**Symptoms:**
```
ChecksumError: Migration 003_add_users checksum mismatch
  Expected: abc123def456
  Actual:   xyz789ghi012
```

**Cause:** Migration file was modified after application.

**Resolution:**

1. **Compare current vs applied:**
   ```bash
   # View stored checksum
   psql -c "SELECT checksum FROM confiture_migrations WHERE version = '003_add_users'"

   # Compute current checksum
   confiture migrate checksum db/migrations/003_add_users.py
   ```

2. **If modification was intentional:**
   - Create a new migration with the changes
   - Or update the stored checksum (audit trail):
     ```bash
     confiture migrate update-checksum 003_add_users
     ```

3. **If modification was accidental:**
   ```bash
   # Restore from version control
   git checkout db/migrations/003_add_users.py
   ```

### Alert: Migration Failed

**Symptoms:**
```
MigrationError: Migration 010_add_indexes failed: relation "users" does not exist
```

**Resolution:**

1. **Check logs for full error:**
   ```bash
   confiture migrate status --verbose
   ```

2. **Check schema state:**
   ```sql
   -- See what tables exist
   SELECT tablename FROM pg_tables WHERE schemaname = 'public';

   -- Check migration history
   SELECT * FROM confiture_migrations ORDER BY applied_at DESC LIMIT 5;
   ```

3. **If partially applied (non-transactional migration):**
   - Assess what was created/modified
   - Manually clean up partial changes
   - Fix migration and retry

4. **If transactional migration:**
   - Should have rolled back automatically
   - Fix the migration file
   - Retry: `confiture migrate up`

### Alert: Connection Pool Exhausted

**Symptoms:**
```
PoolExhaustedError: No connections available (max: 10)
```

**Resolution:**

1. **Check current connections:**
   ```sql
   SELECT count(*) FROM pg_stat_activity WHERE usename = 'confiture';
   ```

2. **Check for stuck connections:**
   ```sql
   SELECT pid, state, query, query_start
   FROM pg_stat_activity
   WHERE usename = 'confiture'
     AND state != 'idle'
   ORDER BY query_start;
   ```

3. **Increase pool size if legitimate:**
   ```yaml
   # confiture.yaml
   connection:
     pool:
       max_size: 20
   ```

4. **Terminate stuck connections:**
   ```sql
   SELECT pg_terminate_backend(pid)
   FROM pg_stat_activity
   WHERE usename = 'confiture'
     AND state = 'idle in transaction'
     AND query_start < now() - interval '1 hour';
   ```

---

## Scheduled Tasks

### Weekly: Drift Check

```cron
# Every Sunday at midnight
0 0 * * 0 confiture migrate drift-detect --format json >> /var/log/confiture/drift.log 2>&1
```

### Monthly: Full Checksum Audit

```cron
# First of every month at 1 AM
0 1 1 * * confiture migrate verify-checksums --full >> /var/log/confiture/checksum-audit.log 2>&1
```

### Daily: Health Check (for Monitoring)

```cron
# Every hour
0 * * * * confiture health check --format json | curl -X POST -d @- https://monitoring.example.com/metrics/confiture
```

---

## Emergency Procedures

### Procedure: Emergency Rollback

**When to use:** Production migration caused application errors.

**Steps:**

1. **Assess impact:**
   - Check application error rates
   - Identify affected tables

2. **Initiate rollback:**
   ```bash
   # Rollback last migration
   confiture migrate down --steps 1 --lock-timeout 60000
   ```

3. **If rollback script fails:**
   ```bash
   # Check if manual intervention needed
   confiture migrate status --verbose

   # Execute rollback SQL manually if needed
   psql -f emergency_rollback.sql
   ```

4. **Verify rollback:**
   ```bash
   confiture migrate status
   confiture migrate drift-detect
   ```

5. **Post-incident:**
   - Document the incident
   - Fix the migration
   - Test in staging before retrying

### Procedure: Force Unlock

**When to use:** Migration process crashed, lock not released.

**Prerequisites:**
- Confirm no migration is actually running
- Have DBA approval

**Steps:**

1. **Verify no active migrations:**
   ```sql
   SELECT pid, query, state
   FROM pg_stat_activity
   WHERE query LIKE '%confiture%'
     AND state = 'active';
   ```

2. **Check lock holder:**
   ```sql
   SELECT l.pid, a.application_name, a.query_start
   FROM pg_locks l
   JOIN pg_stat_activity a ON l.pid = a.pid
   WHERE l.locktype = 'advisory'
     AND l.classid = 12345;
   ```

3. **Force release:**
   ```sql
   -- If PID is from a dead process
   SELECT pg_advisory_unlock_all();
   ```

4. **Retry migration:**
   ```bash
   confiture migrate up
   ```

### Procedure: Rebuild Migration History

**When to use:** Migration tracking table corrupted or lost.

**Steps:**

1. **Backup current state:**
   ```sql
   CREATE TABLE confiture_migrations_backup AS
   SELECT * FROM confiture_migrations;
   ```

2. **Reinitialize tracking:**
   ```bash
   confiture init --force
   ```

3. **Sync history with schema:**
   ```bash
   confiture migrate sync-history
   ```

4. **Verify:**
   ```bash
   confiture migrate status
   confiture migrate drift-detect
   ```

---

## Quick Reference

### Common Commands

| Task | Command |
|------|---------|
| Check status | `confiture migrate status` |
| Apply migrations | `confiture migrate up` |
| Rollback one | `confiture migrate down --steps 1` |
| Dry run | `confiture migrate up --dry-run` |
| Check drift | `confiture migrate drift-detect` |
| Verify checksums | `confiture migrate verify-checksums` |
| Health check | `confiture health check` |

### Environment Variables

| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | PostgreSQL connection string |
| `CONFITURE_ENV` | Environment name (production, staging) |
| `CONFITURE_LOCK_TIMEOUT` | Lock timeout in milliseconds |
| `CONFITURE_LOG_LEVEL` | Logging level (DEBUG, INFO, WARNING) |

### Important Files

| File | Purpose |
|------|---------|
| `confiture.yaml` | Configuration file |
| `db/migrations/` | Migration files |
| `db/schema/` | DDL schema files |
| `confiture_migrations` | Database tracking table |

---

*Last updated: January 2026*
