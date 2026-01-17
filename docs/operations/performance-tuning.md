# Confiture Performance Tuning Guide

This guide provides optimization strategies for PostgreSQL migrations with Confiture.

## Table of Contents

- [Connection Pooling](#connection-pooling)
- [Large Table Migrations](#large-table-migrations)
- [Index Operations](#index-operations)
- [Lock Management](#lock-management)
- [Monitoring & Metrics](#monitoring--metrics)
- [Benchmarking](#benchmarking)

---

## Connection Pooling

### Configuration

```yaml
# confiture.yaml
connection:
  pool:
    min_size: 2        # Minimum connections to maintain
    max_size: 10       # Maximum connections allowed
    max_idle_time: 300 # Close idle connections after 5 minutes
    max_lifetime: 3600 # Recycle connections after 1 hour
```

### Sizing Guidelines

| Workload | Migrations | min_size | max_size | Notes |
|----------|------------|----------|----------|-------|
| Light | < 10 | 1 | 5 | Development, small projects |
| Medium | 10-50 | 2 | 10 | Standard production |
| Heavy | 50-100 | 5 | 20 | Large monoliths |
| Parallel | 100+ | 10 | 50 | Microservices, parallel runs |

### Pool Monitoring

```bash
# Check pool statistics
confiture pool stats
```

**Output:**
```
Connection Pool Statistics
==========================
Active connections:  2
Idle connections:    3
Waiting requests:    0
Total created:       15
Total recycled:      5
Max size:            10
```

**Healthy indicators:**
- `Waiting requests` should be 0
- `Active` should be < `max_size`
- `Idle` should be > 0

**Unhealthy indicators:**
- `Waiting requests` > 0 (pool exhausted)
- `Active` = `max_size` (at capacity)

### External Pooler (PgBouncer)

For high-concurrency environments:

```ini
# pgbouncer.ini
[databases]
mydb = host=localhost dbname=mydb

[pgbouncer]
listen_addr = 127.0.0.1
listen_port = 6432
auth_type = md5
auth_file = /etc/pgbouncer/userlist.txt

# Pool settings
pool_mode = transaction      # Best for migrations
max_client_conn = 200
default_pool_size = 25
min_pool_size = 5
reserve_pool_size = 5

# Timeouts
server_idle_timeout = 600
server_lifetime = 3600
```

**Confiture with PgBouncer:**
```bash
export DATABASE_URL="postgresql://user:pass@localhost:6432/mydb"
confiture migrate up
```

---

## Large Table Migrations

### Decision Matrix

| Table Size | Rows | Strategy | Example |
|------------|------|----------|---------|
| Small | < 100K | Direct DDL | `ALTER TABLE ADD COLUMN` |
| Medium | 100K - 1M | Batched | `BatchedMigration` |
| Large | 1M - 10M | Batched + Off-peak | Scheduled maintenance |
| Very Large | 10M - 100M | Online tools | pg_repack, pt-osc |
| Huge | > 100M | Blue-green | Full schema swap |

### Batched Operations

```python
from confiture.core.large_tables import BatchedMigration, BatchConfig

def up(connection):
    config = BatchConfig(
        batch_size=10000,           # Rows per batch
        sleep_between_batches=0.1,  # 100ms pause
        progress_callback=print,     # Optional progress reporting
    )

    batched = BatchedMigration(connection, config)

    # Add column with default (backfills in batches)
    result = batched.add_column_with_default(
        table="users",
        column="status",
        column_type="TEXT",
        default="'active'",
    )

    print(f"Processed {result.processed_rows} rows in {result.elapsed_time:.2f}s")
```

### Batch Size Guidelines

| Server RAM | CPU Cores | Recommended Batch Size |
|------------|-----------|------------------------|
| 4 GB | 2 | 5,000 |
| 8 GB | 4 | 10,000 |
| 16 GB | 8 | 25,000 |
| 32 GB+ | 16+ | 50,000 |

### Backfill Operations

```python
def up(connection):
    config = BatchConfig(
        batch_size=10000,
        sleep_between_batches=0.2,
    )
    batched = BatchedMigration(connection, config)

    # Step 1: Add nullable column (instant)
    connection.execute("""
        ALTER TABLE orders ADD COLUMN total_with_tax NUMERIC
    """)

    # Step 2: Backfill in batches
    batched.backfill_column(
        table="orders",
        column="total_with_tax",
        expression="total * 1.2",
        where_clause="total_with_tax IS NULL",
    )

    # Step 3: Add NOT NULL constraint
    connection.execute("""
        ALTER TABLE orders ALTER COLUMN total_with_tax SET NOT NULL
    """)
```

### Delete in Batches

```python
def cleanup_old_data(connection):
    config = BatchConfig(batch_size=5000, sleep_between_batches=0.5)
    batched = BatchedMigration(connection, config)

    result = batched.delete_in_batches(
        table="audit_logs",
        where_clause="created_at < NOW() - INTERVAL '2 years'",
    )

    print(f"Deleted {result.processed_rows} rows")
```

---

## Index Operations

### CONCURRENTLY Is Essential

**Always use CONCURRENTLY for production indexes:**

```python
def up(connection):
    # CONCURRENTLY requires autocommit mode
    connection.autocommit = True

    with connection.cursor() as cur:
        cur.execute("""
            CREATE INDEX CONCURRENTLY idx_users_email
            ON users (email)
        """)
```

**Why CONCURRENTLY:**
- Regular `CREATE INDEX` locks the table for writes
- `CONCURRENTLY` allows reads and writes during creation
- Takes longer but doesn't block application

### Index Creation Estimates

| Table Size | Regular Index | CONCURRENTLY | Notes |
|------------|---------------|--------------|-------|
| 100K rows | 1-2 seconds | 5-10 seconds | Minimal impact |
| 1M rows | 10-30 seconds | 1-2 minutes | Schedule off-peak |
| 10M rows | 2-5 minutes | 10-20 minutes | Monitor closely |
| 100M rows | 20-60 minutes | 1-3 hours | Maintenance window |

### Monitor Index Creation

```sql
-- Check progress (PostgreSQL 12+)
SELECT
    phase,
    blocks_total,
    blocks_done,
    ROUND(100.0 * blocks_done / NULLIF(blocks_total, 0), 1) AS percent_done
FROM pg_stat_progress_create_index;
```

### Online Index Builder

```python
from confiture.core.large_tables import OnlineIndexBuilder

def up(connection):
    builder = OnlineIndexBuilder(connection)

    # Create index with monitoring
    builder.create_index_concurrently(
        table="orders",
        columns=["customer_id", "created_at"],
        index_name="idx_orders_customer_date",
    )
```

### Reindex Operations

```python
def maintenance(connection):
    builder = OnlineIndexBuilder(connection)

    # Rebuild bloated index
    builder.reindex_concurrently("idx_orders_customer_date")
```

---

## Lock Management

### Lock Timeouts

```yaml
# confiture.yaml
migration:
  lock_timeout: 30000      # 30 seconds - wait for locks
  statement_timeout: 300000 # 5 minutes - max query time
```

**Per-migration override:**
```python
__lock_timeout__ = 60000  # 60 seconds for this migration

def up(connection):
    # Long-running operation
    ...
```

### Avoiding Lock Contention

**1. Schedule during low traffic:**
```bash
# Cron for 3 AM Sunday
0 3 * * 0 confiture migrate up --lock-timeout 120000
```

**2. Break large migrations into smaller ones:**
```python
# Bad: Single migration touching multiple tables
def up(connection):
    connection.execute("ALTER TABLE users ADD COLUMN a TEXT")
    connection.execute("ALTER TABLE orders ADD COLUMN b TEXT")
    connection.execute("ALTER TABLE products ADD COLUMN c TEXT")

# Good: Separate migrations
# 001_add_users_column.py
# 002_add_orders_column.py
# 003_add_products_column.py
```

**3. Use short-lived locks:**
```python
def up(connection):
    # Add column (brief lock)
    connection.execute("ALTER TABLE users ADD COLUMN status TEXT")
    connection.commit()  # Release lock

    # Backfill (no exclusive lock)
    batched.backfill_column(...)
```

### Monitor Locks

```sql
-- Current locks
SELECT
    l.pid,
    a.usename,
    l.locktype,
    l.mode,
    l.granted,
    a.query
FROM pg_locks l
JOIN pg_stat_activity a ON l.pid = a.pid
WHERE NOT l.granted
ORDER BY a.query_start;

-- Lock waits
SELECT
    blocked.pid AS blocked_pid,
    blocked.query AS blocked_query,
    blocking.pid AS blocking_pid,
    blocking.query AS blocking_query
FROM pg_stat_activity blocked
JOIN pg_locks blocked_locks ON blocked.pid = blocked_locks.pid
JOIN pg_locks blocking_locks ON blocked_locks.locktype = blocking_locks.locktype
    AND blocked_locks.relation = blocking_locks.relation
    AND blocked_locks.pid != blocking_locks.pid
JOIN pg_stat_activity blocking ON blocking_locks.pid = blocking.pid
WHERE NOT blocked_locks.granted;
```

---

## Monitoring & Metrics

### Prometheus Metrics

```yaml
# confiture.yaml
observability:
  prometheus:
    enabled: true
    port: 9090
```

**Exposed Metrics:**

| Metric | Type | Description |
|--------|------|-------------|
| `confiture_migration_duration_seconds` | Histogram | Time to apply migrations |
| `confiture_migration_lock_wait_seconds` | Histogram | Time waiting for locks |
| `confiture_migration_total` | Counter | Total migrations applied |
| `confiture_migration_errors_total` | Counter | Failed migrations |
| `confiture_connection_pool_size` | Gauge | Current pool size |
| `confiture_connection_pool_waiting` | Gauge | Waiting for connection |

### Grafana Dashboards

**Migration Duration Trend:**
```promql
histogram_quantile(0.95,
    rate(confiture_migration_duration_seconds_bucket[5m])
)
```

**Lock Wait Time (P99):**
```promql
histogram_quantile(0.99,
    rate(confiture_migration_lock_wait_seconds_bucket[5m])
)
```

**Error Rate:**
```promql
rate(confiture_migration_errors_total[5m])
```

**Pool Utilization:**
```promql
confiture_connection_pool_size / confiture_connection_pool_max * 100
```

### Alerting Rules

```yaml
# prometheus-rules.yaml
groups:
  - name: confiture
    rules:
      - alert: MigrationTooSlow
        expr: histogram_quantile(0.95, rate(confiture_migration_duration_seconds_bucket[5m])) > 300
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Migrations taking too long"
          description: "P95 migration duration > 5 minutes"

      - alert: MigrationErrors
        expr: rate(confiture_migration_errors_total[5m]) > 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Migration failures detected"

      - alert: ConnectionPoolExhausted
        expr: confiture_connection_pool_waiting > 0
        for: 1m
        labels:
          severity: warning
        annotations:
          summary: "Connection pool has waiting requests"
```

---

## Benchmarking

### Running Benchmarks

```bash
# Benchmark all migrations
confiture benchmark \
    --migrations db/migrations/ \
    --iterations 3 \
    --output benchmark.json

# Benchmark specific migration
confiture benchmark \
    --migration 015_add_indexes \
    --iterations 5
```

**Output:**
```
Migration Benchmark Results
===========================

005_add_users:
  Mean:   1.23s
  Median: 1.18s
  Std:    0.15s
  Min:    1.05s
  Max:    1.45s

006_add_indexes:
  Mean:   45.30s
  Median: 44.80s
  Std:    2.10s
  Min:    42.50s
  Max:    48.20s
```

### Comparing Performance

```bash
# Compare two benchmark runs
confiture benchmark compare \
    --baseline benchmark_v1.json \
    --current benchmark_v2.json
```

**Output:**
```
Performance Comparison
======================

Migration              Baseline    Current    Change
005_add_users          1.20s       0.80s      -33% ✓
006_add_indexes        45.30s      12.10s     -73% ✓ (CONCURRENTLY)
007_backfill           120.50s     125.20s    +4%
015_new_migration      -           2.30s      NEW

Summary:
  Improved: 2
  Regressed: 0
  Unchanged: 1
  New: 1
```

### CI Integration

```yaml
# .github/workflows/benchmark.yml
name: Migration Benchmark

on:
  pull_request:
    paths:
      - 'db/migrations/**'

jobs:
  benchmark:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:15
        env:
          POSTGRES_PASSWORD: postgres
        ports:
          - 5432:5432

    steps:
      - uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install Confiture
        run: pip install confiture

      - name: Download baseline
        uses: actions/download-artifact@v4
        with:
          name: benchmark-baseline
        continue-on-error: true

      - name: Run benchmark
        env:
          DATABASE_URL: postgresql://postgres:postgres@localhost:5432/postgres
        run: |
          confiture benchmark --output benchmark-current.json

      - name: Compare (if baseline exists)
        run: |
          if [ -f benchmark-baseline.json ]; then
            confiture benchmark compare \
              --baseline benchmark-baseline.json \
              --current benchmark-current.json \
              --fail-on-regression 20  # Fail if >20% slower
          fi

      - name: Upload benchmark
        uses: actions/upload-artifact@v4
        with:
          name: benchmark-current
          path: benchmark-current.json
```

---

## Performance Checklist

### Before Production Migration

- [ ] Estimated duration calculated
- [ ] Maintenance window scheduled (if needed)
- [ ] Rollback plan documented
- [ ] Index operations use CONCURRENTLY
- [ ] Large tables use batched operations
- [ ] Lock timeouts configured appropriately
- [ ] Monitoring dashboards ready
- [ ] Alerts configured

### During Migration

- [ ] Monitor lock wait times
- [ ] Watch database CPU/memory
- [ ] Track migration progress
- [ ] Check application error rates
- [ ] Verify replication lag (if applicable)

### After Migration

- [ ] Verify migration completed
- [ ] Check application health
- [ ] Compare performance metrics
- [ ] Update benchmark baselines
- [ ] Document any issues

---

*Last updated: January 2026*
