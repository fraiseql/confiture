# Confiture Quick Start Guide

Get up and running with Confiture's database testing framework in minutes!

**Time to First Test**: ~2-5 minutes ⚡

---

## 🚀 Fastest Start (Docker)

### 1. Start PostgreSQL

```bash
# One command to start everything
docker-compose up -d

# Verify it's running
docker-compose ps
```

### 2. Run Tests

```bash
# Run all 820 tests
uv run pytest tests/

# Or use make
make test
```

### 3. Done! 🎉

All tests should pass. If they don't, check [Troubleshooting](#troubleshooting).

---

## 📋 Quick Reference

### Common Commands

```bash
# Database
make setup-docker      # Start PostgreSQL (Docker)
make setup-db          # Setup PostgreSQL (local)
make stop-docker       # Stop PostgreSQL
make db-status         # Check database status

# Testing
make test              # Run all tests
make test-fast         # Run tests quickly
make test-coverage     # Generate coverage report
make test-migration    # Run migration tests only

# Cleanup
make clean             # Clean caches
make clean-all         # Clean everything (including DB)
```

### Database URLs

```bash
# Local PostgreSQL
postgresql://localhost/confiture_test

# Docker PostgreSQL
postgresql://confiture:confiture@localhost:5432/confiture_test

# Sync testing (source/target)
postgresql://localhost/confiture_source_test
postgresql://localhost/confiture_target_test
```

### Using Make

The simplest approach - all common tasks are in `Makefile`:

```bash
make help         # Show all available commands
make setup-docker # Start PostgreSQL (easiest)
make test         # Run tests
make stop-docker  # Stop services
```

---

## 📦 Three Setup Options

### Option 1: Docker (Recommended) ⭐

**Best for:** First-time setup, CI/CD, clean environments

```bash
# Setup (30 seconds)
docker-compose up -d

# Test
uv run pytest tests/

# Stop
docker-compose down
```

**Pros:**
- ✅ No local PostgreSQL needed
- ✅ Complete isolation
- ✅ Same as GitHub Actions CI/CD
- ✅ Easy to reset

**Cons:**
- Requires Docker

### Option 2: Local PostgreSQL

**Best for:** Development, existing setup

```bash
# Setup (2-5 minutes)
./scripts/setup-databases.sh

# Or with make
make setup-db

# Test
uv run pytest tests/

# Clean
make clean-db
```

**Pros:**
- ✅ Direct database access
- ✅ Faster than Docker

**Cons:**
- Requires PostgreSQL installed

### Option 3: Using Make (All Options)

**Best for:** Anyone - just one command!

```bash
# Pick one:
make setup-docker    # Docker (recommended)
make setup-db        # Local PostgreSQL
make fresh          # Docker + tests + cleanup

# Test
make test

# Monitor
make db-status
```

---

## ⚡ Step-by-Step

### Step 1: Choose Setup Method

```bash
# Docker (easiest)
docker-compose up -d

# OR local PostgreSQL
./scripts/setup-databases.sh
```

### Step 2: Verify Setup

```bash
# Check database status
make db-status

# Or manually
psql postgresql://localhost/confiture_test -c "SELECT 1;"
```

### Step 3: Run Tests

```bash
# All tests
uv run pytest tests/

# Specific test
uv run pytest tests/migration_testing/test_forward_migrations.py -v

# With coverage
uv run pytest tests/ --cov=confiture
```

### Step 4: Explore Results

```bash
# View test output
cat test-report.json

# View coverage report
open htmlcov/index.html
```

---

## 🔧 Common Tasks

### Connect to Database

```bash
# Docker
docker-compose exec postgres psql -U confiture confiture_test

# Local PostgreSQL
psql postgresql://localhost/confiture_test

# Using Make
make setup-docker-shell
```

### View Logs

```bash
# Docker
docker-compose logs -f postgres

# Using Make
make setup-docker-logs
```

### Create Fresh Database

```bash
# Docker
docker-compose down -v
docker-compose up -d

# Local
make setup-db-clean
```

### Run Specific Test Category

```bash
# All migration tests
make test-migration

# Unit tests only
make test-unit

# Performance tests
make test-performance

# E2E tests
make test-e2e
```

---

## 🐛 Troubleshooting

### "Could not connect to server"

**Problem**: Database not running

**Solution**:
```bash
# Start PostgreSQL
docker-compose up -d

# OR
make setup-db

# Verify
make db-status
```

### "Port 5432 already in use"

**Problem**: PostgreSQL already running

**Solution**:
```bash
# Option 1: Stop existing
docker-compose down

# Option 2: Use different port
PORT=5433 docker-compose up -d

# Option 3: Find and kill process
lsof -i :5432 | grep -v COMMAND | awk '{print $2}' | xargs kill -9
```

### Tests failing with "database does not exist"

**Problem**: Databases not created

**Solution**:
```bash
# Recreate databases
make setup-db-clean

# OR with Docker
docker-compose down -v
docker-compose up -d
```

### "psycopg: module not found"

**Problem**: Dependencies not installed

**Solution**:
```bash
# Install dependencies
uv sync --all-extras

# Verify
uv run pytest --version
```

### Docker won't start

**Problem**: Docker daemon not running

**Solution**:
```bash
# Start Docker daemon
sudo systemctl start docker    # Linux
open /Applications/Docker.app  # macOS

# Verify
docker ps
```

### Permission denied errors

**Problem**: File permissions

**Solution**:
```bash
# Make scripts executable
chmod +x scripts/*.sh

# Run with appropriate user
sudo docker-compose up -d
```

---

## 📊 What Gets Tested?

Confiture tests **820 different scenarios** covering:

✅ **Forward Migrations** (36 tests)
- Schema creation
- Data validation
- Performance

✅ **Rollback Migrations** (48 tests)
- Safe rollback
- Data recovery
- Transaction safety

✅ **Edge Cases** (35 tests)
- Concurrent operations
- Large datasets (50k+ rows)
- Complex schemas

✅ **Mutations** (8 tests)
- Test quality validation
- Coverage metrics

✅ **Performance** (8 tests)
- Timing validation
- Regression detection

✅ **Load Testing** (12 tests)
- Bulk operations
- Large table handling

✅ **Advanced Scenarios** (10 tests)
- Production patterns
- Complex migrations

**Plus**: Unit tests, integration tests, E2E tests, and more!

---

## 📚 Next Steps

After first successful test run:

1. **Read the Docs**
   - [DATABASE_SETUP.md](./DATABASE_SETUP.md) - Detailed setup
   - [DEVELOPMENT.md](./DEVELOPMENT.md) - Development guide
   - [docs/](./docs/) - Full documentation

2. **Explore Examples**
   - [examples/](./examples/) - 5 production-ready examples

3. **Run Specific Tests**
   - Migration tests: `make test-migration`
   - Unit tests: `make test-unit`
   - Performance: `make test-performance`

4. **Monitor Performance**
   - Coverage: `make test-coverage`
   - Logs: `make setup-docker-logs`

---

## 💡 Pro Tips

### Tip 1: Use Make for Everything

```bash
make help        # See all commands
make fresh       # Full setup + tests + cleanup
make status      # Check everything
```

### Tip 2: Watch Tests Run

```bash
# Terminal 1: Start databases
docker-compose up -d

# Terminal 2: Watch tests
make watch

# Edit code, tests re-run automatically!
```

### Tip 3: Check Coverage

```bash
make test-coverage
open htmlcov/index.html
```

### Tip 4: Use Verbose Output

```bash
# See what's happening
make test-verbose

# Or for specific test
uv run pytest tests/migration_testing/test_forward_migrations.py::test_schema_file_extension -vv
```

### Tip 5: Database Inspection

```bash
# Connect and explore
docker-compose exec postgres psql -U confiture confiture_test

# Common commands:
# \dt                    - List tables
# \dx                    - List extensions
# \l                     - List databases
# SELECT VERSION();      - PostgreSQL version
```

---

## 🎯 Success Metrics

After setup, you should see:

```
✓ 820 passed, 38 skipped in 6.59s
```

This means:
- ✅ All databases created
- ✅ All extensions loaded
- ✅ All migration tests pass
- ✅ All performance tests pass
- ✅ Framework fully functional

---

## 🚨 Getting Help

If something doesn't work:

1. **Check database status**
   ```bash
   make db-status
   ```

2. **View logs**
   ```bash
   docker-compose logs postgres
   ```

3. **Try full reset**
   ```bash
   make clean-all
   docker-compose up -d
   make test
   ```

4. **Read detailed guide**
   - [DATABASE_SETUP.md](./DATABASE_SETUP.md) - Full setup guide
   - [DEVELOPMENT.md](./DEVELOPMENT.md) - Development workflow
   - [Troubleshooting](./DATABASE_SETUP.md#troubleshooting) - Common issues

---

## ✨ Summary

| Step | Command | Time |
|------|---------|------|
| 1. Start DB | `docker-compose up -d` | 30s |
| 2. Run tests | `uv run pytest tests/` | 10s |
| 3. View results | `echo "✅ Done!"` | 1s |

**Total: ~40 seconds to first successful test run** 🎉

Enjoy using Confiture! 🍓
