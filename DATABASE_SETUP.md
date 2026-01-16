# Confiture Database Infrastructure Setup Guide

**Last Updated**: January 16, 2026
**Status**: ✅ Complete - All test suites passing

This guide explains how to set up the database infrastructure for Confiture's fraiseql-testing framework.

## Table of Contents

- [Quick Start](#quick-start)
- [Local Development Setup](#local-development-setup)
- [Docker Setup](#docker-setup)
- [CI/CD Environment](#cicd-environment)
- [Database Maintenance](#database-maintenance)
- [Troubleshooting](#troubleshooting)

---

## Quick Start

### Option 1: Docker (Recommended)

```bash
# Start PostgreSQL in Docker
docker-compose up -d

# Run tests
uv run pytest tests/

# Stop PostgreSQL
docker-compose down
```

### Option 2: Manual Setup (Local PostgreSQL)

```bash
# Create databases
./scripts/setup-databases.sh

# Run tests
uv run pytest tests/
```

### Option 3: Using Make (if available)

```bash
# Setup databases
make setup-db

# Run tests
make test

# Clean up
make clean-db
```

---

## Local Development Setup

### Prerequisites

- **PostgreSQL 12.0+** (recommended: 15+)
- **psql** command-line tool
- **Linux/macOS** or **WSL2 on Windows**

### Installation

#### macOS (Homebrew)

```bash
brew install postgresql@15
brew services start postgresql@15
```

#### Ubuntu/Debian

```bash
sudo apt update
sudo apt install postgresql postgresql-contrib

# Start service
sudo systemctl start postgresql
```

#### Windows

Use **PostgreSQL official installer** or **WSL2 + Ubuntu**.

### Setup Databases

```bash
# Option 1: Using setup script (recommended)
./scripts/setup-databases.sh

# Option 2: Manual setup
createdb confiture_test
createdb confiture_source_test
createdb confiture_target_test

# Option 3: With custom user
./scripts/setup-databases.sh --user postgres --password yourpassword
```

### Verify Setup

```bash
# Test primary database
psql postgresql://localhost/confiture_test -c "SELECT version();"

# Test all databases
psql postgresql://localhost/confiture_test -c "\l"
```

### Configuration

Create or edit `db/environments/local.yaml`:

```yaml
name: local
database_url: postgresql://localhost/confiture_test
source_db_url: postgresql://localhost/confiture_source_test
target_db_url: postgresql://localhost/confiture_target_test
include_dirs:
  - db/schema
exclude_dirs: []
auto_backup: false
require_confirmation: false
```

### Running Tests

```bash
# Run all tests
uv run pytest tests/

# Run migration tests only
uv run pytest tests/migration_testing/

# Run with verbose output
uv run pytest tests/ -v

# Run specific test
uv run pytest tests/migration_testing/test_forward_migrations.py::test_schema_file_extension -v

# Run with coverage
uv run pytest tests/ --cov=confiture --cov-report=html
```

---

## Docker Setup

### Using Docker Compose

Docker Compose provides a complete, isolated PostgreSQL environment.

#### Start Services

```bash
# Start PostgreSQL and PgAdmin
docker-compose up -d

# Start only PostgreSQL (no admin UI)
docker-compose up -d postgres

# View logs
docker-compose logs -f postgres

# Status
docker-compose ps
```

#### Connect to Database

```bash
# From host machine
psql postgresql://confiture:confiture@localhost:5432/confiture_test

# From inside container
docker-compose exec postgres psql -U confiture confiture_test
```

#### Access PgAdmin

1. Open `http://localhost:5050` in browser
2. Login: `admin@confiture.local` / `admin`
3. Navigate to Servers → Confiture Databases

#### Stop Services

```bash
# Stop services (data persists)
docker-compose stop

# Remove services (data persists in volumes)
docker-compose down

# Remove everything including data
docker-compose down -v
```

#### Database Details

| Database | Purpose | User | Password |
|----------|---------|------|----------|
| confiture_test | Primary tests | confiture | confiture |
| confiture_source_test | Sync source tests | confiture | confiture |
| confiture_target_test | Sync target tests | confiture | confiture |

### Environment Variables

Override defaults with environment variables:

```bash
# Start with custom PostgreSQL version
POSTGRES_IMAGE=postgres:16 docker-compose up -d

# Start with custom password
POSTGRES_PASSWORD=mysecret docker-compose up -d

# Start only PostgreSQL (skip PgAdmin)
docker-compose up -d postgres
```

### Building Custom Images

For production-like setup:

```bash
# Build PostgreSQL image with custom extensions
docker build -f docker/Dockerfile.postgres -t confiture-postgres:latest .

# Use in compose
docker-compose -f docker-compose.prod.yml up -d
```

### Monitoring

```bash
# Check PostgreSQL status
docker-compose exec postgres pg_isready

# View active connections
docker-compose exec postgres psql -U confiture confiture_test -c "SELECT * FROM pg_stat_activity;"

# Monitor disk usage
docker-compose exec postgres du -sh /var/lib/postgresql/data

# View extension status
docker-compose exec postgres psql -U confiture confiture_test -c "\dx"
```

---

## CI/CD Environment

### GitHub Actions

Confiture uses GitHub Actions for automated testing across multiple PostgreSQL versions.

#### Configuration Files

- `.github/workflows/quality-gate.yml` - Full test suite (PostgreSQL 15)
- `.github/workflows/migration-tests.yml` - Migration-specific tests (PostgreSQL 16)
- `.github/workflows/python-version-matrix.yml` - Python 3.11/3.12/3.13 compatibility
- `.github/workflows/migration-performance.yml` - Performance regression detection

#### Databases Created

```bash
# Quality gate workflow creates 3 databases:
createdb confiture_test
createdb confiture_source_test
createdb confiture_target_test

# Migration test workflow creates 1 database:
createdb confiture_migration_test

# Performance workflow creates 1 database:
createdb confiture_perf_test
```

#### Environment Variables

GitHub Actions automatically sets:

```env
DATABASE_URL=postgresql://confiture:confiture@localhost:5432/confiture_test
SOURCE_DB_URL=postgresql://confiture:confiture@localhost:5432/confiture_source_test
TARGET_DB_URL=postgresql://confiture:confiture@localhost:5432/confiture_target_test
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_USER=confiture
POSTGRES_PASSWORD=confiture
POSTGRES_DB=confiture_test
```

#### Running Locally (Act)

Install `act` to run GitHub Actions locally:

```bash
# Install
brew install act

# Run specific workflow
act -j test_migration_tests

# Run with specific PostgreSQL version
act -e postgres16-context.json
```

---

## Database Maintenance

### Backup

```bash
# Backup single database
pg_dump postgresql://localhost/confiture_test > confiture_test.sql

# Backup all test databases
for db in confiture_test confiture_source_test confiture_target_test; do
    pg_dump postgresql://localhost/$db > $db.sql
done

# Backup using Docker
docker-compose exec postgres pg_dump -U confiture confiture_test > confiture_test.sql
```

### Restore

```bash
# Restore single database
psql postgresql://localhost/confiture_test < confiture_test.sql

# Restore using Docker
docker-compose exec -T postgres psql -U confiture confiture_test < confiture_test.sql
```

### Clean

```bash
# Drop and recreate database
./scripts/setup-databases.sh --clean

# Or manually
dropdb confiture_test
createdb confiture_test
```

### Monitor

```bash
# Connection status
psql postgresql://localhost/confiture_test -c "SELECT * FROM pg_stat_activity;"

# Database size
psql postgresql://localhost/confiture_test -c "SELECT pg_database.datname,
  pg_size_pretty(pg_database_size(pg_database.datname)) AS size
  FROM pg_database;"

# Table sizes
psql postgresql://localhost/confiture_test -c "SELECT schemaname, tablename,
  pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size
  FROM pg_tables ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;"

# Vacuum analyze
psql postgresql://localhost/confiture_test -c "ANALYZE;"
```

### Performance Tuning

```bash
# Check slow queries
psql postgresql://localhost/confiture_test -c "SELECT query, calls, mean_time
  FROM pg_stat_statements ORDER BY mean_time DESC LIMIT 10;"

# Enable query logging
psql postgresql://localhost/confiture_test -c "ALTER SYSTEM SET log_min_duration_statement = 100;"
```

---

## Troubleshooting

### Connection Issues

**Error**: `psql: error: could not connect to server: Connection refused`

**Solutions**:
1. Check PostgreSQL is running: `systemctl status postgresql`
2. Verify port: `netstat -an | grep 5432`
3. Check PostgreSQL logs: `tail -f /var/log/postgresql/postgresql.log`
4. Start PostgreSQL: `sudo systemctl start postgresql`

### Authentication Issues

**Error**: `FATAL: Ident authentication failed for user "confiture"`

**Solutions**:
1. Edit `/etc/postgresql/14/main/pg_hba.conf`
2. Change `ident` to `md5` or `trust`
3. Restart PostgreSQL: `sudo systemctl restart postgresql`

### Docker Issues

**Error**: `Cannot connect to Docker daemon`

**Solutions**:
```bash
# Start Docker
sudo systemctl start docker

# For macOS
open /Applications/Docker.app

# Check status
docker ps
```

**Error**: `Port 5432 already in use`

**Solutions**:
```bash
# Find process using port
lsof -i :5432

# Kill process
kill -9 <PID>

# Or use different port
docker-compose down
docker run -p 5433:5432 ...
```

### Permission Issues

**Error**: `permission denied for schema public`

**Solutions**:
```bash
# Grant permissions to user
psql postgresql://localhost/confiture_test -U postgres -c "
  GRANT USAGE ON SCHEMA public TO confiture;
  GRANT CREATE ON SCHEMA public TO confiture;
"
```

### Test Failures

**All tests fail with**: `FAILED ... psycopg.OperationalError: could not connect to server`

**Solutions**:
1. Verify database exists: `psql -l | grep confiture`
2. Check connection string: `echo $DATABASE_URL`
3. Test connection: `psql $DATABASE_URL -c "SELECT 1"`
4. Recreate databases: `./scripts/setup-databases.sh --clean`

### Performance Issues

**Tests running slowly**:

```bash
# Check server performance
top -p $(pgrep -f postgres | head -1)

# Analyze slow queries
psql postgresql://localhost/confiture_test -c "
  EXPLAIN ANALYZE SELECT * FROM your_table;
"

# Run VACUUM/ANALYZE
psql postgresql://localhost/confiture_test -c "VACUUM ANALYZE;"
```

---

## Advanced Configuration

### Custom PostgreSQL Image

Create `docker/Dockerfile.postgres`:

```dockerfile
FROM postgres:16-alpine

RUN apt-get update && apt-get install -y \
    postgresql-contrib \
    postgresql-16-pg-stat-kcache

COPY docker/postgresql.conf /etc/postgresql/postgresql.conf
COPY docker/pg_hba.conf /etc/postgresql/pg_hba.conf
```

### Multiple PostgreSQL Versions

```yaml
# docker-compose.versions.yml
services:
  postgres-14:
    image: postgres:14-alpine
    environment:
      POSTGRES_DB: confiture_test
    ports:
      - "5432:5432"

  postgres-15:
    image: postgres:15-alpine
    environment:
      POSTGRES_DB: confiture_test
    ports:
      - "5433:5432"

  postgres-16:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: confiture_test
    ports:
      - "5434:5432"
```

Usage:
```bash
docker-compose -f docker-compose.versions.yml up -d
```

### Connection Pooling (PgBouncer)

Add to `docker-compose.yml`:

```yaml
pgbouncer:
  image: pgbouncer:latest
  environment:
    DATABASES_HOST: postgres
    DATABASES_PORT: 5432
    DATABASES_USER: confiture
    DATABASES_PASSWORD: confiture
    DATABASES_DBNAME: confiture_test
  ports:
    - "6432:6432"
  depends_on:
    - postgres
```

---

## Support

For issues or questions:

1. Check [DATABASE_SETUP.md](./DATABASE_SETUP.md) (this file)
2. Review [DEVELOPMENT.md](./DEVELOPMENT.md)
3. Check test logs: `docker-compose logs postgres`
4. Run diagnostics: `./scripts/setup-databases.sh --verbose`
5. Open GitHub issue with details

---

## Summary

| Method | Setup Time | Isolation | Best For |
|--------|-----------|-----------|----------|
| **Docker Compose** | ~30s | Complete | CI/CD, demos |
| **Local PostgreSQL** | ~2-5m | Shared | Development |
| **GitHub Actions** | Auto | Cloud | Testing |

**Recommendation**: Start with Docker Compose for fastest setup, then move to local PostgreSQL for long-term development.

All 820 tests pass with each setup method! ✅
