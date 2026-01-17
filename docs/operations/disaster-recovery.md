# Confiture Disaster Recovery Procedures

This document outlines disaster recovery procedures for PostgreSQL migrations managed by Confiture.

## Table of Contents

- [Pre-Disaster Preparation](#pre-disaster-preparation)
- [Recovery Objectives](#recovery-objectives)
- [Disaster Scenarios](#disaster-scenarios)
- [Post-Recovery Procedures](#post-recovery-procedures)
- [Incident Response Template](#incident-response-template)

---

## Pre-Disaster Preparation

### Backup Strategy

#### 1. Database Backups

**Daily Full Backup:**
```bash
#!/bin/bash
# /scripts/backup-database.sh

DATE=$(date +%Y%m%d)
BACKUP_DIR="/backups/postgres"

pg_dump "$DATABASE_URL" \
  --format=custom \
  --compress=9 \
  --file="$BACKUP_DIR/backup_$DATE.dump"

# Retain last 30 days
find "$BACKUP_DIR" -name "*.dump" -mtime +30 -delete
```

**Continuous WAL Archiving:**
```ini
# postgresql.conf
archive_mode = on
archive_command = 'aws s3 cp %p s3://my-bucket/wal/%f'
```

**Point-in-Time Recovery Setup:**
```ini
# postgresql.conf
wal_level = replica
max_wal_senders = 3
wal_keep_size = 1GB
```

#### 2. Migration File Backups

Migration files should be:
- Version controlled in Git
- Replicated to multiple locations
- Tagged with release versions

```bash
# Tag migrations with release
git tag -a v1.5.0 -m "Release 1.5.0 with migrations 001-015"
git push --tags

# Mirror to backup repository
git push backup-origin main --tags
```

#### 3. Configuration Backups

Document and backup:
- `confiture.yaml` configuration
- Environment variables
- Secret references (not actual secrets)

```bash
# Backup configuration
cp confiture.yaml /backups/config/confiture_$(date +%Y%m%d).yaml

# Document environment variables
env | grep CONFITURE > /backups/config/env_$(date +%Y%m%d).txt
```

### Backup Verification

**Weekly Restore Test:**
```bash
#!/bin/bash
# /scripts/test-restore.sh

# Create test database
createdb confiture_restore_test

# Restore latest backup
pg_restore \
  --dbname=confiture_restore_test \
  --no-owner \
  /backups/postgres/backup_latest.dump

# Verify migrations
DATABASE_URL="postgresql://localhost/confiture_restore_test" \
  confiture migrate status

# Verify data integrity
psql confiture_restore_test -c "SELECT COUNT(*) FROM confiture_migrations"

# Cleanup
dropdb confiture_restore_test
```

---

## Recovery Objectives

### Recovery Point Objective (RPO)

| Component | RPO | Method |
|-----------|-----|--------|
| Database data | 5 minutes | Continuous WAL archiving |
| Schema state | 1 minute | WAL includes DDL |
| Migration files | 0 (no loss) | Git version control |
| Configuration | 24 hours | Daily backup |

### Recovery Time Objective (RTO)

| Scenario | RTO Target | Dependencies |
|----------|------------|--------------|
| Single migration rollback | 5 minutes | None |
| Database restore (< 100GB) | 30 minutes | Backup availability |
| Database restore (> 100GB) | 2 hours | Backup availability |
| Full environment rebuild | 4 hours | All backups available |

---

## Disaster Scenarios

### Scenario 1: Failed Migration (Partial Apply)

**Symptoms:**
- Migration error mid-execution
- Schema in inconsistent state
- Application errors

**Assessment:**
```sql
-- Check what was created/modified
SELECT schemaname, tablename
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY tablename;

-- Check recent DDL (requires pg_stat_statements)
SELECT query, calls, total_time
FROM pg_stat_statements
WHERE query LIKE 'CREATE%' OR query LIKE 'ALTER%'
ORDER BY calls DESC LIMIT 10;

-- Check migration history
SELECT * FROM confiture_migrations ORDER BY applied_at DESC LIMIT 5;
```

**Recovery Steps:**

**If migration is transactional (default):**
```bash
# Transaction should have rolled back automatically
# Verify status
confiture migrate status

# Fix migration file, then retry
confiture migrate up
```

**If migration is non-transactional:**
```bash
# Step 1: Assess partial changes
psql -c "\d+ affected_table"

# Step 2: Manual cleanup (example)
psql << 'EOF'
-- Remove partially created objects
DROP INDEX IF EXISTS idx_partial;
DROP COLUMN IF EXISTS users.incomplete_column;

-- Remove from migration history
DELETE FROM confiture_migrations WHERE version = 'failed_migration';
EOF

# Step 3: Fix migration and retry
confiture migrate up
```

### Scenario 2: Database Corruption

**Symptoms:**
- Query errors
- Inconsistent data
- Database won't start
- `pg_dump` fails

**Immediate Actions:**
```bash
# Stop application traffic
kubectl scale deployment app --replicas=0

# Attempt to assess damage
psql -c "SELECT datname, datconnlimit FROM pg_database"
```

**Recovery Option A: Point-in-Time Recovery**
```bash
# Stop PostgreSQL
sudo systemctl stop postgresql

# Configure recovery
cat > /var/lib/postgresql/data/recovery.conf << 'EOF'
restore_command = 'aws s3 cp s3://my-bucket/wal/%f %p'
recovery_target_time = '2024-01-15 14:30:00 UTC'
recovery_target_action = 'promote'
EOF

# Start PostgreSQL (will recover)
sudo systemctl start postgresql

# Verify recovery
confiture migrate status
confiture migrate verify-checksums
```

**Recovery Option B: Full Restore**
```bash
# Drop corrupted database
dropdb mydb

# Create fresh database
createdb mydb

# Restore from backup
pg_restore \
  --dbname=mydb \
  --no-owner \
  --jobs=4 \
  /backups/postgres/backup_latest.dump

# Apply any migrations since backup
confiture migrate up --verify-checksums
```

**Post-Recovery:**
```bash
# Verify schema state
confiture migrate drift-detect

# Restart application
kubectl scale deployment app --replicas=3

# Monitor for issues
kubectl logs -f deployment/app
```

### Scenario 3: Blue-Green Migration Failure

**Symptoms:**
- Traffic switched to broken schema
- Application error spike
- Health checks failing

**Immediate Actions (< 1 minute):**
```bash
# Immediate rollback to blue (original) schema
confiture migrate rollback-blue-green --force
```

**If automatic rollback fails:**
```sql
-- Manual schema swap back
BEGIN;

-- Swap schemas atomically
ALTER SCHEMA public RENAME TO public_failed;
ALTER SCHEMA public_backup RENAME TO public;

COMMIT;
```

**Verification:**
```bash
# Verify current schema
psql -c "SELECT current_schema()"

# Check migration status
confiture migrate status

# Verify application health
curl -f https://app.example.com/health
```

**Post-Incident:**
```bash
# Keep failed schema for analysis
# DO NOT drop until root cause identified

# Document the failure
confiture migrate status --verbose > incident_report.txt

# Investigate
psql << 'EOF'
-- Compare schemas
SELECT table_name, column_name
FROM information_schema.columns
WHERE table_schema = 'public_failed'
EXCEPT
SELECT table_name, column_name
FROM information_schema.columns
WHERE table_schema = 'public';
EOF
```

### Scenario 4: Lost Migration History

**Symptoms:**
- `confiture_migrations` table deleted or corrupted
- Can't determine which migrations are applied
- Confiture shows all migrations as pending

**Assessment:**
```sql
-- Check if table exists
SELECT EXISTS (
    SELECT FROM information_schema.tables
    WHERE table_name = 'confiture_migrations'
);

-- If exists, check contents
SELECT * FROM confiture_migrations ORDER BY applied_at;
```

**Recovery Steps:**

**Step 1: Backup current state**
```sql
-- If table exists but corrupted
CREATE TABLE confiture_migrations_backup AS
SELECT * FROM confiture_migrations;
```

**Step 2: Reinitialize**
```bash
# Recreate tracking table
confiture init --force
```

**Step 3: Sync with current schema**
```bash
# Analyze schema and mark migrations as applied
confiture migrate sync-history
```

This command:
- Analyzes current database schema
- Compares with migration files
- Marks migrations as applied if their changes exist
- Reports any discrepancies

**Step 4: Verify**
```bash
confiture migrate status
confiture migrate drift-detect
confiture migrate verify-checksums
```

**If sync-history is not available:**
```sql
-- Manual reconstruction
-- Mark migrations as applied based on schema analysis

-- Check if users table exists (from 001_create_users)
SELECT EXISTS (SELECT FROM pg_tables WHERE tablename = 'users');

-- If yes, mark as applied
INSERT INTO confiture_migrations (version, applied_at, checksum)
VALUES ('001_create_users', NOW(), 'computed_checksum');

-- Repeat for each migration...
```

### Scenario 5: Accidental Data Deletion

**Symptoms:**
- Data missing from tables
- `DELETE` or `TRUNCATE` executed incorrectly
- Migration rolled back data unexpectedly

**Immediate Actions:**
```bash
# Stop application to prevent further damage
kubectl scale deployment app --replicas=0

# Prevent new connections
psql -c "ALTER DATABASE mydb CONNECTION LIMIT 1"
```

**Recovery Option A: Point-in-Time Recovery (Recommended)**
```bash
# Determine exact time before deletion
# Check application logs, audit logs, or pg_stat_statements

# Perform PITR (see Scenario 2)
```

**Recovery Option B: Selective Table Restore**
```bash
# Restore backup to temporary database
createdb mydb_restore
pg_restore --dbname=mydb_restore /backups/postgres/backup.dump

# Copy specific table data
pg_dump mydb_restore --table=deleted_table --data-only | psql mydb
```

**Recovery Option C: WAL Replay to Extract Data**
```bash
# Advanced: Use pg_waldump to find and extract data
pg_waldump /var/lib/postgresql/data/pg_wal/0000000100000001000000AB
```

---

## Post-Recovery Procedures

### Verification Checklist

- [ ] All expected tables exist
- [ ] All indexes are present and valid
- [ ] All constraints are in place
- [ ] Foreign key relationships intact
- [ ] Sequences at correct values
- [ ] Migration history accurate
- [ ] No schema drift detected
- [ ] Application smoke tests pass
- [ ] Performance benchmarks normal

### Verification Commands

```bash
# Schema verification
confiture migrate status
confiture migrate drift-detect
confiture migrate verify-checksums

# Database integrity
psql << 'EOF'
-- Check table counts
SELECT schemaname, relname, n_live_tup
FROM pg_stat_user_tables
ORDER BY n_live_tup DESC;

-- Check index health
SELECT indexrelname, idx_scan, idx_tup_read, idx_tup_fetch
FROM pg_stat_user_indexes;

-- Check for invalid indexes
SELECT indexrelname FROM pg_stat_user_indexes
WHERE idx_scan = 0 AND indexrelid::regclass::text NOT LIKE 'pg_%';

-- Verify sequences
SELECT sequencename, last_value FROM pg_sequences;
EOF

# Application tests
./run_smoke_tests.sh
```

### Documentation Requirements

After any recovery:

1. **Update incident log**
2. **Document root cause**
3. **Update recovery procedures if needed**
4. **Schedule post-mortem meeting**
5. **Create follow-up tickets**

---

## Incident Response Template

```markdown
# Incident Report: [Brief Title]

**Incident ID:** INC-YYYYMMDD-NNN
**Date:** YYYY-MM-DD
**Duration:** X hours Y minutes
**Severity:** P1/P2/P3/P4
**Status:** Resolved/Ongoing

## Summary

[1-2 sentence description of what happened]

## Impact

- **Users affected:** [Number/percentage]
- **Services affected:** [List]
- **Data impact:** [None/Read-only/Data loss]
- **Financial impact:** [If applicable]

## Timeline (UTC)

| Time | Event |
|------|-------|
| HH:MM | First alert received |
| HH:MM | Investigation started |
| HH:MM | Root cause identified |
| HH:MM | Recovery started |
| HH:MM | Service restored |
| HH:MM | Incident closed |

## Root Cause

[Detailed explanation of what caused the incident]

## Resolution

[Steps taken to resolve the incident]

## Prevention

### Immediate Actions
- [ ] [Action 1]
- [ ] [Action 2]

### Long-term Improvements
- [ ] [Improvement 1]
- [ ] [Improvement 2]

## Lessons Learned

1. [Lesson 1]
2. [Lesson 2]

## References

- [Link to relevant logs]
- [Link to related tickets]
- [Link to runbook used]

---
**Prepared by:** [Name]
**Reviewed by:** [Name]
**Approved by:** [Name]
```

---

## Quick Reference

### Emergency Contacts

| Role | Contact | Escalation |
|------|---------|------------|
| On-call DBA | [Phone/Slack] | 15 minutes |
| Platform Team Lead | [Phone/Slack] | 30 minutes |
| Engineering Manager | [Phone/Slack] | 1 hour |

### Critical Commands

```bash
# Emergency rollback
confiture migrate down --steps 1 --force

# Force unlock
psql -c "SELECT pg_advisory_unlock_all()"

# Stop all migrations
kubectl delete job -l app=confiture

# Check database status
pg_isready && confiture health check
```

### Backup Locations

| Backup Type | Location | Retention |
|-------------|----------|-----------|
| Daily full | s3://backups/daily/ | 30 days |
| WAL archives | s3://backups/wal/ | 7 days |
| Migration files | Git + s3://backups/migrations/ | Forever |
| Configuration | s3://backups/config/ | 90 days |

---

*Last updated: January 2026*
*Review schedule: Quarterly*
*Next review: April 2026*
