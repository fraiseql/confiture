# CLI Reference

Complete reference for all Confiture command-line interface commands.

---

## Global Options

Available for all commands:

```bash
--version       Show version and exit
--help          Show help message and exit
```

---

## `confiture init`

Initialize a new Confiture project with recommended directory structure.

### Usage

```bash
confiture init [PATH]
```

### Arguments

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `PATH` | Path | `.` (current directory) | Project directory to initialize |

### What It Creates

```
db/
├── schema/
│   ├── 00_common/
│   │   └── extensions.sql (example)
│   └── 10_tables/
│       └── example.sql (example users table)
├── migrations/
│   └── (empty, ready for migrations)
├── seeds/
│   ├── common/
│   │   └── 00_example.sql
│   ├── development/
│   └── test/
├── environments/
│   └── local.yaml (example configuration)
└── README.md (database documentation)
```

### Examples

```bash
# Initialize in current directory
confiture init

# Initialize in specific directory
confiture init /path/to/project

# Initialize and view structure
confiture init && tree db/
```

### Interactive Behavior

If the `db/` directory already exists, Confiture will:
1. Warn that files may be overwritten
2. Prompt for confirmation: "Continue? [y/N]"
3. Proceed only if you confirm

### Next Steps After Init

1. **Edit schema files** in `db/schema/`
2. **Configure environments** in `db/environments/`
3. **Build schema**: `confiture build`
4. **Generate migrations**: `confiture migrate diff`

---

## `confiture build`

Build complete schema from DDL files (Medium 1: Build from DDL).

This is the **fastest way** to create or recreate a database from scratch (<1 second for 1000 files).

### Usage

```bash
confiture build [OPTIONS]
```

### Options

| Option | Short | Type | Default | Description |
|--------|-------|------|---------|-------------|
| `--env` | `-e` | String | `local` | Environment to build (references `db/environments/{env}.yaml`) |
| `--output` | `-o` | Path | `db/generated/schema_{env}.sql` | Custom output file path |
| `--project-dir` | - | Path | `.` | Project directory containing `db/` folder |
| `--show-hash` | - | Flag | `false` | Display schema content hash after build |
| `--schema-only` | - | Flag | `false` | Build schema only, exclude seed data |
| `--validate-comments` | - | Flag | from env config | Override: enable comment validation |
| `--no-validate-comments` | - | Flag | from env config | Override: disable comment validation |
| `--fail-on-unclosed` | - | Flag | from env config | Override: fail on unclosed block comments |
| `--no-fail-on-unclosed` | - | Flag | from env config | Override: don't fail on unclosed comments |
| `--fail-on-spillover` | - | Flag | from env config | Override: fail on comment spillover |
| `--no-fail-on-spillover` | - | Flag | from env config | Override: don't fail on spillover |
| `--separator-style` | - | String | from env config | Override separator style (block_comment, line_comment, mysql, custom) |
| `--separator-template` | - | String | from env config | Custom separator template with {file_path} placeholder |

### How It Works

1. **Load environment config** from `db/environments/{env}.yaml`
2. **Discover SQL files** in configured `include_dirs` (alphabetical order)
3. **Concatenate files** with metadata headers
4. **Write output** to generated file
5. **Display summary** (file count, size, hash)

### Examples

```bash
# Build local environment (default)
confiture build
# Output: db/generated/schema_local.sql

# Build for production
confiture build --env production
# Output: db/generated/schema_production.sql

# Custom output location
confiture build --output /tmp/schema.sql

# Build with hash for change detection
confiture build --show-hash
# Shows: 🔐 Hash: a3f5c9d2e8b1...

# Build schema only (no seed data)
confiture build --schema-only

# Build from different project directory
confiture build --project-dir /path/to/project
```

### Comment Validation Flags

Override environment configuration for SQL comment validation:

```bash
# Enable comment validation (catches concatenation errors)
confiture build --validate-comments

# Disable comment validation
confiture build --no-validate-comments

# Strict validation: fail on unclosed block comments
confiture build --validate-comments --fail-on-unclosed

# Strict validation: fail if comment spills into next file
confiture build --validate-comments --fail-on-spillover

# Comprehensive validation
confiture build --validate-comments --fail-on-unclosed --fail-on-spillover
```

**When to use:**
- Use `--validate-comments` in CI/CD to catch schema concatenation issues early
- Use `--no-validate-comments` for legacy schemas with known comment issues
- Use `--fail-on-*` flags for strict production builds

### Separator Style Flags

Configure how files are separated in concatenated output:

```bash
# Block comment separators (safest, default)
confiture build --separator-style block_comment
# Result: /* File: db/schema/01_tables.sql */

# Line comment separators (faster, less visible)
confiture build --separator-style line_comment
# Result: -- File: db/schema/01_tables.sql

# MySQL-compatible separators
confiture build --separator-style mysql

# Custom separators with template
confiture build --separator-style custom --separator-template "\n/* {file_path} */\n"

# Override just the template (uses custom style if configured)
confiture build --separator-template "\n/* ===== {file_path} ===== */\n"
```

**Available styles:**
- `block_comment` - SQL block comments (/* ... */) - safest, most visible
- `line_comment` - SQL line comments (--) - faster, less visible
- `mysql` - MySQL-compatible separators
- `custom` - Custom template (requires `--separator-template`)

**Template placeholders:**
- `{file_path}` - Relative path to the SQL file

### Output Format

Generated SQL file includes:

```sql
-- Schema built by Confiture 🍓
-- Environment: local
-- Generated: 2025-10-12 14:30:00 UTC
-- Files: 42
-- Base directory: db/schema

-- File: 00_common/extensions.sql
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- File: 10_tables/users.sql
CREATE TABLE users (...);

-- ... more files ...
```

### Performance

- **Speed**: <1 second for 1000+ files
- **Deterministic**: Same input = same output (order guaranteed)
- **Cacheable**: Use `--show-hash` to detect changes

### Environment Configuration

The `--env` option loads configuration from `db/environments/{env}.yaml`:

```yaml
name: local
include_dirs:
  - db/schema/00_common
  - db/schema/10_tables
  - db/seeds/common  # Excluded with --schema-only
exclude_dirs: []

database:
  host: localhost
  port: 5432
  database: myapp_local
  user: postgres
  password: postgres
```

### Use Cases

- **Local development**: Fresh database in <1 second
- **CI/CD**: Build test databases quickly
- **Disaster recovery**: Recreate production schema
- **Documentation**: Generate single-file schema snapshot

### CI/CD Patterns

**Strict build for CI/CD:**
```bash
# Validate comments and use safe separators
confiture build --env ci --validate-comments --separator-style block_comment
```

**Production build (trust CI validation):**
```bash
# Skip validation for speed, but keep safe separators
confiture build --env production --no-validate-comments --separator-style block_comment
```

**Local development (permissive):**
```bash
# No validation, faster build
confiture build --env local --no-validate-comments
```

**Legacy schema support:**
```bash
# Disable strict checks for compatibility
confiture build --env legacy --no-validate-comments --no-fail-on-unclosed --no-fail-on-spillover
```

---

## `confiture build --dump` (cacheable artifact)

`confiture build` also emits a content-addressed `pg_dump` artifact for fast,
cached CI provisioning:

| Option | Description |
|---|---|
| `--dump <path>` | Also write a `pg_dump` artifact. A directory auto-names `schema_{env}.{profile}.{hash}.pgdump` inside it (cache by `db/` hash); a file path is used verbatim. Requires a server URL (`--database-url` or env). |
| `--dump-format custom\|directory` | `custom` = `-Fc` (default), `directory` = `-Fd` (parallel dump). |
| `--seed-profile <name>` | Apply only the named seed profile (see `seed.profiles`) during `--sequential` seed application and `--dump`. |

The artifact is restorable by [`confiture restore`](#confiture-restore). See the
[Parallel CI provisioning guide](../guides/parallel-ci-provisioning.md).

---

## `confiture test-db`

CI-path primitive for parallel-test database provisioning: build a template once,
hand out lock-free per-worker clones. See the
[Parallel CI provisioning guide](../guides/parallel-ci-provisioning.md).

| Subcommand | Description | Exit codes |
|---|---|---|
| `provision-template --template <name> [--env] [--from-artifact <path>] [--seed-profile <name>] [--force]` | Build/apply (or restore an artifact) into a template DB and stamp its `db/` hash. | 0 ok; 5 bad input/refused clobber; 4 build/restore failed |
| `clone --template <src> --target <dst> [--tablespace <ts>] [--no-sync-commit-off]` | Clone via `CREATE DATABASE … WITH TEMPLATE` (retries while the source is in use). `--tablespace` places the clone in a (tmpfs) tablespace, falling back to disk on any tablespace failure; `--no-sync-commit-off` keeps durable commits (default sets `synchronous_commit=off` on the clone). `--format json` redacts DSN passwords in `target_url`. | 0 ok; 4 clone failed |
| `ram-setup --tablespace <name> --location <dir> [--owner <user>] [--force]` | Create or idempotently reset a tmpfs tablespace for RAM clones (DROP+re-CREATE, dropping managed clones in it). Refuses a LOCATION outside `/dev/shm`/`/run` without `--force`. Prints a `sudo install -d …` command when it lacks the OS rights to prepare the dir. | 0 ok; 5 bad input / refused / **action required** (`action_required` flag set) |
| `drop --target <name> [--force]` | Drop a confiture-managed clone/template (refuses unmanaged DBs without `--force`). | 0 ok; 5 refused |
| `status --template <name> [--env]` | Report staleness vs the current `db/` hash. | **0 current; 1 stale/absent** |
| `list` | List confiture-managed templates and clones. | 0 |
| `prune --template <name>` | Drop every clone of a template (reap leaked clones). | 0 |

All accept `--database-url` (else the env config supplies the server URL),
`--env`, `--project-dir`, and `--format text\|json`.

---

## `confiture sync`

Copy data from a production database to a local/staging target (Medium 3), with
optional PII anonymization. See the [Production Sync
guide](../guides/03-production-sync.md).

### Usage

```bash
confiture sync --from <env|dsn> --to <env|dsn> [OPTIONS]
```

### Options

| Option | Description |
|--------|-------------|
| `--from` | Source database: an environment name (`db/environments/{name}.yaml`) or a DSN. **Required.** |
| `--to` | Target database: an environment name or a DSN. **Required.** |
| `--anonymize` | Apply PII anonymization rules during the copy. |
| `--anonymization-config` | Rules YAML (default: `db/sync/anonymization.yaml`). |
| `--tables` | Comma-separated tables to include (default: all). |
| `--exclude` | Comma-separated tables to exclude. |
| `--batch-size` | Rows per batch for anonymized inserts (default: 5000). |
| `--checkpoint` | Checkpoint file for resumable syncs. |
| `--resume` | Resume from `--checkpoint`, skipping completed tables. |
| `--format`, `-f` | Output format: `text` (default) or `json`. |

### Safety

Without `--anonymize` the copy is **verbatim** — real PII lands unmasked in the
target. The command prints a prominent warning (text → stderr; JSON → the
`warnings` array) so the risk is never silent. The anonymization rules file maps
each table to a list of `{column, strategy, seed}` rules, where `strategy` is one
of `email`, `phone`, `name`, `redact`, `hash`.

### Examples

```bash
# Basic sync (verbatim — warns about plaintext PII)
confiture sync --from production --to local

# With anonymization (db/sync/anonymization.yaml)
confiture sync --from production --to local --anonymize

# Specific tables, JSON output
confiture sync --from production --to staging --tables users,posts --format json

# Resumable long sync
confiture sync --from production --to staging --checkpoint sync.json
confiture sync --from production --to staging --resume --checkpoint sync.json
```

---

## `confiture migrate`

Migration management commands (Medium 2: Incremental Migrations).

All migration commands are subcommands of `confiture migrate`:

- `confiture migrate status` - View migration status
- `confiture migrate current` - Print the latest applied revision
- `confiture migrate generate` - Create new migration template
- `confiture migrate diff` - Compare schemas and detect changes
- `confiture migrate up` - Apply pending migrations
- `confiture migrate down` - Rollback applied migrations (relative, `--steps N`)
- `confiture migrate down-to` - Rollback to a specific revision (absolute)
- `confiture migrate preflight` - Pre-deploy safety check

### Connection source and precedence

`migrate up`, `down`, `down-to`, `current`, `status`, `verify`, and `preflight`
accept a direct PostgreSQL DSN via `--database-url` / `-d`, so tooling that
resolves a DSN at runtime no longer has to synthesize a temporary YAML file.

Since **0.20.0** (#152) the connection source follows a single, secure
contract — **explicit-and-singular wins; ambiguity fails loud**. Two env vars
are treated differently by intent: `CONFITURE_DATABASE_URL` is the *canonical*,
confiture-specific var (set on purpose); `DATABASE_URL` is the *ambient*,
ubiquitous one and must never silently clobber a config. Resolution order:

1. `--database-url <dsn>` flag — always wins (validated).
2. An **explicit** `--config`/`--env` **and** `CONFITURE_DATABASE_URL` both
   present → **error** `CONFIG_007` (exit 5). Two explicit sources are never
   silently reconciled — pick one, or pass `--no-config`.
3. An explicit `--config`/`--env` (no canonical var) → the config file. An
   ambient `DATABASE_URL` does **not** override an explicit config.
4. `CONFITURE_DATABASE_URL` while `--config` is only the **default** → the
   canonical var (it beats a *default* config).
5. A present config file (even the default) → the config; it beats the ambient
   `DATABASE_URL`. With no config present, the ambient `DATABASE_URL` is used.
6. `--no-config` suppresses config discovery entirely → the environment
   (`CONFITURE_DATABASE_URL`, else `DATABASE_URL`) is the **sole** DSN source;
   with neither set, `CONFIG_010` (exit 5). Use this for runtime-resolved DSNs
   that must not appear in `argv`.

When a DSN is supplied via flag or env var, **no YAML is required** — the
migrations directory falls back to `db/migrations` and the tracking table to
`tb_confiture`. A malformed DSN (not starting with `postgresql://` /
`postgres://`) fails with `CONFIG_003` (exit 5).

> **Mutating commands** (`up`, `down`, `down-to`) require an *intentional*
> source: a flag, the canonical var, an explicit/default config, or
> `--no-config`. They refuse to run against a merely-ambient `DATABASE_URL`
> (`CONFIG_010`) rather than silently migrating the wrong database.
>
> **`migrate status`** connects on any intentional source but stays in its
> informative "status-unknown" state (exit 0) when only an ambient
> `DATABASE_URL` is set — it never auto-connects to whatever `DATABASE_URL`
> happens to be in the environment.
>
> **SSH tunnels**: a `--config` YAML may define an `ssh_tunnel` block that
> rewrites the DSN. `--database-url` bypasses that — the flag is for
> directly-reachable databases. Tunnelled connections still require `--config`.
>
> **`migrate preflight`**: `--database-url` is the *tracking* DB used for
> pending-migration detection; it is distinct from `--against`, which is the
> throwaway database migrations are replayed into.

---

### `confiture migrate status`

Display migration status (pending vs applied).

#### Usage

```bash
confiture migrate status [OPTIONS]
```

#### Options

| Option | Short | Type | Default | Description |
|--------|-------|------|---------|-------------|
| `--migrations-dir` | - | Path | `db/migrations` | Directory containing migration files |
| `--config` | `-c` | Path | (none) | Config file to check applied status from database |

> **Note (v0.5.9+):** The `-c`/`--config` flag must appear _after_ `status`:
> `confiture migrate status -c config.yaml`
> Using the old form (`confiture migrate -c config.yaml status`) produces `No such option: -c`.

#### Examples

```bash
# Show all migrations (file-based status only)
confiture migrate status

# Show applied vs pending (requires database connection)
confiture migrate status --config db/environments/local.yaml
confiture migrate status -c db/environments/local.yaml  # short form (v0.5.9+: after subcommand)

# Custom migrations directory
confiture migrate status --migrations-dir custom/migrations
```

#### Output

**Without config (file list only):**

```
                 Migrations
┌─────────┬────────────────────┬─────────┐
│ Version │ Name               │ Status  │
├─────────┼────────────────────┼─────────┤
│ 001     │ create_users       │ unknown │
│ 002     │ add_user_bio       │ unknown │
│ 003     │ add_timestamps     │ unknown │
└─────────┴────────────────────┴─────────┘

📊 Total: 3 migrations
```

**With config (database status):**

```
                 Migrations
┌─────────┬────────────────────┬──────────────┐
│ Version │ Name               │ Status       │
├─────────┼────────────────────┼──────────────┤
│ 001     │ create_users       │ ✅ applied   │
│ 002     │ add_user_bio       │ ✅ applied   │
│ 003     │ add_timestamps     │ ⏳ pending   │
└─────────┴────────────────────┴──────────────┘

📊 Total: 3 migrations (2 applied, 1 pending)
```

#### Use Cases

- Check which migrations need to be applied
- Verify migration history before deployment
- Debug migration issues
- Document current database state

#### Exit Codes

| Code | Meaning |
|------|---------|
| `0` | All migrations applied (nothing pending), or no `--config` provided |
| `1` | Pending migrations exist in the target database |
| `2` | Tracking table not found in the target database |
| `3` | Fatal error (connection failure, bad config, permission denied) |

#### Scripting Example

```bash
confiture migrate status -c db/environments/prod.yaml
case $? in
  0) echo "Up to date" ;;
  1) echo "Pending migrations — run migrate up" ;;
  2) echo "Tracking table missing — run migrate up or migrate baseline" ;;
  3) echo "Fatal error" ; exit 1 ;;
esac
```

---

### `confiture migrate current`

Print the **latest applied** migration revision — a narrow, stable contract for
tooling ("what is deployed right now?") without parsing the full `migrate
status` payload.

| Option | Short | Type | Default | Description |
|--------|-------|------|---------|-------------|
| `--config` | `-c` | Path | `db/environments/local.yaml` | Configuration file |
| `--database-url` | `-d` | str | (none) | Tracking-DB DSN (see [Connection source and precedence](#connection-source-and-precedence)) |
| `--format` | `-f` | str | `text` | `text` (bare revision) or `json` |
| `--output` | `-o` | Path | (stdout) | Write output to a file |

Output:

- **text** — the bare revision string, or an empty line if none applied.
- **json** — `{revision, name, applied_at, checksum}`; `revision` is `null` when
  the tracking table exists but is empty.

Exit codes:

| Exit | Meaning |
|---|---|
| 0 | Current revision printed (or `null` when the tracking table is empty) |
| 2 | Tracking table absent — confiture not initialized on this database (`PRECON_1001`) |
| 3 | Database connection failed |

```bash
confiture migrate current -c db/environments/prod.yaml
confiture migrate current --database-url "$DATABASE_URL" --format json
```

`migrate current` is the narrow form; [`migrate status`](#confiture-migrate-status)
is the full applied/pending picture.

---

### `confiture migrate generate`

Create a new empty migration template.

#### Usage

```bash
confiture migrate generate NAME [OPTIONS]
```

#### Arguments

| Argument | Type | Required | Description |
|----------|------|----------|-------------|
| `NAME` | String | ✅ Yes | Migration name in snake_case (e.g., `add_user_bio`) |

#### Options

| Option | Short | Type | Default | Description |
|--------|-------|------|---------|-------------|
| `--migrations-dir` | - | Path | `db/migrations` | Directory to create migration file in |
| `--format`, `-f` | `-f` | String | `text` | Output format: `text` or `json` |
| `--force` | - | Flag | off | Overwrite existing migration file |
| `--dry-run` | - | Flag | off | Preview what would be created without writing files |
| `--verbose`, `-v` | `-v` | Flag | off | Show version calculation details |
| `--from` | - | Path | — | Old schema file (required with `--generator`) |
| `--to` | - | Path | — | New schema file (required with `--generator`) |
| `--generator` | - | String | — | Named external generator from `migration_generators` config |
| `--config`, `-c` | `-c` | Path | `db/environments/local.yaml` | Environment config file |

#### Examples

```bash
# Generate new migration
confiture migrate generate add_user_bio
# Creates: db/migrations/20260403120230_add_user_bio.py

# Custom migrations directory
confiture migrate generate add_timestamps --migrations-dir custom/migrations

# Use an external schema-diff tool (see External generators below)
confiture migrate generate add_email_column \
  --from db/schema/v1.sql \
  --to   db/schema/v2.sql \
  --generator schema_diff
```

#### External generators

You can plug any schema-diff tool into `confiture migrate generate` via the
`migration_generators` config key:

```yaml
# db/environments/local.yaml
migration:
  migration_generators:
    schema_diff:
      command: "pgdiff --from {from} --to {to} --output {output}"
      description: "Generate migration SQL from pgdiff"
```

Then run:

```bash
confiture migrate generate add_email_column \
  --from db/schema/v1.sql \
  --to   db/schema/v2.sql \
  --generator schema_diff
```

**Placeholders** interpolated by Confiture (shell-quoted absolute paths):

| Placeholder | Value |
|---|---|
| `{from}` | Absolute path to the old schema file |
| `{to}` | Absolute path to the new schema file |
| `{output}` | Absolute path where the tool must write its SQL |

Confiture reads `{output}`, strips any `BEGIN`/`COMMIT` wrappers (case-insensitive,
with or without semicolons), and writes the result as `{version}_{name}.up.sql` in
`db/migrations/`. An empty `{version}_{name}.down.sql` stub is also created.

Use `--dry-run` to preview the resolved command and target filename without executing:

```bash
confiture migrate generate add_email_column \
  --from db/schema/v1.sql \
  --to   db/schema/v2.sql \
  --generator schema_diff \
  --dry-run
# Resolved command: pgdiff --from '/abs/v1.sql' --to '/abs/v2.sql' --output '/abs/20260403120345_add_email_column.up.sql'
# Target file:      db/migrations/20260403120345_add_email_column.up.sql
```

#### Generated Template

```python
"""Migration: add_user_bio

Version: 003
"""

from confiture.models.migration import Migration


class AddUserBio(Migration):
    """Migration: add_user_bio."""

    version = "003"
    name = "add_user_bio"

    def up(self) -> None:
        """Apply migration."""
        # TODO: Add your SQL statements here
        # Example:
        # self.execute("ALTER TABLE users ADD COLUMN bio TEXT")
        pass

    def down(self) -> None:
        """Rollback migration."""
        # TODO: Add your rollback SQL statements here
        # Example:
        # self.execute("ALTER TABLE users DROP COLUMN bio")
        pass
```

#### Naming Conventions

**Good names** (descriptive, snake_case):
- `add_user_bio`
- `create_posts_table`
- `add_email_index`
- `rename_status_to_state`

**Bad names** (vague, unclear):
- `update` (too vague)
- `fix` (what fix?)
- `AddUserBio` (use snake_case, not PascalCase)

#### Workflow

1. **Generate**: `confiture migrate generate add_user_bio`
2. **Edit**: Add SQL to `up()` and `down()` methods
3. **Test**: `confiture migrate up --config test.yaml`
4. **Verify**: `confiture migrate status`
5. **Rollback** (if needed): `confiture migrate down`

---

### `confiture migrate diff`

Compare two schema files and show differences (schema diff detection).

Optionally generate a migration from the detected changes.

#### Usage

```bash
confiture migrate diff OLD_SCHEMA NEW_SCHEMA [OPTIONS]
```

#### Arguments

| Argument | Type | Required | Description |
|----------|------|----------|-------------|
| `OLD_SCHEMA` | Path | ✅ Yes | Path to old schema SQL file |
| `NEW_SCHEMA` | Path | ✅ Yes | Path to new schema SQL file |

#### Options

| Option | Short | Type | Default | Description |
|--------|-------|------|---------|-------------|
| `--generate` | - | Flag | `false` | Generate migration file from diff |
| `--name` | - | String | (none) | Migration name (required with `--generate`) |
| `--migrations-dir` | - | Path | `db/migrations` | Directory to generate migration in |

#### Examples

```bash
# Show differences only
confiture migrate diff old_schema.sql new_schema.sql

# Generate migration from diff
confiture migrate diff old_schema.sql new_schema.sql --generate --name update_users

# Custom migrations directory
confiture migrate diff old.sql new.sql \
  --generate \
  --name add_posts \
  --migrations-dir custom/migrations
```

#### Output (No Changes)

```
✅ No changes detected. Schemas are identical.
```

#### Output (With Changes)

```
📊 Schema differences detected:

┌──────────────┬─────────────────────────────────────────┐
│ Type         │ Details                                  │
├──────────────┼─────────────────────────────────────────┤
│ table_added  │ Table 'posts' added                     │
│ column_added │ Column 'users.bio' added (type: TEXT)   │
│ index_added  │ Index 'idx_users_email' added on users │
└──────────────┴─────────────────────────────────────────┘

📈 Total changes: 3

✅ Migration generated: 20260403120230_update_users.py
```

#### Detected Change Types

The differ detects:

- **Tables**: `table_added`, `table_removed`, `table_renamed`
- **Columns**: `column_added`, `column_removed`, `column_type_changed`, `column_renamed`
- **Indexes**: `index_added`, `index_removed`
- **Constraints**: `constraint_added`, `constraint_removed`
- **Functions**: `function_added`, `function_removed`, `function_changed`

#### Workflow with Build

```bash
# 1. Build current schema
confiture build --env local --output old.sql

# 2. Edit schema files in db/schema/
vim db/schema/10_tables/users.sql  # Add bio column

# 3. Build new schema
confiture build --env local --output new.sql

# 4. Generate migration from diff
confiture migrate diff old.sql new.sql --generate --name add_user_bio

# 5. Apply migration
confiture migrate up
```

#### Use Cases

- **Auto-generate migrations** from schema changes
- **Review changes** before committing
- **Detect drift** between environments
- **Document schema evolution**

---

### `confiture migrate up`

Apply pending migrations (forward migrations).

#### Usage

```bash
confiture migrate up [OPTIONS]
```

#### Options

| Option | Short | Type | Default | Description |
|--------|-------|------|---------|-------------|
| `--migrations-dir` | - | Path | `db/migrations` | Directory containing migration files |
| `--config` | `-c` | Path | `db/environments/local.yaml` | Configuration file with database credentials |
| `--target` | `-t` | String | (none) | Target migration version (applies all if not specified) |
| `--force` | - | Flag | `false` | Force migration application, skipping state checks |

#### Examples

```bash
# Apply all pending migrations
confiture migrate up

# Apply up to specific version
confiture migrate up --target 003

# Use custom config
confiture migrate up --config db/environments/production.yaml

# Custom migrations directory
confiture migrate up --migrations-dir custom/migrations

# Force apply all migrations (skip state checks)
confiture migrate up --force
```

#### Force Mode Behavior

The `--force` flag **skips migration state checks** and applies all migrations regardless of whether they've been applied before. This is useful for:

- **Testing workflows**: Reapplying migrations after manual schema drops
- **Development iteration**: Forcing reapplication during migration development
- **Recovery scenarios**: Rebuilding databases from scratch

**⚠️ Warning**: Force mode bypasses safety checks and may cause:
- Duplicate data or schema conflicts
- Performance issues from reapplying the same changes
- Inconsistent database state

**Use force mode only when you understand the risks and have verified the migrations are safe to reapply.**

#### Output (Success)

```
📦 Found 2 pending migration(s)

⚡ Applying 20260403120115_add_user_bio... ✅
⚡ Applying 20260403120230_add_timestamps... ✅

✅ Successfully applied 2 migration(s)!
```

#### Output (Force Mode)

```
⚠️  Force mode enabled - skipping migration state checks
This may cause issues if applied incorrectly. Use with caution!

📦 Force mode: Found 3 migration(s) to apply

⚡ Applying 20260403120000_create_users... ✅
⚡ Applying 20260403120115_add_user_bio... ✅
⚡ Applying 20260403120230_add_timestamps... ✅

✅ Force mode: Successfully applied 3 migration(s)!
⚠️  Remember to verify your database state after force application
```

#### Output (No Pending)

```
✅ No pending migrations. Database is up to date.
```

#### Output (Error)

```
📦 Found 2 pending migration(s)

⚡ Applying 20260403120115_add_user_bio... ✅
⚡ Applying 20260403120230_add_timestamps... ❌ Error: column "bio" already exists
```

#### Transaction Behavior

- Each migration runs in a **separate transaction**
- If a migration fails, **previous migrations remain applied**
- **Rollback** failed migration with `confiture migrate down`

#### Target Version Behavior

```bash
# Migrations: 001, 002, 003, 004, 005
# Applied: 001, 002
# Pending: 003, 004, 005

# Apply all pending
confiture migrate up
# Applies: 003, 004, 005

# Apply up to 004 only
confiture migrate up --target 004
# Applies: 003, 004
# Skips: 005
```

#### Use Cases

- **Local development**: Apply schema changes
- **CI/CD**: Automated database updates
- **Production deployment**: Apply migrations safely
- **Environment sync**: Update staging to match production

#### Exit Codes

| Code | Meaning |
|------|---------|
| `0` | All migrations applied successfully |
| `1` | Generic/unknown error |
| `2` | Validation or configuration error (bad flags, missing config) |
| `3` | Migration execution error (SQL failure, duplicate versions) |
| `6` | Lock/pool error (retriable — another process holds the lock) |

#### Scripting Example

```bash
confiture migrate up -c db/environments/prod.yaml
case $? in
  0) echo "Migrations applied successfully" ;;
  2) echo "Configuration error — check flags" ; exit 1 ;;
  3) echo "Migration failed — check SQL" ; exit 1 ;;
  6) echo "Lock timeout — retry later" ; sleep 10 ; exit 1 ;;
  *) echo "Unknown error" ; exit 1 ;;
esac
```

---

### `confiture migrate down`

Rollback applied migrations (reverse migrations).

#### Usage

```bash
confiture migrate down [OPTIONS]
```

#### Options

| Option | Short | Type | Default | Description |
|--------|-------|------|---------|-------------|
| `--migrations-dir` | - | Path | `db/migrations` | Directory containing migration files |
| `--config` | `-c` | Path | `db/environments/local.yaml` | Configuration file with database credentials |
| `--steps` | `-n` | Integer | `1` | Number of migrations to rollback |

#### Examples

```bash
# Rollback last migration
confiture migrate down

# Rollback last 3 migrations
confiture migrate down --steps 3

# Use custom config
confiture migrate down --config db/environments/staging.yaml

# Custom migrations directory
confiture migrate down --migrations-dir custom/migrations
```

#### Output (Success)

```
📦 Rolling back 2 migration(s)

⚡ Rolling back 20260403120230_add_timestamps... ✅
⚡ Rolling back 20260403120115_add_user_bio... ✅

✅ Successfully rolled back 2 migration(s)!
```

#### Output (No Applied Migrations)

```
⚠️  No applied migrations to rollback.
```

#### Rollback Order

Migrations are rolled back in **reverse order** (newest first):

```bash
# Applied migrations: 001, 002, 003, 004, 005

# Rollback 1 step
confiture migrate down --steps 1
# Rolls back: 005
# Remaining: 001, 002, 003, 004

# Rollback 3 steps
confiture migrate down --steps 3
# Rolls back: 005, 004, 003 (in that order)
# Remaining: 001, 002
```

#### Safety Considerations

⚠️ **Warning**: Rollbacks can be **destructive**:

- **Data loss**: `DROP TABLE` deletes all data
- **Production risk**: Always test rollbacks in staging first
- **Irreversible**: Some changes (like data type conversions) may lose information

**Best practices**:
1. **Test rollbacks** in development/staging before production
2. **Backup data** before rolling back in production
3. **Review `down()` methods** for destructive operations
4. **Use transactions** (automatic in Confiture)

#### Use Cases

- **Undo mistakes**: Revert failed migrations
- **Development iteration**: Test migration changes
- **Production hotfix**: Emergency rollback of problematic changes
- **Environment reset**: Return to known-good state

---

### `confiture migrate down-to`

Roll back to a **specific revision** (absolute), the counterpart to `migrate
down --steps N` (relative). Name the revision to return to — typically captured
earlier with [`migrate current`](#confiture-migrate-current) — and Confiture
computes the rollback set, validates that every required `.down.sql` exists
**before** touching the database, and rolls back newest→oldest under the
migration lock. If any required `.down.sql` is missing it refuses atomically:
**nothing is rolled back**.

```bash
confiture migrate down-to 20260101000001 -c db/environments/staging.yaml
confiture migrate down-to 20260101000001 --dry-run --format json
```

| Option | Short | Type | Default | Description |
|--------|-------|------|---------|-------------|
| `revision` | | str (arg) | — | Target revision to keep applied |
| `--migrations-dir` | | Path | `db/migrations` | Migrations directory |
| `--config` | `-c` | Path | `db/environments/local.yaml` | Configuration file |
| `--database-url` | `-d` | str | (none) | Tracking-DB DSN (see [precedence](#connection-source-and-precedence)) |
| `--dry-run` | | flag | off | Print the plan, apply nothing, exit 0 |
| `--format` | `-f` | str | `text` | `text` or `json` (`{from, to, rolled_back, skipped, errors}`) |
| `--output` | `-o` | Path | (stdout) | Write output to a file |

Edge cases and exit codes:

| Case | Exit | Behavior |
|---|---|---|
| `<revision>` == current | 0 | No-op ("already at `<revision>`") |
| `<revision>` newer than current | 3 | Refuse — "use `migrate up --target`" (`MIGR_100`) |
| `<revision>` unknown | 3 | Refuse — "unknown revision" (`MIGR_100`) |
| any required `.down.sql` missing | 8 | Refuse atomically, nothing applied (`ROLLBACK_600`) |

> `migrate down-to` (and `migrate down`) acquire the migration advisory lock for
> the duration of the rollback, so the applied-set read and the rollback are
> atomic with respect to a concurrent `migrate up`.

---

### `confiture migrate rebuild`

Rebuild database from DDL schema and bootstrap tracking table.

When staging/QA environments restored from production backups have large migration gaps (10+ pending), `migrate up` often fails due to lock exhaustion or cumulative DDL complexity. `rebuild` automates the manual workaround of: build DDL, apply with psql, hand-insert tracking rows.

#### Usage

```bash
confiture migrate rebuild [OPTIONS]
```

#### Options

| Option | Short | Type | Default | Description |
|--------|-------|------|---------|-------------|
| `--config` | `-c` | Path | `db/environments/local.yaml` | Configuration file |
| `--migrations-dir` | - | Path | `db/migrations` | Migrations directory |
| `--drop-schemas` | - | Flag | `false` | Drop all user schemas before rebuild |
| `--seed` | - | Flag | `false` | Apply seed files after DDL rebuild |
| `--backup-tracking` | - | Flag | `false` | Dump tracking table to JSON before clearing |
| `--verify` | - | Flag | `false` | Run status check after rebuild |
| `--dry-run` | - | Flag | `false` | Show what would happen |
| `--yes` | `-y` | Flag | `false` | Skip confirmation prompt |
| `--format` | `-f` | String | `text` | Output format: `text` or `json` |

#### Examples

```bash
# Drop all schemas, rebuild from DDL, bootstrap tracking
confiture migrate rebuild --drop-schemas --yes

# Preview what would happen without making changes
confiture migrate rebuild --dry-run

# Full rebuild with seeds and post-rebuild verification
confiture migrate rebuild --drop-schemas --seed --verify --yes

# Dump tracking table before rebuild (creates JSON backup file)
confiture migrate rebuild --backup-tracking --drop-schemas --yes
```

#### Process

1. **Backup** tracking table (if `--backup-tracking`)
2. **Drop** all user schemas (if `--drop-schemas`)
3. **Build** DDL from `db/schema/` via `SchemaBuilder`
4. **Create** tracking table and mark all migration files as applied
5. **Seed** (if `--seed`) — apply seed files after DDL rebuild
6. **Verify** (if `--verify`) — run status check to confirm 0 pending

#### Use Cases

- **Staging/QA refresh**: Environments restored from production backups with large migration gaps
- **Development reset**: Quickly rebuild a local database from scratch
- **CI/CD**: Rebuild test databases before running integration tests

#### Exit Codes

| Code | Meaning |
|------|---------|
| `0` | Rebuild completed successfully |
| `1` | Error (config not found, migrations dir not found, database error) |

---

### `confiture migrate validate`

Validate and fix migration file naming conventions.

Confiture only recognizes `.sql` files that match the expected naming pattern. This command helps identify and fix misnamed migration files that would be silently ignored.

#### Usage

```bash
confiture migrate validate [OPTIONS]
```

#### Options

| Option | Short | Type | Default | Description |
|--------|-------|------|---------|-------------|
| `--migrations-dir` | - | Path | `db/migrations` | Directory containing migration files |
| `--fix-naming` | - | Flag | `False` | Automatically rename orphaned migration files to match naming convention |
| `--require-grant-migration` | - | Flag | `False` | Verify each changed `GRANT`/`REVOKE` in the grant directory is carried by an accompanying migration (`.up.sql` or `.py`). Semantic match across table/schema/sequence/function objects; unverifiable grants degrade to a file-presence check with a surfaced note. See the [migrate validate guide](../guides/migrate-validate.md#--require-grant-migration). |
| `--allow-grant-only` | - | Flag | `False` | Suppress `--require-grant-migration` for build-only branches |
| `--dry-run` | - | Flag | `False` | Preview changes without actually renaming files |
| `--format` | `-f` | Text | `text` | Output format: `text` (default) or `json` |
| `--output` | `-o` | Path | None | Save output to file |

#### Examples

```bash
# Check for orphaned files
confiture migrate validate

# Preview what would be fixed
confiture migrate validate --fix-naming --dry-run

# Auto-fix orphaned file names
confiture migrate validate --fix-naming

# Output as JSON for CI/CD integration
confiture migrate validate --format json
confiture migrate validate --fix-naming --format json

# Verify changed grants are carried by an accompanying migration (pre-commit)
confiture migrate validate --require-grant-migration --staged
```

#### Recognized Migration File Patterns

Confiture only applies migrations that match these patterns:

```
✅ RECOGNIZED PATTERNS:
{NNN}_{name}.py           # Python class migration
{NNN}_{name}.up.sql       # Forward migration (SQL)
{NNN}_{name}.down.sql     # Rollback migration (SQL)

Examples:
20260403120000_create_users.py
20260403120115_add_email.up.sql
20260403120115_add_email.down.sql
20260403120230_create_posts.py

❌ NOT RECOGNIZED (Will be ignored):
20260403120000_create_users.sql      # Missing .up suffix
20260403120115_add_email.sql         # Missing .up suffix
```

#### Orphaned Files Detection

The validator scans for `.sql` files that don't match the expected pattern and warns about them:

```bash
$ confiture migrate validate
⚠️  WARNING: Orphaned migration files detected
These SQL files exist but won't be applied by Confiture:
  • 20260403120000_initial_schema.sql → rename to: 20260403120000_initial_schema.up.sql
  • 20260403120115_add_columns.sql → rename to: 20260403120115_add_columns.up.sql

To automatically fix these files, run:
  confiture migrate validate --fix-naming
```

#### Auto-Fix Capability

The `--fix-naming` flag automatically renames orphaned files to match the naming convention:

```bash
$ confiture migrate validate --fix-naming
✅ Fixed orphaned migration files:
  • 20260403120000_initial_schema.sql → 20260403120000_initial_schema.up.sql
  • 20260403120115_add_columns.sql → 20260403120115_add_columns.up.sql
```

**Important**: Files are renamed to `.up.sql` (forward migrations). For rollback migrations, rename to `.down.sql` manually.

#### Dry-Run Preview

Use `--dry-run` to preview changes before applying them:

```bash
$ confiture migrate validate --fix-naming --dry-run
📋 DRY-RUN: Would fix the following orphaned files:
  • 20260403120000_users.sql → 20260403120000_users.up.sql
  • 20260403120115_posts.sql → 20260403120115_posts.up.sql

# Files are NOT renamed during dry-run
```

#### JSON Output for CI/CD

Output as JSON for programmatic access:

```bash
# Check for orphaned files
$ confiture migrate validate --format json
{
  "status": "issues_found",
  "orphaned_files": [
    "20260403120000_initial_schema.sql",
    "20260403120115_add_columns.sql"
  ]
}

# Auto-fix and report results
$ confiture migrate validate --fix-naming --format json
{
  "status": "fixed",
  "fixed": [
    ["20260403120000_initial_schema.sql", "20260403120000_initial_schema.up.sql"],
    ["20260403120115_add_columns.sql", "20260403120115_add_columns.up.sql"]
  ],
  "errors": []
}
```

#### Safety Guarantees

- **Content preserved**: File contents are never modified, only filenames
- **No data loss**: Files are renamed, not deleted
- **Atomic operations**: Rename is atomic (all-or-nothing)
- **Error handling**: Reports specific errors for failures (e.g., target file exists)

#### Why This Matters

Silently ignored migration files create a dangerous scenario:

```
1. Developer writes migration: 20260403120000_add_users_table.sql (forgot .up suffix)
2. confiture scans migrations: Doesn't match pattern, silently skips
3. No error or warning: Developer thinks migration is discoverable
4. Deploy to production: Code expects new schema, database is old
5. Application crashes: Schema mismatch causes failures
```

**Solution**: Use `confiture migrate validate` in your CI/CD pipeline to catch these issues early.

#### Integration with Other Commands

The `migrate status` and `migrate up` commands automatically warn about orphaned files:

```bash
$ confiture migrate status
⚠️  WARNING: Orphaned migration files detected
  • 20260403120000_schema.sql → rename to: 20260403120000_schema.up.sql
```

---

### `confiture migrate preflight`

Pre-deploy safety check. Answers four questions before running `migrate up`:

1. Are all pending migrations **reversible**? (`.down.sql` exists)
2. Do any contain **non-transactional statements**? (`CREATE INDEX CONCURRENTLY`, `ALTER TYPE ... ADD VALUE`, etc.)
3. Are there **duplicate migration versions** on disk?
4. Have applied migration files been **tampered with**? (checksum verification, DB required)

#### Usage

```bash
confiture migrate preflight [OPTIONS]
```

#### Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--migrations-dir` | Path | `db/migrations` | Migrations directory |
| `--format`, `-f` | String | `table` | Output format: `table` or `json` |
| `--output`, `-o` | Path | stdout | Save the JSON report to a file (clean JSON, no progress chatter) |
| `--strict` | flag | off | Treat warnings as errors for exit purposes |

`--format json` (no `--against`) returns the **structured report**
`{ok, summary, issues[]}` (issue #148); each `issues[]` element is the shared
[issue object](error-codes.md#pflight_--preflight-report-issue-codes-148) with a
`PFLIGHT_*` code.

#### Exit Codes (no `--against`)

| Code | Meaning |
|------|---------|
| `0` | No error-severity issues (warnings alone are non-fatal unless `--strict`) |
| `7` | One or more error-severity issues (or, under `--strict`, any warning) |

A preflight that *crashes* (config / DB error) exits per the
[exit-code convention](exit-codes.md) (e.g. 5, 3) with the error envelope.

#### Examples

```bash
# Basic check
confiture migrate preflight

# JSON output for CI/CD — {ok, summary, issues[]}
confiture migrate preflight --format json

# Fail on warnings too
confiture migrate preflight --strict

# Custom migrations directory
confiture migrate preflight --migrations-dir custom/migrations
```

#### Table Output

```
Pre-flight Check
──────────────────────────────────────────────────────────
  Version    Name               Reversible  Transactional
  20260301   create_users       ✓           ✓
  20260302   add_status_enum    ✓           ✗ ALTER TYPE status ADD VALUE
  20260303   add_index          ✗           ✗ CREATE INDEX CONCURRENTLY: idx_users_email

Summary: 3 migrations checked
  ✗ 1 irreversible (missing .down.sql)
  ✗ 2 non-transactional statements
  ✓ No duplicate versions
  → Not safe to deploy with rollback guarantee
```

#### JSON Output

```json
{
  "safe_to_deploy": false,
  "all_reversible": false,
  "all_transactional": false,
  "has_duplicates": false,
  "has_checksum_mismatches": false,
  "checksum_verified": false,
  "migrations": [
    {
      "version": "20260301",
      "name": "create_users",
      "has_down": true,
      "reversible": true,
      "fully_transactional": true,
      "non_transactional_statements": [],
      "checksum": null
    }
  ],
  "duplicate_versions": {},
  "checksum_mismatches": []
}
```

#### Library API

```python
from confiture import Migrator

# Mode 1: Without context (all files, no checksum verification)
with Migrator.from_config("db/environments/prod.yaml") as m:
    result = m.preflight()

# Mode 2: Inside context (pending only + checksum verification)
with Migrator.from_config("db/environments/prod.yaml") as m:
    result = m.preflight()
    if not result.safe_to_deploy:
        for info in result.irreversible:
            print(f"Missing .down.sql: {info.version}_{info.name}")
        for info in result.non_transactional:
            print(f"Non-transactional: {info.version} — {info.non_transactional_statements}")

# Mode 3: Specific versions
result = m.preflight(versions=["20260301", "20260303"])
```

#### Non-Transactional Statements Detected

| Statement | Risk |
|-----------|------|
| `CREATE INDEX CONCURRENTLY` | Cannot run inside transaction |
| `DROP INDEX CONCURRENTLY` | Cannot run inside transaction |
| `ALTER TYPE ... ADD VALUE` | Non-transactional in PG < 16 |
| `REINDEX ... CONCURRENTLY` | Cannot run inside transaction |
| `CREATE DATABASE` / `DROP DATABASE` | Cannot run inside transaction |
| `VACUUM` | Cannot run inside transaction |
| `CLUSTER` | Cannot run inside transaction |

Detection uses **pglast** (PostgreSQL's C parser) when available, with a **regex fallback** for environments without the `[ast]` extra.

#### CI/CD Integration

```bash
# Gate deployment on preflight check
confiture migrate preflight --format json | jq -e '.safe_to_deploy' || {
  echo "Pre-flight check failed — aborting deployment"
  exit 1
}

# Allow non-transactional but require reversibility
result=$(confiture migrate preflight --format json)
if echo "$result" | jq -e '.all_reversible' > /dev/null; then
  confiture migrate up
else
  echo "Irreversible migrations detected — manual approval required"
  exit 1
fi
```

---

### `confiture migrate validate` - Git-Aware Schema Validation

Enable automatic validation of database schema changes using git history. Perfect for CI/CD pipelines, pre-commit hooks, and code review gates.

#### Git-Aware Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--check-drift` | Flag | `False` | Detect schema differences between git refs |
| `--require-migration` | Flag | `False` | Ensure DDL changes have migration files |
| `--check-acl-coverage` | Flag | `False` | Static: every `CREATE TABLE` in migrations must have a matching `GRANT` (same file or `db/7_grant/`). No-op when the config has no `acls:` block. See [ACL Coverage](../guides/acl-coverage.md) |
| `--base-ref` | String | `origin/main` | Reference point for comparison (branch, tag, or commit) |
| `--since` | String | None | Alias for `--base-ref` (e.g., `--since origin/dev`) |
| `--staged` | Flag | `False` | Only validate staged files (pre-commit hook mode) |

**`--check-acl-coverage`** runs the `ACL001` lint rule against the migrations directory. It exits 1 on any uncovered table and 0 otherwise. Compatible with `--format json`; violations are surfaced under `check: "acl_coverage"`.

```bash
# Static, no database connection.  Pre-merge gate.
confiture migrate validate --check-acl-coverage --config confiture.yaml
```

#### Examples

**Check for schema drift against main branch:**

```bash
# Compare current schema against origin/main
confiture migrate validate --check-drift --base-ref origin/main

# Output on drift detected:
# ⚠️  Schema differences detected
#   • ADD_TABLE posts
#   • ADD_COLUMN users.bio
```

**Require migration files for DDL changes:**

```bash
# Validate that schema changes have corresponding migrations
confiture migrate validate --require-migration --base-ref origin/main

# Output if missing migration:
# ❌ DDL changes without migration files
#    Changes: 1
#    DDL changes found but no migrations added
```

**Both checks together (recommended):**

```bash
confiture migrate validate \
  --check-drift \
  --require-migration \
  --base-ref origin/main
```

**Pre-commit hook validation (staged files only):**

```bash
# Validate only currently staged changes
confiture migrate validate --check-drift --require-migration --staged

# This is fast (<500ms) and perfect for pre-commit hooks
```

**Compare against different references:**

```bash
# Against a tag
confiture migrate validate --check-drift --base-ref v1.5.0

# Against a commit
confiture migrate validate --check-drift --base-ref HEAD~10

# Against a different branch
confiture migrate validate --check-drift --base-ref origin/develop
```

**JSON output for CI/CD:**

```bash
confiture migrate validate \
  --check-drift \
  --require-migration \
  --base-ref origin/main \
  --format json \
  --output validation-report.json

# Output: Machine-parseable JSON for CI systems
```

#### Output Examples

**Text format (default):**

```
Schema Validation Report
━━━━━━━━━━━━━━━━━━━━━━━━

Git Drift Check (origin/main → HEAD)
  Status: ✅ PASSED
  Schema Changes: 0

Migration Accompaniment Check
  DDL Changes: No
  New Migrations: -
  Status: ✅ VALID

Overall Result: ✅ PASSED
```

**With detected issues:**

```
Schema Validation Report
━━━━━━━━━━━━━━━━━━━━━━━━

Git Drift Check (origin/main → HEAD)
  Status: ⚠️  ISSUES FOUND
  Schema Changes: 2
    • ADD_TABLE posts
    • ADD_COLUMN users.bio

Migration Accompaniment Check
  DDL Changes: Yes
  New Migrations: No (0 files)
  Status: ❌ INVALID

Overall Result: ❌ FAILED
```

#### Use Cases

**1. Local Development (Pre-Commit Hook)**

```yaml
# .pre-commit-config.yaml
- repo: local
  hooks:
    - id: confiture-validate
      name: Validate schema changes
      entry: confiture migrate validate --check-drift --require-migration --staged
      language: system
      pass_filenames: false
      stages: [commit]
```

**2. CI/CD Pipeline (GitHub Actions)**

```yaml
name: Validate Schema

on: [pull_request, push]

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
        with:
          fetch-depth: 0

      - name: Setup Python
        uses: actions/setup-python@v4
        with:
          python-version: "3.11"

      - name: Install Confiture
        run: pip install confiture

      - name: Validate schema
        run: |
          confiture migrate validate \
            --check-drift \
            --require-migration \
            --base-ref origin/main
```

**3. Code Review Gate (Bash Script)**

```bash
#!/bin/bash
set -e

if ! confiture migrate validate \
    --check-drift \
    --require-migration \
    --base-ref origin/main; then
  echo "❌ Schema validation failed"
  echo "You must:"
  echo "  1. Add missing migration files, or"
  echo "  2. Update schema files to match migrations"
  exit 1
fi

echo "✅ Schema validation passed"
```

#### Exit Codes

| Code | Meaning |
|------|---------|
| `0` | Validation passed - no issues found |
| `1` | Validation failed - schema issues detected |
| `2` | Error - git not found or invalid configuration |

#### Common Scenarios

**Scenario 1: I modified schema but forgot a migration**

```bash
# Modified db/schema/users.sql but didn't create migration
confiture migrate validate --require-migration --base-ref origin/main

# Output:
# ❌ DDL changes without migration files

# Fix: Create migration file
touch db/migrations/20260403120115_add_email_column.up.sql
git add db/migrations/20260403120115_add_email_column.up.sql
confiture migrate validate --require-migration
# ✅ Now passes
```

**Scenario 2: I want to ensure my PR doesn't introduce drift**

```bash
confiture migrate validate --check-drift --base-ref origin/main

# Detects structural DDL differences
# Ignores whitespace and comment-only changes
# Prevents untracked schema changes in code review
```

**Scenario 3: My git command is hanging**

```bash
# Use a more recent base to limit diff
confiture migrate validate --check-drift --base-ref HEAD~10

# Or use a specific branch
confiture migrate validate --check-drift --base-ref origin/develop
```

#### Performance Tips

**For pre-commit hooks (must be <500ms):**
- Use `--staged` flag to validate only changed files
- Run only on commit stage, not on other stages

**For CI/CD (should be <5s):**
- Use recent base refs (e.g., `origin/main` instead of `v1.0.0`)
- Limit to recent commits with `--base-ref HEAD~50` if needed

**For large repositories:**
- Use more recent refs to reduce diff scope
- Consider running in CI only, not on every local commit

#### Troubleshooting

**"Not a git repository" error:**

```bash
# Solution 1: Initialize git
git init
cd /path/to/git/root
confiture migrate validate --check-drift

# Solution 2: Run from git repo root
cd /path/to/project
confiture migrate validate --check-drift
```

**"Invalid git reference" error:**

```bash
# List available branches
git branch -a

# Fetch latest from remote
git fetch origin

# Use correct branch name
confiture migrate validate --check-drift --base-ref origin/main
```

**"Command timed out" error:**

```bash
# Use more recent base
confiture migrate validate --check-drift --base-ref HEAD~10

# Or check git repo health
git fsck

# Or fetch fresh data
git fetch origin
```

#### Detailed Documentation

For comprehensive guide including decision trees, integration examples, and best practices, see **[Git-Aware Schema Validation Guide](../guides/git-aware-validation.md)**.

---

### `confiture migrate schema-to-schema`

Medium 4: **zero-downtime** schema migration via PostgreSQL's Foreign Data
Wrapper (FDW). Runs the old and new schemas side-by-side, copies data in the
background while the old schema stays live, then cuts over. Use it for column
renames, type changes, and table splits/merges on large tables; for simple
add/drop use `migrate up` (Medium 2) instead.

Every subcommand takes a `--source` (old database) and `--target` (new
database). Each resolves an **environment name** (`db/environments/{name}.yaml`),
a **config path**, or a raw **DSN** — the core needs a live connection to both.

```bash
confiture migrate schema-to-schema [SUBCOMMAND] --source <db> --target <db> [OPTIONS]
```

| Subcommand | Purpose |
|------------|---------|
| `setup` | Create the FDW server + import the foreign schema (target → source) |
| `analyze` | Recommend a per-table strategy (FDW vs COPY) from table sizes |
| `migrate` | Migrate every table declared in a column-mapping YAML |
| `migrate-table` | Migrate one table with an inline `src_col:dst_col,…` mapping |
| `verify` | Compare source/target row counts (exit `1` on mismatch) |
| `cleanup` | Drop the FDW server + foreign schema from the target after cutover |

All subcommands accept `--format`/`-f` (`text` or `json`) and route failures
through the unified `{ok: false, error: {…}}` envelope (an unresolvable
`--source`/`--target` is `CONFIG_004`/`CONFIG_006`, exit `5`/`3`).

#### `setup`

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--source` | String | *required* | Source (old) database: env name, config path, or DSN |
| `--target` | String | *required* | Target (new) database |
| `--skip-import` | flag | off | Create the FDW server without importing the foreign schema |

#### `analyze`

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--schema` | String | `public` | Schema to analyze |

Auto-selects FDW (<10M rows) or COPY (≥10M rows) per table.

#### `migrate`

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--mapping` | Path | *required* | Per-table column-mapping YAML (see the guide) |
| `--strategy` | String | `fdw` | `fdw` or `copy` |

#### `migrate-table`

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--source-table` | String | *required* | Source table name |
| `--target-table` | String | *required* | Target table name |
| `--mapping` | String | *required* | Inline column mapping `src_col:dst_col,…` |
| `--strategy` | String | `fdw` | `fdw` or `copy` |

#### `verify`

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--tables` | String | *required* | Comma-separated tables to verify |
| `--source-schema` | String | `old_schema` | Source schema name |
| `--target-schema` | String | `public` | Target schema name |

Exits `1` (a found-issue signal) when any table's row counts differ.

#### Examples

```bash
# 1. Set up the FDW from the new (target) database back to the old (source)
confiture migrate schema-to-schema setup --source old_prod --target new_prod

# 2. See the recommended strategy per table
confiture migrate schema-to-schema analyze --source old_prod --target new_prod

# 3. Migrate every table named in the mapping file
confiture migrate schema-to-schema migrate \
    --source old_prod --target new_prod \
    --mapping db/migration/column_mapping.yaml

# 4. Migrate a single table with an inline mapping
confiture migrate schema-to-schema migrate-table \
    --source old_prod --target new_prod \
    --source-table old_users --target-table users \
    --mapping "full_name:display_name,email:email"

# 5. Verify row-count parity before cutover (exit 1 on mismatch)
confiture migrate schema-to-schema verify \
    --source old_prod --target new_prod --tables users,posts

# 6. Remove the FDW after the monitoring period
confiture migrate schema-to-schema cleanup --source old_prod --target new_prod
```

See the **[Schema-to-Schema Migration Guide](../guides/04-schema-to-schema.md)**
for the full cutover playbook and the column-mapping YAML format.

---

## `confiture drift`

Compare the live database schema against expected DDL and/or the configured `acls:` block.

### Usage

```bash
confiture drift [OPTIONS]
```

### Options

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--config` | `-c` | Path | `confiture.yaml` | Configuration file |
| `--schema` | - | Path | None | Schema SQL file to compare against (optional when `--check-acls` is set) |
| `--check-acls` | - | Flag | `False` | Compare live `pg_class.relacl` against the `acls:` block. See [ACL Coverage](../guides/acl-coverage.md) |
| `--warn-only` | - | Flag | `False` | Demote `MISSING_GRANT` items from CRITICAL to WARNING (progressive rollout) |
| `--format` | `-f` | Text | `table` | Output format: `table` or `json` |
| `--fail-on-warning` | - | Flag | `False` | Exit with code 1 on warnings as well as critical drift |

### Exit Codes

| Code | Meaning |
|---|---|
| 0 | No drift detected |
| 1 | Critical drift detected (or any drift with `--fail-on-warning`) |
| 2 | Connection or configuration error (e.g. `--check-acls` without an `acls:` block) |

### Examples

**Structural drift only:**

```bash
confiture drift --config confiture.yaml --schema db/generated/schema.sql
```

**ACL drift only (no structural diff):**

```bash
confiture drift --check-acls --config confiture.yaml
```

**Both structural and ACL drift:**

```bash
confiture drift --check-acls --schema db/generated/schema.sql --config confiture.yaml
```

**Soft launch — surface gaps without failing CI:**

```bash
confiture drift --check-acls --warn-only --config confiture.yaml
```

**JSON output (back-compat — new ACL items live inside the existing `drift_items` array):**

```bash
confiture drift --check-acls --format json --config confiture.yaml
```

See **[ACL Coverage](../guides/acl-coverage.md)** for the full guide, including the asymmetry between the `MISSING_GRANT` and `EXTRA_GRANT` query paths.

---

## `confiture admin`

Administrative commands for database setup and maintenance.

### `confiture admin install-helpers`

Install view helper functions for managing dependent views during column changes.

```bash
confiture admin install-helpers [OPTIONS]
```

#### Options

| Option | Description |
|--------|-------------|
| `--env, -e` | Environment name (default: `local`) |
| `--config, -c` | Configuration file path |
| `--dry-run` | Show SQL without executing |
| `--force` | Reinstall even if already installed |

#### What It Installs

Creates a `confiture` schema with two PL/pgSQL functions:

- `confiture.save_and_drop_dependent_views(schemas TEXT[])` — save and drop all views depending on tables in given schemas
- `confiture.recreate_saved_views()` — recreate previously saved views in correct dependency order

These are used in migrations that rename columns or change column types on tables with dependent views.

#### Examples

```bash
# Install helpers for local environment
confiture admin install-helpers

# Preview the SQL that would run
confiture admin install-helpers --dry-run

# Reinstall after upgrading confiture
confiture admin install-helpers --force
```

With `migration.view_helpers: auto` (the default), helpers are installed automatically on the first `confiture migrate up`. This command is only needed with `view_helpers: manual`.

See the [View Helpers guide](../guides/view-helpers.md) for usage in migrations.

---

## Error Handling

### Common Errors and Solutions

#### File Not Found

```
❌ File not found: db/schema/
💡 Tip: Run 'confiture init' to create project structure
```

**Solution**: Run `confiture init` to create the project structure.

#### Configuration Error

```
❌ Error building schema: Invalid environment configuration
```

**Solution**: Check `db/environments/{env}.yaml` for syntax errors.

#### Database Connection Failed

```
❌ Error: could not connect to server: Connection refused
```

**Solutions**:
- Verify PostgreSQL is running: `pg_isready`
- Check connection details in `db/environments/{env}.yaml`
- Test connection: `psql -h localhost -U postgres`

#### Migration Already Applied

```
❌ Error: migration 003 is already applied
```

**Solution**: Check status with `confiture migrate status --config {env}.yaml`

#### Migration Failed

```
❌ Error: column "bio" already exists
```

**Solutions**:
1. Review migration SQL for errors
2. Rollback: `confiture migrate down`
3. Fix migration file
4. Reapply: `confiture migrate up`

---

## Exit Codes

Confiture uses standard exit codes:

| Exit Code | Meaning |
|-----------|---------|
| `0` | Success |
| `1` | Error (file not found, database error, etc.) |

Use in scripts:

```bash
# Exit on error
confiture build --env production || exit 1

# Conditional execution
if confiture migrate up --config prod.yaml; then
  echo "Migrations applied successfully"
else
  echo "Migration failed!"
  exit 1
fi
```

---

## Shell Completion

Confiture supports shell completion for bash, zsh, and fish.

### Setup

```bash
# Bash
eval "$(_CONFITURE_COMPLETE=bash_source confiture)"

# Zsh
eval "$(_CONFITURE_COMPLETE=zsh_source confiture)"

# Fish
_CONFITURE_COMPLETE=fish_source confiture | source
```

### Add to Shell RC

```bash
# Add to ~/.bashrc
echo 'eval "$(_CONFITURE_COMPLETE=bash_source confiture)"' >> ~/.bashrc

# Add to ~/.zshrc
echo 'eval "$(_CONFITURE_COMPLETE=zsh_source confiture)"' >> ~/.zshrc

# Add to ~/.config/fish/config.fish
echo '_CONFITURE_COMPLETE=fish_source confiture | source' >> ~/.config/fish/config.fish
```

---

## Environment Variables

Confiture supports environment variables for common options:

| Variable | Description | Example |
|----------|-------------|---------|
| `CONFITURE_ENV` | Default environment | `export CONFITURE_ENV=production` |
| `CONFITURE_PROJECT_DIR` | Default project directory | `export CONFITURE_PROJECT_DIR=/app` |
| `DATABASE_URL` | PostgreSQL connection URL | `export DATABASE_URL=postgresql://...` |

**Note**: Command-line options always override environment variables.

---

## Examples

### Development Workflow

```bash
# 1. Initialize project
confiture init

# 2. Edit schema files
vim db/schema/10_tables/users.sql

# 3. Build schema
confiture build

# 4. Apply to local database
psql -f db/generated/schema_local.sql

# 5. Generate migration
confiture migrate diff old.sql new.sql --generate --name add_users

# 6. Apply migration
confiture migrate up
```

### CI/CD Pipeline

```bash
#!/bin/bash
set -e

# Build schema
confiture build --env test --schema-only

# Run tests
pytest tests/

# Apply migrations
confiture migrate up --config test.yaml

# Verify database
psql -c "SELECT version FROM tb_confiture ORDER BY applied_at DESC LIMIT 1"
```

### Production Deployment

```bash
#!/bin/bash
set -e

# Check pending migrations
confiture migrate status --config production.yaml

# Backup database
pg_dump -Fc myapp_production > backup.dump

# Apply migrations
confiture migrate up --config production.yaml

# Verify
confiture migrate status --config production.yaml
```

---

## `confiture coordinate` (Multi-Agent Coordination)

Multi-agent coordination commands for safe parallel schema development. These commands enable multiple agents or team members to work on database schemas simultaneously with automatic conflict detection.

### `confiture coordinate init`

Initialize coordination database and tables.

```bash
confiture coordinate init --db-url postgresql://localhost/confiture_coord
```

**Options:**
- `--db-url`: PostgreSQL connection URL for coordination database

### `confiture coordinate register`

Register an intention to make schema changes.

```bash
confiture coordinate register \
    --agent-id alice \
    --feature-name user_profiles \
    --tables-affected users,profiles \
    --schema-changes "ALTER TABLE users ADD COLUMN bio TEXT" \
    --risk-level medium \
    --estimated-hours 3
```

**Options:**
- `--agent-id`: Unique identifier for the agent (required)
- `--feature-name`: Name of the feature being implemented (required)
- `--tables-affected`: Comma-separated list of tables (required)
- `--schema-changes`: DDL statements to be executed (optional but recommended)
- `--columns-affected`: Comma-separated list of columns (optional)
- `--functions-affected`: Comma-separated list of functions (optional)
- `--constraints-affected`: Comma-separated list of constraints (optional)
- `--indexes-affected`: Comma-separated list of indexes (optional)
- `--risk-level`: Risk level: low, medium, high, critical (default: medium)
- `--estimated-hours`: Estimated completion time in hours (optional)
- `--blocking`: Mark as blocking other work (default: false)
- `--format`: Output format: text or json (default: text)

**Returns:**
- Intent ID for tracking
- Allocated branch name
- Detected conflicts (if any)

### `confiture coordinate check`

Check for conflicts before making changes.

```bash
confiture coordinate check \
    --agent-id bob \
    --tables-affected users
```

**Options:**
- `--agent-id`: Your agent identifier (required)
- `--tables-affected`: Tables you want to modify (required)
- `--columns-affected`: Columns you want to modify (optional)
- `--functions-affected`: Functions you want to modify (optional)
- `--format`: Output format: text or json (default: text)

**Returns:**
- List of conflicts with other active intentions
- Conflict severity (warning or error)
- Suggestions for resolution

### `confiture coordinate status`

View status of all registered intentions.

```bash
# Human-readable output
confiture coordinate status

# JSON output for CI/CD
confiture coordinate status --format json

# Filter by agent
confiture coordinate status --agent-id alice

# Filter by status
confiture coordinate status --status IN_PROGRESS
```

**Options:**
- `--agent-id`: Filter by specific agent (optional)
- `--status`: Filter by status: REGISTERED, IN_PROGRESS, COMPLETED, ABANDONED, CONFLICTED (optional)
- `--intent-id`: Get specific intention details (optional)
- `--format`: Output format: text or json (default: text)

### `confiture coordinate complete`

Mark an intention as completed.

```bash
confiture coordinate complete \
    --intent-id int_abc123def456 \
    --outcome success \
    --notes "User profiles implemented and tested"
```

**Options:**
- `--intent-id`: Intent ID to complete (required)
- `--outcome`: Outcome: success, partial, failed (required)
- `--notes`: Additional notes (optional)
- `--merge-commit`: Git merge commit SHA (optional)

### `confiture coordinate abandon`

Abandon an intention (work not completed).

```bash
confiture coordinate abandon \
    --intent-id int_abc123def456 \
    --reason "Requirements changed"
```

**Options:**
- `--intent-id`: Intent ID to abandon (required)
- `--reason`: Reason for abandoning (required)

### `confiture coordinate list`

List all intentions with optional filtering.

```bash
# List all intentions
confiture coordinate list

# Filter by date range
confiture coordinate list --since "2026-01-01" --until "2026-01-31"

# Filter by agent
confiture coordinate list --agent-id alice

# JSON output
confiture coordinate list --format json
```

**Options:**
- `--agent-id`: Filter by agent (optional)
- `--status`: Filter by status (optional)
- `--since`: Show intentions since date (YYYY-MM-DD) (optional)
- `--until`: Show intentions until date (YYYY-MM-DD) (optional)
- `--format`: Output format: text or json (default: text)

### `confiture coordinate conflicts`

Show all active conflicts between intentions.

```bash
# View all conflicts
confiture coordinate conflicts

# JSON output for automation
confiture coordinate conflicts --format json

# Filter by severity
confiture coordinate conflicts --severity error
```

**Options:**
- `--severity`: Filter by severity: warning or error (optional)
- `--format`: Output format: text or json (default: text)

### JSON Output Format

All coordination commands support `--format json` for CI/CD integration:

```json
{
  "intent_id": "int_abc123def456",
  "agent_id": "alice",
  "feature_name": "user_profiles",
  "status": "IN_PROGRESS",
  "tables_affected": ["users", "profiles"],
  "conflicts": [
    {
      "type": "table",
      "severity": "warning",
      "conflicting_intent_id": "int_xyz789",
      "suggestion": "Coordinate with agent bob who is also working on 'users' table"
    }
  ],
  "registered_at": "2026-01-22T10:30:00Z",
  "allocated_branch": "feature/user_profiles_001"
}
```

### Coordination Examples

**Pre-merge conflict check in CI/CD:**

```bash
# In GitHub Actions
confiture coordinate check \
    --agent-id github-ci-${PR_NUMBER} \
    --tables-affected $(git diff --name-only origin/main | grep 'db/schema' | xargs) \
    --format json > conflicts.json

if jq -e '.conflicts | length > 0' conflicts.json; then
  echo "❌ Schema conflicts detected!"
  exit 1
fi
```

**Dashboard integration:**

```bash
# Get current status as JSON
confiture coordinate status --format json > dashboard.json

# Serve to monitoring dashboard
curl -X POST https://dashboard.example.com/api/schema-status \
    -H "Content-Type: application/json" \
    -d @dashboard.json
```

**For detailed coordination workflows and best practices**, see **[Multi-Agent Coordination Guide](../guides/multi-agent-coordination.md)**.

---

## Further Reading

- **[Getting Started Guide](../getting-started.md)** - Step-by-step tutorial
- **[Multi-Agent Coordination Guide](../guides/multi-agent-coordination.md)** - Complete coordination guide
- **[Migration Decision Tree](../guides/migration-decision-tree.md)** - Choosing the right strategy
- **[Configuration Reference](./configuration.md)** - Environment configuration
- **[API Reference](../api/index.md)** - Python API documentation

---

**Last Updated**: January 22, 2026
**Version**: 1.1 (Added Multi-Agent Coordination)
