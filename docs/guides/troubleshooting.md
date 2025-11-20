# Troubleshooting Guide

Common issues and solutions when using Confiture migrations.

---

## Migration Issues

### "No pending migrations" after schema changes

**Problem**: You made schema changes but `confiture migrate up` reports "No pending migrations. Database is up to date."

**Cause**: Confiture tracks applied migrations in the `confiture_migrations` table. If you manually modified the database schema (outside of migrations), the tracking state may be out of sync.

**Learn more**: See [Migration Tracking](../guides/medium-2-incremental-migrations.md#tracking-table) for details on how Confiture tracks migration state.

**Example scenario**: After running `DROP SCHEMA public CASCADE` to reset your database, migration tracking still shows migrations as "applied" even though the schema is empty.

**Solutions**:

1. **Check migration status**:
   ```bash
   confiture migrate status --config db/environments/local.yaml
   ```

2. **Use `--force` flag** (for testing/development only):
   ```bash
   # ⚠️  WARNING: Use with caution!
   confiture migrate up --force --config db/environments/local.yaml
   ```

   **Output**:
   ```
   ⚠️  Force mode enabled - skipping migration state checks
   This may cause issues if applied incorrectly. Use with caution!

   📦 Force mode: Found 3 migration(s) to apply

   ⚡ Applying 001_create_users... ✅
   ⚡ Applying 002_add_user_bio... ✅
   ⚡ Applying 003_add_timestamps... ✅

   ✅ Force mode: Successfully applied 3 migration(s)!
   ⚠️  Remember to verify your database state after force application
   ```

   The `--force` flag skips migration state checks and reapplies all migrations. This is useful for:
   - Development workflows where you frequently drop/recreate databases
   - Testing migration scripts
   - Recovery after manual schema modifications

3. **Complete workflow example** (from issue #4):
   ```bash
   # 1. Build initial schema
   confiture build --env local

   # 2. Apply migrations normally
   confiture migrate up --config db/environments/local.yaml

   # 3. Manually drop schema (simulating testing scenario)
   psql -d your_database -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"

   # 4. Normal migrate fails (tracking still shows "applied")
   confiture migrate up --config db/environments/local.yaml
   # Output: "✅ No pending migrations. Database is up to date."

   # 5. Force reapplication
   confiture migrate up --force --config db/environments/local.yaml
   # Output: Successfully reapplies all migrations
   ```

4. **Reset migration tracking** (destructive):
   ```bash
   # Drop migration tracking table (removes all migration history)
   psql -d your_database -c "DROP TABLE IF EXISTS confiture_migrations CASCADE;"

   # Reinitialize tracking
   confiture migrate up --config db/environments/local.yaml
   ```

### Migration fails with "already applied"

**Problem**: `confiture migrate up` fails with "Migration X is already applied".

**Cause**: Migration tracking shows the migration was already applied, but the actual database schema may be different.

**Solutions**:

1. **Check what was actually applied**:
   ```bash
   confiture migrate status --config db/environments/local.yaml
   ```

2. **Verify database state**:
   ```sql
   -- Check if migration changes are actually present
   SELECT column_name FROM information_schema.columns
   WHERE table_name = 'your_table' AND column_name = 'expected_column';
   ```

3. **Use force mode** (if safe):
   ```bash
   confiture migrate up --force --config db/environments/local.yaml
   ```

### Migration rollback fails

**Problem**: `confiture migrate down` fails or doesn't work as expected.

**Cause**: Rollback SQL may be incorrect, or database state may have changed since migration was applied.

**Solutions**:

1. **Check rollback SQL** in the migration's `down()` method
2. **Manual rollback** if automatic rollback fails:
   ```bash
   # Connect to database
   psql -d your_database

   # Manually undo the changes
   -- Example: DROP COLUMN if migration added a column
   ALTER TABLE users DROP COLUMN IF EXISTS bio;
   ```

3. **Reset and reapply** (development only):
   ```bash
   # Rollback all migrations
   confiture migrate down --steps 999 --config db/environments/local.yaml

   # Reapply cleanly
   confiture migrate up --config db/environments/local.yaml
   ```

---

## Database Connection Issues

### "Connection refused"

**Problem**: Commands fail with "could not connect to server: Connection refused".

**Solutions**:

1. **Check PostgreSQL is running**:
   ```bash
   # Check if PostgreSQL is running
   pg_isready

   # Start PostgreSQL (varies by system)
   sudo systemctl start postgresql  # Linux
   brew services start postgresql   # macOS
   ```

2. **Verify connection details** in `db/environments/{env}.yaml`:
   ```yaml
   database_url: postgresql://user:password@localhost:5432/database_name
   # OR
   database:
     host: localhost
     port: 5432
     database: database_name
     user: postgres
     password: your_password
   ```

3. **Test connection manually**:
   ```bash
   psql -h localhost -U postgres -d your_database
   ```

### "Authentication failed"

**Problem**: "FATAL: password authentication failed for user 'postgres'".

**Solutions**:

1. **Check password** in environment config
2. **Use correct user** (may need to create user):
   ```sql
   CREATE USER your_user WITH PASSWORD 'your_password';
   GRANT ALL PRIVILEGES ON DATABASE your_database TO your_user;
   ```

3. **Check pg_hba.conf** for authentication method

---

## Schema Build Issues

### "File not found" errors

**Problem**: `confiture build` fails with "No such file or directory".

**Solutions**:

1. **Initialize project structure**:
   ```bash
   confiture init
   ```

2. **Check file paths** in environment config:
   ```yaml
   include_dirs:
     - db/schema/00_common
     - db/schema/10_tables
   ```

3. **Verify files exist**:
   ```bash
   find db/schema -name "*.sql"
   ```

### Build produces empty or incorrect schema

**Problem**: Generated schema file is empty or missing expected tables.

**Solutions**:

1. **Check include_dirs** configuration
2. **Verify SQL file syntax** (invalid SQL may be skipped)
3. **Check file permissions**
4. **Use `--show-hash`** to debug:
   ```bash
   confiture build --show-hash
   ```

---

## Development Workflow Issues

### Testing migrations safely

**Problem**: Need to test migrations without affecting production data.

**Solutions**:

1. **Use separate test database**:
   ```yaml
   # db/environments/test.yaml
   database_url: postgresql://localhost/confiture_test
   ```

2. **Force reapplication in development**:
   ```bash
   # After schema changes, force reapply
   confiture migrate up --force --config db/environments/local.yaml
   ```

3. **Clean rebuild for testing**:
   ```bash
   # Drop and recreate database
   psql -c "DROP DATABASE IF EXISTS confiture_test;"
   psql -c "CREATE DATABASE confiture_test;"

   # Rebuild from schema
   confiture build --env test
   psql -d confiture_test -f db/generated/schema_test.sql

   # Apply migrations
   confiture migrate up --config db/environments/test.yaml
   ```

---

## Performance Issues

### Migrations are slow

**Problem**: `confiture migrate up` takes too long.

**Solutions**:

1. **Check migration SQL** - optimize slow queries
2. **Add indexes** in separate migrations
3. **Use transactions** (automatic in Confiture)
4. **Batch operations** where possible

### Schema builds are slow

**Problem**: `confiture build` takes too long for large schemas.

**Solutions**:

1. **Use `--schema-only`** to skip seed data
2. **Optimize SQL files** (remove unnecessary comments)
3. **Use Rust performance layer** (automatic in v0.3+)

---

## Best Practices

### When to use `--force`

**✅ Safe uses**:
- Local development with frequent schema drops
- Testing migration scripts
- CI/CD pipelines with fresh databases
- Recovery after known-safe manual changes

**❌ Avoid in production**:
- Never use `--force` in production
- Never use `--force` with untested migrations
- Never use `--force` on shared databases

### Migration safety checklist

Before applying migrations:

1. **Backup database**:
   ```bash
   pg_dump -Fc myapp_production > backup_$(date +%Y%m%d_%H%M%S).dump
   ```

2. **Test in staging**:
   ```bash
   confiture migrate up --config staging.yaml
   ```

3. **Check rollback**:
   ```bash
   confiture migrate down --config staging.yaml
   ```

4. **Verify data integrity**:
   ```sql
   -- Run your data validation queries
   SELECT COUNT(*) FROM users;
   ```

### Recovery procedures

**After failed migration in production**:

1. **Don't panic** - Confiture uses transactions
2. **Check what was applied**:
   ```bash
   confiture migrate status --config production.yaml
   ```

3. **Rollback if safe**:
   ```bash
   confiture migrate down --steps 1 --config production.yaml
   ```

4. **Manual recovery** if rollback fails:
   - Restore from backup
   - Apply fixes manually
   - Reinitialize migration tracking

---

## Getting Help

If you're still stuck:

1. **Check the logs** - Confiture provides detailed error messages
2. **Review migration files** - Verify SQL syntax and logic
3. **Test manually** - Run SQL commands directly in `psql`
4. **Check documentation** - See [CLI Reference](../reference/cli.md)
5. **File an issue** - [GitHub Issues](https://github.com/fraiseql/confiture/issues)

---

## Common Error Patterns

### SQL Syntax Errors

```
❌ Migration failed: syntax error at or near "BIO"
```

**Fix**: Check SQL syntax, quotes, and keywords.

### Permission Errors

```
❌ Migration failed: permission denied for table users
```

**Fix**: Grant proper permissions to migration user.

### Constraint Violations

```
❌ Migration failed: duplicate key value violates unique constraint
```

**Fix**: Check data before adding constraints, or use conditional logic.

### Connection Timeouts

```
❌ Migration failed: connection timeout
```

**Fix**: Check network, increase timeouts, or run during low-traffic periods.

---

*Last Updated: November 20, 2025*