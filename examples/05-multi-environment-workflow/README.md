# Multi-Environment CI/CD Workflow

**A production-ready CI/CD setup for Confiture**

This example demonstrates a complete multi-environment workflow with automated testing, safe deployments, and production-grade practices. Perfect for teams deploying to staging and production environments.

You'll learn how to:

1. Set up multiple environments (local, CI, staging, production)
2. Automate schema builds and migrations in GitHub Actions
3. Run migration verification tests
4. Safely deploy to production with dry-run validation
5. Handle environment-specific configurations
6. Implement rollback strategies

**Time to complete**: 30 minutes
**Skill level**: Intermediate

---

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Prerequisites](#prerequisites)
- [Project Structure](#project-structure)
- [Environment Setup](#environment-setup)
- [Local Development Workflow](#local-development-workflow)
- [CI/CD Pipeline](#cicd-pipeline)
- [Staging Deployment](#staging-deployment)
- [Production Deployment](#production-deployment)
- [Rollback Procedures](#rollback-procedures)
- [Monitoring and Verification](#monitoring-and-verification)
- [Best Practices](#best-practices)
- [Troubleshooting](#troubleshooting)

---

## Architecture Overview

### Environment Tiers

```
┌─────────────────────────────────────────────────────────────┐
│                   Development Pipeline                       │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  LOCAL          CI              STAGING         PRODUCTION   │
│  ┌────────┐   ┌────────┐      ┌────────┐      ┌────────┐   │
│  │ Dev DB │   │Test DB │      │Stg DB  │      │Prod DB │   │
│  │        │   │        │      │        │      │        │   │
│  │ Fresh  │   │ Fresh  │      │ Migr.  │      │ Migr.  │   │
│  │ builds │   │ builds │      │ only   │      │ only   │   │
│  │ & test │   │ tests  │      │        │      │        │   │
│  │ migr.  │   │ auto   │      │ manual │      │ manual │   │
│  └────────┘   └────────┘      └────────┘      └────────┘   │
│      ↓            ↓               ↓                ↓        │
│   Instant      <2min          Verified         Verified    │
│   rebuild      feedback       + approved       + manual    │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### Deployment Flow

```
Developer → Local Testing → Git Push → CI Tests → Staging → Production
   ↓            ↓              ↓          ↓          ↓           ↓
Schema      Migration      Auto        Auto     Manual      Manual
changes     testing        build       test     approval    approval
                          + test      pass                 + dry-run
```

---

## Prerequisites

### Required Software

- **Python 3.11+**: `python --version`
- **PostgreSQL 14+**: `psql --version`
- **Confiture**: `pip install confiture`
- **Git**: `git --version`
- **Make** (optional but recommended): `make --version`

### Required Access

- **GitHub repository** with Actions enabled
- **PostgreSQL databases** for each environment:
  - Local: `localhost:5432`
  - CI: GitHub Actions (ephemeral)
  - Staging: Your staging server
  - Production: Your production server

### Environment Variables

Set these in GitHub Secrets:

```bash
# Staging database
STAGING_DB_HOST
STAGING_DB_PORT
STAGING_DB_NAME
STAGING_DB_USER
STAGING_DB_PASSWORD

# Production database
PRODUCTION_DB_HOST
PRODUCTION_DB_PORT
PRODUCTION_DB_NAME
PRODUCTION_DB_USER
PRODUCTION_DB_PASSWORD
```

---

## Project Structure

```
05-multi-environment-workflow/
├── README.md                           # This file
├── Makefile                            # Common commands
├── .gitignore                          # Git ignore rules
│
├── db/
│   ├── schema/                         # DDL source files
│   │   ├── 00_common/
│   │   │   ├── extensions.sql         # PostgreSQL extensions
│   │   │   └── roles.sql              # Database roles (prod only)
│   │   ├── 10_tables/
│   │   │   ├── users.sql              # Users table
│   │   │   ├── projects.sql           # Projects table
│   │   │   └── tasks.sql              # Tasks table
│   │   ├── 20_indexes/
│   │   │   └── performance.sql        # Performance indexes
│   │   ├── 30_views/
│   │   │   └── analytics.sql          # Reporting views
│   │   └── 40_functions/
│   │       └── triggers.sql           # Trigger functions
│   │
│   ├── migrations/                     # Incremental migrations
│   │   ├── 001_add_user_bio.py
│   │   ├── 002_add_project_status.py
│   │   └── 003_add_task_priority.py
│   │
│   ├── environments/                   # Environment configs
│   │   ├── local.yaml                 # Local development
│   │   ├── ci.yaml                    # CI testing
│   │   ├── staging.yaml               # Staging server
│   │   └── production.yaml            # Production server
│   │
│   └── seeds/                          # Test data
│       ├── local/                     # Local dev data
│       │   └── sample_users.sql
│       └── ci/                        # CI test data
│           └── test_fixtures.sql
│
├── tests/                              # Migration tests
│   ├── test_schema_build.py           # Schema build tests
│   ├── test_migrations.py             # Migration tests
│   └── test_data_integrity.py         # Data validation tests
│
├── scripts/                            # Deployment scripts
│   ├── verify_migration.sh            # Pre-deployment checks
│   ├── backup_production.sh           # Production backup
│   └── rollback.sh                    # Emergency rollback
│
└── .github/
    └── workflows/
        ├── ci.yml                     # Continuous integration
        ├── deploy-staging.yml         # Staging deployment
        └── deploy-production.yml      # Production deployment
```

---

## Environment Setup

### Local Environment

**1. Create local database:**

```bash
createdb confiture_workflow
```

**2. Configure environment:**

File: `db/environments/local.yaml`

```yaml
name: local
database:
  host: localhost
  port: 5432
  database: confiture_workflow
  user: postgres
  password: postgres

include_dirs:
  - db/schema

exclude_dirs:
  - db/schema/00_common/roles.sql  # Skip production roles locally
```

**3. Build schema:**

```bash
make build-local
# OR: confiture build --env local
```

**4. Load test data:**

```bash
psql confiture_workflow < db/seeds/local/sample_users.sql
```

### CI Environment

**Configuration:** `db/environments/ci.yaml`

```yaml
name: ci
database:
  host: localhost
  port: 5432
  database: confiture_ci
  user: postgres
  password: postgres  # GitHub Actions default

include_dirs:
  - db/schema

exclude_dirs:
  - db/schema/00_common/roles.sql

# CI-specific optimizations
options:
  skip_indexes: false       # Keep indexes for realistic tests
  parallel_build: true      # Faster builds
  verbose: true             # Detailed logs
```

**GitHub Actions Setup:**

The CI pipeline runs automatically on every push (see `.github/workflows/ci.yml`).

### Staging Environment

**Configuration:** `db/environments/staging.yaml`

```yaml
name: staging
database:
  host: ${STAGING_DB_HOST}      # From GitHub Secrets
  port: ${STAGING_DB_PORT}
  database: ${STAGING_DB_NAME}
  user: ${STAGING_DB_USER}
  password: ${STAGING_DB_PASSWORD}
  sslmode: require              # Require SSL

include_dirs:
  - db/schema

exclude_dirs: []

options:
  migration_timeout: 300        # 5 minute timeout
  verbose: true
  dry_run_first: true          # Always dry-run before apply
```

**Deployment:**

Staging deploys automatically when changes are merged to `main` branch.

### Production Environment

**Configuration:** `db/environments/production.yaml`

```yaml
name: production
database:
  host: ${PRODUCTION_DB_HOST}
  port: ${PRODUCTION_DB_PORT}
  database: ${PRODUCTION_DB_NAME}
  user: ${PRODUCTION_DB_USER}
  password: ${PRODUCTION_DB_PASSWORD}
  sslmode: require
  connect_timeout: 10

include_dirs:
  - db/schema

exclude_dirs: []

options:
  migration_timeout: 600        # 10 minute timeout
  verbose: true
  require_backup: true          # Backup before migration
  require_dry_run: true         # Mandatory dry-run
  require_approval: true        # Manual approval required
```

**Deployment:**

Production requires manual approval via GitHub Actions workflow.

---

## Local Development Workflow

### Daily Development

```bash
# 1. Pull latest changes
git pull origin main

# 2. Rebuild local database
make rebuild-local

# 3. Make schema changes
vim db/schema/10_tables/users.sql

# 4. Create migration for existing databases
vim db/migrations/004_add_user_avatar.py

# 5. Test migration locally
make migrate-local

# 6. Verify changes
make verify-local

# 7. Run tests
make test

# 8. Commit changes
git add db/schema/ db/migrations/
git commit -m "feat: add user avatar column"

# 9. Push to trigger CI
git push origin feature/user-avatar
```

### Makefile Commands

```bash
# Build fresh local database
make build-local

# Drop and rebuild (WARNING: destroys data)
make rebuild-local

# Apply pending migrations
make migrate-local

# Rollback last migration
make rollback-local

# Verify schema integrity
make verify-local

# Run all tests
make test

# Run specific test
make test-unit
make test-integration

# Check migration status
make status-local
```

### Testing Migrations Locally

**Test migration applies cleanly:**

```bash
# Apply migration
confiture migrate up --env local

# Verify table structure
psql confiture_workflow -c "\d users"

# Test application queries
psql confiture_workflow -c "SELECT email, avatar_url FROM users LIMIT 5"
```

**Test rollback:**

```bash
# Rollback migration
confiture migrate down --env local

# Verify column removed
psql confiture_workflow -c "\d users"

# Re-apply
confiture migrate up --env local
```

**Test fresh build includes change:**

```bash
# Drop database
dropdb confiture_workflow

# Rebuild from schema files
createdb confiture_workflow
confiture build --env local

# Verify column exists (without running migration)
psql confiture_workflow -c "\d users"
```

---

## CI/CD Pipeline

### Continuous Integration (ci.yml)

**Triggers:** Every push and pull request

**Jobs:**

```yaml
name: CI

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest

    services:
      postgres:
        image: postgres:15
        env:
          POSTGRES_PASSWORD: postgres
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5

    steps:
      - uses: actions/checkout@v3

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: |
          pip install confiture pytest pytest-cov

      - name: Build schema
        run: |
          confiture build --env ci

      - name: Run migrations
        run: |
          confiture migrate up --env ci

      - name: Run tests
        run: |
          pytest tests/ -v --cov=db

      - name: Verify schema integrity
        run: |
          ./scripts/verify_migration.sh ci
```

**What CI Tests:**

1. Schema builds without errors
2. All migrations apply cleanly
3. Schema structure matches expectations
4. Data integrity constraints work
5. Indexes are created correctly
6. Rollback works for each migration

**CI Test Results:**

```
✅ Schema build: 0.4s
✅ Migration 001: 0.1s
✅ Migration 002: 0.1s
✅ Migration 003: 0.1s
✅ Tests: 23 passed, 0 failed
✅ Coverage: 94%
```

---

## Staging Deployment

### Automatic Staging Deployment

**Trigger:** Merge to `main` branch

**Workflow:** `.github/workflows/deploy-staging.yml`

```yaml
name: Deploy to Staging

on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    environment: staging

    steps:
      - uses: actions/checkout@v3

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'

      - name: Install Confiture
        run: pip install confiture

      - name: Check migration status
        env:
          STAGING_DB_HOST: ${{ secrets.STAGING_DB_HOST }}
          STAGING_DB_PASSWORD: ${{ secrets.STAGING_DB_PASSWORD }}
        run: |
          confiture migrate status --env staging

      - name: Dry-run migration
        run: |
          confiture migrate up --env staging --dry-run

      - name: Apply migrations
        run: |
          confiture migrate up --env staging

      - name: Verify deployment
        run: |
          ./scripts/verify_migration.sh staging

      - name: Run smoke tests
        run: |
          pytest tests/integration/ --env staging
```

### Manual Staging Deployment

**Option 1: Via GitHub Actions UI**

1. Go to Actions tab
2. Select "Deploy to Staging"
3. Click "Run workflow"
4. Select branch
5. Click "Run workflow"

**Option 2: Via CLI**

```bash
# Set environment variables
export STAGING_DB_HOST=staging.example.com
export STAGING_DB_PASSWORD=<secret>

# Check status
make status-staging

# Dry-run
confiture migrate up --env staging --dry-run

# Apply
make deploy-staging
```

### Staging Verification

```bash
# Connect to staging database
psql -h staging.example.com -U confiture_user confiture_staging

# Check applied migrations
SELECT * FROM confiture_migrations ORDER BY applied_at DESC LIMIT 5;

# Verify table structure
\d users

# Test queries
SELECT COUNT(*) FROM users;
```

---

## Production Deployment

### Pre-Deployment Checklist

**Before deploying to production:**

- [ ] All tests pass in CI
- [ ] Staging deployment successful
- [ ] Staging verified for 24+ hours
- [ ] Backup taken (automatic)
- [ ] Dry-run reviewed
- [ ] Team notified
- [ ] Rollback plan ready
- [ ] Off-hours deployment scheduled (if needed)

### Production Deployment Workflow

**Trigger:** Manual approval required

**Workflow:** `.github/workflows/deploy-production.yml`

```yaml
name: Deploy to Production

on:
  workflow_dispatch:  # Manual trigger only
    inputs:
      confirmation:
        description: 'Type "deploy-to-production" to confirm'
        required: true

jobs:
  deploy:
    runs-on: ubuntu-latest
    environment: production

    steps:
      - name: Validate confirmation
        run: |
          if [ "${{ github.event.inputs.confirmation }}" != "deploy-to-production" ]; then
            echo "Invalid confirmation"
            exit 1
          fi

      - uses: actions/checkout@v3

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'

      - name: Install Confiture
        run: pip install confiture

      - name: Backup production database
        run: |
          ./scripts/backup_production.sh

      - name: Check migration status
        env:
          PRODUCTION_DB_HOST: ${{ secrets.PRODUCTION_DB_HOST }}
          PRODUCTION_DB_PASSWORD: ${{ secrets.PRODUCTION_DB_PASSWORD }}
        run: |
          confiture migrate status --env production

      - name: Dry-run migration (required)
        run: |
          confiture migrate up --env production --dry-run > dry-run.log
          cat dry-run.log

      - name: Wait for approval
        uses: trstringer/manual-approval@v1
        with:
          approvers: tech-leads,dbas
          minimum-approvals: 2

      - name: Apply migrations
        run: |
          confiture migrate up --env production --verbose

      - name: Verify deployment
        run: |
          ./scripts/verify_migration.sh production

      - name: Notify team
        if: always()
        uses: slackapi/slack-github-action@v1
        with:
          status: ${{ job.status }}
```

### Deploying to Production

**Step 1: Trigger workflow**

1. Go to GitHub Actions
2. Select "Deploy to Production"
3. Click "Run workflow"
4. Type `deploy-to-production` in confirmation
5. Click "Run workflow"

**Step 2: Monitor backup**

```
Running backup...
✅ Backup created: production-backup-2025-10-12-14-30.sql (2.3 GB)
✅ Uploaded to S3: s3://backups/production-2025-10-12-14-30.sql
✅ Retention: 30 days
```

**Step 3: Review dry-run**

```
Dry-run results:
────────────────────────────────────────
Migration: 004_add_user_avatar
SQL:
  ALTER TABLE users ADD COLUMN avatar_url TEXT;

Affected tables: users
Estimated rows: 1,203,456
Lock type: ACCESS EXCLUSIVE
Est. duration: <1s

⚠️  This migration will briefly lock the users table
────────────────────────────────────────
```

**Step 4: Approve deployment**

- Tech leads review dry-run output
- Minimum 2 approvals required
- Click "Approve" in GitHub Actions UI

**Step 5: Monitor deployment**

```
Applying migrations to production...
✅ Migration 004_add_user_avatar: 0.8s
✅ Verification passed
✅ Deployment complete
```

**Step 6: Verify in production**

```bash
# Check migration applied
psql production -c "
  SELECT version, name, applied_at
  FROM confiture_migrations
  ORDER BY applied_at DESC
  LIMIT 1
"

# Verify column exists
psql production -c "\d users"

# Test query
psql production -c "SELECT email, avatar_url FROM users LIMIT 1"
```

---

## Rollback Procedures

### Automatic Rollback (Migration Failure)

If a migration fails, Confiture automatically rolls back:

```
Applying migration 005_complex_change...
❌ Error: constraint violation
🔄 Rolling back migration 005_complex_change...
✅ Rollback complete
Database restored to previous state
```

### Manual Rollback (Post-Deployment Issue)

**Scenario:** Migration applied successfully but caused unexpected issues.

**Step 1: Assess situation**

```bash
# Check current migration status
confiture migrate status --env production

# Review recent migrations
psql production -c "
  SELECT * FROM confiture_migrations
  ORDER BY applied_at DESC
  LIMIT 3
"
```

**Step 2: Execute rollback**

```bash
# Rollback last migration
confiture migrate down --env production

# Expected output:
# Rolling back migration 004_add_user_avatar...
# Executing down() method...
# ✅ Rollback complete (0.5s)
```

**Step 3: Verify rollback**

```bash
# Check migration status
confiture migrate status --env production

# Verify column removed
psql production -c "\d users"
```

**Step 4: Notify team**

```bash
# Post to Slack/email
echo "Production rollback completed
Migration: 004_add_user_avatar
Reason: Unexpected query performance impact
Status: Database restored to previous state
Next steps: Investigating performance issue"
```

### Emergency Rollback Script

**Script:** `scripts/rollback.sh`

```bash
#!/bin/bash
# Emergency rollback script
# Usage: ./scripts/rollback.sh production

ENV=$1

if [ -z "$ENV" ]; then
  echo "Usage: ./scripts/rollback.sh <environment>"
  exit 1
fi

echo "⚠️  EMERGENCY ROLLBACK for $ENV"
echo "This will rollback the last migration"
read -p "Are you sure? (type 'rollback'): " confirm

if [ "$confirm" != "rollback" ]; then
  echo "Aborted"
  exit 1
fi

# Backup current state
echo "Creating backup..."
pg_dump > "emergency-backup-$(date +%Y%m%d-%H%M%S).sql"

# Rollback
echo "Rolling back..."
confiture migrate down --env "$ENV"

# Verify
echo "Verifying..."
./scripts/verify_migration.sh "$ENV"

echo "✅ Rollback complete"
```

### Rollback Testing

**Always test rollback in staging first:**

```bash
# Test rollback in staging
confiture migrate down --env staging

# Verify rollback worked
psql staging -c "\d users"

# Re-apply migration
confiture migrate up --env staging

# Verify re-application worked
psql staging -c "\d users"
```

---

## Monitoring and Verification

### Verification Script

**Script:** `scripts/verify_migration.sh`

```bash
#!/bin/bash
# Verify migration completed successfully
# Usage: ./scripts/verify_migration.sh <environment>

ENV=$1
EXIT_CODE=0

echo "🔍 Verifying migration for environment: $ENV"

# Check migration status
echo "Checking migration status..."
confiture migrate status --env "$ENV" || EXIT_CODE=1

# Verify table structures
echo "Verifying table structures..."
psql -h "$DB_HOST" -U "$DB_USER" -d "$DB_NAME" -c "
  SELECT
    table_name,
    column_name,
    data_type
  FROM information_schema.columns
  WHERE table_schema = 'public'
  ORDER BY table_name, ordinal_position
" || EXIT_CODE=1

# Check indexes
echo "Verifying indexes..."
psql -h "$DB_HOST" -U "$DB_USER" -d "$DB_NAME" -c "
  SELECT
    schemaname,
    tablename,
    indexname
  FROM pg_indexes
  WHERE schemaname = 'public'
  ORDER BY tablename, indexname
" || EXIT_CODE=1

# Verify constraints
echo "Verifying constraints..."
psql -h "$DB_HOST" -U "$DB_USER" -d "$DB_NAME" -c "
  SELECT
    conname,
    contype,
    conrelid::regclass AS table_name
  FROM pg_constraint
  WHERE connamespace = 'public'::regnamespace
  ORDER BY conrelid::regclass::text, conname
" || EXIT_CODE=1

# Test basic queries
echo "Testing basic queries..."
psql -h "$DB_HOST" -U "$DB_USER" -d "$DB_NAME" -c "
  SELECT COUNT(*) FROM users;
" || EXIT_CODE=1

if [ $EXIT_CODE -eq 0 ]; then
  echo "✅ Verification passed"
else
  echo "❌ Verification failed"
fi

exit $EXIT_CODE
```

### Migration Monitoring

**Key metrics to monitor:**

```sql
-- Migration history
SELECT
  version,
  name,
  applied_at,
  applied_by,
  execution_time_ms
FROM confiture_migrations
ORDER BY applied_at DESC
LIMIT 10;

-- Table sizes
SELECT
  schemaname,
  tablename,
  pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;

-- Index usage
SELECT
  schemaname,
  tablename,
  indexname,
  idx_scan,
  idx_tup_read,
  idx_tup_fetch
FROM pg_stat_user_indexes
ORDER BY idx_scan DESC;

-- Lock monitoring (during migration)
SELECT
  locktype,
  relation::regclass,
  mode,
  granted
FROM pg_locks
WHERE relation IS NOT NULL;
```

---

## Best Practices

### 1. Environment Isolation

**Do:**
- Use separate databases for each environment
- Never share credentials between environments
- Use environment variables for sensitive data
- Test migrations in staging before production

**Don't:**
- Connect to production from local machine
- Use production data in development
- Share database credentials in code
- Skip staging deployments

### 2. Migration Safety

**Do:**
- Always write and test `down()` methods
- Test rollback in staging
- Use `IF NOT EXISTS` for idempotency
- Add migrations in small, focused changes
- Keep migrations fast (<5s when possible)

**Don't:**
- Delete data in migrations (archive instead)
- Make breaking changes without coordination
- Deploy migrations during peak traffic
- Combine schema and data changes in one migration

### 3. Schema Files

**Do:**
- Keep schema files in sync with migrations
- Use numbered directories for ordering
- Add comments to complex SQL
- Use `IF NOT EXISTS` everywhere
- Update schema files after every migration

**Don't:**
- Modify old migration files
- Make manual schema changes
- Skip schema file updates
- Use database-specific syntax (when possible)

### 4. Testing

**Do:**
- Test every migration up and down
- Run full test suite in CI
- Verify data integrity after migrations
- Test performance impact in staging
- Use realistic data volumes in testing

**Don't:**
- Skip tests for "simple" migrations
- Test only in local environment
- Ignore performance degradation
- Deploy without CI passing

### 5. Deployment

**Do:**
- Deploy during low-traffic windows
- Monitor during deployment
- Have rollback plan ready
- Communicate with team
- Document deployment steps

**Don't:**
- Deploy on Fridays or before holidays
- Deploy multiple migrations at once
- Skip dry-run in production
- Deploy without approval
- Panic if something goes wrong (follow rollback procedure)

---

## Troubleshooting

### CI Tests Failing

**Problem:** Schema build fails in CI

```
Error: relation "uuid_generate_v4" does not exist
```

**Solution:** Enable extensions in CI environment

```yaml
# .github/workflows/ci.yml
services:
  postgres:
    image: postgres:15
    env:
      POSTGRES_PASSWORD: postgres
    options: >-
      --health-cmd pg_isready
```

Check `db/schema/00_common/extensions.sql` includes needed extensions.

---

**Problem:** Migration test fails

```
Error: column "bio" already exists
```

**Solution:** Ensure migrations are idempotent or CI database is clean

```bash
# In CI workflow, drop database before tests
- name: Clean database
  run: |
    dropdb confiture_ci || true
    createdb confiture_ci
```

---

### Staging Deployment Issues

**Problem:** Connection timeout to staging database

```
Error: connection to server at "staging.example.com" failed
```

**Solution:** Check network access and firewall rules

```bash
# Test connection
psql -h staging.example.com -U confiture_user -d confiture_staging -c "SELECT 1"

# Check SSL requirement
psql "postgresql://user@host/db?sslmode=require"
```

---

**Problem:** Migration fails with lock timeout

```
Error: could not obtain lock on relation "users"
```

**Solution:** Migration timeout during active traffic

```bash
# Check for blocking queries
SELECT pid, query, state
FROM pg_stat_activity
WHERE datname = 'confiture_staging';

# Kill blocking query (if safe)
SELECT pg_terminate_backend(pid);

# Retry migration
confiture migrate up --env staging
```

---

### Production Deployment Issues

**Problem:** Dry-run shows unexpected changes

```
Dry-run: Will drop column "legacy_field"
```

**Solution:** Review migration code before proceeding

```python
# Check migration file
def up(self):
    # Should this really drop the column?
    self.execute("ALTER TABLE users DROP COLUMN legacy_field")
```

**Action:**
- If unexpected, abort deployment
- Fix migration file
- Re-test in staging
- Create new PR

---

**Problem:** Deployment approved but migration fails

```
Error: check constraint "email_format" is violated by some row
```

**Solution:** Data doesn't meet new constraint

```bash
# Rollback automatically triggered
✅ Rollback complete

# Fix data first
UPDATE users SET email = LOWER(email) WHERE email != LOWER(email);

# Then retry migration
```

---

**Problem:** Need to rollback but down() wasn't tested

```
Error: cannot drop column "bio": other objects depend on it
```

**Solution:** Manual intervention required

```bash
# Check dependencies
SELECT * FROM information_schema.columns
WHERE column_name = 'bio';

# Drop dependent objects first
DROP VIEW user_profiles;

# Retry rollback
confiture migrate down --env production

# Recreate view
CREATE VIEW user_profiles AS ...;
```

**Prevention:** Always test rollback in staging!

---

## Summary

You've learned:

- ✅ **Multi-environment setup**: Local, CI, staging, production with proper isolation
- ✅ **CI/CD automation**: Automated testing and deployment pipelines
- ✅ **Safe deployments**: Dry-run, approvals, backups, and verification
- ✅ **Rollback procedures**: Automatic and manual rollback strategies
- ✅ **Monitoring**: Migration verification and health checks
- ✅ **Best practices**: Production-grade deployment patterns

### Key Takeaways

1. **Always test in staging** before production
2. **Always test rollback** before deploying
3. **Always backup** before production migrations
4. **Always dry-run** in production
5. **Always have approval** for production changes

### Next Steps

**Production-Ready Checklist:**

- [ ] Set up all four environments
- [ ] Configure GitHub Secrets
- [ ] Test CI pipeline with sample migration
- [ ] Deploy to staging successfully
- [ ] Test rollback in staging
- [ ] Document team deployment process
- [ ] Set up monitoring and alerts
- [ ] Schedule first production deployment

**Advanced Topics:**

- [Zero-Downtime Migrations](../03-zero-downtime-migration/) - Deploy without downtime
- [Production Data Sync](../04-production-sync-anonymization/) - Copy production to staging
- [Migration Performance](../../docs/guides/migration-performance.md) - Optimize large migrations

---

## Additional Resources

### Documentation

- [Confiture CLI Reference](../../docs/reference/cli.md)
- [Migration Best Practices](../../docs/guides/migration-best-practices.md)
- [Environment Configuration](../../docs/guides/environment-configuration.md)

### Scripts Reference

- `make build-local` - Build fresh local database
- `make migrate-local` - Apply pending migrations locally
- `make test` - Run all tests
- `make deploy-staging` - Deploy to staging
- `./scripts/verify_migration.sh` - Verify migration success
- `./scripts/backup_production.sh` - Backup production database
- `./scripts/rollback.sh` - Emergency rollback

### Team Communication Templates

**Pre-deployment announcement:**

```
📢 Database Migration Scheduled

Environment: Production
Time: 2025-10-12 02:00 UTC (off-peak)
Duration: ~5 minutes
Impact: Brief lock on users table

Migration: 004_add_user_avatar
Changes: Adds avatar_url column to users table

Approvers: @tech-lead @dba
Rollback plan: Available if needed

Status updates: #deployments channel
```

**Post-deployment confirmation:**

```
✅ Production Migration Complete

Migration: 004_add_user_avatar
Status: Success
Duration: 0.8s
Affected rows: 1,203,456

Verification: Passed
Monitoring: No errors detected

Deployment log: [link]
```

---

**Part of the Confiture examples** 🍓

*Production-grade database migrations with confidence*
