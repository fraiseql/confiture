# Troubleshooting

Common issues and solutions when using Confiture.

---

## Migration Issues

### Orphaned migration files (silently ignored)

**Cause**: Migration files don't match the expected naming pattern and are silently ignored by Confiture.

**Problem**: Files like `001_initial_schema.sql` or `002_add_columns.sql` (without `.up.sql` suffix) are skipped:

```bash
$ ls db/migrations/
001_initial_schema.sql       ❌ SILENTLY IGNORED
002_add_columns.sql          ❌ SILENTLY IGNORED
003_add_indexes.up.sql       ✅ RECOGNIZED
```

When you apply migrations, only 003 is applied, but your code expects changes from 001 and 002, causing:
- Schema mismatches
- Application crashes
- Data inconsistencies

**Solutions**:

1. **Validate and auto-fix**:
   ```bash
   # Check for orphaned files
   confiture migrate validate

   # Preview fixes
   confiture migrate validate --fix-naming --dry-run

   # Actually fix the files
   confiture migrate validate --fix-naming
   ```

2. **Manual rename**:
   ```bash
   # Rename file with proper suffix
   mv db/migrations/001_initial_schema.sql db/migrations/001_initial_schema.up.sql
   mv db/migrations/002_add_columns.sql db/migrations/002_add_columns.up.sql
   ```

3. **Verify all migrations are recognized**:
   ```bash
   confiture migrate status
   # Should show all migration files you created
   ```

**Prevention**:
- Always use `.up.sql` and `.down.sql` suffixes for SQL migrations
- Add migration validation to your CI/CD pipeline
- Use `confiture migrate validate` before committing

**See**: [Migration Naming Best Practices](docs/guides/migration-naming-best-practices.md)

---

### "No pending migrations" after schema changes

**Cause**: Migration tracking is out of sync with actual schema.

**Solutions**:

1. Check status:
   ```bash
   confiture migrate status
   ```

2. Use `--force` (development only):
   ```bash
   confiture migrate up --force
   ```

3. Reset tracking (destructive):
   ```bash
   psql -c "DROP TABLE IF EXISTS tb_confiture CASCADE;"
   confiture migrate up
   ```

### "Migration already applied"

**Cause**: Tracking shows migration applied, but schema may differ.

**Solutions**:

1. Verify database state:
   ```sql
   SELECT column_name FROM information_schema.columns
   WHERE table_name = 'your_table';
   ```

2. Check migration history:
   ```sql
   SELECT * FROM tb_confiture ORDER BY applied_at DESC;
   ```

3. Remove incorrect entry (careful!):
   ```sql
   DELETE FROM tb_confiture WHERE version = '005_add_email';
   ```

### Migration rollback fails

**Solutions**:

1. Check rollback SQL in migration's `down()` method
2. Manual rollback:
   ```sql
   ALTER TABLE users DROP COLUMN IF EXISTS bio;
   ```
3. Reset and reapply (development only):
   ```bash
   confiture migrate down --steps 999
   confiture migrate up
   ```

### Foreign key violation during rollback

**Solutions**:

1. Rollback dependent tables first
2. Use CASCADE in rollback:
   ```python
   def down(connection):
       with connection.cursor() as cur:
           cur.execute("DROP TABLE users CASCADE")
   ```

---

## Connection Issues

### "Connection refused"

**Solutions**:

1. Check PostgreSQL is running:
   ```bash
   pg_isready -h localhost -p 5432
   ```

2. Start PostgreSQL:
   ```bash
   sudo systemctl start postgresql  # Linux
   brew services start postgresql   # macOS
   ```

3. Test connection:
   ```bash
   psql -h localhost -U postgres -d your_database
   ```

### "Authentication failed"

**Solutions**:

1. Verify DATABASE_URL
2. Check pg_hba.conf authentication method
3. Reset password:
   ```sql
   ALTER USER myuser WITH PASSWORD 'newpassword';
   ```

### "Too many connections"

**Solutions**:

1. Check connection count:
   ```sql
   SELECT count(*) FROM pg_stat_activity WHERE usename = 'confiture';
   ```

2. Increase limit:
   ```sql
   ALTER ROLE confiture CONNECTION LIMIT 50;
   ```

3. Use connection pooling (PgBouncer)

### "SSL connection required"

Add SSL to connection string:
```bash
export DATABASE_URL="postgresql://user:pass@host/db?sslmode=require"
```

---

## Locking Issues

### "Lock acquisition timeout"

**Solutions**:

1. Check for running migrations:
   ```sql
   SELECT pid, usename, query FROM pg_stat_activity
   WHERE query LIKE '%confiture%';
   ```

2. Check advisory locks:
   ```sql
   SELECT l.pid, a.query FROM pg_locks l
   JOIN pg_stat_activity a ON l.pid = a.pid
   WHERE l.locktype = 'advisory';
   ```

3. Increase timeout:
   ```bash
   confiture migrate up --lock-timeout 120000
   ```

### "Deadlock detected"

**Solutions**:

1. Batch updates with commits:
   ```python
   for batch in batches:
       update_batch(connection)
       connection.commit()
   ```

2. Use CONCURRENTLY for indexes:
   ```python
   connection.autocommit = True
   cur.execute("CREATE INDEX CONCURRENTLY idx_name ON table(column)")
   ```

---

## Performance Issues

### Migration taking too long

**Solutions**:

1. Check table size:
   ```sql
   SELECT pg_size_pretty(pg_table_size('large_table'));
   ```

2. Use batched operations:
   ```python
   from confiture.core.large_tables import BatchedMigration, BatchConfig

   config = BatchConfig(batch_size=10000, sleep_between_batches=0.1)
   batched = BatchedMigration(connection, config)
   ```

3. Create indexes concurrently:
   ```python
   connection.autocommit = True
   cur.execute("CREATE INDEX CONCURRENTLY ...")
   ```

### Query timeout

**Solutions**:

1. Increase timeout:
   ```bash
   confiture migrate up --statement-timeout 600000
   ```

2. Set per-migration timeout:
   ```python
   __timeout__ = 600  # seconds
   ```

---

## Schema Build Issues

### "File not found"

**Solutions**:

1. Initialize project:
   ```bash
   confiture init
   ```

2. Verify files exist:
   ```bash
   find db/schema -name "*.sql"
   ```

### Empty schema output

Check `include_dirs` in configuration matches actual directory structure.

---

## Kubernetes Issues

### Job keeps restarting

**Solutions**:

1. Check logs:
   ```bash
   kubectl logs -l job-name=confiture-migration --previous
   ```

2. Increase deadline:
   ```yaml
   job:
     activeDeadlineSeconds: 1800
   ```

3. Test database connectivity from pod:
   ```bash
   kubectl run -it --rm debug --image=postgres:15 -- \
     psql "$DATABASE_URL" -c "SELECT 1"
   ```

### Secret not found

```bash
kubectl create secret generic db-credentials \
  --from-literal=DATABASE_URL="postgresql://..." \
  -n your-namespace
```

---

## CI/CD Issues

### Dry run passes but deploy fails

**Causes**:
- Different PostgreSQL versions
- Missing extensions
- Data-dependent failures

**Solutions**:

1. Match PostgreSQL version in CI
2. Test with production-like data
3. Install required extensions

### Concurrent pipelines conflict

```yaml
# GitHub Actions
concurrency:
  group: migration-${{ github.ref }}
  cancel-in-progress: false  # Never cancel migrations!
```

---

## Common Error Patterns

### SQL Syntax Error

```
Migration failed: syntax error at or near "BIO"
```
Check SQL syntax, quotes, and reserved keywords.

### Permission Denied

```
Migration failed: permission denied for table users
```
Grant permissions to migration user.

### Constraint Violation

```
Migration failed: duplicate key value violates unique constraint
```
Check data before adding constraints.

---

## Best Practices

### When to use `--force`

**Safe**:
- Local development
- CI/CD with fresh databases
- Testing migration scripts

**Avoid**:
- Production
- Shared databases
- Untested migrations

### Safety Checklist

Before production migrations:

1. Backup database:
   ```bash
   pg_dump -Fc myapp > backup.dump
   ```

2. Test in staging:
   ```bash
   confiture migrate up --config staging.yaml
   ```

3. Test rollback:
   ```bash
   confiture migrate down --config staging.yaml
   ```

4. Verify data integrity

---

## Getting Help

1. Check logs with `--log-level DEBUG`
2. Review migration files
3. Test SQL directly in `psql`
4. [GitHub Issues](https://github.com/evoludigit/confiture/issues)
