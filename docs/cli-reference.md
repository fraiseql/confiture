# CLI Reference

Complete reference for all Confiture commands.

## Table of Contents

- [Global Options](#global-options)
- [confiture init](#confiture-init)
- [confiture migrate status](#confiture-migrate-status)
- [confiture migrate generate](#confiture-migrate-generate)
- [confiture migrate diff](#confiture-migrate-diff)
- [confiture migrate up](#confiture-migrate-up)
- [confiture migrate down](#confiture-migrate-down)
- [Exit Codes](#exit-codes)
- [Environment Variables](#environment-variables)

---

## Global Options

Available for all commands:

```bash
confiture [COMMAND] [OPTIONS]
```

### `--version`

Show version and exit.

```bash
confiture --version
# Output: confiture version 0.1.0
```

### `--help`

Show help message and exit.

```bash
confiture --help
confiture migrate --help
confiture migrate up --help
```

---

## `confiture init`

Initialize a new Confiture project with directory structure and configuration files.

### Synopsis

```bash
confiture init [PATH]
```

### Arguments

| Argument | Description | Default | Required |
|----------|-------------|---------|----------|
| `PATH` | Project directory to initialize | `.` (current directory) | No |

### Examples

```bash
# Initialize in current directory
confiture init

# Initialize in specific directory
confiture init /path/to/project

# Initialize in new project
mkdir myapp && cd myapp
confiture init
```

### Created Structure

```
project/
├── db/
│   ├── schema/
│   │   ├── 00_common/
│   │   │   └── extensions.sql
│   │   └── 10_tables/
│   │       └── example.sql
│   ├── migrations/
│   └── environments/
│       └── local.yaml
└── db/README.md
```

### Created Files

#### `db/schema/00_common/extensions.sql`
Example file for PostgreSQL extensions.

#### `db/schema/10_tables/example.sql`
Example table definition (users table).

#### `db/environments/local.yaml`
Local development configuration:
```yaml
name: local
include_dirs:
  - db/schema/00_common
  - db/schema/10_tables
exclude_dirs: []

database:
  host: localhost
  port: 5432
  database: myapp_local
  user: postgres
  password: postgres
```

#### `db/README.md`
Documentation for the database directory structure.

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Error (e.g., directory already exists) |

### Notes

- Safe to run multiple times (prompts before overwriting)
- Creates numbered directories (`00_`, `10_`) for execution order
- Example files are templates - replace with your schema

---

## `confiture migrate status`

Show status of all migrations (applied vs pending).

### Synopsis

```bash
confiture migrate status [OPTIONS]
```

### Options

| Option | Description | Default |
|--------|-------------|---------|
| `--migrations-dir PATH` | Migrations directory | `db/migrations` |
| `--config PATH`, `-c PATH` | Configuration file (optional) | None |

### Examples

```bash
# Show migrations (file list only)
confiture migrate status

# Show migrations with applied/pending status
confiture migrate status --config db/environments/local.yaml

# Custom migrations directory
confiture migrate status --migrations-dir custom/migrations
```

### Output Without Config

```
                    Migrations
┏━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━┓
┃ Version ┃ Name               ┃ Status  ┃
┡━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━┩
│ 001     │ create_users       │ unknown │
│ 002     │ add_user_bio       │ unknown │
└─────────┴────────────────────┴─────────┘

📊 Total: 2 migrations
```

### Output With Config

```
                    Migrations
┏━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━┓
┃ Version ┃ Name               ┃ Status      ┃
┡━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━┩
│ 001     │ create_users       │ ✅ applied  │
│ 002     │ add_user_bio       │ ⏳ pending  │
└─────────┴────────────────────┴─────────────┘

📊 Total: 2 migrations (1 applied, 1 pending)
```

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Error (e.g., directory not found) |

### Notes

- Without `--config`: Shows file list only (no database connection)
- With `--config`: Connects to database to show applied/pending status
- Reads from `confiture_migrations` tracking table

---

## `confiture migrate generate`

Generate an empty migration template file.

### Synopsis

```bash
confiture migrate generate NAME [OPTIONS]
```

### Arguments

| Argument | Description | Required |
|----------|-------------|----------|
| `NAME` | Migration name (snake_case) | Yes |

### Options

| Option | Description | Default |
|--------|-------------|---------|
| `--migrations-dir PATH` | Migrations directory | `db/migrations` |

### Examples

```bash
# Generate migration
confiture migrate generate add_posts_table

# Custom directory
confiture migrate generate add_index --migrations-dir custom/migrations
```

### Output

```
✅ Migration generated successfully!

📄 File: db/migrations/001_add_posts_table.py

✏️  Edit the migration file to add your SQL statements.
```

### Generated File Structure

```python
"""Migration: add_posts_table

Version: 001
"""

from confiture.models.migration import Migration


class AddPostsTable(Migration):
    """Migration: add_posts_table."""

    version = "001"
    name = "add_posts_table"

    def up(self) -> None:
        """Apply migration."""
        # TODO: Add your SQL statements here
        # Example:
        # self.execute("CREATE TABLE users (id SERIAL PRIMARY KEY)")
        pass

    def down(self) -> None:
        """Rollback migration."""
        # TODO: Add your rollback SQL statements here
        # Example:
        # self.execute("DROP TABLE users")
        pass
```

### Version Numbering

- First migration: `001`
- Second migration: `002`
- Automatically increments from existing migrations
- Zero-padded to 3 digits

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Error (e.g., invalid name) |

### Notes

- File naming: `{version}_{name}.py`
- Class naming: Converts snake_case to PascalCase
- Always implement both `up()` and `down()` methods

---

## `confiture migrate diff`

Compare two schema files and optionally generate a migration.

### Synopsis

```bash
confiture migrate diff OLD_SCHEMA NEW_SCHEMA [OPTIONS]
```

### Arguments

| Argument | Description | Required |
|----------|-------------|----------|
| `OLD_SCHEMA` | Path to old schema file | Yes |
| `NEW_SCHEMA` | Path to new schema file | Yes |

### Options

| Option | Description | Default |
|--------|-------------|---------|
| `--generate` | Generate migration from diff | `false` |
| `--name NAME` | Migration name (required with `--generate`) | None |
| `--migrations-dir PATH` | Migrations directory | `db/migrations` |

### Examples

```bash
# Compare two schemas
confiture migrate diff db/schema/old.sql db/schema/new.sql

# Compare and generate migration
confiture migrate diff old.sql new.sql --generate --name add_bio_column

# Custom migrations directory
confiture migrate diff old.sql new.sql \
    --generate \
    --name my_migration \
    --migrations-dir custom/migrations
```

### Output (No Changes)

```
✅ No changes detected. Schemas are identical.
```

### Output (With Changes)

```
📊 Schema differences detected:

┏━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Type         ┃ Details                                ┃
┡━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ ADD_COLUMN   │ Table: users, Column: bio (TEXT)       │
│ ADD_INDEX    │ Table: users, Index: idx_users_bio     │
└──────────────┴────────────────────────────────────────┘

📈 Total changes: 2
```

### Output (With `--generate`)

```
📊 Schema differences detected:
[... diff output ...]

✅ Migration generated: 002_add_bio_column.py
```

### Detected Change Types

| Change Type | Description |
|-------------|-------------|
| `ADD_TABLE` | New table created |
| `DROP_TABLE` | Table removed |
| `RENAME_TABLE` | Table renamed (with confidence score) |
| `ADD_COLUMN` | New column added |
| `DROP_COLUMN` | Column removed |
| `RENAME_COLUMN` | Column renamed (with confidence score) |
| `CHANGE_COLUMN_TYPE` | Column type changed |
| `CHANGE_NULLABLE` | Column nullable constraint changed |
| `CHANGE_DEFAULT` | Column default value changed |
| `ADD_INDEX` | Index created |
| `DROP_INDEX` | Index removed |

### Generated Migration Example

For `ADD_COLUMN`:
```python
def up(self) -> None:
    """Apply migration."""
    self.execute("ALTER TABLE users ADD COLUMN bio TEXT")

def down(self) -> None:
    """Rollback migration."""
    self.execute("ALTER TABLE users DROP COLUMN bio")
```

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Error (e.g., file not found, invalid SQL) |

### Notes

- Intelligent rename detection (uses similarity scoring)
- Always review generated migrations before applying
- Complex changes may need manual adjustment

---

## `confiture migrate up`

Apply pending migrations to the database.

### Synopsis

```bash
confiture migrate up [OPTIONS]
```

### Options

| Option | Description | Default |
|--------|-------------|---------|
| `--config PATH`, `-c PATH` | Configuration file | `db/environments/local.yaml` |
| `--migrations-dir PATH` | Migrations directory | `db/migrations` |
| `--target VERSION`, `-t VERSION` | Target version (applies up to this version) | None (apply all) |

### Examples

```bash
# Apply all pending migrations
confiture migrate up --config db/environments/local.yaml

# Apply up to specific version
confiture migrate up --config db/environments/local.yaml --target 003

# Short form
confiture migrate up -c db/environments/production.yaml

# Custom migrations directory
confiture migrate up --config local.yaml --migrations-dir custom/migrations
```

### Output (Success)

```
📦 Found 2 pending migration(s)

⚡ Applying 001_create_users... ✅
⚡ Applying 002_add_user_bio... ✅

✅ Successfully applied 2 migration(s)!
```

### Output (No Pending)

```
✅ No pending migrations. Database is up to date.
```

### Output (With Target)

```
📦 Found 3 pending migration(s)

⚡ Applying 001_create_users... ✅
⚡ Applying 002_add_user_bio... ✅
⏭️  Skipping 003_add_posts (after target)

✅ Successfully applied 2 migration(s)!
```

### Migration Execution

1. **Load migration module** - Dynamically import Python file
2. **Extract class** - Find Migration subclass
3. **Initialize** - Create instance with database connection
4. **Execute up()** - Run migration SQL in transaction
5. **Record** - Insert into `confiture_migrations` table
6. **Commit** - Commit transaction

### Tracking Table

Migrations are tracked in `confiture_migrations`:

```sql
CREATE TABLE confiture_migrations (
    id SERIAL PRIMARY KEY,
    version VARCHAR(255) NOT NULL UNIQUE,
    name VARCHAR(255) NOT NULL,
    applied_at TIMESTAMP NOT NULL DEFAULT NOW(),
    execution_time_ms INTEGER,
    checksum VARCHAR(64)
);
```

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success (all migrations applied) |
| 1 | Error (migration failed, connection failed, etc.) |

### Error Handling

If a migration fails:
- Transaction is **rolled back**
- Database remains in previous state
- No entry added to tracking table
- Error message displayed with details

### Notes

- Each migration runs in its own transaction
- Migrations are idempotent (safe to re-run if interrupted)
- Always test on development/staging before production
- Can be interrupted with Ctrl+C (current migration will complete or rollback)

---

## `confiture migrate down`

Rollback applied migrations.

### Synopsis

```bash
confiture migrate down [OPTIONS]
```

### Options

| Option | Description | Default |
|--------|-------------|---------|
| `--config PATH`, `-c PATH` | Configuration file | `db/environments/local.yaml` |
| `--migrations-dir PATH` | Migrations directory | `db/migrations` |
| `--steps N`, `-n N` | Number of migrations to rollback | `1` |

### Examples

```bash
# Rollback last migration
confiture migrate down --config db/environments/local.yaml

# Rollback last 3 migrations
confiture migrate down --config db/environments/local.yaml --steps 3

# Short form
confiture migrate down -c local.yaml -n 2

# Custom migrations directory
confiture migrate down --config local.yaml --migrations-dir custom/migrations
```

### Output (Success)

```
📦 Rolling back 1 migration(s)

⚡ Rolling back 002_add_user_bio... ✅

✅ Successfully rolled back 1 migration(s)!
```

### Output (Multiple)

```
📦 Rolling back 3 migration(s)

⚡ Rolling back 003_add_posts... ✅
⚡ Rolling back 002_add_user_bio... ✅
⚡ Rolling back 001_create_users... ✅

✅ Successfully rolled back 3 migration(s)!
```

### Output (No Applied)

```
⚠️  No applied migrations to rollback.
```

### Rollback Execution

1. **Get applied migrations** - Query `confiture_migrations` table
2. **Select last N** - Take last N applied migrations
3. **Reverse order** - Rollback in reverse order
4. **For each migration**:
   - Load migration module
   - Execute `down()` in transaction
   - Remove from tracking table
   - Commit transaction

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success (all migrations rolled back) |
| 1 | Error (rollback failed, connection failed, etc.) |

### Error Handling

If a rollback fails:
- Transaction is **rolled back**
- Database remains in previous state
- Tracking table entry remains
- Subsequent rollbacks are blocked until fixed

### Safety Notes

- ⚠️ **Destructive operation** - May delete data
- Always backup before rollback in production
- Test rollback in development first
- Some operations are irreversible (e.g., DROP TABLE)

### Best Practices

```python
# Good: Reversible
def up(self):
    self.execute("ALTER TABLE users ADD COLUMN bio TEXT")

def down(self):
    self.execute("ALTER TABLE users DROP COLUMN bio")

# Bad: Data loss in down()
def up(self):
    self.execute("ALTER TABLE users RENAME COLUMN name TO full_name")

def down(self):
    # This loses data if full_name contains different data!
    self.execute("ALTER TABLE users RENAME COLUMN full_name TO name")

# Better: Keep both columns temporarily
def up(self):
    self.execute("ALTER TABLE users ADD COLUMN full_name TEXT")
    self.execute("UPDATE users SET full_name = name")
    # Don't drop 'name' yet - do it in next migration after validation

def down(self):
    self.execute("ALTER TABLE users DROP COLUMN full_name")
```

---

## Exit Codes

Standard exit codes used by all Confiture commands:

| Code | Meaning | Example |
|------|---------|---------|
| 0 | Success | Migration applied successfully |
| 1 | Error | Migration failed, file not found, database connection error |
| 2 | Usage error | Missing required argument, invalid option |

### Checking Exit Codes

```bash
# Bash
confiture migrate up
if [ $? -eq 0 ]; then
    echo "Success"
else
    echo "Failed"
fi

# Or
confiture migrate up && echo "Success" || echo "Failed"
```

---

## Environment Variables

Confiture supports environment variable expansion in configuration files.

### Usage in Config Files

```yaml
# db/environments/production.yaml
name: production

database:
  host: ${DB_HOST}
  port: ${DB_PORT}
  database: ${DB_NAME}
  user: ${DB_USER}
  password: ${DB_PASSWORD}
```

### Setting Environment Variables

```bash
# Linux/macOS
export DB_HOST=production-db.example.com
export DB_PORT=5432
export DB_NAME=myapp_production
export DB_USER=myapp_user
export DB_PASSWORD=secret

confiture migrate up --config db/environments/production.yaml

# One-liner
DB_HOST=localhost DB_NAME=test confiture migrate up
```

```powershell
# Windows PowerShell
$env:DB_HOST = "production-db.example.com"
$env:DB_NAME = "myapp_production"

confiture migrate up --config db/environments/production.yaml
```

### Common Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `DB_HOST` | Database host | `localhost`, `db.example.com` |
| `DB_PORT` | Database port | `5432` |
| `DB_NAME` | Database name | `myapp_production` |
| `DB_USER` | Database user | `postgres`, `myapp_user` |
| `DB_PASSWORD` | Database password | `secret123` |

### .env Files (Optional)

Using python-dotenv or direnv:

```bash
# .env
DB_HOST=localhost
DB_PORT=5432
DB_NAME=myapp_local
DB_USER=postgres
DB_PASSWORD=postgres
```

```bash
# Load and run
set -a; source .env; set +a
confiture migrate up
```

---

## Configuration File Reference

### Complete Example

```yaml
# db/environments/production.yaml
name: production

# Schema directories (processed in order)
include_dirs:
  - db/schema/00_common
  - db/schema/10_tables
  - db/schema/20_views
  - db/schema/30_functions

# Exclude directories (optional)
exclude_dirs:
  - db/schema/scratch
  - db/schema/deprecated

# Database connection
database:
  host: ${DB_HOST:-localhost}
  port: ${DB_PORT:-5432}
  database: ${DB_NAME}
  user: ${DB_USER}
  password: ${DB_PASSWORD}

# Optional settings (future features)
# migration_table: confiture_migrations
# auto_backup: true
# backup_dir: db/backups
```

### Default Values

```yaml
${VAR:-default}  # Use default if VAR not set
${VAR}           # Error if VAR not set
```

---

## Tips & Tricks

### Dry Run (Manual)

Confiture doesn't have built-in dry-run, but you can:

```bash
# View migration SQL
cat db/migrations/001_create_users.py

# Or extract SQL programmatically
python -c "
from pathlib import Path
exec(Path('db/migrations/001_create_users.py').read_text())
# Inspect the up() method
"
```

### Batch Operations

```bash
# Apply migrations in CI/CD
confiture migrate up --config production.yaml || exit 1

# Chain commands
confiture migrate status -c local.yaml && \
confiture migrate up -c local.yaml && \
echo "Migrations complete"
```

### Migration Naming Conventions

```bash
# Good names
confiture migrate generate create_users_table
confiture migrate generate add_bio_column
confiture migrate generate add_email_index
confiture migrate generate migrate_old_data

# Avoid
confiture migrate generate migration1  # Too generic
confiture migrate generate fix          # Too vague
```

---

## See Also

- [Getting Started Guide](./getting-started.md) - Installation and tutorials
- [Migration Strategies](./migration-strategies.md) - When to use each approach
- [Examples](../examples/) - Sample projects

---

**Part of the FraiseQL family** 🍓

*Vibe-engineered with ❤️ by [evoludigit](https://github.com/evoludigit)*
