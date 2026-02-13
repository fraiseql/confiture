# Error Reference Guide

Complete guide to understanding and fixing Confiture errors.

When something goes wrong, Confiture provides detailed error messages with step-by-step solutions. This guide explains each error type and how to fix it.

---

## Error Message Format

All Confiture errors follow this format:

```
❌ [Brief error description]

📋 CAUSE:
  [What caused this error to occur]

✅ HOW TO FIX:
  1. [First step to resolve]
  2. [Second step to resolve]
  3. [Additional steps...]

💡 EXAMPLES:
  $ [Command example 1]
  $ [Command example 2]

📚 LEARN MORE:
  [Link to detailed documentation]
```

**Example**:
```
❌ Database connection failed

📋 CAUSE:
  Cannot reach PostgreSQL database at the specified URL

✅ HOW TO FIX:
  1. Verify PostgreSQL is running: pg_isready localhost
  2. Check your DATABASE_URL parameter
  3. Verify username/password: psql -U postgres
  4. Check network connectivity: ping localhost

💡 EXAMPLES:
  $ confiture build --database-url postgresql://localhost/mydb
  $ export DATABASE_URL=postgresql://user:pass@localhost/mydb

📚 LEARN MORE:
  https://github.com/fraiseql/confiture/blob/main/docs/error-reference.md#db_connection_failed
```

---

## Database Connection Errors

### DB_CONNECTION_FAILED

**When it happens**: You try to run a command that needs database access (build with --sequential, migrate, seed apply) but Confiture can't connect to PostgreSQL.

**Common causes**:
- PostgreSQL is not running
- Database URL is incorrect
- Wrong host/port
- Network connectivity issues
- Firewall blocking access

**How to fix**:
1. **Verify PostgreSQL is running**
   ```bash
   pg_isready localhost
   # Output: localhost:5432 - accepting connections
   ```

2. **Check your DATABASE_URL**
   ```bash
   echo $DATABASE_URL
   # Should look like: postgresql://user:password@localhost:5432/dbname
   ```

3. **Test connection manually**
   ```bash
   psql postgresql://localhost/mydb
   # Should connect successfully
   ```

4. **Check network (for remote databases)**
   ```bash
   ping database.example.com
   nc -zv database.example.com 5432
   ```

**Examples**:
```bash
# Using environment variable
export DATABASE_URL=postgresql://user:pass@localhost/mydb
confiture build --sequential

# Using command-line flag
confiture build --database-url postgresql://localhost/mydb --sequential

# With non-standard port
confiture migrate up --database-url postgresql://localhost:5433/mydb
```

**Related**:
- [PostgreSQL installation guide](https://www.postgresql.org/download/)
- [Database connection troubleshooting](./guides/database-setup.md)

---

### DB_PERMISSION_DENIED

**When it happens**: The database user doesn't have required permissions for the operation.

**Common causes**:
- User can't create tables
- User can't create schemas
- User can't create migrations table
- User can't write to confiture_migrations table

**How to fix**:
1. **Connect as a privileged user**
   ```bash
   psql -U postgres postgresql://localhost/mydb
   ```

2. **Grant necessary permissions**
   ```sql
   -- Grant all permissions to a user
   ALTER USER myuser CREATEDB CREATEUSER;

   -- Or grant specific permissions
   GRANT CREATE ON DATABASE mydb TO myuser;
   GRANT USAGE ON SCHEMA public TO myuser;
   GRANT CREATE ON SCHEMA public TO myuser;
   ```

3. **Verify permissions**
   ```sql
   -- Check user privileges
   SELECT * FROM pg_user WHERE usename = 'myuser';
   ```

**Examples**:
```bash
# Fix permissions as postgres user
psql -U postgres -c "ALTER USER myuser CREATEDB;"

# Then try again with the user
confiture build --database-url postgresql://myuser:pass@localhost/mydb
```

**Related**:
- [PostgreSQL user management](https://www.postgresql.org/docs/current/sql-createrole.html)
- [Database permissions guide](./guides/database-permissions.md)

---

## File System Errors

### SCHEMA_DIR_NOT_FOUND

**When it happens**: The schema directory (where DDL files are stored) doesn't exist.

**Common causes**:
- Directory hasn't been created yet
- Wrong path specified
- Directory name typo (schema vs schemas)

**Default location**: `db/schema/`

**How to fix**:
1. **Create the directory**
   ```bash
   mkdir -p db/schema
   ```

2. **Create standard project structure**
   ```bash
   confiture init
   # Creates db/schema/, db/migrations/, db/seeds/, etc.
   ```

3. **Verify path**
   ```bash
   ls -la db/schema/
   # Should exist and be a directory
   ```

**Examples**:
```bash
# Create schema directory with subdirectories
mkdir -p db/schema/01_tables
mkdir -p db/schema/02_views
mkdir -p db/schema/03_functions

# Or use init to create everything at once
confiture init

# Then try building
confiture build
```

**Expected structure**:
```
db/
├── schema/
│   ├── 01_tables/
│   │   ├── users.sql
│   │   ├── posts.sql
│   │   └── comments.sql
│   ├── 02_views/
│   │   └── user_stats.sql
│   └── 03_functions/
│       └── calculate_age.sql
├── migrations/
├── seeds/
└── generated/
```

---

### MIGRATIONS_DIR_NOT_FOUND

**When it happens**: The migrations directory doesn't exist, but you're trying to run migrations.

**Default location**: `db/migrations/`

**How to fix**:
1. **Create the directory**
   ```bash
   mkdir -p db/migrations
   ```

2. **Use confiture init**
   ```bash
   confiture init
   ```

3. **Verify it exists**
   ```bash
   ls -la db/migrations/
   ```

**Examples**:
```bash
# Create migrations directory
mkdir -p db/migrations

# Generate your first migration
confiture migrate generate "initial schema"

# Apply migrations
confiture migrate up
```

---

### SEEDS_DIR_NOT_FOUND

**When it happens**: The seeds directory doesn't exist, but you're trying to load seed data.

**Default location**: `db/seeds/`

**How to fix**:
1. **Create the directory**
   ```bash
   mkdir -p db/seeds
   ```

2. **Or use confiture init**
   ```bash
   confiture init
   ```

3. **Add seed files**
   ```bash
   # Create seed files with INSERT statements
   cat > db/seeds/users.sql << EOF
   INSERT INTO users (name, email) VALUES
   ('Alice', 'alice@example.com'),
   ('Bob', 'bob@example.com');
   EOF
   ```

**Examples**:
```bash
# Create seeds directory
mkdir -p db/seeds

# Add seed data
echo "INSERT INTO users (name) VALUES ('Test User');" > db/seeds/users.sql

# Apply seeds
confiture seed apply
```

---

## Migration Errors

### MIGRATION_CONFLICT

**When it happens**: Multiple migration files have the same version number, creating ambiguity.

**Example**:
```
db/migrations/
├── 001_initial_schema.up.sql      ❌ CONFLICT
├── 001_create_users.up.sql         ❌ CONFLICT
└── 002_add_posts.up.sql            ✅ OK
```

**How to fix**:
1. **Identify duplicates**
   ```bash
   confiture migrate status
   # Shows which migrations have conflicts
   ```

2. **Rename conflicting files**
   ```bash
   # Rename second file to next available number
   mv db/migrations/001_create_users.up.sql db/migrations/002_create_users.up.sql
   mv db/migrations/002_add_posts.up.sql db/migrations/003_add_posts.up.sql
   ```

3. **Verify resolution**
   ```bash
   confiture migrate status
   # Should show no conflicts
   ```

**Examples**:
```bash
# Check for conflicts
confiture migrate validate

# Fix numbering
ls db/migrations/ | sort

# Rename to fix
for file in db/migrations/*.up.sql; do
  # Renumber as needed
  mv "$file" "fixed_$file"
done
```

**Prevention**:
- Use `confiture migrate generate` to auto-generate with next available number
- Follow naming convention: `NNN_description.up.sql`
- Review migrations before committing to version control

---

### SEED_VALIDATION_FAILED

**When it happens**: Seed files contain invalid SQL or problematic patterns.

**Common issues**:
- DDL statements (CREATE, ALTER, DROP) in seed files
- Double semicolons `;;`
- Missing ON CONFLICT clauses for UPSERTs
- Transaction control statements (BEGIN, COMMIT, ROLLBACK)

**How to fix**:
1. **Validate seed files**
   ```bash
   confiture seed validate
   # Shows specific errors
   ```

2. **Fix issues manually**
   ```bash
   # Remove DDL (use migrations instead)
   # Wrong: CREATE TABLE users (id INT);
   # Right: INSERT INTO users VALUES (...);
   ```

3. **Use auto-fix (if available)**
   ```bash
   confiture seed validate --fix
   ```

4. **Test with dry-run**
   ```bash
   confiture seed apply --dry-run
   ```

**Examples**:
```bash
# Bad seed file
cat > db/seeds/bad.sql << EOF
CREATE TABLE users (...);  -- ❌ DDL not allowed
INSERT INTO users VALUES (1, 'Alice');;  -- ❌ Double semicolon
EOF

# Good seed file
cat > db/seeds/good.sql << EOF
INSERT INTO users (id, name) VALUES (1, 'Alice');
INSERT INTO users (id, name) VALUES (2, 'Bob');
EOF

# Validate
confiture seed validate
confiture seed validate --format json  # Get detailed report
```

---

## SQL and Database Errors

### SQL_SYNTAX_ERROR

**When it happens**: A SQL statement has syntax errors (migrations, schemas, or seeds).

**Common causes**:
- Typos in keywords
- Unclosed parentheses
- Missing semicolons
- Invalid column/table names

**How to fix**:
1. **Find the problematic SQL**
   - Error message usually shows the SQL line
   - Check the file indicated in the error

2. **Validate SQL manually**
   ```bash
   # Test the SQL in psql
   psql postgresql://localhost/mydb -f db/migrations/001_schema.sql
   ```

3. **Check for common issues**
   - Parentheses matching
   - Semicolon at end of statement
   - Valid PostgreSQL keywords
   - Table/column names quoted if needed

**Examples**:
```bash
# Bad SQL
CREATE TABLE users (
  id INT PRIMARY KEY,
  name VARCHAR(100)
  -- Missing closing paren and semicolon
);

# Good SQL
CREATE TABLE users (
  id INT PRIMARY KEY,
  name VARCHAR(100)
);
```

---

### TABLE_ALREADY_EXISTS

**When it happens**: You try to create a table that already exists.

**Cause**: Migration or schema trying to CREATE TABLE that's already in the database.

**How to fix**:
1. **Use IF NOT EXISTS**
   ```sql
   CREATE TABLE IF NOT EXISTS users (
     id INT PRIMARY KEY,
     name VARCHAR(100)
   );
   ```

2. **Check if migration already applied**
   ```bash
   confiture migrate status
   ```

3. **Verify database state**
   ```sql
   \dt  -- List all tables in psql
   ```

**Examples**:
```bash
# Check table exists
psql -c "\dt users"

# Drop and recreate (development only)
psql -c "DROP TABLE IF EXISTS users;"
confiture migrate up
```

---

### FOREIGN_KEY_CONSTRAINT

**When it happens**: You try to insert data that violates a foreign key constraint.

**Causes**:
- Inserting child record without parent
- Parent table has no matching row
- Data type mismatch

**How to fix**:
1. **Verify referenced table exists**
   ```sql
   SELECT * FROM users WHERE id = 1;
   -- Should exist before inserting posts
   ```

2. **Check constraint definition**
   ```sql
   \d posts  -- Show table structure including constraints
   ```

3. **Load parent data first**
   ```bash
   # Load users before posts
   confiture seed apply --seeds-dir db/seeds/01_users
   confiture seed apply --seeds-dir db/seeds/02_posts
   ```

**Examples**:
```bash
# Seed file: users.sql (load first)
INSERT INTO users (id, name) VALUES (1, 'Alice');

# Seed file: posts.sql (load after)
INSERT INTO posts (user_id, title) VALUES (1, 'First Post');

# Apply in order
confiture seed apply
```

---

### INSUFFICIENT_DISK_SPACE

**When it happens**: Your disk is full and database operation can't complete.

**How to fix**:
1. **Check available disk space**
   ```bash
   df -h
   # Look for /, /var, /home partitions
   ```

2. **Find and clean up large files**
   ```bash
   du -sh /var/lib/postgresql/*/base/*
   # Find large table files
   ```

3. **Free up space**
   ```bash
   # Clean package cache
   apt-get clean

   # Remove old logs
   rm -rf /var/log/*.gz
   ```

4. **Retry operation**
   ```bash
   confiture build
   ```

**Prevention**:
- Monitor disk usage regularly
- Set up automatic cleanup of old backups
- Plan for database growth

---

### LOCK_TIMEOUT

**When it happens**: Migration can't acquire lock on database (another migration running).

**Causes**:
- Another migration process running
- Long-running query holding locks
- Deadlock situation

**How to fix**:
1. **Check active connections**
   ```sql
   SELECT pid, usename, query FROM pg_stat_activity
   WHERE state != 'idle';
   ```

2. **Wait for other operation to complete**
   - Find the process from step 1
   - Wait for it to finish

3. **Increase timeout**
   ```bash
   confiture migrate up --lock-timeout 60
   # Wait 60 seconds instead of 30
   ```

4. **Terminate blocking process (if safe)**
   ```sql
   SELECT pg_terminate_backend(pid)
   FROM pg_stat_activity
   WHERE query LIKE '%YOUR_QUERY%';
   ```

**Examples**:
```bash
# Monitor locks
watch 'psql -c "SELECT pid, usename, query FROM pg_stat_activity WHERE state != '"'"'idle'"'"';"'

# Migrate with longer timeout
confiture migrate up --lock-timeout 120

# Kill specific connection
psql -c "SELECT pg_terminate_backend(12345);"
```

---

## Quick Reference

| Error | Type | Severity | Fix Difficulty |
|-------|------|----------|-----------------|
| DB_CONNECTION_FAILED | Database | High | Easy |
| DB_PERMISSION_DENIED | Database | High | Medium |
| SCHEMA_DIR_NOT_FOUND | File System | High | Easy |
| MIGRATIONS_DIR_NOT_FOUND | File System | High | Easy |
| SEEDS_DIR_NOT_FOUND | File System | Medium | Easy |
| MIGRATION_CONFLICT | Migration | High | Medium |
| SEED_VALIDATION_FAILED | Migration | Medium | Medium |
| SQL_SYNTAX_ERROR | SQL | High | Medium |
| TABLE_ALREADY_EXISTS | SQL | Medium | Easy |
| FOREIGN_KEY_CONSTRAINT | Data | Medium | Medium |
| INSUFFICIENT_DISK_SPACE | System | High | Hard |
| LOCK_TIMEOUT | Database | Medium | Medium |

---

## Getting More Help

**For each error message**:
- Check the "💡 EXAMPLES" section for copy-paste commands
- Follow the "✅ HOW TO FIX" steps in order
- Use "📚 LEARN MORE" link for detailed documentation

**Additional resources**:
- [Troubleshooting Guide](./troubleshooting.md)
- [Database Setup](./guides/database-setup.md)
- [Migration Best Practices](./guides/02-incremental-migrations.md)
- [Seed Data Guide](./guides/seed-validation.md)
- [PostgreSQL Documentation](https://www.postgresql.org/docs/)

**Still stuck?**:
- Check the [GitHub Issues](https://github.com/evoludigit/confiture/issues)
- Review [Architecture Documentation](./architecture/)
- Check command help: `confiture build --help`

---

**Last Updated**: February 13, 2026
**Version**: 0.4.1+
**Status**: Comprehensive error documentation for Phase 2 M2
