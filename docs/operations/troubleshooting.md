# Confiture Troubleshooting Guide

This guide provides solutions for common issues encountered when using Confiture.

## Table of Contents

- [Connection Issues](#connection-issues)
- [Migration Issues](#migration-issues)
- [Locking Issues](#locking-issues)
- [Performance Issues](#performance-issues)
- [Kubernetes Issues](#kubernetes-issues)
- [CI/CD Issues](#cicd-issues)

---

## Connection Issues

### Problem: "Connection refused"

**Symptoms:**
```
psycopg.OperationalError: connection to server at "localhost" (127.0.0.1), port 5432 failed: Connection refused
```

**Causes & Solutions:**

1. **PostgreSQL not running:**
   ```bash
   # Check PostgreSQL status
   pg_isready -h localhost -p 5432

   # Start PostgreSQL (Linux systemd)
   sudo systemctl start postgresql

   # Start PostgreSQL (macOS Homebrew)
   brew services start postgresql
   ```

2. **Wrong connection parameters:**
   ```bash
   # Verify DATABASE_URL
   echo $DATABASE_URL

   # Test connection directly
   psql "$DATABASE_URL" -c "SELECT 1"
   ```

3. **Firewall blocking:**
   ```bash
   # Check port accessibility
   nc -zv localhost 5432

   # Check firewall rules (Linux)
   sudo iptables -L -n | grep 5432
   ```

4. **PostgreSQL not listening on expected interface:**
   ```bash
   # Check postgresql.conf
   grep listen_addresses /etc/postgresql/*/main/postgresql.conf

   # Should be: listen_addresses = 'localhost' or '*'
   ```

### Problem: "Authentication failed"

**Symptoms:**
```
psycopg.OperationalError: FATAL: password authentication failed for user "myuser"
```

**Solutions:**

1. **Verify credentials:**
   ```bash
   # Test with psql
   psql -U myuser -h localhost -d mydb
   ```

2. **Check pg_hba.conf:**
   ```bash
   # View authentication config
   sudo cat /etc/postgresql/*/main/pg_hba.conf

   # Should have line like:
   # host    all    all    127.0.0.1/32    md5
   ```

3. **Reset password if needed:**
   ```sql
   -- As superuser
   ALTER USER myuser WITH PASSWORD 'newpassword';
   ```

### Problem: "Too many connections"

**Symptoms:**
```
FATAL: too many connections for role "confiture"
```

**Solutions:**

1. **Check connection count:**
   ```sql
   SELECT count(*) FROM pg_stat_activity WHERE usename = 'confiture';
   SELECT rolconnlimit FROM pg_roles WHERE rolname = 'confiture';
   ```

2. **Increase role connection limit:**
   ```sql
   ALTER ROLE confiture CONNECTION LIMIT 50;
   ```

3. **Configure connection pooling:**
   ```yaml
   # confiture.yaml
   connection:
     pool:
       min_size: 2
       max_size: 10
   ```

4. **Use external connection pooler:**
   ```bash
   # PgBouncer configuration
   [databases]
   mydb = host=localhost dbname=mydb

   [pgbouncer]
   pool_mode = transaction
   max_client_conn = 100
   default_pool_size = 20
   ```

### Problem: "SSL connection required"

**Symptoms:**
```
FATAL: no pg_hba.conf entry for host "x.x.x.x", user "myuser", database "mydb", SSL off
```

**Solutions:**

1. **Add SSL to connection string:**
   ```bash
   export DATABASE_URL="postgresql://user:pass@host/db?sslmode=require"
   ```

2. **SSL mode options:**
   - `disable` - No SSL
   - `allow` - Try non-SSL first
   - `prefer` - Try SSL first
   - `require` - SSL required
   - `verify-ca` - Verify server certificate
   - `verify-full` - Verify server certificate and hostname

---

## Migration Issues

### Problem: "Migration already applied"

**Symptoms:**
```
Migration 005_add_email is already marked as applied
```

**Solutions:**

1. **Check migration status:**
   ```bash
   confiture migrate status
   ```

2. **If intentionally re-running:**
   ```bash
   # Rollback first
   confiture migrate down --target 004_previous_migration

   # Then apply
   confiture migrate up
   ```

3. **If migration table is incorrect:**
   ```sql
   -- View applied migrations
   SELECT * FROM confiture_migrations ORDER BY applied_at DESC;

   -- Remove incorrect entry (DANGEROUS - verify first!)
   DELETE FROM confiture_migrations WHERE version = '005_add_email';
   ```

### Problem: "Migration file not found"

**Symptoms:**
```
MigrationError: Migration file not found: 005_add_email.py
```

**Solutions:**

1. **Check file exists:**
   ```bash
   ls -la db/migrations/005_add_email.py
   ```

2. **Check migrations directory in config:**
   ```yaml
   # confiture.yaml
   migrations:
     directory: db/migrations  # Verify this path
   ```

3. **Check file naming:**
   - Must match pattern: `NNN_description.py`
   - Example: `005_add_email.py`, `010_create_orders.py`

### Problem: "Syntax error in migration"

**Symptoms:**
```
MigrationError: Error in 005_add_email.py
  SyntaxError: invalid syntax (line 15)
```

**Solutions:**

1. **Check Python syntax:**
   ```bash
   python -m py_compile db/migrations/005_add_email.py
   ```

2. **Validate migration structure:**
   ```python
   # Required structure
   def up(connection):
       """Apply migration."""
       with connection.cursor() as cur:
           cur.execute("...")

   def down(connection):
       """Rollback migration."""
       with connection.cursor() as cur:
           cur.execute("...")
   ```

### Problem: "Foreign key violation during rollback"

**Symptoms:**
```
psycopg.IntegrityError: update or delete on table "users" violates foreign key constraint
```

**Solutions:**

1. **Rollback dependent tables first:**
   ```bash
   # Check dependencies
   confiture migrate status --show-dependencies

   # Rollback in correct order
   confiture migrate down --target 003_before_fk
   ```

2. **Temporarily disable FK checks (use with caution):**
   ```sql
   -- In migration down() function
   SET session_replication_role = 'replica';
   -- ... perform rollback ...
   SET session_replication_role = 'origin';
   ```

3. **Add CASCADE to drop:**
   ```python
   def down(connection):
       with connection.cursor() as cur:
           cur.execute("DROP TABLE users CASCADE")
   ```

---

## Locking Issues

### Problem: "Lock acquisition timeout"

**Symptoms:**
```
LockError: Could not acquire migration lock within 30000ms
```

**Solutions:**

1. **Check for running migrations:**
   ```sql
   SELECT pid, usename, application_name, state, query
   FROM pg_stat_activity
   WHERE query LIKE '%confiture%' OR application_name LIKE '%confiture%';
   ```

2. **Check advisory locks:**
   ```sql
   SELECT l.pid, a.usename, a.query, l.granted
   FROM pg_locks l
   JOIN pg_stat_activity a ON l.pid = a.pid
   WHERE l.locktype = 'advisory';
   ```

3. **Increase timeout:**
   ```bash
   confiture migrate up --lock-timeout 120000  # 2 minutes
   ```

4. **Force release stale lock (after confirming no migration running):**
   ```sql
   -- Get the lock class ID from Confiture config
   SELECT pg_advisory_unlock(12345);  -- Default lock ID
   ```

### Problem: "Deadlock detected"

**Symptoms:**
```
psycopg.OperationalError: deadlock detected
DETAIL: Process 1234 waits for AccessExclusiveLock on relation 5678
```

**Solutions:**

1. **Avoid long-running transactions:**
   ```python
   # Bad: Single long transaction
   def up(connection):
       update_million_rows(connection)  # Holds lock for minutes

   # Good: Batched with commits
   def up(connection):
       for batch in batches:
           update_batch(connection)
           connection.commit()
   ```

2. **Use CONCURRENTLY for indexes:**
   ```python
   def up(connection):
       connection.autocommit = True
       with connection.cursor() as cur:
           cur.execute("CREATE INDEX CONCURRENTLY idx_name ON table(column)")
   ```

3. **Schedule migrations during low-traffic:**
   ```bash
   # Cron for 3 AM
   0 3 * * * confiture migrate up
   ```

---

## Performance Issues

### Problem: "Migration taking too long"

**Symptoms:**
- Migration running for >10 minutes
- Database CPU high
- Application timeouts

**Solutions:**

1. **Check table size:**
   ```sql
   SELECT pg_size_pretty(pg_table_size('large_table'));
   SELECT reltuples AS row_estimate FROM pg_class WHERE relname = 'large_table';
   ```

2. **Use batched operations:**
   ```python
   from confiture.core.large_tables import BatchedMigration, BatchConfig

   def up(connection):
       config = BatchConfig(batch_size=10000, sleep_between_batches=0.1)
       batched = BatchedMigration(connection, config)
       batched.add_column_with_default(
           table="large_table",
           column="new_col",
           column_type="TEXT",
           default="'value'"
       )
   ```

3. **Create indexes concurrently:**
   ```python
   def up(connection):
       connection.autocommit = True
       with connection.cursor() as cur:
           cur.execute("""
               CREATE INDEX CONCURRENTLY idx_users_email
               ON users (email)
           """)
   ```

4. **Add progress monitoring:**
   ```bash
   # In another terminal
   watch -n 5 "psql -c \"SELECT * FROM pg_stat_progress_create_index\""
   ```

### Problem: "Database CPU spike during migration"

**Solutions:**

1. **Add sleep between batches:**
   ```python
   config = BatchConfig(
       batch_size=5000,
       sleep_between_batches=0.5  # 500ms between batches
   )
   ```

2. **Reduce batch size:**
   ```python
   config = BatchConfig(batch_size=1000)  # Smaller batches
   ```

3. **Run during maintenance window:**
   - Schedule for low-traffic period
   - Notify stakeholders
   - Have rollback plan ready

### Problem: "Query timeout"

**Symptoms:**
```
psycopg.OperationalError: canceling statement due to statement timeout
```

**Solutions:**

1. **Increase statement timeout:**
   ```bash
   confiture migrate up --statement-timeout 600000  # 10 minutes
   ```

2. **Set per-migration timeout:**
   ```python
   # In migration file
   __timeout__ = 600  # 10 minutes for this migration
   ```

3. **Break into smaller migrations:**
   - Split large operations
   - Each migration should complete in <5 minutes

---

## Kubernetes Issues

### Problem: "Migration job keeps restarting"

**Symptoms:**
- Job shows multiple restarts
- Pod in CrashLoopBackOff

**Solutions:**

1. **Check pod logs:**
   ```bash
   kubectl logs -l job-name=confiture-migration --previous
   ```

2. **Check job events:**
   ```bash
   kubectl describe job confiture-migration
   ```

3. **Increase activeDeadlineSeconds:**
   ```yaml
   # values.yaml
   job:
     activeDeadlineSeconds: 1800  # 30 minutes
   ```

4. **Check database connectivity from pod:**
   ```bash
   kubectl run -it --rm debug --image=postgres:15 -- \
     psql "$DATABASE_URL" -c "SELECT 1"
   ```

### Problem: "Health check failing"

**Symptoms:**
- Readiness probe failing
- Pod stuck in `Running` but not ready

**Solutions:**

1. **Check health endpoint manually:**
   ```bash
   kubectl port-forward pod/confiture-xxx 8080:8080
   curl localhost:8080/ready
   ```

2. **Increase probe timeouts:**
   ```yaml
   readinessProbe:
     httpGet:
       path: /ready
       port: 8080
     initialDelaySeconds: 30
     periodSeconds: 10
     timeoutSeconds: 5
   ```

3. **Check migration progress:**
   ```bash
   kubectl logs -f pod/confiture-xxx
   ```

### Problem: "Secret not found"

**Symptoms:**
```
Error: secret "db-credentials" not found
```

**Solutions:**

1. **Verify secret exists:**
   ```bash
   kubectl get secret db-credentials -n your-namespace
   ```

2. **Create secret if missing:**
   ```bash
   kubectl create secret generic db-credentials \
     --from-literal=DATABASE_URL="postgresql://..." \
     -n your-namespace
   ```

3. **Check secret key name:**
   ```yaml
   # values.yaml
   database:
     existingSecret: db-credentials
     existingSecretKey: DATABASE_URL  # Must match key in secret
   ```

---

## CI/CD Issues

### Problem: "Dry run passes but deploy fails"

**Causes:**

1. **Different PostgreSQL versions:**
   ```bash
   # Check versions
   psql -c "SELECT version()"
   ```

2. **Missing extensions:**
   ```sql
   -- Check required extensions
   SELECT * FROM pg_extension;

   -- Install if needed
   CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
   ```

3. **Data-dependent failures:**
   - Dry run uses empty database
   - Production has data that violates new constraints

**Solutions:**

1. **Use same PostgreSQL version in CI:**
   ```yaml
   services:
     postgres:
       image: postgres:15  # Match production version
   ```

2. **Test with production-like data:**
   - Use anonymized production dump
   - Generate realistic test data

### Problem: "Concurrent pipeline runs conflict"

**Symptoms:**
```
LockError: Another migration is in progress
```

**Solutions:**

1. **Disable concurrent runs:**
   ```yaml
   # GitHub Actions
   concurrency:
     group: migration-${{ github.ref }}
     cancel-in-progress: false  # Never cancel migrations!
   ```

2. **Use deployment locks:**
   ```yaml
   # GitLab CI
   deploy-production:
     resource_group: production-db
   ```

3. **Implement queue-based deployment:**
   - Use Argo Workflows with concurrency limits
   - Implement deployment queue in CI

---

## Getting Help

### Collect Debug Information

Before reporting issues, collect:

```bash
# Version info
confiture --version

# Configuration (sanitized)
confiture config show

# Status
confiture migrate status --verbose

# Recent logs
confiture migrate up --log-level DEBUG 2>&1 | tail -100
```

### Resources

- **Documentation**: https://confiture.readthedocs.io
- **GitHub Issues**: https://github.com/evoludigit/confiture/issues
- **Discussions**: https://github.com/evoludigit/confiture/discussions

---

*Last updated: January 2026*
