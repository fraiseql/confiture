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


<!-- BEGIN GENERATED: cli confiture init -->

**Usage**

```bash
confiture init [OPTIONS] [PATH]
```

**Arguments**

| Argument | Type | Required | Description |
|---|---|---|---|
| `PATH` | path | no | Project directory to initialize |

<!-- END GENERATED: cli confiture init -->

## `confiture build`

Build complete schema from DDL files (Medium 1: Build from DDL).

This is the **fastest way** to create or recreate a database from scratch (<1 second for 1000 files).

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
- Use the `--fail-on-unclosed` and `--fail-on-spillover` flags for strict production builds

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


<!-- BEGIN GENERATED: cli confiture build -->

**Usage**

```bash
confiture build [OPTIONS]
```

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--env` | `-e` | text | `local` | Environment to build (default: local) |
| `--output` | `-o` | path | - | Output file path (default: db/generated/schema_{env}.sql) |
| `--project-dir` | - | path | `.` | Project directory (default: current directory) |
| `--show-hash` | - | Flag | off | Display schema hash after build (default: off) |
| `--schema-only` | - | Flag | off | Build schema only, exclude seed data (default: off) |
| `--validate-comments` / `--no-validate-comments` | - | Flag | - | Enable/disable comment validation (default: from config) |
| `--fail-on-unclosed` / `--no-fail-on-unclosed` | - | Flag | - | Fail on unclosed block comments (default: from config) |
| `--fail-on-spillover` / `--no-fail-on-spillover` | - | Flag | - | Fail on comment spillover into next file (default: from config) |
| `--two-pass` / `--no-two-pass` | - | Flag | - | Two-pass FK emission: strip REFERENCES from CREATE TABLE, emit ALTER TABLE after (default: from config) |
| `--separator-style` | - | text | - | Separator style: block_comment, line_comment, mysql, custom (default: from config) |
| `--separator-template` | - | text | - | Custom separator template with {file_path} placeholder (default: none) |
| `--sequential` | - | Flag | off | Apply seed files sequentially after build (default: off) |
| `--database-url` | - | text | - | Database connection URL (required for --sequential, default: from config) |
| `--continue-on-error` | - | Flag | off | Continue applying seed files if one fails (only with --sequential) |
| `--warn-duplicates` | - | Flag | off | Report objects defined more than once across the build's files (build_001/build_002), then build |
| `--fail-on-duplicates` | - | Flag | off | Report duplicate definitions and exit 1 without building |
| `--format` | `-f` | text | `text` | Output format: text or json or csv (default: text) |
| `--report` | - | path | - | Save structured build report (JSON/CSV) to file (default: stdout). Distinct from --output/-o, which is the generated *schema* file. |
| `--dump` | - | path | - | Also emit a content-addressed pg_dump -Fc artifact restorable by 'confiture restore'. Pass a file path, or an existing directory to auto-name 'schema_{env}.{profile}.{hash}.pgdump' inside it (cache by db/ hash). |
| `--dump-format` | - | text | `custom` | Artifact format for --dump: custom (-Fc) or directory (-Fd, parallel). Default: custom. |
| `--seed-profile` | - | text | - | Apply only the named seed profile (seed.profiles.<name>) during --sequential seed application and --dump. Unknown name → exit 5. |

<!-- END GENERATED: cli confiture build -->

## `confiture build --dump` (cacheable artifact)

`confiture build` also emits a content-addressed `pg_dump` artifact for fast,
cached CI provisioning:

| Option | Description |
|---|---|
| `--dump <path>` | Also write a `pg_dump` artifact. A directory auto-names `schema_{env}.{profile}.{hash}.pgdump` inside it (cache by `db/` hash); a file path is used verbatim. Requires a server URL (`--database-url` or env). |
| `--dump-format custom\|directory` | `custom` = `-Fc` (default), `directory` = `-Fd` (parallel dump). |
| `--seed-profile <name>` | Apply only the named seed profile (see `seed.profiles`) during `--sequential` seed application and `--dump`. |

The artifact is restorable by [`confiture restore`](../guides/restore.md). See the
[Parallel CI provisioning guide](../guides/parallel-ci-provisioning.md).

---

## `confiture test-db`

CI-path primitive for parallel-test database provisioning: build a template once,
hand out lock-free per-worker clones. See the
[Parallel CI provisioning guide](../guides/parallel-ci-provisioning.md).

| Subcommand | Description | Exit codes |
|---|---|---|
| `provision-template --template <name> [--env] [--from-artifact <path>] [--seed-profile <name>] [--force]` | Build/apply (or restore an artifact) into a template DB and stamp its `db/` hash. | 0 ok; 5 bad input/refused clobber; 4 build/restore failed |
| `clone --template <src> --target <dst> [--tablespace <ts>] [--no-sync-commit-off] [--max-clone-concurrency <n>]` | Clone via `CREATE DATABASE … WITH TEMPLATE` (retries while the source is in use). `--tablespace` places the clone in a (tmpfs) tablespace, falling back to disk on any tablespace failure; `--no-sync-commit-off` keeps durable commits (default sets `synchronous_commit=off` on the clone); `--max-clone-concurrency <n>` bounds concurrent clones of this template across processes (`>=1`; default unbounded) to throttle WAL/checkpoint thrash on `fsync=on` clusters (#166). `--format json` redacts DSN passwords in `target_url`. | 0 ok; 4 clone failed |
| `ram-setup --tablespace <name> --location <dir> [--owner <user>] [--force]` | Create or idempotently reset a tmpfs tablespace for RAM clones (DROP+re-CREATE, dropping managed clones in it). Refuses a LOCATION outside `/dev/shm`/`/run` without `--force`. Prints a `sudo install -d …` command when it lacks the OS rights to prepare the dir. | 0 ok; 5 bad input / refused / **action required** (`action_required` flag set) |
| `drop --target <name> [--force]` | Drop a confiture-managed clone/template (refuses unmanaged DBs without `--force`). | 0 ok; 5 refused |
| `status --template <name> [--env]` | Report staleness vs the current `db/` hash. | **0 current; 1 stale/absent** |
| `list` | List confiture-managed templates and clones. | 0 |
| `prune --template <name>` | Drop every clone of a template (reap leaked clones). | 0 |

All accept `--database-url` (else the env config supplies the server URL),
`--env`, `--project-dir`, and `--format text\|json`.

---

### `confiture test-db clone`

Clone a template into a fresh database via CREATE DATABASE … WITH TEMPLATE.

<!-- BEGIN GENERATED: cli confiture test-db clone -->

**Usage**

```bash
confiture test-db clone [OPTIONS]
```

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--template` | - | text | - | Source template database. |
| `--target` | - | text | - | Clone database name to create. |
| `--env` | `-e` | text | `local` | Environment (for server URL). |
| `--project-dir` | - | path | `.` | Project directory. |
| `--database-url` | - | text | - | PG server URL. |
| `--sync-commit-off` / `--no-sync-commit-off` | - | Flag | on | Set synchronous_commit=off on the clone (default on; opt out for durable commits). |
| `--max-clone-concurrency` | - | integer | - | Bound concurrent clones of this template across processes (>=1); default unbounded. Throttles WAL/checkpoint thrash on fsync=on clusters. |
| `--format` | `-f` | text | `text` | Output format: text or json (default: text) |

<!-- END GENERATED: cli confiture test-db clone -->

### `confiture test-db drop`

Drop a confiture-managed clone or template (terminating its backends).

<!-- BEGIN GENERATED: cli confiture test-db drop -->

**Usage**

```bash
confiture test-db drop [OPTIONS]
```

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--target` | - | text | - | Database to drop. |
| `--force` | - | Flag | off | Drop even if not confiture-managed (use with care). |
| `--env` | `-e` | text | `local` | Environment (for server URL). |
| `--project-dir` | - | path | `.` | Project directory. |
| `--database-url` | - | text | - | PG server URL. |
| `--format` | `-f` | text | `text` | Output format: text or json (default: text) |

<!-- END GENERATED: cli confiture test-db drop -->

### `confiture test-db list`

List confiture-managed templates and clones on the server.

<!-- BEGIN GENERATED: cli confiture test-db list -->

**Usage**

```bash
confiture test-db list [OPTIONS]
```

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--env` | `-e` | text | `local` | Environment (for server URL). |
| `--project-dir` | - | path | `.` | Project directory. |
| `--database-url` | - | text | - | PG server URL. |
| `--format` | `-f` | text | `text` | Output format: text or json (default: text) |

<!-- END GENERATED: cli confiture test-db list -->

### `confiture test-db provision-template`

Build (or restore) a template database and stamp its db/ content hash.

<!-- BEGIN GENERATED: cli confiture test-db provision-template -->

**Usage**

```bash
confiture test-db provision-template [OPTIONS]
```

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--template` | - | text | - | Template database name. |
| `--env` | `-e` | text | `local` | Environment to build. |
| `--project-dir` | - | path | `.` | Project directory. |
| `--from-artifact` | - | path | - | Restore a pg_dump -Fc/-Fd artifact (from 'build --dump') instead of applying DDL. |
| `--seed-profile` | - | text | - | Apply only the named seed profile (seed.profiles.<name>) on the DDL path. |
| `--force` | - | Flag | off | Replace a same-named database even if not confiture-managed. |
| `--database-url` | - | text | - | PG server URL (default: from env config). |
| `--format` | `-f` | text | `text` | Output format: text or json (default: text) |

<!-- END GENERATED: cli confiture test-db provision-template -->

### `confiture test-db prune`

Drop every clone of a template (reaps clones leaked by crashed workers).

<!-- BEGIN GENERATED: cli confiture test-db prune -->

**Usage**

```bash
confiture test-db prune [OPTIONS]
```

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--template` | - | text | - | Template whose clones to drop. |
| `--env` | `-e` | text | `local` | Environment (for server URL). |
| `--project-dir` | - | path | `.` | Project directory. |
| `--database-url` | - | text | - | PG server URL. |
| `--format` | `-f` | text | `text` | Output format: text or json (default: text) |

<!-- END GENERATED: cli confiture test-db prune -->

### `confiture test-db ram-setup`

Create or idempotently reset a tmpfs-backed tablespace for RAM clones.

<!-- BEGIN GENERATED: cli confiture test-db ram-setup -->

**Usage**

```bash
confiture test-db ram-setup [OPTIONS]
```

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--tablespace` | - | text | - | Tablespace name to (re)create. |
| `--location` | - | text | - | tmpfs LOCATION directory (e.g. /dev/shm/<dir>). |
| `--owner` | - | text | `postgres` | OS user the PG server runs as (owns the LOCATION dir). |
| `--force` | - | Flag | off | Drop non-managed DBs in the tablespace and bypass the tmpfs-root allowlist. |
| `--env` | `-e` | text | `local` | Environment (for server URL). |
| `--project-dir` | - | path | `.` | Project directory. |
| `--database-url` | - | text | - | PG server URL. |
| `--format` | `-f` | text | `text` | Output format: text or json (default: text) |

<!-- END GENERATED: cli confiture test-db ram-setup -->

### `confiture test-db status`

Report template staleness vs the current db/ hash (exit 0 current, 1 stale/absent).

<!-- BEGIN GENERATED: cli confiture test-db status -->

**Usage**

```bash
confiture test-db status [OPTIONS]
```

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--template` | - | text | - | Template database name. |
| `--env` | `-e` | text | `local` | Environment to hash. |
| `--project-dir` | - | path | `.` | Project directory. |
| `--database-url` | - | text | - | PG server URL. |
| `--format` | `-f` | text | `text` | Output format: text or json (default: text) |

<!-- END GENERATED: cli confiture test-db status -->

## `confiture sync`

Copy data from a production database to a local/staging target (Medium 3), with
optional PII anonymization. See the [Production Sync
guide](../guides/03-production-sync.md).

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


<!-- BEGIN GENERATED: cli confiture sync -->

**Usage**

```bash
confiture sync [OPTIONS]
```

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--from` | - | text | - | Source database: env name or DSN. |
| `--to` | - | text | - | Target database: env name or DSN. |
| `--anonymize` | - | Flag | off | Mask PII during the copy (see --anonymization-config). |
| `--anonymization-config` | - | path | `db/sync/anonymization.yaml` | Anonymization rules YAML (default: db/sync/anonymization.yaml). |
| `--tables` | - | text | - | Comma-separated tables to include (default: all). |
| `--exclude` | - | text | - | Comma-separated tables to exclude. |
| `--batch-size` | - | integer | `5000` | Rows per batch for anonymized inserts. |
| `--checkpoint` | - | path | - | Checkpoint file for resumable syncs. |
| `--resume` | - | Flag | off | Resume from --checkpoint, skipping completed tables. |
| `--format` | `-f` | text | `text` | Output format: text or json (default: text) |

<!-- END GENERATED: cli confiture sync -->

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


<!-- BEGIN GENERATED: cli confiture migrate status -->

**Usage**

```bash
confiture migrate status [OPTIONS]
```

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--migrations-dir` | - | path | `db/migrations` | Migrations directory (default: db/migrations) |
| `--config` | `-c` | path | - | Config file for database connection. Must appear after 'status': confiture migrate status -c config.yaml |
| `--database-url` | `-d` | text | - | PostgreSQL DSN for the tracking database. Always wins over --config / --env and the env vars. The canonical CONFITURE_DATABASE_URL beats a *default* --config but conflicts with an *explicit* one (CONFIG_007); the ambient DATABASE_URL never overrides a present config. Pass --no-config to make the environment the sole source. When a DSN is supplied, no YAML is required (tracking table defaults to tb_confiture). SSH-tunnel configs still require --config. |
| `--no-config` | - | Flag | off | Suppress config-file discovery entirely; the environment (CONFITURE_DATABASE_URL, else DATABASE_URL) becomes the sole DSN source. Use this for runtime-resolved DSNs that must not be exposed in argv. |
| `--format` | `-f` | text | `table` | Output format: table or json or csv (default: table) |
| `--output` | `-o` | path | - | Save output to file (default: stdout, useful with json/csv) |
| `--check-rebuild` | - | Flag | off | Check whether a full rebuild is recommended instead of migrate up |
| `--rebuild-threshold` | - | integer | - | Number of pending migrations that triggers rebuild advisory (default: from config or 5) |

<!-- END GENERATED: cli confiture migrate status -->

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


<!-- BEGIN GENERATED: cli confiture migrate current -->

**Usage**

```bash
confiture migrate current [OPTIONS]
```

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--config` | `-c` | path | `db/environments/local.yaml` | Configuration file (default: db/environments/local.yaml) |
| `--database-url` | `-d` | text | - | PostgreSQL DSN for the tracking database. Always wins over --config / --env and the env vars. The canonical CONFITURE_DATABASE_URL beats a *default* --config but conflicts with an *explicit* one (CONFIG_007); the ambient DATABASE_URL never overrides a present config. Pass --no-config to make the environment the sole source. When a DSN is supplied, no YAML is required (tracking table defaults to tb_confiture). SSH-tunnel configs still require --config. |
| `--no-config` | - | Flag | off | Suppress config-file discovery entirely; the environment (CONFITURE_DATABASE_URL, else DATABASE_URL) becomes the sole DSN source. Use this for runtime-resolved DSNs that must not be exposed in argv. |
| `--format` | `-f` | text | `text` | Output format: text or json (default: text) |
| `--output` | `-o` | path | - | Save output to file (default: stdout) |

<!-- END GENERATED: cli confiture migrate current -->

### `confiture migrate generate`

Create a new empty migration template.

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


<!-- BEGIN GENERATED: cli confiture migrate generate -->

**Usage**

```bash
confiture migrate generate [OPTIONS] NAME
```

**Arguments**

| Argument | Type | Required | Description |
|---|---|---|---|
| `NAME` | text | yes | Migration name (snake_case) |

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--migrations-dir` | - | path | `db/migrations` | Migrations directory (default: db/migrations) |
| `--format` | `-f` | text | `text` | Output format: text or json (default: text) |
| `--force` | - | Flag | off | Overwrite existing migration file (default: off) |
| `--dry-run` | - | Flag | off | Show what would be generated without creating (default: off) |
| `--verbose` | `-v` | Flag | off | Show version calculation details (default: off) |
| `--from` | - | path | - | Old schema file path (required with --generator) |
| `--to` | - | path | - | New schema file path (required with --generator) |
| `--generator` | - | text | - | Named external generator from migration_generators config |
| `--config` | `-c` | path | `db/environments/local.yaml` | Environment config file (default: db/environments/local.yaml) |
| `--snapshot` / `--no-snapshot` | - | Flag | - | Write schema history snapshot (default: from config, True) |
| `--snapshots-dir` | - | path | - | Override snapshot output directory (default: db/schema_history) |
| `--live-snapshot` / `--no-live-snapshot` | - | Flag | - | Snapshot via temp database + pg_dump (captures DO-block objects) |

<!-- END GENERATED: cli confiture migrate generate -->

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


<!-- BEGIN GENERATED: cli confiture migrate diff -->

**Usage**

```bash
confiture migrate diff [OPTIONS] [OLD_SCHEMA] [NEW_SCHEMA]
```

**Arguments**

| Argument | Type | Required | Description |
|---|---|---|---|
| `OLD_SCHEMA` | path | no | Old schema file |
| `NEW_SCHEMA` | path | no | New schema file |

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--from` | - | text | - | Current state: a schema file, a directory of .sql files, '-' for stdin, or 'db' for the configured database (default: the first positional) |
| `--to` | - | text | - | Desired state: a schema file, a directory of .sql files (what fraiseql's emit-ddl option writes), or '-' for stdin (default: the second positional) |
| `--config` | `-c` | path | `db/environments/local.yaml` | Environment config, read for `--from db` (default: db/environments/local.yaml) |
| `--generate` | - | Flag | off | Generate a migration from the differences: a .up.sql/.down.sql pair with --from/--to, a Python migration with positional files |
| `--name` | - | text | - | Migration name (default: none, required with --generate) |
| `--migrations-dir` | - | path | `db/migrations` | Migrations directory (default: db/migrations) |
| `--format` | `-f` | text | `text` | Output format: text or json or csv (default: text) |
| `--allow-destructive` | - | Flag | off | Write data-losing DDL unmarked, whatever migration.destructive says |
| `--forbid-destructive` | - | Flag | off | Refuse to generate a migration that loses data (exit 5, DIFFER_401) |
| `--report` | `-o` | path | - | Save report to file (default: stdout) |

<!-- END GENERATED: cli confiture migrate diff -->

### `confiture migrate up`

Apply pending migrations (forward migrations).

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


<!-- BEGIN GENERATED: cli confiture migrate up -->

**Usage**

```bash
confiture migrate up [OPTIONS]
```

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--migrations-dir` | - | path | `db/migrations` | Migrations directory (default: db/migrations) |
| `--config` | `-c` | path | `db/environments/local.yaml` | Configuration file (default: db/environments/local.yaml) |
| `--database-url` | `-d` | text | - | PostgreSQL DSN for the tracking database. Always wins over --config / --env and the env vars. The canonical CONFITURE_DATABASE_URL beats a *default* --config but conflicts with an *explicit* one (CONFIG_007); the ambient DATABASE_URL never overrides a present config. Pass --no-config to make the environment the sole source. When a DSN is supplied, no YAML is required (tracking table defaults to tb_confiture). SSH-tunnel configs still require --config. |
| `--no-config` | - | Flag | off | Suppress config-file discovery entirely; the environment (CONFITURE_DATABASE_URL, else DATABASE_URL) becomes the sole DSN source. Use this for runtime-resolved DSNs that must not be exposed in argv. |
| `--target` | `-t` | text | - | Target migration version (default: applies all pending) |
| `--strict` | - | Flag | off | Enable strict mode, fail on warnings (default: off) |
| `--force` | - | Flag | off | Force application, skip state checks (default: off) |
| `--lock-timeout` | - | integer | - | Lock timeout in milliseconds (default: migration.locking.timeout_ms, else 30000) |
| `--no-lock` | - | Flag | off | Disable migration locking (default: migration.locking.enabled; DANGEROUS in multi-pod) |
| `--dry-run` | - | Flag | off | Analyze without executing (default: off) |
| `--dry-run-execute` | - | Flag | off | Execute in SAVEPOINT for testing (default: off, guaranteed rollback) |
| `--verify-checksums` / `--no-verify-checksums` | - | Flag | on | Verify migration checksums before running (default: on) |
| `--on-checksum-mismatch` | - | text | `fail` | Checksum mismatch behavior: fail, warn, ignore (default: fail) |
| `--verbose` | `-v` | Flag | off | Show detailed analysis in dry-run (default: off) |
| `--format` | `-f` | text | `text` | Output format: text or json (default: text) |
| `--output` | `-o` | path | - | Save report to file (default: stdout) |
| `--auto-detect-baseline` | - | Flag | off | Introspect DB and self-baseline if tb_confiture is missing (default: off) |
| `--snapshots-dir` | - | path | - | Schema history snapshots directory for --auto-detect-baseline (default: db/schema_history) |
| `--require-reversible` | - | Flag | off | Abort if any pending migration lacks a .down.sql file (guarantees rollback capability). |
| `--allow-destructive` | - | Flag | off | Apply migrations gated as destructive (data is lost): the generator's -- confiture:destructive directive, or destructive = True on a Python migration. |
| `--online` | - | Flag | off | Apply a migration the classifier marks multi-step as expand → backfill → contract stages with a checkpoint each (see migrate steps); other migrations apply the classic way. |
| `--max-lock-ms` | - | integer | - | With --online: pause this many ms between backfill batches while another session waits for a lock on the table (overrides migration.backfill.max_lock_ms). |
| `--batched` | - | Flag | off | Use batch processing for large-table operations (default: off) |
| `--batch-size` | - | integer | `10000` | Rows per batch when --batched is active (default: 10000) |
| `--batch-sleep` | - | float | `0.1` | Seconds to sleep between batches to reduce lock pressure (default: 0.1) |
| `--yes` | `-y` | Flag | off | Skip the --dry-run-execute confirmation prompt (default: off) |

<!-- END GENERATED: cli confiture migrate up -->

### `confiture migrate down`

Rollback applied migrations (reverse migrations).

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


<!-- BEGIN GENERATED: cli confiture migrate down -->

**Usage**

```bash
confiture migrate down [OPTIONS]
```

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--migrations-dir` | - | path | `db/migrations` | Migrations directory (default: db/migrations) |
| `--config` | `-c` | path | `db/environments/local.yaml` | Configuration file (default: db/environments/local.yaml) |
| `--database-url` | `-d` | text | - | PostgreSQL DSN for the tracking database. Always wins over --config / --env and the env vars. The canonical CONFITURE_DATABASE_URL beats a *default* --config but conflicts with an *explicit* one (CONFIG_007); the ambient DATABASE_URL never overrides a present config. Pass --no-config to make the environment the sole source. When a DSN is supplied, no YAML is required (tracking table defaults to tb_confiture). SSH-tunnel configs still require --config. |
| `--no-config` | - | Flag | off | Suppress config-file discovery entirely; the environment (CONFITURE_DATABASE_URL, else DATABASE_URL) becomes the sole DSN source. Use this for runtime-resolved DSNs that must not be exposed in argv. |
| `--steps` | `-n` | integer | `1` | Number of migrations to rollback (default: 1) |
| `--dry-run` | - | Flag | off | Analyze rollback without executing (default: off) |
| `--lock-timeout` | - | integer | - | Lock timeout in milliseconds (default: migration.locking.timeout_ms, else 30000) |
| `--no-lock` | - | Flag | off | Disable migration locking (default: migration.locking.enabled; DANGEROUS in multi-pod) |
| `--verbose` | `-v` | Flag | off | Show detailed analysis in dry-run (default: off) |
| `--format` | `-f` | text | `text` | Output format: text or json (default: text) |
| `--output` | `-o` | path | - | Save report to file (default: stdout) |

<!-- END GENERATED: cli confiture migrate down -->

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


<!-- BEGIN GENERATED: cli confiture migrate down-to -->

**Usage**

```bash
confiture migrate down-to [OPTIONS] REVISION
```

**Arguments**

| Argument | Type | Required | Description |
|---|---|---|---|
| `REVISION` | text | yes | Target revision to roll back to (stays applied). Use 'migrate current' to find it. |

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--migrations-dir` | - | path | `db/migrations` | Migrations directory (default: db/migrations) |
| `--config` | `-c` | path | `db/environments/local.yaml` | Configuration file (default: db/environments/local.yaml) |
| `--database-url` | `-d` | text | - | PostgreSQL DSN for the tracking database. Always wins over --config / --env and the env vars. The canonical CONFITURE_DATABASE_URL beats a *default* --config but conflicts with an *explicit* one (CONFIG_007); the ambient DATABASE_URL never overrides a present config. Pass --no-config to make the environment the sole source. When a DSN is supplied, no YAML is required (tracking table defaults to tb_confiture). SSH-tunnel configs still require --config. |
| `--no-config` | - | Flag | off | Suppress config-file discovery entirely; the environment (CONFITURE_DATABASE_URL, else DATABASE_URL) becomes the sole DSN source. Use this for runtime-resolved DSNs that must not be exposed in argv. |
| `--dry-run` | - | Flag | off | Print the rollback plan and exit 0 without applying anything. |
| `--format` | `-f` | text | `text` | Output format: text or json (default: text) |
| `--output` | `-o` | path | - | Save output to file (default: stdout) |

<!-- END GENERATED: cli confiture migrate down-to -->

### `confiture migrate rebuild`

Rebuild database from DDL schema and bootstrap tracking table.

When staging/QA environments restored from production backups have large migration gaps (10+ pending), `migrate up` often fails due to lock exhaustion or cumulative DDL complexity. `rebuild` automates the manual workaround of: build DDL, apply with psql, hand-insert tracking rows.

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


<!-- BEGIN GENERATED: cli confiture migrate rebuild -->

**Usage**

```bash
confiture migrate rebuild [OPTIONS]
```

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--config` | `-c` | path | `db/environments/local.yaml` | Configuration file (default: db/environments/local.yaml) |
| `--migrations-dir` | - | path | `db/migrations` | Migrations directory (default: db/migrations) |
| `--drop-schemas` | - | Flag | off | Drop all user schemas before rebuild |
| `--seed` | - | Flag | off | Apply seed files after DDL rebuild |
| `--backup-tracking` | - | Flag | off | Dump tracking table to JSON before clearing |
| `--verify` | - | Flag | off | Run status check after rebuild to confirm 0 pending |
| `--dry-run` | - | Flag | off | Show what would happen without making changes |
| `--yes` | `-y` | Flag | off | Skip confirmation prompt |
| `--format` | `-f` | text | `text` | Output format: text or json (default: text) |

<!-- END GENERATED: cli confiture migrate rebuild -->

### `confiture migrate validate`

Validate and fix migration file naming conventions.

Confiture only recognizes `.sql` files that match the expected naming pattern. This command helps identify and fix misnamed migration files that would be silently ignored.

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

# Compose checks: both run, one config parse, one DB connection
confiture migrate validate --check-acls --check-imports
confiture migrate validate --check-signatures --check-live-drift --env production
```

#### Composing checks (0.40.0)

Pass as many checks as you like: **all of them run**. Before 0.40.0 the command
evaluated a chain of `if <flag>: … return` blocks in source order, so
`--check-acls --check-imports` ran only the ACL check and exited 0 — a green
gate for a check that never ran (#187).

- The exit code is the worst outcome across the checks that ran, so a passing
  check cannot mask a failing one.
- Checks needing a database share one connection (and one SSH tunnel), and the
  config is parsed once for the whole run.
- `--format json` emits **one** document. A single check keeps its own
  documented payload byte-for-byte; two or more are wrapped in
  [`migrate-validate-composed.schema.json`](./json-schemas/migrate-validate-composed.schema.json),
  keyed by check name.

One combination is rejected loudly rather than composed:

| Combination | Exit | Why |
|---|---|---|
| `--list-patterns` or `--list-unmigrated-bodies` with anything else | 5 | Report modes: they always exit 0, so there is no result to compose. |

`--idempotent` was also rejected alongside `--check-drift` /
`--require-migration` / `--require-migration-bodies` /
`--require-grant-migration` in 0.37.0 through 0.40.0 (#181). That guard is
**retired in 0.41.0**: the combination composes like any other.

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


<!-- BEGIN GENERATED: cli confiture migrate validate -->

**Usage**

```bash
confiture migrate validate [OPTIONS]
```

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--migrations-dir` | - | path | `db/migrations` | Migrations directory (default: db/migrations) |
| `--fix-naming` | - | Flag | off | Auto-rename orphaned files to match convention (default: off) |
| `--idempotent` | - | Flag | off | Validate migrations are idempotent, can re-run (default: off) |
| `--list-patterns` | - | Flag | off | Print machine-readable catalog of detection patterns (read-only, no DB needed). Use with `--format json` for tooling. Report mode: cannot be combined with any other check. |
| `--strict-cor` | - | Flag | off | Treat info-severity CREATE OR REPLACE shape-risk findings as blocking (exit 1). Off by default — info findings are still rendered but don't fail the gate. |
| `--fail-on-unanalyzable` | - | Flag | off | Treat statements the analyzer could not read as a failure (exit 1). Off by default. Pair with --base-ref so an existing backlog of dynamic SQL does not fail every run. Requires --idempotent. |
| `--check-drift` | - | Flag | off | Validate schema against git refs for drift (default: off) |
| `--require-migration` | - | Flag | off | Ensure DDL changes have migration files (static, no DB required). Also detects function parameter type changes missing a DROP FUNCTION. Companion to --check-signatures which detects stale overloads in a live DB. |
| `--require-migration-bodies` | - | Flag | off | Additionally require a function/procedure BODY change (between --base-ref and HEAD) to be carried by a migration that re-defines it (#178). Static, no DB. Implies --require-migration. OFF by default — drain the standing backlog first (see --list-unmigrated-bodies). The runtime counterpart is --check-body-replay. |
| `--list-unmigrated-bodies` | - | Flag | off | Report-only: list function body changes (between --base-ref and HEAD) not carried by a migration, WITHOUT failing (exit 0). Use to size and drain the backlog before enabling --require-migration-bodies. Report mode: cannot be combined with any other check. |
| `--base-ref` | - | text | `origin/main` | Base git reference for comparison (default: origin/main) |
| `--since` | - | text | - | Shortcut for --base-ref (default: none) |
| `--staged` | - | Flag | off | Validate staged files only, pre-commit mode (default: off) |
| `--require-grant-migration` | - | Flag | off | Verify that each changed GRANT/REVOKE in the grant directory is carried by an accompanying migration (SQL or Python). Semantic match across table/schema/sequence/function objects; grants that can't be statically verified degrade to a file-presence check and are surfaced as notes (default: off). |
| `--allow-grant-only` | - | Flag | off | Suppress --require-grant-migration failure for build-only branches (default: off) |
| `--dry-run` | - | Flag | off | Preview changes without renaming (default: off) |
| `--check-live-drift` | - | Flag | off | Compare the live database schema against the DDL files. Requires --config and a database connection. |
| `--ignore-column-order` | - | Flag | off | With --check-live-drift: do not report column_order_mismatch (#226) |
| `--check-signatures` | - | Flag | off | Compare function signatures in --schema against the live DB. Detects stale overloads created by CREATE OR REPLACE with changed param types. Companion to --require-migration (static pre-commit check, no DB needed). Requires --config (or --env) and --schema. |
| `--check-imports` | - | Flag | off | Import-check pending Python migration modules. Level 1: catches syntax errors and missing imports. Level 2: verifies version, name, up(), down() are defined. No database connection required. |
| `--check-body` | - | Flag | off | Compare function bodies (prosrc) between source SQL and the live database. Requires --check-signatures. Opt-in because body comparison is heavier than signature-only comparison. |
| `--show-diff` | - | Flag | off | With --check-body: also emit, per drifted function, the expected body, the live body, and a unified diff of the two (normalised) bodies. Requires --check-body. Opt-in because bodies can be large; the default output stays hash-only for terse CI logs. Also applies to --check-body-views. |
| `--check-body-views` | - | Flag | off | Compare view and materialized-view definitions between the source schema and the live database. The expected views are built into a scratch DB and read back through the same pg_get_viewdef deparser as live, so only genuine predicate/projection changes register (formatting, schema-qualification and *-expansion differences do not). Requires --config (or --env) and --schema. Honours --schemas and --ssh (with --scratch-url). |
| `--check-body-replay` | - | Flag | off | Detect out-of-band function/procedure hot-patches by REPLAY: rebuild the expected database by replaying all migrations into a scratch DB, then diff prosrc against live. Unlike --check-body (expected = source DDL, swamped by the build-vs-migrate backlog), this reports only definitions no migration produced — the clean production drift signal. Requires --config (or --env); honours --schemas, --migrations-dir, --ssh (with --scratch-url). Heaviest drift check (replays the full migration history). |
| `--scratch-url` | - | text | - | Writable PostgreSQL server on which to build the expected scratch database for --check-body-views / --check-body-replay (default: the live server from the config). Required when using --ssh, since the scratch DB cannot be built on the remote read-only live server. |
| `--check-acls` / `--check-acl-coverage` | - | Flag | off | Static: verify every `CREATE TABLE` in db/migrations/ has a matching `GRANT` either in the same migration or in the configured global grant sweep directory (defaults to db/7_grant). No-op when the config has no `acls:` block. No database connection required. Use --check-acls; --check-acl-coverage is a deprecated alias. |
| `--check-ownership-coverage` | - | Flag | off | Static: verify every `CREATE { TABLE \| VIEW \| MATERIALIZED VIEW \| SEQUENCE }` in db/migrations/ is paired with a matching `ALTER … OWNER TO <expected_owner>` in the same file (`own_001`). Also flags bare `ALTER … OWNER TO` on objects the migration didn't create (`own_002` — three severity tiers: silent when guarded + companion `requires_superuser=True`, WARNING when only guarded, ERROR when bare). No-op when the config has no `ownership:` block, or when `ownership.lint_enabled` is false. Requires the [ast] extra (pglast). |
| `--check-function-uniqueness` | - | Flag | off | Static: verify every `CREATE FUNCTION` / `CREATE PROCEDURE` in the configured DDL directories has a unique fully-qualified signature. Two files defining the same `schema.name(args)` are silently shadowed by `confiture build` — this rule (`func_001`) catches the duplicate first. No-op when the config has no `function_coverage:` block, or when `function_coverage.enabled` is false. Requires the [ast] extra (pglast). |
| `--check-security-definer` | - | Flag | off | Flag `SECURITY DEFINER` functions/procedures that do not pin `search_path` (CVE-2018-1058). Rule `sec_002`. Without `--against-db`: static DDL scan (no DB, requires [ast]/pglast). With `--against-db`: live `pg_proc` query (authoritative; works even when ALTER FUNCTION patched the search_path separately from the CREATE). No-op when config has no `security_lint:` block or `security_lint.enabled` is false. Default severity advisory (warning, exit 0); set `security_lint.severity: error` for exit 1. See docs/guides/security-definer-lint.md. |
| `--against-db` | - | Flag | off | Used with `--check-security-definer`: query the live database (`pg_proc.proconfig`) instead of scanning DDL source files. Authoritative for migrate-strategy databases where `ALTER FUNCTION … SET search_path` may have been applied after the original CREATE. |
| `--emit-remediation` | - | path | - | Used with `--check-security-definer`: write a SQL remediation script containing one `ALTER FUNCTION … SET search_path = …` statement per flagged callable to the given file path. Does nothing when no violations are found. |
| `--ddl-dir` | - | path | - | DDL directory to scan for `--check-function-uniqueness` and `--check-security-definer` (repeatable). Defaults to `db/schema` if not provided. |
| `--schemas` | - | text | `public` | Comma-separated list of schemas to inspect for stale overloads (default: public). Used with --check-signatures. |
| `--config` | `-c` | path | `confiture.yaml` | Config file path. Use --env as a shortcut for db/environments/{name}.yaml. |
| `--env` | - | text | - | Environment name — shortcut for --config db/environments/{name}.yaml (e.g. --env production). Cannot be combined with --config. |
| `--ssh` | - | text | - | Open an SSH tunnel before connecting: user@host or host (e.g. lionel@printoptim.io). Used with --check-signatures and --check-live-drift. Overrides the ssh_tunnel block in the config file. |
| `--schema` | - | path | - | Schema SQL file to compare against. If omitted with --check-signatures, schema is auto-built from DDL files. |
| `--format` | `-f` | text | `text` | Output format: text or json or csv (default: text) |
| `--output` | `-o` | path | - | Save output to file (default: stdout) |

<!-- END GENERATED: cli confiture migrate validate -->

### `confiture migrate preflight`

Pre-deploy safety check. Answers four questions before running `migrate up`:

1. Are all pending migrations **reversible**? (`.down.sql` exists)
2. Do any contain **non-transactional statements**? (`CREATE INDEX CONCURRENTLY`, `ALTER TYPE ... ADD VALUE`, etc.)
3. Are there **duplicate migration versions** on disk?
4. Have applied migration files been **tampered with**? (checksum verification, DB required)

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

Detection uses **pglast** (PostgreSQL's C parser), a dependency since 0.50.0; a file it cannot parse is reported as `IDEM_UNPARSEABLE` rather than scanned by anything less exact.

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


<!-- BEGIN GENERATED: cli confiture migrate preflight -->

**Usage**

```bash
confiture migrate preflight [OPTIONS]
```

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--migrations-dir` | - | path | `db/migrations` | Migrations directory (default: db/migrations) |
| `--format` | `-f` | text | `table` | Output format: table or json (default: table) |
| `--output` | `-o` | path | - | Save output to file (default: stdout) |
| `--against` | - | text | - | PostgreSQL URL of the preflight database to test migrations against. Typically seeded from pg_dump --schema-only. Migrations are executed inside a transaction that is always rolled back. |
| `--config` | `-c` | path | - | Config file for pending-migration detection. Connects to the configured database to read the tracking table. |
| `--database-url` | `-d` | text | - | PostgreSQL DSN of the tracking database for pending-migration detection (distinct from --against, which is the throwaway target). Takes precedence over --config / --env and the CONFITURE_DATABASE_URL / DATABASE_URL env vars. |
| `--env` | - | text | - | Environment shortcut — db/environments/{name}.yaml (e.g. --env production). |
| `--no-config` | - | Flag | off | Suppress config-file discovery entirely; the environment (CONFITURE_DATABASE_URL, else DATABASE_URL) becomes the sole DSN source. Use this for runtime-resolved DSNs that must not be exposed in argv. |
| `--since` | - | text | - | Test migrations with version >= SINCE (e.g. --since 20260428000000). Inclusive. Alternative to --config when no second DB connection is available. |
| `--allow-non-transactional` | - | Flag | off | Run non-transactional migrations (CREATE INDEX CONCURRENTLY, etc.) outside the rollback SAVEPOINT in autocommit mode. The preflight DB will be permanently modified (db_consumed=True). By default such migrations are skipped. |
| `--check-dependents` | - | text | `off` | Enumerate live dependents of CREATE OR REPLACE targets via pg_depend on the --against preflight DB. 'off' (default), 'fail' (exit 1 on dependents found), or 'warn' (render dependents as informational, exit code unchanged). Requires the [ast] extra (pglast). |
| `--strict` | - | Flag | off | Treat warnings as errors for exit purposes (warnings → exit 7). |

<!-- END GENERATED: cli confiture migrate preflight -->

### `confiture migrate verify` — runtime correctness

Runs each applied migration's `.verify.sql` sidecar (a `SELECT` returning a
truthy value) inside a read-only `SAVEPOINT`. This checks *runtime state*; for
*file integrity* — have applied migration files been modified since? — use
[`confiture verify-checksums`](#confiture-verify-checksums).

#### Exit codes

| Exit | Meaning |
|------|---------|
| `0` | All verified (or no ledger, under `--allow-uninitialized`) |
| `1` | At least one `.verify.sql` failed |
| `2` | `PRECON_1001` — the database has no migration ledger |
| `3` | Database connection failed |
| `5` | Configuration problem |

The JSON payload carries `ledger_present` (0.37.0+): `false` means the database
has no migration ledger at all, and is only emitted under
`--allow-uninitialized`. A present-but-empty ledger reports `true` with
`total_applied: 0` — "not initialized" and "nothing applied yet" are different
states.

```bash
# CI gate against a migrated database
confiture migrate verify -c db/environments/production.yaml

# A database built from schema files legitimately has no ledger
confiture migrate verify -c db/environments/ci.yaml --allow-uninitialized
```

---


<!-- BEGIN GENERATED: cli confiture migrate verify -->

**Usage**

```bash
confiture migrate verify [OPTIONS]
```

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--migrations-dir` | - | path | `db/migrations` | Migrations directory (default: db/migrations) |
| `--config` | `-c` | path | - | Configuration file path |
| `--database-url` | `-d` | text | - | PostgreSQL DSN for the tracking database. Always wins over --config / --env and the env vars. The canonical CONFITURE_DATABASE_URL beats a *default* --config but conflicts with an *explicit* one (CONFIG_007); the ambient DATABASE_URL never overrides a present config. Pass --no-config to make the environment the sole source. When a DSN is supplied, no YAML is required (tracking table defaults to tb_confiture). SSH-tunnel configs still require --config. |
| `--no-config` | - | Flag | off | Suppress config-file discovery entirely; the environment (CONFITURE_DATABASE_URL, else DATABASE_URL) becomes the sole DSN source. Use this for runtime-resolved DSNs that must not be exposed in argv. |
| `--version` | - | text | - | Verify a single migration version (default: verify all applied) |
| `--format` | `-f` | text | `text` | Output format: text or json (default: text) |
| `--output` | `-o` | path | - | Save output to file (default: stdout) |
| `--allow-uninitialized` | - | Flag | off | Treat a database with no migration ledger as success (exit 0) instead of exit 2. For gates that legitimately run against schema-built databases. |

<!-- END GENERATED: cli confiture migrate verify -->

### `confiture verify-checksums` — file integrity

Compares SHA-256 checksums of migration files against the checksums stored when
they were applied, detecting files modified after application (tampering /
schema drift). Top-level, **not** a `migrate` subcommand.

`confiture verify` (a deprecated alias since 0.19.0) was removed in 0.51.0; use `verify-checksums`.

#### Exit codes

| Exit | Meaning |
|------|---------|
| `0` | All checksums verified (or no ledger, under `--allow-uninitialized`) |
| `1` | Checksum mismatches found — the CI gate this command exists to trip |
| `2` | `PRECON_1001` — the database has no migration ledger |

Before 0.37.0 an absent ledger crashed to exit 1 with a raw psycopg
`relation "tb_confiture" does not exist`, making it indistinguishable from
"checksums are wrong". See [exit codes](exit-codes.md) for why exit 2 rather
than 0 was chosen.

```bash
confiture verify-checksums --config db/environments/production.yaml

# Post-restore, where the ledger may legitimately be absent
confiture verify-checksums --allow-uninitialized
```

---


<!-- BEGIN GENERATED: cli confiture verify-checksums -->

**Usage**

```bash
confiture verify-checksums [OPTIONS]
```

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--migrations-dir` | - | path | `db/migrations` | Migrations directory |
| `--config` | `-c` | path | `db/environments/local.yaml` | Configuration file |
| `--fix` | - | Flag | off | Update stored checksums to match current files (dangerous) |
| `--allow-uninitialized` | - | Flag | off | Treat a database with no migration ledger as success (exit 0) instead of exit 2. For gates that legitimately run against schema-built databases. |
| `--format` | `-f` | text | `text` | Output format: text or json (default: text) |

<!-- END GENERATED: cli confiture verify-checksums -->

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

#### Scoping `--idempotent` to changed migrations (0.37.0)

**In CI you must set `fetch-depth: 0`.** `actions/checkout` defaults to a
shallow clone with no `origin/main` and no merge base; without full history the
run fails with `GIT_003` (exit 7).

`--idempotent` scans every migration by default. In a project with an
unremediated back-catalogue that makes it unusable as a hard gate, since every
branch trips on violations it did not introduce. Scope it to what the branch
actually changed:

```yaml
- uses: actions/checkout@v4
  with:
    fetch-depth: 0          # required
- run: confiture migrate validate --idempotent --base-ref origin/main
```

For a pre-commit hook use `--staged`, which reads the **staging index** rather
than the working tree — so it judges what is about to be committed, and catches
a migration that has been staged but not yet committed (`--base-ref` compares
committed trees and cannot see one):

```bash
confiture migrate validate --idempotent --staged
```

⚠️ **Scoping requires an explicit flag.** `--base-ref` carries a default of
`origin/main`, but that default does **not** scope — a bare
`confiture migrate validate --idempotent` scans everything, exactly as before,
and still works outside a git repository. Only an explicitly passed
`--base-ref`, `--since`, or `--staged` turns scoping on. When both `--staged`
and `--base-ref` are given, `--staged` wins.

Scoping fails loud rather than silently selecting nothing: an unreachable base
ref is `GIT_003` (exit 7), a migrations directory outside the repository is a
configuration error, and running outside a git repository with an explicit
scope flag is `GIT_002` (exit 7). A gate that scanned zero files must never be
mistakable for a gate that passed.

Under `--format json`, a scoped run reports its selection under `meta.scope`:

```json
"meta": {
  "backend": "ast",
  "scope": {"mode": "base-ref", "base_ref": "origin/main",
            "files_selected": 3, "files_skipped": 412}
}
```

An unscoped run emits no `scope` key at all. When the scope selects no
migrations the run succeeds with a `message` explaining that nothing changed
since the base ref — deliberately distinct from the "directory contains no
files" message, since the remedies differ.

Since 0.41.0 `--idempotent` composes with `--check-drift`,
`--require-migration`, `--require-migration-bodies` and
`--require-grant-migration`. Earlier versions rejected those combinations with
exit 5, because only one of the two checks would have run.

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
        run: pip install fraiseql-confiture

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


<!-- BEGIN GENERATED: cli confiture migrate validate -->

**Usage**

```bash
confiture migrate validate [OPTIONS]
```

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--migrations-dir` | - | path | `db/migrations` | Migrations directory (default: db/migrations) |
| `--fix-naming` | - | Flag | off | Auto-rename orphaned files to match convention (default: off) |
| `--idempotent` | - | Flag | off | Validate migrations are idempotent, can re-run (default: off) |
| `--list-patterns` | - | Flag | off | Print machine-readable catalog of detection patterns (read-only, no DB needed). Use with `--format json` for tooling. Report mode: cannot be combined with any other check. |
| `--strict-cor` | - | Flag | off | Treat info-severity CREATE OR REPLACE shape-risk findings as blocking (exit 1). Off by default — info findings are still rendered but don't fail the gate. |
| `--fail-on-unanalyzable` | - | Flag | off | Treat statements the analyzer could not read as a failure (exit 1). Off by default. Pair with --base-ref so an existing backlog of dynamic SQL does not fail every run. Requires --idempotent. |
| `--check-drift` | - | Flag | off | Validate schema against git refs for drift (default: off) |
| `--require-migration` | - | Flag | off | Ensure DDL changes have migration files (static, no DB required). Also detects function parameter type changes missing a DROP FUNCTION. Companion to --check-signatures which detects stale overloads in a live DB. |
| `--require-migration-bodies` | - | Flag | off | Additionally require a function/procedure BODY change (between --base-ref and HEAD) to be carried by a migration that re-defines it (#178). Static, no DB. Implies --require-migration. OFF by default — drain the standing backlog first (see --list-unmigrated-bodies). The runtime counterpart is --check-body-replay. |
| `--list-unmigrated-bodies` | - | Flag | off | Report-only: list function body changes (between --base-ref and HEAD) not carried by a migration, WITHOUT failing (exit 0). Use to size and drain the backlog before enabling --require-migration-bodies. Report mode: cannot be combined with any other check. |
| `--base-ref` | - | text | `origin/main` | Base git reference for comparison (default: origin/main) |
| `--since` | - | text | - | Shortcut for --base-ref (default: none) |
| `--staged` | - | Flag | off | Validate staged files only, pre-commit mode (default: off) |
| `--require-grant-migration` | - | Flag | off | Verify that each changed GRANT/REVOKE in the grant directory is carried by an accompanying migration (SQL or Python). Semantic match across table/schema/sequence/function objects; grants that can't be statically verified degrade to a file-presence check and are surfaced as notes (default: off). |
| `--allow-grant-only` | - | Flag | off | Suppress --require-grant-migration failure for build-only branches (default: off) |
| `--dry-run` | - | Flag | off | Preview changes without renaming (default: off) |
| `--check-live-drift` | - | Flag | off | Compare the live database schema against the DDL files. Requires --config and a database connection. |
| `--ignore-column-order` | - | Flag | off | With --check-live-drift: do not report column_order_mismatch (#226) |
| `--check-signatures` | - | Flag | off | Compare function signatures in --schema against the live DB. Detects stale overloads created by CREATE OR REPLACE with changed param types. Companion to --require-migration (static pre-commit check, no DB needed). Requires --config (or --env) and --schema. |
| `--check-imports` | - | Flag | off | Import-check pending Python migration modules. Level 1: catches syntax errors and missing imports. Level 2: verifies version, name, up(), down() are defined. No database connection required. |
| `--check-body` | - | Flag | off | Compare function bodies (prosrc) between source SQL and the live database. Requires --check-signatures. Opt-in because body comparison is heavier than signature-only comparison. |
| `--show-diff` | - | Flag | off | With --check-body: also emit, per drifted function, the expected body, the live body, and a unified diff of the two (normalised) bodies. Requires --check-body. Opt-in because bodies can be large; the default output stays hash-only for terse CI logs. Also applies to --check-body-views. |
| `--check-body-views` | - | Flag | off | Compare view and materialized-view definitions between the source schema and the live database. The expected views are built into a scratch DB and read back through the same pg_get_viewdef deparser as live, so only genuine predicate/projection changes register (formatting, schema-qualification and *-expansion differences do not). Requires --config (or --env) and --schema. Honours --schemas and --ssh (with --scratch-url). |
| `--check-body-replay` | - | Flag | off | Detect out-of-band function/procedure hot-patches by REPLAY: rebuild the expected database by replaying all migrations into a scratch DB, then diff prosrc against live. Unlike --check-body (expected = source DDL, swamped by the build-vs-migrate backlog), this reports only definitions no migration produced — the clean production drift signal. Requires --config (or --env); honours --schemas, --migrations-dir, --ssh (with --scratch-url). Heaviest drift check (replays the full migration history). |
| `--scratch-url` | - | text | - | Writable PostgreSQL server on which to build the expected scratch database for --check-body-views / --check-body-replay (default: the live server from the config). Required when using --ssh, since the scratch DB cannot be built on the remote read-only live server. |
| `--check-acls` / `--check-acl-coverage` | - | Flag | off | Static: verify every `CREATE TABLE` in db/migrations/ has a matching `GRANT` either in the same migration or in the configured global grant sweep directory (defaults to db/7_grant). No-op when the config has no `acls:` block. No database connection required. Use --check-acls; --check-acl-coverage is a deprecated alias. |
| `--check-ownership-coverage` | - | Flag | off | Static: verify every `CREATE { TABLE \| VIEW \| MATERIALIZED VIEW \| SEQUENCE }` in db/migrations/ is paired with a matching `ALTER … OWNER TO <expected_owner>` in the same file (`own_001`). Also flags bare `ALTER … OWNER TO` on objects the migration didn't create (`own_002` — three severity tiers: silent when guarded + companion `requires_superuser=True`, WARNING when only guarded, ERROR when bare). No-op when the config has no `ownership:` block, or when `ownership.lint_enabled` is false. Requires the [ast] extra (pglast). |
| `--check-function-uniqueness` | - | Flag | off | Static: verify every `CREATE FUNCTION` / `CREATE PROCEDURE` in the configured DDL directories has a unique fully-qualified signature. Two files defining the same `schema.name(args)` are silently shadowed by `confiture build` — this rule (`func_001`) catches the duplicate first. No-op when the config has no `function_coverage:` block, or when `function_coverage.enabled` is false. Requires the [ast] extra (pglast). |
| `--check-security-definer` | - | Flag | off | Flag `SECURITY DEFINER` functions/procedures that do not pin `search_path` (CVE-2018-1058). Rule `sec_002`. Without `--against-db`: static DDL scan (no DB, requires [ast]/pglast). With `--against-db`: live `pg_proc` query (authoritative; works even when ALTER FUNCTION patched the search_path separately from the CREATE). No-op when config has no `security_lint:` block or `security_lint.enabled` is false. Default severity advisory (warning, exit 0); set `security_lint.severity: error` for exit 1. See docs/guides/security-definer-lint.md. |
| `--against-db` | - | Flag | off | Used with `--check-security-definer`: query the live database (`pg_proc.proconfig`) instead of scanning DDL source files. Authoritative for migrate-strategy databases where `ALTER FUNCTION … SET search_path` may have been applied after the original CREATE. |
| `--emit-remediation` | - | path | - | Used with `--check-security-definer`: write a SQL remediation script containing one `ALTER FUNCTION … SET search_path = …` statement per flagged callable to the given file path. Does nothing when no violations are found. |
| `--ddl-dir` | - | path | - | DDL directory to scan for `--check-function-uniqueness` and `--check-security-definer` (repeatable). Defaults to `db/schema` if not provided. |
| `--schemas` | - | text | `public` | Comma-separated list of schemas to inspect for stale overloads (default: public). Used with --check-signatures. |
| `--config` | `-c` | path | `confiture.yaml` | Config file path. Use --env as a shortcut for db/environments/{name}.yaml. |
| `--env` | - | text | - | Environment name — shortcut for --config db/environments/{name}.yaml (e.g. --env production). Cannot be combined with --config. |
| `--ssh` | - | text | - | Open an SSH tunnel before connecting: user@host or host (e.g. lionel@printoptim.io). Used with --check-signatures and --check-live-drift. Overrides the ssh_tunnel block in the config file. |
| `--schema` | - | path | - | Schema SQL file to compare against. If omitted with --check-signatures, schema is auto-built from DDL files. |
| `--format` | `-f` | text | `text` | Output format: text or json or csv (default: text) |
| `--output` | `-o` | path | - | Save output to file (default: stdout) |

<!-- END GENERATED: cli confiture migrate validate -->

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

#### `confiture migrate schema-to-schema analyze`

Analyze tables and recommend a per-table strategy (FDW vs COPY).

<!-- BEGIN GENERATED: cli confiture migrate schema-to-schema analyze -->

**Usage**

```bash
confiture migrate schema-to-schema analyze [OPTIONS]
```

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--source` | - | text | - | Source (old) database: env name, config path, or DSN. |
| `--target` | - | text | - | Target (new) database: env name, config path, or DSN. |
| `--schema` | - | text | `public` | Schema to analyze (default: public). |
| `--format` | `-f` | text | `text` | Output format: text or json (default: text) |

<!-- END GENERATED: cli confiture migrate schema-to-schema analyze -->

#### `confiture migrate schema-to-schema cleanup`

Remove the FDW server + foreign schema from the target after cutover.

<!-- BEGIN GENERATED: cli confiture migrate schema-to-schema cleanup -->

**Usage**

```bash
confiture migrate schema-to-schema cleanup [OPTIONS]
```

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--source` | - | text | - | Source (old) database: env name, config path, or DSN. |
| `--target` | - | text | - | Target (new) database: env name, config path, or DSN. |
| `--format` | `-f` | text | `text` | Output format: text or json (default: text) |

<!-- END GENERATED: cli confiture migrate schema-to-schema cleanup -->

#### `confiture migrate schema-to-schema migrate`

Migrate every table declared in the column-mapping YAML.

<!-- BEGIN GENERATED: cli confiture migrate schema-to-schema migrate -->

**Usage**

```bash
confiture migrate schema-to-schema migrate [OPTIONS]
```

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--source` | - | text | - | Source (old) database: env name, config path, or DSN. |
| `--target` | - | text | - | Target (new) database: env name, config path, or DSN. |
| `--mapping` | - | path | - | Per-table column-mapping YAML (see the guide). |
| `--strategy` | - | text | `fdw` | Migration strategy: fdw or copy (default: fdw). |
| `--format` | `-f` | text | `text` | Output format: text or json (default: text) |

<!-- END GENERATED: cli confiture migrate schema-to-schema migrate -->

#### `confiture migrate schema-to-schema migrate-table`

Migrate a single table with an inline column mapping.

<!-- BEGIN GENERATED: cli confiture migrate schema-to-schema migrate-table -->

**Usage**

```bash
confiture migrate schema-to-schema migrate-table [OPTIONS]
```

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--source` | - | text | - | Source (old) database: env name, config path, or DSN. |
| `--target` | - | text | - | Target (new) database: env name, config path, or DSN. |
| `--source-table` | - | text | - | Source table name. |
| `--target-table` | - | text | - | Target table name. |
| `--mapping` | - | text | - | Inline column mapping 'src_col:dst_col,...'. |
| `--strategy` | - | text | `fdw` | fdw or copy (default: fdw). |
| `--format` | `-f` | text | `text` | Output format: text or json (default: text) |

<!-- END GENERATED: cli confiture migrate schema-to-schema migrate-table -->

#### `confiture migrate schema-to-schema setup`

Set up the Foreign Data Wrapper from target → source.

<!-- BEGIN GENERATED: cli confiture migrate schema-to-schema setup -->

**Usage**

```bash
confiture migrate schema-to-schema setup [OPTIONS]
```

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--source` | - | text | - | Source (old) database: env name, config path, or DSN. |
| `--target` | - | text | - | Target (new) database: env name, config path, or DSN. |
| `--skip-import` | - | Flag | off | Create the FDW server without importing the foreign schema. |
| `--format` | `-f` | text | `text` | Output format: text or json (default: text) |

<!-- END GENERATED: cli confiture migrate schema-to-schema setup -->

#### `confiture migrate schema-to-schema verify`

Verify row-count integrity between source and target (exit 1 on mismatch).

<!-- BEGIN GENERATED: cli confiture migrate schema-to-schema verify -->

**Usage**

```bash
confiture migrate schema-to-schema verify [OPTIONS]
```

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--source` | - | text | - | Source (old) database: env name, config path, or DSN. |
| `--target` | - | text | - | Target (new) database: env name, config path, or DSN. |
| `--tables` | - | text | - | Comma-separated tables to verify. |
| `--source-schema` | - | text | `old_schema` |  |
| `--target-schema` | - | text | `public` |  |
| `--format` | `-f` | text | `text` | Output format: text or json (default: text) |

<!-- END GENERATED: cli confiture migrate schema-to-schema verify -->

### `confiture migrate apply-as`

Apply exactly one migration as an explicit PostgreSQL role.

<!-- BEGIN GENERATED: cli confiture migrate apply-as -->

**Usage**

```bash
confiture migrate apply-as [OPTIONS] ROLE VERSION
```

**Arguments**

| Argument | Type | Required | Description |
|---|---|---|---|
| `ROLE` | text | yes | PostgreSQL role under which to apply the migration. Connection URL is read from `apply_as.<role>.url` in the env config. |
| `VERSION` | text | yes | Migration version to apply (e.g. 20260528120000). |

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--config` | `-c` | path | `confiture.yaml` | Config file path. Use --env as a shortcut for db/environments/{name}.yaml. |
| `--env` | - | text | - | Environment name — shortcut for --config db/environments/{name}.yaml. Cannot be combined with --config. |
| `--migrations-dir` | - | path | `db/migrations` | Migrations directory (default: db/migrations). |
| `--format` | `-f` | text | `text` | Output format: text or json (default: text) |

<!-- END GENERATED: cli confiture migrate apply-as -->

### `confiture migrate baseline`

Mark migrations as applied without running them.

<!-- BEGIN GENERATED: cli confiture migrate baseline -->

**Usage**

```bash
confiture migrate baseline [OPTIONS]
```

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--through` | `-t` | text | - | Mark all migrations through this version as applied. Required unless --from-db is given. |
| `--from-db` | - | text | - | Source DSN to copy tb_confiture rows from. When set, history is copied from another database rather than marked manually. Combined with --through, the copy is capped at the named version. |
| `--source-table` | - | text | - | Override the source DB's tracking table name when it differs from the target (default: same as target). |
| `--migrations-dir` | - | path | `db/migrations` | Migrations directory (default: db/migrations) |
| `--config` | `-c` | path | `db/environments/local.yaml` | Configuration file (default: db/environments/local.yaml) |
| `--dry-run` | - | Flag | off | Show what would be marked without making changes (default: off) |

<!-- END GENERATED: cli confiture migrate baseline -->

### `confiture migrate estimate`

Estimate row counts for tables to decide if --batched is needed.

<!-- BEGIN GENERATED: cli confiture migrate estimate -->

**Usage**

```bash
confiture migrate estimate [OPTIONS]
```

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--config` | `-c` | path | `db/environments/local.yaml` | Configuration file (default: db/environments/local.yaml) |
| `--table` | `-t` | text | - | Tables to estimate (default: all tables) |
| `--format` | `-f` | text | `table` | Output format: table or json (default: table) |

<!-- END GENERATED: cli confiture migrate estimate -->

### `confiture migrate fix`

Auto-fix non-idempotent SQL in migrations.

<!-- BEGIN GENERATED: cli confiture migrate fix -->

**Usage**

```bash
confiture migrate fix [OPTIONS]
```

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--migrations-dir` | - | path | `db/migrations` | Migrations directory (default: db/migrations) |
| `--idempotent` | - | Flag | off | Fix non-idempotent SQL statements (default: off) |
| `--ownership` | - | Flag | off | Insert missing `ALTER … OWNER TO <expected_owner>` after each CREATE that lacks one. Requires an `ownership:` block in the config and the [ast] extra (pglast). |
| `--config` | `-c` | path | `confiture.yaml` | Config file (needed for --ownership; defaults to confiture.yaml) |
| `--force` | - | Flag | off | With --ownership --apply: rewrite migration files even when their checksum is already recorded in the local tracking table. Use with care — downstream `migrate verify` will report drift. |
| `--dry-run` | - | Flag | off | Preview changes without modifying files (default: off) |
| `--format` | `-f` | text | `text` | Output format: text or json (default: text) |
| `--output` | `-o` | path | - | Save output to file (default: stdout) |

<!-- END GENERATED: cli confiture migrate fix -->

### `confiture migrate fix-signatures`

Fix stale function overloads: DROP old signature + re-apply source definition.

<!-- BEGIN GENERATED: cli confiture migrate fix-signatures -->

**Usage**

```bash
confiture migrate fix-signatures [OPTIONS]
```

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--config` | `-c` | path | `confiture.yaml` | Config file path. Use --env as a shortcut for db/environments/{name}.yaml. |
| `--env` | - | text | - | Environment name — shortcut for --config db/environments/{name}.yaml. |
| `--schema` | - | path | - | Schema SQL file containing the authoritative function definitions. If omitted, schema is auto-built from DDL files. |
| `--schemas` | - | text | `public` | Comma-separated list of schemas to inspect (default: public). |
| `--ssh` | - | text | - | Open an SSH tunnel before connecting: user@host or host. Overrides the ssh_tunnel block in the config file. |
| `--apply` | - | Flag | off | Execute the fixes in a single transaction. Default is dry-run: print the SQL and exit without changing the DB. |
| `--format` | `-f` | text | `text` | Output format: text or json (default: text) |
| `--output` | `-o` | path | - | Save output to file (default: stdout). |
| `--check-body` | - | Flag | off | Also detect and fix function body drift (same signature, different body). Runs CREATE OR REPLACE from source for each drifted function — no DROP needed. |

<!-- END GENERATED: cli confiture migrate fix-signatures -->

### `confiture migrate introspect`

Detect migration level by comparing live schema to history snapshots.

<!-- BEGIN GENERATED: cli confiture migrate introspect -->

**Usage**

```bash
confiture migrate introspect [OPTIONS]
```

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--config` | `-c` | path | `db/environments/local.yaml` | Configuration file (default: db/environments/local.yaml) |
| `--snapshots-dir` | - | path | `db/schema_history` | Schema history snapshots directory (default: db/schema_history) |
| `--format` | `-f` | text | `text` | Output format: text or json (default: text) |

<!-- END GENERATED: cli confiture migrate introspect -->

### `confiture migrate reinit`

Reset tracking table and re-baseline from migration files on disk.

<!-- BEGIN GENERATED: cli confiture migrate reinit -->

**Usage**

```bash
confiture migrate reinit [OPTIONS]
```

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--through` | `-t` | text | - | Mark migrations as applied through this version (default: all files on disk) |
| `--migrations-dir` | - | path | `db/migrations` | Migrations directory (default: db/migrations) |
| `--config` | `-c` | path | `db/environments/local.yaml` | Configuration file (default: db/environments/local.yaml) |
| `--dry-run` | - | Flag | off | Show what would happen without making changes (default: off) |
| `--yes` | `-y` | Flag | off | Skip confirmation prompt |

<!-- END GENERATED: cli confiture migrate reinit -->

### `confiture migrate steps`

List the online runner's checkpoints, or resume an online migration from them.

<!-- BEGIN GENERATED: cli confiture migrate steps -->

**Usage**

```bash
confiture migrate steps [OPTIONS]
```

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--config` | `-c` | path | `db/environments/local.yaml` | Path to environment config file |
| `--migrations-dir` | - | path | `db/migrations` | Directory containing migration files |
| `--resume` | - | text | - | Continue the online migration with this version from its last checkpoint |
| `--allow-destructive` | - | Flag | off | Run a contract stage that drops the old column (data is lost) |
| `--max-lock-ms` | - | integer | - | Pause this many ms between backfill batches while another session waits for a lock on the table (overrides migration.backfill.max_lock_ms) |
| `--format` | `-f` | text | `table` | Output format: table or json (default: table) |
| `--output` | `-o` | path | - | Write output to file |

<!-- END GENERATED: cli confiture migrate steps -->

## `confiture lint`

Lint the schema DDL of an environment against the registered rules — naming,
primary keys, documentation, duplicate definitions, security — and, opt-in,
the tenant, replica and security-definer families. Rules are selected by code
or family; see [lint-rules.md](lint-rules.md) for the catalogue and the
[schema linting guide](../guides/schema-linting.md) for adoption with a baseline.

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Nothing reached `--fail-on` (default `error`); with `--baseline`, nothing new |
| 1 | A finding at or above `--fail-on` — or, with `--baseline`, any finding the file does not know |
| 2 | Usage error (`--write-baseline` without `--baseline`; `--fail-on` together with one of its aliases) |
| 5 | Configuration error: unknown rule or family, unknown `--fail-on` severity (`CONFIG_010`), missing or malformed baseline file (`CONFIG_012`) |

### Making lint block — `--fail-on`

`--fail-on <severity>` is the whole gate: `error` (the default), `warning`,
`info`, or `never` for "report every finding and never fail". `--fail-on-error`
and `--fail-on-warning` are aliases for the first two, kept because pipelines
use them; passing an alias *and* `--fail-on` states the gate twice and exits 2.

A threshold no selected rule can reach is reported rather than obeyed quietly:
the summary says so in one line and `--format json` carries the same answer as
`gate: {threshold, reachable, reason, max_selectable_severity}`. Reachability is
computed from the registry's declared severities plus the escalations the
environment config makes (`security_lint.severity`, declared replicas), so a
project that has escalated is told the truth and not a generic warning.

### Examples

```bash
confiture lint --env production --format json
confiture lint --select doc,build --ignore doc_002
confiture lint --fail-on warning                                           # block on warnings too
confiture lint --fail-on never --format json                               # report, never fail
confiture lint --baseline .confiture-lint-baseline.json --write-baseline   # once
confiture lint --baseline .confiture-lint-baseline.json                    # every run
```


<!-- BEGIN GENERATED: cli confiture lint -->

**Usage**

```bash
confiture lint [OPTIONS]
```

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--env` | `-e` | text | `local` | Environment to lint (default: local) |
| `--project-dir` | - | path | `.` | Project directory (default: current directory) |
| `--format` | `-f` | text | `table` | Output format: table or json or csv (default: table) |
| `--output` | `-o` | path | - | Output file path (default: stdout, only with json/csv) |
| `--fail-on` | - | text | - | Severity at which the run fails: error (default), warning, info or never. `--fail-on-error` and `--fail-on-warning` are aliases for the first two; passing both an alias and this exits 2. When no selected rule can emit at the threshold, the run says so instead of passing quietly (#247). |
| `--fail-on-error` | - | Flag | on | Alias for `--fail-on error` (default: on) |
| `--fail-on-warning` | - | Flag | off | Alias for `--fail-on warning` (default: off, stricter) |
| `--select` | - | text | - | Rules or families to run, comma-separated (#150). `default` means the rules a plain lint runs, so `--select default,replica` is the defaults plus one family. Omit to run the defaults. See `--list-rules`. |
| `--ignore` | - | text | - | Rules or families to skip, comma-separated. Applied after --select, so --ignore always wins. |
| `--baseline` | - | path | - | Baseline file (#219): fail only on findings it does not know, print only those, rewrite it when findings disappear |
| `--write-baseline` | - | Flag | off | Create or reset the --baseline file from the current findings |
| `--list-rules` | - | Flag | off | Print the rule catalogue (code, family, severity, default/opt-in) and exit 0. Honours --format json. |
| `--replica-safe` | - | Flag | off | Deprecated alias for `--select default,replica` (#139). Still supported; new rules register instead of adding a flag. |
| `--migrations-dir` | - | path | `db/migrations` | Migrations directory for --replica-safe (default: db/migrations) |
| `--check-tenant-isolation` | - | Flag | off | Deprecated alias for `--select default,tenant` (tenant_001): flag function INSERTs missing the FK column a tenant-scoped view requires. |
| `--check-security-definer` | - | Flag | off | Deprecated alias for `--select default,security-definer`. Runs sec_002 over the env's schema DDL: flag SECURITY DEFINER functions/procedures that do not pin search_path (CVE-2018-1058). No-op when the config has no `security_lint:` block or `security_lint.enabled` is false. Default severity is advisory (warning); set `security_lint.severity: error` to make it a hard gate. |

<!-- END GENERATED: cli confiture lint -->

## `confiture drift`

Compare the live database schema against expected DDL and/or the configured `acls:` block.

Structural drift compares tables, columns (type, nullability, order) and indexes. Only the indexes the
DDL declares with `CREATE INDEX` are compared: the index PostgreSQL creates to back a `PRIMARY KEY`,
`UNIQUE` or `EXCLUDE` constraint (`t_pkey`, `t_code_key`, or the constraint's name) is never reported
as `extra_index`, while a free-standing index the live database has and the DDL does not is — on every
table the DDL declares, whether or not that table declares an index of its own.

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

)** - Step-by-step tutorial
- **[Multi-Agent Coordination Guide](../guides/multi-agent-coordination.md)** - Complete coordination guide
- **[Migration Decision Tree](../guides/migration-decision-tree.md)** - Choosing the right strategy
- **[Configuration Reference](./configuration.md)** - Environment configuration
- **[API Reference](../api/index.md)** - Python API documentation

---

**Last Updated**: January 22, 2026
**Version**: 1.1 (Added Multi-Agent Coordination)

<!-- BEGIN GENERATED: cli confiture drift -->

**Usage**

```bash
confiture drift [OPTIONS]
```

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--config` | `-c` | path | `confiture.yaml` | Configuration file (default: confiture.yaml) |
| `--schema` | - | path | - | Schema SQL file, or a directory of .sql files, to compare against (optional when --check-acls is set) |
| `--default-schema` | - | text | `public` | Schema an unqualified CREATE TABLE in --schema belongs to (#227) |
| `--ignore-column-order` | - | Flag | off | Do not report column_order_mismatch (#226); also drift.ignore_column_order in the config |
| `--check-acls` | - | Flag | off | Also compare live grants against the `acls:` block in the config |
| `--check-ownership` | - | Flag | off | Also compare live `pg_class.relowner` against the `ownership:` block |
| `--warn-only` | - | Flag | off | Demote MISSING_GRANT items from critical to warning (progressive rollout) |
| `--format` | `-f` | text | `table` | Output format: table or json (default: table) |
| `--fail-on-warning` | - | Flag | off | Exit with code 1 on warnings as well as critical drift (default: off) |

<!-- END GENERATED: cli confiture drift -->

## `confiture bootstrap`

One-shot environment ownership setup (idempotent).

<!-- BEGIN GENERATED: cli confiture bootstrap -->

**Usage**

```bash
confiture bootstrap [OPTIONS]
```

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--config` | `-c` | path | `confiture.yaml` | Config file path. Use --env as a shortcut for db/environments/{name}.yaml. |
| `--env` | - | text | - | Environment name — shortcut for --config db/environments/{name}.yaml (e.g. --env production). Cannot be combined with --config. |
| `--check` / `--no-check` | - | Flag | on | Read-only: report drift; exit 1 if drift exists. Default mode. |
| `--dry-run` | - | Flag | off | Print the SQL that --apply would run; no side effects. |
| `--apply` | - | Flag | off | Execute the bootstrap plan against the database. |
| `--all-schemas` | - | Flag | off | Authorize `REASSIGN OWNED` across schemas outside `ownership.apply_to`. Required when postgres-owned objects exist in non-scoped schemas. Use during maintenance windows. |
| `--format` | `-f` | text | `text` | Output format: text or json (default: text) |

<!-- END GENERATED: cli confiture bootstrap -->

## `confiture branch`

Schema branching commands (requires pgGit)

### `confiture branch checkout`

Switch to a different schema branch.

<!-- BEGIN GENERATED: cli confiture branch checkout -->

**Usage**

```bash
confiture branch checkout [OPTIONS] NAME
```

**Arguments**

| Argument | Type | Required | Description |
|---|---|---|---|
| `NAME` | text | yes | Branch name to checkout |

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--config` | `-c` | path | `db/environments/local.yaml` | Configuration file |

<!-- END GENERATED: cli confiture branch checkout -->

### `confiture branch commit`

Commit current schema changes.

<!-- BEGIN GENERATED: cli confiture branch commit -->

**Usage**

```bash
confiture branch commit [OPTIONS] MESSAGE
```

**Arguments**

| Argument | Type | Required | Description |
|---|---|---|---|
| `MESSAGE` | text | yes | Commit message |

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--config` | `-c` | path | `db/environments/local.yaml` | Configuration file |

<!-- END GENERATED: cli confiture branch commit -->

### `confiture branch create`

Create a new schema branch.

<!-- BEGIN GENERATED: cli confiture branch create -->

**Usage**

```bash
confiture branch create [OPTIONS] NAME
```

**Arguments**

| Argument | Type | Required | Description |
|---|---|---|---|
| `NAME` | text | yes | Name of the new branch |

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--from` | `-f` | text | - | Parent branch (default: current branch) |
| `--checkout` / `--no-checkout` | - | Flag | on | Checkout new branch after creation (default: on) |
| `--copy-data` / `--no-copy-data` | - | Flag | on | Copy data from parent branch (default: on) |
| `--config` | `-c` | path | `db/environments/local.yaml` | Configuration file (default: db/environments/local.yaml) |

<!-- END GENERATED: cli confiture branch create -->

### `confiture branch delete`

Delete a schema branch.

<!-- BEGIN GENERATED: cli confiture branch delete -->

**Usage**

```bash
confiture branch delete [OPTIONS] NAME
```

**Arguments**

| Argument | Type | Required | Description |
|---|---|---|---|
| `NAME` | text | yes | Branch name to delete |

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--force` | `-f` | Flag | off | Force delete even if branch has unmerged commits |
| `--config` | `-c` | path | `db/environments/local.yaml` | Configuration file |

<!-- END GENERATED: cli confiture branch delete -->

### `confiture branch diff`

Show differences between branches.

<!-- BEGIN GENERATED: cli confiture branch diff -->

**Usage**

```bash
confiture branch diff [OPTIONS] [SOURCE] [TARGET]
```

**Arguments**

| Argument | Type | Required | Description |
|---|---|---|---|
| `SOURCE` | text | no | Source branch (default: current branch) |
| `TARGET` | text | no | Target branch to compare against |

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--config` | `-c` | path | `db/environments/local.yaml` | Configuration file |

<!-- END GENERATED: cli confiture branch diff -->

### `confiture branch list`

List all schema branches.

<!-- BEGIN GENERATED: cli confiture branch list -->

**Usage**

```bash
confiture branch list [OPTIONS]
```

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--config` | `-c` | path | `db/environments/local.yaml` | Configuration file (default: db/environments/local.yaml) |
| `--format` | `-f` | text | `table` | Output format: table or json (default: table) |

<!-- END GENERATED: cli confiture branch list -->

### `confiture branch log`

Show commit history for current branch.

<!-- BEGIN GENERATED: cli confiture branch log -->

**Usage**

```bash
confiture branch log [OPTIONS]
```

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--limit` | `-n` | integer | `10` | Maximum number of commits to show |
| `--config` | `-c` | path | `db/environments/local.yaml` | Configuration file |

<!-- END GENERATED: cli confiture branch log -->

### `confiture branch merge`

Merge one branch into another.

<!-- BEGIN GENERATED: cli confiture branch merge -->

**Usage**

```bash
confiture branch merge [OPTIONS] SOURCE
```

**Arguments**

| Argument | Type | Required | Description |
|---|---|---|---|
| `SOURCE` | text | yes | Source branch to merge from |

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--into` | - | text | - | Target branch (default: current branch) |
| `--dry-run` | - | Flag | off | Show what would be merged without making changes |
| `--config` | `-c` | path | `db/environments/local.yaml` | Configuration file |

<!-- END GENERATED: cli confiture branch merge -->

### `confiture branch merge-abort`

Abort an in-progress merge.

<!-- BEGIN GENERATED: cli confiture branch merge-abort -->

**Usage**

```bash
confiture branch merge-abort [OPTIONS]
```

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--config` | `-c` | path | `db/environments/local.yaml` | Configuration file |

<!-- END GENERATED: cli confiture branch merge-abort -->

### `confiture branch status`

Show current branch status and uncommitted changes.

<!-- BEGIN GENERATED: cli confiture branch status -->

**Usage**

```bash
confiture branch status [OPTIONS]
```

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--config` | `-c` | path | `db/environments/local.yaml` | Configuration file |

<!-- END GENERATED: cli confiture branch status -->

## `confiture coordinate`

Multi-agent coordination for schema changes

### `confiture coordinate abandon`

Abandon an intention before completion.

<!-- BEGIN GENERATED: cli confiture coordinate abandon -->

**Usage**

```bash
confiture coordinate abandon [OPTIONS]
```

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--intent-id` | - | text | - | Intention ID |
| `--reason` | - | text | - | Reason for abandonment |
| `--database-url` | - | text | - | Database URL |
| `--format` | `-f` | text | `text` | Output format: text or json (default: text) |

<!-- END GENERATED: cli confiture coordinate abandon -->

### `confiture coordinate check`

Check for conflicts with a proposed set of schema changes.

<!-- BEGIN GENERATED: cli confiture coordinate check -->

**Usage**

```bash
confiture coordinate check [OPTIONS]
```

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--agent-id` | - | text | - | Agent ID |
| `--feature-name` | - | text | - | Feature name |
| `--schema-changes` | - | text | - | DDL statements or SQL file path |
| `--tables-affected` | - | text | - | Comma-separated table names |
| `--database-url` | - | text | - | Database URL |
| `--format` | `-f` | text | `text` | Output format: text or json (default: text) |

<!-- END GENERATED: cli confiture coordinate check -->

### `confiture coordinate conflicts`

List all detected conflicts between intentions.

<!-- BEGIN GENERATED: cli confiture coordinate conflicts -->

**Usage**

```bash
confiture coordinate conflicts [OPTIONS]
```

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--database-url` | - | text | - | Database URL |
| `--format` | `-f` | text | `text` | Output format: text or json (default: text) |

<!-- END GENERATED: cli confiture coordinate conflicts -->

### `confiture coordinate list-intents`

List all registered intentions with optional filtering.

<!-- BEGIN GENERATED: cli confiture coordinate list-intents -->

**Usage**

```bash
confiture coordinate list-intents [OPTIONS]
```

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--status-filter` | - | text | - | Filter by status (registered, in_progress, completed, merged, abandoned, conflicted) |
| `--agent-filter` | - | text | - | Filter by agent ID |
| `--database-url` | - | text | - | Database URL |
| `--format` | `-f` | text | `text` | Output format: text or json (default: text) |

<!-- END GENERATED: cli confiture coordinate list-intents -->

### `confiture coordinate register`

Register a new agent intention for schema changes.

<!-- BEGIN GENERATED: cli confiture coordinate register -->

**Usage**

```bash
confiture coordinate register [OPTIONS]
```

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--agent-id` | - | text | - | Identifier for the agent, e.g. claude-payments (required) |
| `--feature-name` | - | text | - | Human-readable feature name (required) |
| `--schema-changes` | - | text | - | DDL statements or path to SQL file (required) |
| `--tables-affected` | - | text | - | Comma-separated table names affected (default: none) |
| `--risk-level` | - | text | `low` | Risk assessment: low, medium, high (default: low) |
| `--estimated-hours` | - | float | `0` | Estimated hours to complete (default: 0) |
| `--database-url` | - | text | - | Database URL (default: from config) |
| `--metadata` | - | text | - | JSON metadata string (default: none) |
| `--format` | `-f` | text | `text` | Output format: text or json (default: text) |

<!-- END GENERATED: cli confiture coordinate register -->

### `confiture coordinate resolve`

Mark a conflict as reviewed and provide resolution notes.

<!-- BEGIN GENERATED: cli confiture coordinate resolve -->

**Usage**

```bash
confiture coordinate resolve [OPTIONS]
```

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--conflict-id` | - | integer | - | Conflict ID |
| `--notes` | - | text | - | Resolution notes |
| `--database-url` | - | text | - | Database URL |
| `--format` | `-f` | text | `text` | Output format: text or json (default: text) |

<!-- END GENERATED: cli confiture coordinate resolve -->

### `confiture coordinate status`

Show detailed status of a specific intention.

<!-- BEGIN GENERATED: cli confiture coordinate status -->

**Usage**

```bash
confiture coordinate status [OPTIONS]
```

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--intent-id` | - | text | - | Intention ID |
| `--database-url` | - | text | - | Database URL |
| `--format` | `-f` | text | `text` | Output format: text or json (default: text) |

<!-- END GENERATED: cli confiture coordinate status -->

## `confiture debug`

Debug SQL queries step by step.

### `confiture debug cte`

Debug a SQL query with CTEs by executing each CTE in isolation.

<!-- BEGIN GENERATED: cli confiture debug cte -->

**Usage**

```bash
confiture debug cte [OPTIONS]
```

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--database-url` | `-d` | text | - | PostgreSQL connection URL |
| `--sql` | `-s` | text | - | SQL query to debug |
| `--file` | `-f` | path | - | SQL file to debug |
| `--max-rows` | `-n` | integer | `20` | Max rows per CTE step (default: 20) |
| `--format` | `-f` | text | `table` | Output format: table or json (default: table) |
| `--stop-on-error` / `--continue-on-error` | - | Flag | on | Stop at first failing CTE |

<!-- END GENERATED: cli confiture debug cte -->

## `confiture diff`

Compare two SQL schema files and report differences.

<!-- BEGIN GENERATED: cli confiture diff -->

**Usage**

```bash
confiture diff [OPTIONS]
```

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--from` | - | path | - | Old schema SQL file |
| `--to` | - | path | - | New schema SQL file |
| `--format` | `-f` | text | `text` | Output format: text or json (default: text) |

<!-- END GENERATED: cli confiture diff -->

## `confiture generate`

Generate migrations and SQL function tree files

### `confiture generate alloc`

Return the next sort-stable filename for a schema subtree.

<!-- BEGIN GENERATED: cli confiture generate alloc -->

**Usage**

```bash
confiture generate alloc [OPTIONS] TARGET_DIR
```

**Arguments**

| Argument | Type | Required | Description |
|---|---|---|---|
| `TARGET_DIR` | path | yes | Directory in which to allocate the next filename (must be within --schema-dir). |

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--schema-dir` | - | path | `db/schema` | Root of the schema tree (default: db/schema). |
| `--verb` | - | text | - | Verb suffix appended after the prefix, e.g. 'create' → '00001_create.sql'. |
| `--json` | - | Flag | off | Emit a JSON object {path: ...} instead of plain text. |

<!-- END GENERATED: cli confiture generate alloc -->

### `confiture generate diff`

Show detailed diff between branches.

<!-- BEGIN GENERATED: cli confiture generate diff -->

**Usage**

```bash
confiture generate diff [OPTIONS] BRANCH
```

**Arguments**

| Argument | Type | Required | Description |
|---|---|---|---|
| `BRANCH` | text | yes | Branch name to diff |

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--base` | `-b` | text | `main` | Base branch to compare against (default: main) |
| `--show-sql` | `-s` | Flag | off | Show the actual SQL for each change (default: off) |
| `--config` | - | path | `db/environments/local.yaml` | Configuration file (default: db/environments/local.yaml) |

<!-- END GENERATED: cli confiture generate diff -->

### `confiture generate from-branch`

Generate migrations from a pgGit branch.

<!-- BEGIN GENERATED: cli confiture generate from-branch -->

**Usage**

```bash
confiture generate from-branch [OPTIONS] BRANCH
```

**Arguments**

| Argument | Type | Required | Description |
|---|---|---|---|
| `BRANCH` | text | yes | Branch name to generate migrations from |

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--base` | `-b` | text | `main` | Base branch to compare against (default: main) |
| `--output` | `-o` | path | `db/migrations` | Output directory for migration files (default: db/migrations) |
| `--combined` | `-c` | Flag | off | Generate single combined migration (default: off) |
| `--config` | - | path | `db/environments/local.yaml` | Configuration file (default: db/environments/local.yaml) |

<!-- END GENERATED: cli confiture generate from-branch -->

### `confiture generate pgtap`

Generate pgTAP test scaffolds for PostgreSQL stored functions.

<!-- BEGIN GENERATED: cli confiture generate pgtap -->

**Usage**

```bash
confiture generate pgtap [OPTIONS]
```

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--database-url` | `-d` | text | - | PostgreSQL connection URL |
| `--schema` | `-s` | text | `public` | Schema to introspect |
| `--output` | `-o` | path | - | Output file path |
| `--include` | - | text | - | SQL LIKE pattern to filter functions |
| `--no-volatility` | - | Flag | off | Skip volatility tests (default: include) |
| `--no-return-type` | - | Flag | off | Skip return type tests (default: include) |

<!-- END GENERATED: cli confiture generate pgtap -->

### `confiture generate preview`

Preview what migrations would be generated.

<!-- BEGIN GENERATED: cli confiture generate preview -->

**Usage**

```bash
confiture generate preview [OPTIONS] BRANCH
```

**Arguments**

| Argument | Type | Required | Description |
|---|---|---|---|
| `BRANCH` | text | yes | Branch name to preview |

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--base` | `-b` | text | `main` | Base branch to compare against (default: main) |
| `--config` | - | path | `db/environments/local.yaml` | Configuration file (default: db/environments/local.yaml) |

<!-- END GENERATED: cli confiture generate preview -->

### `confiture generate renumber`

Move a SQL file or subtree and rewrite cross-references.

<!-- BEGIN GENERATED: cli confiture generate renumber -->

**Usage**

```bash
confiture generate renumber [OPTIONS] OLD_PATH NEW_PATH
```

**Arguments**

| Argument | Type | Required | Description |
|---|---|---|---|
| `OLD_PATH` | path | yes | Source file or directory to move. |
| `NEW_PATH` | path | yes | Target file path or directory. When a directory is given, the next available prefix is allocated automatically. |

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--schema-dir` | - | path | `db/schema` | Root of the schema tree (default: db/schema). |
| `--dry-run` | - | Flag | off | Show what would move and what refs would be rewritten, without touching disk. |
| `--force` | - | Flag | off | Proceed even if the old filename is referenced outside the db/ tree (e.g. by application code that loads SQL files by literal path). |
| `--json` | - | Flag | off | Emit structured JSON output. |

<!-- END GENERATED: cli confiture generate renumber -->

### `confiture generate scaffold`

Write SQL files produced by a pluggable framework emitter.

<!-- BEGIN GENERATED: cli confiture generate scaffold -->

**Usage**

```bash
confiture generate scaffold [OPTIONS]
```

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--from` | - | text | - | Emitter callable as 'module.path:callable_name'. Called with no args; must return list[EmittedFunction]. |
| `--schema-dir` | - | path | `db/schema` | Root of the schema tree (default: db/schema). |
| `--overrides-dir` | - | path | - | Override mirror directory. Files present here are skipped during scaffold. |
| `--dry-run` | - | Flag | off | Show what would be written without touching disk. |
| `--json` | - | Flag | off | Emit a JSON object {results: [{path, action}, ...]} instead of plain text. |

<!-- END GENERATED: cli confiture generate scaffold -->

### `confiture generate stubs`

Generate typed Python wrapper functions for stored procedures.

<!-- BEGIN GENERATED: cli confiture generate stubs -->

**Usage**

```bash
confiture generate stubs [OPTIONS]
```

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--database-url` | `-d` | text | - | PostgreSQL connection URL |
| `--schema` | `-s` | text | `public` | Schema to introspect |
| `--output` | `-o` | path | - | Output file path |
| `--format` | - | text | `pydantic` | Output format: pydantic\|dataclass\|typeddict |
| `--include` | - | text | - | SQL LIKE pattern to filter functions |

<!-- END GENERATED: cli confiture generate stubs -->

## `confiture hooks`

Operate on configured notification hooks

### `confiture hooks test`

Fire a synthetic notification through one configured hook.

<!-- BEGIN GENERATED: cli confiture hooks test -->

**Usage**

```bash
confiture hooks test [OPTIONS]
```

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--config` | `-c` | path | `confiture.yaml` | Path to environment config (default: confiture.yaml) |
| `--env` | `-e` | text | - | Environment name — shortcut for db/environments/{env}.yaml |
| `--id` | - | text | - | Hook id to test (required when multiple hooks configured) |
| `--no-dry-run` | - | Flag | off | Send through the real transport. Default is dry-run — the configured transport is swapped for StdoutTransport so no external service is contacted. |

<!-- END GENERATED: cli confiture hooks test -->

## `confiture install-helpers`

Install confiture SQL helper functions in the target database.

<!-- BEGIN GENERATED: cli confiture install-helpers -->

**Usage**

```bash
confiture install-helpers [OPTIONS]
```

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--config` | `-c` | path | - | Configuration file (YAML) |
| `--env` | `-e` | text | `local` | Environment name (default: local) |
| `--dry-run` | - | Flag | off | Show SQL without executing |
| `--force` | - | Flag | off | Reinstall even if already installed |

<!-- END GENERATED: cli confiture install-helpers -->

## `confiture introspect`

Introspect a PostgreSQL database and export its schema as structured JSON.

<!-- BEGIN GENERATED: cli confiture introspect -->

**Usage**

```bash
confiture introspect [OPTIONS]
```

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--db` | - | text | - | PostgreSQL connection URL (e.g. postgresql://user:pass@host/dbname) |
| `--schema` | - | text | `public` | Schema to introspect (default: public) |
| `--format` | `-f` | text | `json` | Output format: json or yaml (default: json) |
| `--all-tables` | - | Flag | off | Include all tables, not just tb_* (default: off) |
| `--hints` / `--no-hints` | - | Flag | on | Include naming-convention hints block (default: on) |
| `--output` | `-o` | path | - | Write output to file instead of stdout |

<!-- END GENERATED: cli confiture introspect -->

## `confiture lint-unified`

Run unified SQL lint checks (Squawk, SQLFluff, SchemaLinter, and/or tree numbering).

<!-- BEGIN GENERATED: cli confiture lint-unified -->

**Usage**

```bash
confiture lint-unified [OPTIONS] [FILES]...
```

**Arguments**

| Argument | Type | Required | Description |
|---|---|---|---|
| `FILES` | path | no | SQL files or directories to lint (default: all schema files) |

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--check` | `-c` | text | - | Which checks to run: safety (squawk), format (sqlfluff), schema (SchemaLinter), tree (GEN001–GEN004 file-numbering). Default: all. |
| `--git-diff` | - | Flag | off | Only lint files changed in the current git diff (default: off) |
| `--env` | `-e` | text | `local` | Environment for schema lint (default: local) |
| `--schema-dir` | - | path | - | Root of the DDL file tree for --check tree (default: inferred from env config). |
| `--overrides-dir` | - | path | - | Overrides mirror directory for GEN004 orphan check (optional). |
| `--format` | `-f` | text | `table` | Output format: table or json (default: table) |
| `--fail-on-error` | - | Flag | on | Exit with code 1 if errors found (default: on) |

<!-- END GENERATED: cli confiture lint-unified -->

## `confiture mcp`

Run confiture as an MCP server.

<!-- BEGIN GENERATED: cli confiture mcp -->

**Usage**

```bash
confiture mcp [OPTIONS] COMMAND [ARGS]...
```

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--database-url` | `-d` | text | - | PostgreSQL connection URL |
| `--schema` | `-s` | text | `public` | Schema to expose |
| `--stdio` | - | Flag | off | Run in stdio mode (for Claude Code) |
| `--include` | - | text | - | LIKE pattern to filter functions |
| `--port` | - | integer | - | HTTP port (not yet implemented) |
| `--no-confiture-tools` | - | Flag | off | Disable built-in Confiture migration/introspection tools |

<!-- END GENERATED: cli confiture mcp -->

## `confiture restore`

Restore a PostgreSQL backup using three-phase pg_restore.

<!-- BEGIN GENERATED: cli confiture restore -->

**Usage**

```bash
confiture restore [OPTIONS] BACKUP_FILE
```

**Arguments**

| Argument | Type | Required | Description |
|---|---|---|---|
| `BACKUP_FILE` | path | yes | Path to pg_dump backup file. Must be custom (-Fc) or directory (-Fd) format. |

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--database` | `-d` | text | - | Target database name |
| `--host` | - | text | `/var/run/postgresql` | PostgreSQL host or socket path |
| `--port` | - | integer | `5432` | PostgreSQL port |
| `--username` | `-U` | text | - | PostgreSQL user |
| `--jobs` | `-j` | integer | `4` | Parallel workers for the data phase |
| `--no-owner` / `--owner` | - | Flag | off | Skip ownership restoration |
| `--no-acl` / `--acl` | - | Flag | off | Skip access privilege restoration |
| `--exit-on-error` / `--no-exit-on-error` | - | Flag | on | Abort on first error (recommended for production restores) |
| `--min-tables` | - | integer | `0` | Post-restore: minimum expected table count (0 = skip check) |
| `--min-tables-schema` | - | text | `public` | Schema for --min-tables validation |
| `--superuser` | - | text | - | Run pg_restore via sudo as this OS user |
| `--refresh-matviews` / `--no-refresh-matviews` | - | Flag | on | Refresh materialized views after a database-wide ANALYZE (default). --no-refresh-matviews leaves them WITH NO DATA for you to refresh later. |

<!-- END GENERATED: cli confiture restore -->

## `confiture seed`

Seed data validation and management

### `confiture seed apply`

Load seed data into the database.

<!-- BEGIN GENERATED: cli confiture seed apply -->

**Usage**

```bash
confiture seed apply [OPTIONS]
```

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--seeds-dir` | - | path | `db/seeds` | Directory containing seed files (default: db/seeds) |
| `--env` | - | text | `local` | Environment name for database URL lookup (default: local) |
| `--sequential` | - | Flag | off | Apply files sequentially, solves 650+ row parser limits |
| `--continue-on-error` | - | Flag | off | Continue if file fails (--sequential only, useful for CI/CD) |
| `--database-url` | - | text | - | Database URL (overrides environment config) |
| `--copy-format` | - | Flag | off | Use COPY format (2-10x faster for large datasets) |
| `--copy-threshold` | - | integer | `1000` | Row threshold for auto COPY (default: 1000, use >1000 rows) |
| `--format` | `-f` | text | `text` | Output format: text or json or csv (default: text) |
| `--output` / `--report` | `-o` | path | - | Save structured output (JSON/CSV) to file. --report is a back-compat alias for --output/-o (DOCS-M2). |
| `--profile` | - | text | - | Apply only the named seed profile (seed.profiles.<name> in env config). |

<!-- END GENERATED: cli confiture seed apply -->

### `confiture seed benchmark`

Compare VALUES vs COPY format performance.

<!-- BEGIN GENERATED: cli confiture seed benchmark -->

**Usage**

```bash
confiture seed benchmark [OPTIONS]
```

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--seeds-dir` | - | path | `db/seeds` | Directory containing seed files (default: db/seeds) |

<!-- END GENERATED: cli confiture seed benchmark -->

### `confiture seed convert`

Transform INSERT statements to COPY format (2-10x faster).

<!-- BEGIN GENERATED: cli confiture seed convert -->

**Usage**

```bash
confiture seed convert [OPTIONS]
```

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--input` | - | path | - | Input file with INSERT statements (required) |
| `--output` | - | path | - | Output file for COPY format (default: stdout) |
| `--batch` | - | Flag | off | Process all .sql files in directory (requires --output) |

<!-- END GENERATED: cli confiture seed convert -->

### `confiture seed generate`

Generate a seed SQL stub for a PostgreSQL table.

<!-- BEGIN GENERATED: cli confiture seed generate -->

**Usage**

```bash
confiture seed generate [OPTIONS] TABLE
```

**Arguments**

| Argument | Type | Required | Description |
|---|---|---|---|
| `TABLE` | text | yes | Table name to generate seed data for |

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--database-url` | `-d` | text | - | PostgreSQL connection URL |
| `--schema` | `-s` | text | `public` | Schema name (default: public) |
| `--env` | `-e` | text | `development` | Seed environment directory |
| `--output-dir` | `-o` | path | `db/seeds` | Seeds output directory (default: db/seeds) |
| `--rows` | `-n` | integer | `10` | Number of stub rows (default: 10) |
| `--overwrite` | - | Flag | off | Overwrite existing seed file (default: off) |
| `--format` | `-f` | text | `text` | Output format: text or json (default: text) |

<!-- END GENERATED: cli confiture seed generate -->

### `confiture seed validate`

Validate seed files for data consistency and quality.

<!-- BEGIN GENERATED: cli confiture seed validate -->

**Usage**

```bash
confiture seed validate [OPTIONS]
```

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--seeds-dir` | - | path | `db/seeds` | Directory containing seed files (default: db/seeds) |
| `--env` | - | text | - | Environment name for multi-env validation (default: none) |
| `--all` | - | Flag | off | Validate all environments (default: off) |
| `--database-url` | - | text | - | Database URL for database mode validation (default: none) |
| `--format` | `-f` | text | `text` | Output format: text or json or csv (default: text) |
| `--output` | - | path | - | Output file path (default: stdout) |
| `--fix` | - | Flag | off | Automatically fix issues where possible (default: off) |
| `--dry-run` | - | Flag | off | Show what would be fixed without modifying (default: off) |
| `--prep-seed` | - | Flag | off | Enable prep-seed pattern validation (default: off) |
| `--level` | `-l` | integer range | `3` | Prep-seed validation level 1-5 (default: 3) |
| `--static-only` | - | Flag | off | Run only Levels 1-3, no database (default: off) |
| `--full-execution` | - | Flag | off | Run all levels 1-5, requires database (default: off) |

<!-- END GENERATED: cli confiture seed validate -->

## `confiture validate-config`

Validate configuration and the migrations tree — without connecting (#144).

<!-- BEGIN GENERATED: cli confiture validate-config -->

**Usage**

```bash
confiture validate-config [OPTIONS]
```

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--config` | `-c` | path | - | Configuration file to validate (default: db/environments/local.yaml) |
| `--database-url` | `-d` | text | - | PostgreSQL DSN for the tracking database. Always wins over --config / --env and the env vars. The canonical CONFITURE_DATABASE_URL beats a *default* --config but conflicts with an *explicit* one (CONFIG_007); the ambient DATABASE_URL never overrides a present config. Pass --no-config to make the environment the sole source. When a DSN is supplied, no YAML is required (tracking table defaults to tb_confiture). SSH-tunnel configs still require --config. |
| `--migrations-path` | - | path | `db/migrations` | Migrations directory to validate (default: db/migrations) |
| `--format` | `-f` | text | `text` | Output format: text or json (default: text) |
| `--strict` | - | Flag | off | Treat warnings as errors for exit purposes. |

<!-- END GENERATED: cli confiture validate-config -->

## `confiture validate-profile`

Validate anonymization profile YAML structure and schema.

<!-- BEGIN GENERATED: cli confiture validate-profile -->

**Usage**

```bash
confiture validate-profile [OPTIONS] PATH
```

**Arguments**

| Argument | Type | Required | Description |
|---|---|---|---|
| `PATH` | path | yes | Path to anonymization profile YAML file |

<!-- END GENERATED: cli confiture validate-profile -->

