# Configuration Reference

Complete reference for Confiture configuration files.

---

## Overview

Confiture uses YAML configuration files stored in `db/environments/` to define:

- **Database connection** settings
- **Schema build** directories
- **Migration** behavior
- **Safety** settings

**Convention**: One YAML file per environment (e.g., `local.yaml`, `staging.yaml`, `production.yaml`).

---

## Configuration File Location

```
db/
└── environments/
    ├── local.yaml           # Local development
    ├── development.yaml     # Shared dev environment
    ├── staging.yaml         # Pre-production testing
    ├── production.yaml      # Production database
    └── test.yaml            # CI/CD testing
```

**Usage**: Reference by filename without extension:

```bash
confiture build --env local        # Loads db/environments/local.yaml
confiture build --env production   # Loads db/environments/production.yaml
```

---

## Configuration Schema

### Complete Example

<!-- doctest:config-complete-example -->
```yaml
# Environment name
name: production

# PostgreSQL connection URL (required)
database_url: postgresql://app_user:secret@db.example.com:5432/myapp_production

# Directories to include when building schema (required)
include_dirs:
  - db/schema/00_common
  - db/schema/10_tables
  - db/schema/20_views
  - db/schema/30_functions
  - db/schema/40_triggers
  # Note: Seeds excluded in production

# Directories to exclude (optional)
exclude_dirs:
  - db/schema/99_development

# Migration tracking configuration (optional)
migration:
  # Tracking table name (optional, default: tb_confiture)
  tracking_table: tb_confiture


```

---

## Required Fields

### `name`

**Type**: String
**Required**: Yes
**Description**: Environment name for display and logging

```yaml
name: production
```

**Best practices**:
- Use lowercase names
- Match filename (e.g., `production.yaml` → `name: production`)
- Use consistent naming across projects

---

### `database_url`

**Type**: String (PostgreSQL URL)
**Required**: Yes
**Format**: `postgresql://[user[:password]@][host][:port]/database`

```yaml
# Full URL with credentials
database_url: postgresql://myuser:mypassword@localhost:5432/myapp_local

# Minimal (uses defaults: postgres@localhost:5432)
database_url: postgresql:///myapp_local

# With host only
database_url: postgresql://dbhost.example.com/myapp_production

# Alternative postgres:// prefix (equivalent)
database_url: postgres://myuser:pass@localhost/mydb
```

**Components**:

| Component | Default | Example | Description |
|-----------|---------|---------|-------------|
| `user` | `postgres` | `app_user` | Database user |
| `password` | (empty) | `secret123` | User password |
| `host` | `localhost` | `db.example.com` | Database host |
| `port` | `5432` | `5433` | PostgreSQL port |
| `database` | (none) | `myapp_local` | Database name (required) |

**Security**: Use environment variables in production:

```yaml
# In production.yaml
database_url: ${DATABASE_URL}
```

```bash
# Set in environment
export DATABASE_URL=postgresql://app_user:secret@db.example.com:5432/myapp_production

# Run commands
confiture migrate up --config db/environments/production.yaml
```

**Note**: Confiture uses `pydantic` validation, so `${VAR}` syntax requires Pydantic v2+ or manual substitution.

**Alternative**: Use a secrets manager (Vault, AWS Secrets Manager):

```python
# Custom script to inject secrets
import yaml
import boto3

def load_config_with_secrets(env_name: str):
    # Load base config
    with open(f"db/environments/{env_name}.yaml") as f:
        config = yaml.safe_load(f)

    # Inject secret from AWS Secrets Manager
    client = boto3.client('secretsmanager')
    secret = client.get_secret_value(SecretId=f'confiture/{env_name}/database_url')
    config['database_url'] = secret['SecretString']

    return config
```

---

### `include_dirs`

**Type**: Array of strings or objects
**Required**: Yes
**Description**: Directories to include when building schema with advanced filtering and ordering options

#### Simple String Format (Backward Compatible)

```yaml
include_dirs:
  - db/schema/00_common
  - db/schema/10_tables
  - db/seeds/common
```

#### Advanced Object Format

```yaml
include_dirs:
  - path: db/schema
    recursive: true          # Default: true
    include:                 # Include patterns (optional)
      - "**/*.sql"
    exclude:                 # Exclude patterns (optional)
      - "**/*.bak"
      - "**/temp/**"
    order: 10                # Build block: groups run low to high (optional, default 0)
    auto_discover: true      # Default: true — a missing directory is skipped, not an error
```

**Configuration Options**:

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `path` | string | required | Directory path (relative or absolute) |
| `recursive` | boolean | `true` | Recursively discover files in subdirectories |
| `include` | array[string] | `["**/*.sql"]` | Glob patterns for files to include |
| `exclude` | array[string] | `[]` | Glob patterns for files to exclude |
| `order` | integer | `0` | Build block: entries are grouped by this value and the groups concatenated low to high |
| `auto_discover` | boolean | `true` | Skip this entry when its directory does not exist, instead of failing the build |

**Path resolution**:
- **Relative paths**: Resolved from project root (where `db/` directory is located)
- **Absolute paths**: Used as-is
- **Validation**: a missing include directory fails the build unless `auto_discover: true` (the
  default), which skips the entry. `auto_discover` decides nothing about *which* files are selected.

**Pattern syntax**: since 1.5.0 these are **gitignore's** globs, matched against the path relative to
the include directory:

- A pattern containing **no `/`** matches the file's *name*, at any depth — `*.sql` and `*.bak` reach
  everywhere under the entry.
- A pattern containing a `/` is matched against the whole relative path, **left-anchored**:
  `10_tables/*.sql` names the `10_tables/` directly under the entry, not an `a/10_tables/` deeper down.
  A trailing `/` names a directory and takes everything beneath it.
- `**` spans **zero or more** directories, so `**/*.sql` selects a top-level `x.sql` as well as a
  nested one, and `**/temp/**` excludes `temp/x.sql` and `a/b/temp/x.sql` alike.
- `*` and `?` never cross a `/`; `[abc]` is a character class and `[!abc]` its negation; matching is
  case-sensitive.

Before 1.5.0 they were matched with `PurePath.match`, where `**` is a single component and matching is
anchored at the *right* end — so the three examples above excluded a different set of files from the
one they name. `confiture build --list-files` prints the selection a configuration produces, naming
the entry and the pattern that put each file there; diff it across an upgrade to see what moved.

> **Two dialects, two key names that look alike.** `seed.profiles.<name>.include` / `.exclude` are
> spelled exactly like an `include_dirs` entry's, but they are `fnmatch` globs over a bare *filename*:
> seed discovery is a flat, non-recursive listing where a path never appears and `**` has nothing to
> span. Only `include_dirs` patterns read the gitignore dialect above.

**Ordering strategy**:

`order` **partitions the build.** Entries are grouped by their `order` value, the groups are
concatenated low to high, and *within* a group the build's sort mode decides — alphabetical by default,
numeric-prefix order under `build.sort_mode: hex`. Every entry defaults to `order: 0`, so a
configuration that never sets the key has exactly one group and its files are sorted as one list.

**The order entries are listed in sequences nothing.** `order` is the only sequencing key: writing
`- db/seeds` above `- db/schema` still builds `db/schema` first when its `order` is lower. Re-listing
two entries that share an `order` does not change the build either. The list order breaks exactly one
tie: when two entries both select the same file — an entry for `db/schema` and one for
`db/schema/10_tables`, say — the file is built once, under the entry with the lower `order`, and among
entries sharing an `order` under the one listed first.

Use numbered prefixes or explicit `order` values to control execution order:

```
db/schema/
├── 00_common/        # Extensions, types (run first)
├── 10_tables/        # Base tables
├── 20_views/         # Views (depend on tables)
├── 30_functions/     # Functions
├── 40_triggers/      # Triggers (run last)
└── 50_permissions/   # Grants
```

**Environment-specific includes**:

`local.yaml` — the schema, then both seed blocks:

<!-- doctest:include-dirs-local -->
```yaml
include_dirs:
  - path: db/schema
    recursive: true
  - path: db/seeds/common
    order: 20
  - path: db/seeds/development
    order: 30
```

`production.yaml` — the same, minus anything under a `development/` directory:

<!-- doctest:include-dirs-production -->
```yaml
include_dirs:
  - path: db/schema
    recursive: true
  - path: db/seeds/common
    order: 20
    exclude:
      - "**/development/**"
```

Both blocks are executed by a test, which builds the tree described here and asserts that
`db/seeds/common/development/` is absent from the production build. Before 1.5.0 it was **present**:
`**/development/**` needed three path components and that directory is two below its entry, so a
production build shipped development seeds.

`db/schema` sets no `order`, so it is block `0` and is built before both seed blocks — not because it
is listed first, but because `0 < 20 < 30`.

---

## Build Configuration

### `build`

**Type**: Object
**Required**: No
**Description**: Build-time configuration options

```yaml
build:
  sort_mode: hex  # Enable hexadecimal file sorting
```

**Options**:

#### `sort_mode`

**Type**: string
**Default**: `alphabetical`
**Values**: `alphabetical`, `hex`
**Description**: File sorting algorithm for deterministic builds

```yaml
# Alphabetical sorting (default)
build:
  sort_mode: alphabetical

# Hexadecimal sorting for complex schemas
build:
  sort_mode: hex
```

**When to use hex sorting**:
- Large schemas with 10+ main categories
- Need more than 9 numbered prefixes
- Clear visual hierarchy required

**Hex sorting details**:
- Files with a `{HH}_` prefix sort by its value; there is no `0x` marker,
  because `x` is not a hex digit
- The base belongs to the directory: one hex-lettered sibling makes the whole
  group hexadecimal
- Unnumbered files sort after every numbered one, by name
- The key reads every path component, so the order does not depend on the
  filesystem

**See [Hexadecimal Sorting](../features/hexadecimal-sorting.md)** for complete documentation.

---

## Seed Configuration

### `seed`

**Type**: Object
**Required**: No
**Description**: Seed data execution configuration

```yaml
seed:
  execution_mode: sequential
```

**Options**:

#### `execution_mode`

**Type**: string
**Default**: `concatenate`
**Values**: `concatenate`, `sequential`
**Description**: How seed files are executed

```yaml
# Default: concatenate all seed files into single SQL stream
seed:
  execution_mode: concatenate

# Sequential: apply each seed file separately within a savepoint
seed:
  execution_mode: sequential
```

**When to use sequential**:
- Seed files have 500+ INSERT statements
- You need per-file error isolation
- Large seed files would fail with concatenation
- Parser limit errors occur

**Sequential benefits**:
- ✅ Avoids PostgreSQL parser limits
- ✅ Per-file error handling
- ✅ Fresh parser state for each file
- ✅ Continue-on-error support

**Usage**:

```bash
# With config: seed.execution_mode: sequential
confiture build --sequential --database-url postgresql://localhost/mydb

# Or explicitly
confiture seed apply --sequential --env local
```

**See [Sequential Seed Execution](../guides/sequential-seed-execution.md)** for complete guide.

---

## Optional Fields

### `exclude_dirs`

**Type**: Array of strings
**Default**: `[]` (empty list)
**Description**: Directories to exclude from schema build (even if matched by `include_dirs`)

```yaml
include_dirs:
  - db/schema  # Include all subdirectories

exclude_dirs:
  - db/schema/99_experimental  # Except this one
  - db/schema/archived
```

**Use cases**:
- Exclude work-in-progress schema files
- Skip archived or deprecated schemas
- Prevent test fixtures from being included

---

### `migration.tracking_table`

**Type**: String
**Default**: `tb_confiture`
**Description**: Name of the table that tracks applied migrations. Nested under
the `migration:` section. Optionally schema-qualified (e.g. `public.tb_confiture`).

```yaml
migration:
  tracking_table: tb_confiture
```

**Custom table name** (if the default conflicts):

```yaml
migration:
  tracking_table: my_custom_migrations
```

See [Tracking Table](./tracking-table.md) for the full table schema and columns.

---


### `migration.locking`

**Type**: Object (`enabled`, `timeout_ms`)
**Default**: `enabled: true`, `timeout_ms: 30000`
**Description**: The advisory lock every `migrate up` / `migrate down` / `migrate apply-as`
takes so two deployments never apply concurrently. The CLI flags `--lock-timeout` and
`--no-lock` override it for one run; the library reads it through
`Migrator.from_config(...)`.

```yaml
migration:
  locking:
    enabled: true        # false = never lock (single-writer environments only)
    timeout_ms: 30000    # how long to wait for the lock before exit 6
```

---

### `drift`

How `confiture drift --schema` and `migrate validate --check-live-drift` judge
column order (#226). Both sides carry it — the expected DDL in declaration
order, the live database by `ordinal_position` — and a table whose columns are
the same set in a different order is one `column_order_mismatch` item.

```yaml
drift:
  ignore_column_order: false        # true: never report column_order_mismatch
  column_order_severity: warning    # or critical: the item fails the run
```

`--ignore-column-order` on either command wins over the file for that run.

### `acls`

**Type**: Array of `AclExpectation` (optional)
**Default**: `[]`
**Description**: Expected `GRANT`s per schema. Read by `confiture drift --check-acls` (runtime) and `confiture lint` / `confiture migrate validate --check-acl-coverage` (static).

```yaml
acls:
  - schema: tenant
    apply_to: ALL_TABLES               # or list of relname glob patterns
    ignore: [tb_*_legacy, "*_tmp"]     # optional, evaluated against bare relname
    grants:
      - role: ${APP_ROLE}              # ${VAR} expansion at config-load time
        privileges: [SELECT, INSERT, UPDATE, DELETE]
      - role: ${ETL_ROLE}
        privileges: [SELECT, INSERT, UPDATE, DELETE]
  - schema: public
    apply_to: ALL_TABLES
    grants:
      - role: ${APP_ROLE}
        privileges: [SELECT, INSERT, UPDATE, DELETE, TRUNCATE]
```

**`AclExpectation` fields**:

| Field | Type | Default | Notes |
|---|---|---|---|
| `schema` | string | required | PostgreSQL schema name |
| `apply_to` | `"ALL_TABLES"` or list of glob patterns | required | `ALL_TABLES` = every base table (`relkind='r'`); list = `fnmatch` against bare relname |
| `ignore` | list of glob patterns | `[]` | Exempt tables matching any pattern |
| `grants` | list of `AclGrant` | required | Per-role expected privileges |

**`AclGrant` fields**:

| Field | Type | Notes |
|---|---|---|
| `role` | string | Role name; supports `${VAR}` expansion |
| `privileges` | list | Subset of `{SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER}`; case-insensitive on load |

**Validation**:
- Unknown keys rejected (`extra="forbid"`).
- Unknown privileges (e.g. `EXECUTE` — for functions, not tables) rejected with a model-level error.
- `${VAR}` referenced but not in `os.environ` raises `ConfigurationError`. Empty-string fallback is never used.
- Views, materialized views, and foreign tables are out of scope for v1 (their grant semantics differ from base tables); coverage applies to `pg_class.relkind = 'r'` only.

**Opt-out**: Mark a table owner-only with a magic comment in the contiguous comment block above its `CREATE TABLE`:

```sql
-- confiture:owner-only
CREATE TABLE catalog.tb_audit_ledger ( ... );
```

**See [ACL Coverage](../guides/acl-coverage.md)** for the full guide.

---


## Field reference

<!-- BEGIN GENERATED: config-fields -->

### Every field, from the models

Generated from `confiture.config.environment`; the description is the model's own.

#### `Environment`

| Field | Type | Default | Description |
|---|---|---|---|
| `name` | str | `` | Environment name (e.g., "local", "production") |
| `database_url` | str | **required** | PostgreSQL connection URL |
| `include_dirs` | list[str \| [DirectoryConfig](#directoryconfig)] | `[]` | Directories to include when building schema (supports both string and dict formats) |
| `superuser_dirs` | list[str \| [DirectoryConfig](#directoryconfig)] | `[]` | Directories whose files run in the superuser phase of ``build_split()`` (extensions, roles); excluded from the schema hash. |
| `superuser_post_dirs` | list[str \| [DirectoryConfig](#directoryconfig)] | `[]` | Directories routed to the post-schema superuser phase in build_split() |
| `exclude_dirs` | list[str] | `[]` | Directories to exclude from schema build |
| `build` | [BuildConfig](#buildconfig) | (nested) | Build configuration options |
| `migration` | [MigrationConfig](#migrationconfig) | (nested) | Migration configuration options (includes tracking_table) |
| `infrastructure` | [InfrastructureConfig](#infrastructureconfig) | (nested) | Deployment topology — the read replicas the replica-safety policy takes into account (``infrastructure.replicas``). |
| `seed` | [SeedConfig](#seedconfig) | (nested) | Seed data application configuration |
| `drift` | [DriftConfig](#driftconfig) | (nested) | How ``confiture drift`` and ``migrate validate --check-live-drift`` judge column order (``drift.ignore_column_order``, ``drift.column_order_severity``). |
| `ssh_tunnel` | [SshTunnelConfig](#sshtunnelconfig) \| NoneType | - | SSH tunnel to reach a database that is not directly routable; ``null`` means connect directly. |
| `acls` | list[[AclTableExpectation](#acltableexpectation)] | `[]` | Expected table grants per schema for ``drift --check-acls`` and the ``acl_001`` lint (list of ``AclTableExpectation``). |
| `acls_lint_enabled` | bool | `false` | Run the static ``acl_001`` grant-coverage lint over migrations; ``acls:`` alone only feeds ``drift --check-acls``. |
| `ownership` | [OwnershipExpectation](#ownershipexpectation) \| NoneType | - | Expected relation ownership per schema for ``drift --check-ownership`` and the ``own_001`` lint; ``null`` disables both. |
| `function_coverage` | [FunctionCoverage](#functioncoverage) \| NoneType | - | Which schemas' functions the function-uniqueness check covers (``migrate validate --check-function-uniqueness``). |
| `security_lint` | [SecurityLinting](#securitylinting) \| NoneType | - | The ``sec_002`` SECURITY DEFINER lint: enabled flag, schema scope, ignore globs and severity. |
| `lint` | [LintSettings](#lintsettings) | (nested) | What the lint rules resolve against — ``lint.ignore_objects`` excuses a name ``build_003`` cannot find in the build. |

#### `DirectoryConfig`

| Field | Type | Default | Description |
|---|---|---|---|
| `path` | str | **required** | Directory to read, relative to the project root. |
| `recursive` | bool | `true` | Descend into subdirectories (default: true). |
| `include` | list[str] | `['**/*.sql']` | Glob patterns a file must match to be built (default: ``**/*.sql``). |
| `exclude` | list[str] | `[]` | Glob patterns that remove files from the build. |
| `auto_discover` | bool | `true` | What happens when this directory does not exist: ``true`` (the default) skips the entry, ``false`` fails the build. It decides nothing about which files are selected — ``include`` and ``exclude`` decide that on their own. |
| `order` | int | `0` | Which block of the build this entry's files land in. Entries are grouped by ``order``, the groups concatenated low to high, and inside a group the build's sort mode decides. Every entry defaults to 0, so a config that never sets it has one group. The order entries are *listed* in sequences nothing; it breaks one tie, deciding which entry owns a file two entries both select. |

#### `BuildConfig`

| Field | Type | Default | Description |
|---|---|---|---|
| `sort_mode` | str | `alphabetical` | Options: alphabetical, hex |
| `two_pass` | bool | `false` | Two-pass FK emission (issue #94) |
| `validate_comments` | [CommentValidationConfig](#commentvalidationconfig) | (nested) | Block-comment validation before a build (``enabled``, ``fail_on_unclosed_blocks``, ``fail_on_spillover``). |
| `separators` | [SeparatorConfig](#separatorconfig) | (nested) | How file boundaries are marked in the built schema (``style``: block_comment, line_comment, mysql, custom; ``custom_template``). |
| `lint` | [BuildLintConfig](#buildlintconfig) | (nested) | Lint run as part of ``confiture build`` (``enabled``, ``fail_on_error``, ``fail_on_warning``, ``rules``). |

#### `CommentValidationConfig`

| Field | Type | Default | Description |
|---|---|---|---|
| `enabled` | bool | `true` | Whether to validate comments (default: True) |
| `fail_on_unclosed_blocks` | bool | `true` | Fail if unclosed block comments found (default: True) |
| `fail_on_spillover` | bool | `true` | Fail if file ends inside unclosed comment (default: True) |

#### `SeparatorConfig`

| Field | Type | Default | Description |
|---|---|---|---|
| `style` | str | `block_comment` | Separator style (block_comment, line_comment, mysql, custom) |
| `custom_template` | str \| NoneType | - | Custom template for separators (only used if style=custom) |

#### `BuildLintConfig`

| Field | Type | Default | Description |
|---|---|---|---|
| `enabled` | bool | `false` | Whether to lint schema (default: False - disabled by default) |
| `fail_on_error` | bool | `true` | Fail build if linting errors found (default: True) |
| `fail_on_warning` | bool | `false` | Fail build if linting warnings found (default: False) |
| `rules` | list[str] | `['naming_convention', 'primary_key', 'documentation', 'missing_index', 'security']` | List of linting rules to apply |

#### `MigrationConfig`

| Field | Type | Default | Description |
|---|---|---|---|
| `strict_mode` | bool | `false` | Whether to fail on warnings/notices (default: False) |
| `destructive` | `gated` \| `allow` \| `forbid` | `gated` | What ``migrate diff --generate`` does with a change that loses data (a dropped table or column, a narrowed type): ``gated`` (default) writes it marked ``-- confiture:destructive`` so ``migrate up`` needs ``--allow-destructive``; ``allow`` writes it unmarked; ``forbid`` refuses to generate (``DIFFER_401``). ``--allow-destructive`` / ``--forbid-destructive`` on ``migrate diff`` override it per run. |
| `backfill` | [BackfillConfig](#backfillconfig) | (nested) | The online runner's backfill settings (batch size, lock-waiter guard) |
| `locking` | [LockingConfig](#lockingconfig) | (nested) | Distributed locking configuration |
| `view_helpers` | `auto` \| `manual` \| `off` | `auto` | View helper installation mode ("auto", "manual", "off") |
| `migration_generators` | dict[str, [MigrationGeneratorConfig](#migrationgeneratorconfig)] | `{}` | Named external generator commands |
| `snapshot_history` | bool | `true` | Write schema snapshot alongside each generated migration (default: True) |
| `snapshots_dir` | str | `db/schema_history` | Directory for schema history snapshots (default: db/schema_history) |
| `live_snapshot` | bool | `false` | Use live-snapshot mode (temp DB + pg_dump) by default (default: False) |
| `tracking_table` | str | `tb_confiture` | Name of the confiture tracking table, optionally schema-qualified (e.g. ``public.tb_confiture``). Defaults to ``tb_confiture``. |
| `rebuild_threshold` | int | `5` | Number of pending migrations above which ``migrate status --check-rebuild`` recommends a rebuild from DDL (default: 50). |
| `grant_dir` | str | `db/7_grant` | Directory holding GRANT/REVOKE files that grant-accompaniment and the ACL lint read (default: ``db/grants``). |
| `allow_unsafe_under_replication` | bool | `false` | Downgrade replica-unsafe preflight findings to warnings even when ``infrastructure.replicas`` are declared. |

#### `BackfillConfig`

| Field | Type | Default | Description |
|---|---|---|---|
| `batch_size` | int | `5000` | Rows per committed batch of a backfill (default: 5000). |
| `max_lock_ms` | int \| NoneType | - | Pause, in milliseconds, between batches while another session waits for a lock on the table; unset disables the guard. ``--max-lock-ms`` on ``migrate steps --resume`` and ``migrate up --online`` overrides it per run. |

#### `LockingConfig`

| Field | Type | Default | Description |
|---|---|---|---|
| `enabled` | bool | `true` | Whether locking is enabled (default: True) |
| `timeout_ms` | int | `30000` | Lock acquisition timeout in milliseconds (default: 30000) |

#### `MigrationGeneratorConfig`

| Field | Type | Default | Description |
|---|---|---|---|
| `command` | str | **required** | Shell command template with {from}, {to}, {output} placeholders |
| `description` | str | `` | Human-readable label for the generator |

#### `InfrastructureConfig`

| Field | Type | Default | Description |
|---|---|---|---|
| `replicas` | list[str] | `[]` | Read replicas of this environment (hostnames or DSNs); declaring any makes replica-unsafe DDL a preflight error. |

#### `SeedConfig`

| Field | Type | Default | Description |
|---|---|---|---|
| `execution_mode` | str | `concatenate` | Execution strategy ("concatenate" \| "sequential") |
| `continue_on_error` | bool | `false` | Continue applying files if one fails (default: False) |
| `transaction_mode` | `savepoint` \| `transaction` | `savepoint` | "savepoint" (one transaction, a savepoint per file — a failure rolls back that file only) or "transaction" (each file commits on its own, so files before a failure stay applied) |
| `profiles` | dict[str, [SeedProfile](#seedprofile)] | `{}` | Named seed subsets (see :class:`SeedProfile`). Absent ⇒ today's apply-all behaviour is unchanged. |

#### `SeedProfile`

| Field | Type | Default | Description |
|---|---|---|---|
| `include` | list[str] | `[]` | Globs a *filename* must match to be included (empty = all files). |
| `exclude` | list[str] | `[]` | Globs over a *filename* that remove an otherwise-included file. |

#### `DriftConfig`

| Field | Type | Default | Description |
|---|---|---|---|
| `ignore_column_order` | bool | `false` | Never report ``column_order_mismatch`` (default: false). |
| `column_order_severity` | `warning` \| `critical` | `warning` | Severity of a ``column_order_mismatch`` item: ``warning`` (default) or ``critical`` (fails the run). |

#### `SshTunnelConfig`

| Field | Type | Default | Description |
|---|---|---|---|
| `host` | str | **required** | SSH server hostname (e.g. "printoptim.io") |
| `user` | str \| NoneType | - | SSH username. Defaults to the current OS user if omitted. |
| `remote_host` | str | `localhost` | PostgreSQL host on the remote side (default: localhost). Ignored when ``remote_socket`` is set. |
| `remote_port` | int | `5432` | PostgreSQL port on the remote side (default: 5432). Ignored when ``remote_socket`` is set. |
| `remote_socket` | str \| NoneType | - | Unix domain socket path on the remote side (e.g. ``/var/run/postgresql/.s.PGSQL.5432``). When set, the tunnel forwards a local TCP port to this socket instead of a TCP ``remote_host:remote_port`` pair. Requires OpenSSH ≥ 6.7. |
| `local_port` | int | `0` | Local port to bind. 0 = pick a free port automatically (default: 0) |
| `identity_file` | str \| NoneType | - | Path to SSH private key. If omitted, uses ssh-agent / default key. |
| `timeout_s` | int | `10` | Seconds to wait for the tunnel to open (default: 10) |

#### `AclTableExpectation`

| Field | Type | Default | Description |
|---|---|---|---|
| `schema` | str | **required** | Schema the entry applies to (YAML key ``schema``). |
| `apply_to` | `ALL_TABLES` \| list[str] | **required** | ``ALL_TABLES`` or an explicit list of table names in that schema. |
| `ignore` | list[str] | `[]` | Table names in the schema that are exempt from the expectation. |
| `grants` | list[[AclGrant](#aclgrant)] | **required** | The roles and privileges every in-scope table must carry. |

#### `AclGrant`

| Field | Type | Default | Description |
|---|---|---|---|
| `role` | str | **required** | Database role the privileges are granted to. |
| `privileges` | list[`SELECT` \| `INSERT` \| `UPDATE` \| `DELETE` \| `TRUNCATE` \| `REFERENCES` \| `TRIGGER`] | **required** | Table privileges the role must hold (SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER, ALL); case-insensitive in YAML. |

#### `OwnershipExpectation`

| Field | Type | Default | Description |
|---|---|---|---|
| `expected_owner` | str | **required** | Canonical role that should own every in-scope relation in the environment. |
| `apply_to` | list[[OwnershipApplyTo](#ownershipapplyto)] | **required** | Per-schema scope entries (which relkinds to check). |
| `ignore` | list[str] | `[]` | Object-path globs that opt specific relations out of both static lint and runtime drift detection. |
| `lint_enabled` | bool | `true` | Master switch for the static ``own_001`` rule. |
| `bootstrap_connection_url` | str \| NoneType | - | Optional superuser URL used by ``confiture bootstrap`` (issue #137). Required for ``--apply`` because ``CREATE ROLE`` and ``REASSIGN OWNED`` both need superuser. Falls back to the env's main URL only when the user passes the explicit override; we never guess. Supports ``${VAR}`` expansion at load time. |
| `default_privileges` | dict[str, dict[str, list[str]]] \| NoneType | - | Mapping of ``schema -> role -> [PRIVILEGE, ...]`` used to plan ``ALTER DEFAULT PRIVILEGES`` statements in ``confiture bootstrap`` (issue #137 part 1). ``None`` means the bootstrap step is skipped with a one-line notice. Privilege strings are validated against the standard PostgreSQL allow-list. |

#### `OwnershipApplyTo`

| Field | Type | Default | Description |
|---|---|---|---|
| `schema` | str | **required** | Schema the ownership expectation applies to (YAML key ``schema``). |
| `relkinds` | list[str] | `['r', 'S', 'v', 'm']` | ``pg_class.relkind`` letters to check (default: r tables, S sequences, v views, m materialized views). |

#### `FunctionCoverage`

| Field | Type | Default | Description |
|---|---|---|---|
| `enabled` | bool | `false` | Master switch. When False the rule is a no-op even if scope-matching files contain duplicates. |
| `apply_to` | list[str] | `['*']` | Schema-name patterns (``fnmatch``-style) that scope the check. ``["*"]`` covers every schema; ``["public", "stat_etl"]`` covers only those two. |
| `ignore` | list[str] | `[]` | Object-path globs (``schema.name``) that opt specific callables out of detection regardless of how many files define them. |

#### `SecurityLinting`

| Field | Type | Default | Description |
|---|---|---|---|
| `enabled` | bool | `false` | Master switch. |
| `apply_to` | list[str] | `['*']` | Schema-name patterns (``fnmatch``-style) that scope the check. ``["*"]`` covers every schema. |
| `ignore` | list[str] | `[]` | Object-path globs (``schema.name``) that opt specific callables out of detection for deliberate exceptions. |
| `severity` | str | `warning` | Violation severity — ``"warning"`` (advisory, exit 0) or ``"error"`` (hard gate, exit 1). |

#### `LintSettings`

| Field | Type | Default | Description |
|---|---|---|---|
| `ignore_objects` | list[str] | `[]` | ``fnmatch`` globs over ``schema.name``. A reference matching one is never reported as unresolved — the escape hatch for an object created outside the DDL tree (``public.gen_random_uuid``, ``pg_stat_statements*``). |
| `search_path` | list[str] | `[]` | The schemas an unqualified *relation* in a body is looked for in, in order. Empty (the default) means an unqualified name is not judged at all: without knowing what resolves it, every ``now()`` becomes a finding. Unqualified *routine* calls are never judged even with this set — ``pg_catalog`` is on every search path and confiture cannot enumerate it. |
| `status_words` | list[str] | `['TODO', 'FIXME', 'WIP', 'DRAFT']` | The words in a file or directory name that say the work is unfinished, matched case-insensitively against the underscore-separated parts of the name. The default is the vocabulary ``tree_008`` was filed for; a project that writes ``_SPIKE`` says so here. |

### Complete skeleton (every field at its default)

```yaml
name: ''
database_url: null
include_dirs:
  - path: null
    recursive: true
    include:
      - '**/*.sql'
    exclude: []
    auto_discover: true
    order: 0
superuser_dirs:
  - path: null
    recursive: true
    include:
      - '**/*.sql'
    exclude: []
    auto_discover: true
    order: 0
superuser_post_dirs:
  - path: null
    recursive: true
    include:
      - '**/*.sql'
    exclude: []
    auto_discover: true
    order: 0
exclude_dirs: []
build:
  sort_mode: alphabetical
  two_pass: false
  validate_comments:
    enabled: true
    fail_on_unclosed_blocks: true
    fail_on_spillover: true
  separators:
    style: block_comment
    custom_template: null
  lint:
    enabled: false
    fail_on_error: true
    fail_on_warning: false
    rules:
      - naming_convention
      - primary_key
      - documentation
      - missing_index
      - security
migration:
  strict_mode: false
  destructive: gated
  backfill:
    batch_size: 5000
    max_lock_ms: null
  locking:
    enabled: true
    timeout_ms: 30000
  view_helpers: auto
  migration_generators:
    <name>:
      command: null
      description: ''
  snapshot_history: true
  snapshots_dir: db/schema_history
  live_snapshot: false
  tracking_table: tb_confiture
  rebuild_threshold: 5
  grant_dir: db/7_grant
  allow_unsafe_under_replication: false
infrastructure:
  replicas: []
seed:
  execution_mode: concatenate
  continue_on_error: false
  transaction_mode: savepoint
  profiles:
    <name>:
      include: []
      exclude: []
drift:
  ignore_column_order: false
  column_order_severity: warning
ssh_tunnel:
  host: null
  user: null
  remote_host: localhost
  remote_port: 5432
  remote_socket: null
  local_port: 0
  identity_file: null
  timeout_s: 10
acls:
  - schema: null
    apply_to: null
    ignore: []
    grants:
      - role: null
        privileges: null
acls_lint_enabled: false
ownership:
  expected_owner: null
  apply_to:
    - schema: null
      relkinds:
        - r
        - S
        - v
        - m
  ignore: []
  lint_enabled: true
  bootstrap_connection_url: null
  default_privileges: null
function_coverage:
  enabled: false
  apply_to:
    - '*'
  ignore: []
security_lint:
  enabled: false
  apply_to:
    - '*'
  ignore: []
  severity: warning
lint:
  ignore_objects: []
  search_path: []
  status_words:
    - TODO
    - FIXME
    - WIP
    - DRAFT
```

<!-- END GENERATED: config-fields -->

## Environment Examples

### Local Development

```yaml
# db/environments/local.yaml
name: local

database_url: postgresql://localhost/myapp_local

include_dirs:
  - db/schema/00_common
  - db/schema/10_tables
  - db/seeds/common       # Include test data
  - db/seeds/development

exclude_dirs: []

migration:
  tracking_table: tb_confiture
```

**Usage**:

```bash
confiture build --env local
confiture migrate up --config db/environments/local.yaml
```

---

### Staging Environment

```yaml
# db/environments/staging.yaml
name: staging

database_url: postgresql://app_user:${STAGING_DB_PASSWORD}@staging-db.internal:5432/myapp_staging

include_dirs:
  - db/schema/00_common
  - db/schema/10_tables
  - db/seeds/common       # Include realistic test data

exclude_dirs:
  - db/schema/99_experimental

migration:
  tracking_table: tb_confiture
```

**Usage** (CI/CD):

```bash
export STAGING_DB_PASSWORD=$(aws secretsmanager get-secret-value ...)
confiture migrate up --config db/environments/staging.yaml
```

---

### Production Environment

```yaml
# db/environments/production.yaml
name: production

database_url: ${DATABASE_URL}  # Injected from secrets manager

include_dirs:
  - db/schema/00_common
  - db/schema/10_tables
  - db/schema/20_views
  - db/schema/30_functions
  # No seeds in production

exclude_dirs: []

migration:
  tracking_table: tb_confiture
```

**Usage** (manual deployment):

```bash
export DATABASE_URL=$(vault read secret/production/database_url)
confiture migrate up --config db/environments/production.yaml
# Prompts: "Apply 3 migrations to production? [y/N]"
```

---

### CI/CD Test Environment

```yaml
# db/environments/ci.yaml
name: ci

database_url: postgresql://postgres:postgres@localhost:5432/confiture_test

include_dirs:
  - db/schema/00_common
  - db/schema/10_tables
  - db/seeds/test          # Test fixtures

exclude_dirs: []

migration:
  tracking_table: tb_confiture
```

**Usage** (GitHub Actions):

```yaml
# .github/workflows/test.yml
- name: Run tests
  run: |
    confiture build --env ci
    psql -f db/generated/schema_ci.sql
    pytest
```

### Test-harness environment variables

The pytest-xdist provisioning fixtures (see the
[parallel CI provisioning guide](../guides/parallel-ci-provisioning.md)) read a
small set of environment variables — they are independent of the YAML config:

| Variable | Default | Purpose |
|----------|---------|---------|
| `CONFITURE_TEST_DB_URL` | `postgresql://localhost/confiture_test` | PG **server** URL the `test-db` fixtures provision against (the database component is ignored for admin work). |
| `CONFITURE_TEST_RAM_TABLESPACE` | unset | Name of a tmpfs tablespace to place per-worker clones in (provision it with `confiture test-db ram-setup`). **Unset → on-disk clones, behaviour unchanged.** A misconfigured or post-reboot-broken tablespace degrades to disk automatically. |
| `CONFITURE_TEST_MAX_CLONE_CONCURRENCY` | auto | Cap on concurrent per-worker clones (#166). A valid int: `>= 1` bounds clones to that many across processes; `<= 0` forces unbounded. **Unset → auto:** throttle to 2 on an `fsync=on` cluster (concurrent clones thrash WAL/checkpoint), unbounded on `fsync=off` (typical CI). Set `=1` to serialise a very large template. |

---

## Advanced Configuration

### Multiple Schemas (PostgreSQL Schemas)

```yaml
# Support multiple PostgreSQL schemas
include_dirs:
  - db/schema/public/00_common
  - db/schema/public/10_tables
  - db/schema/analytics/00_common
  - db/schema/analytics/10_tables
```

**Schema organization**:

```sql
-- db/schema/public/00_common/schemas.sql
CREATE SCHEMA IF NOT EXISTS public;
CREATE SCHEMA IF NOT EXISTS analytics;

-- db/schema/analytics/10_tables/events.sql
CREATE TABLE analytics.events (...);
```

---

### Dynamic Configuration (Python API)

For advanced use cases, load and modify config programmatically:

```python
from pathlib import Path
from confiture.config.environment import Environment

# Load base config
env = Environment.load("production", project_dir=Path("/app"))

# Modify for specific deployment
env.database_url = get_secret("production/database_url")

# Use modified config
from confiture.core.builder import SchemaBuilder

builder = SchemaBuilder(environment=env)
builder.build()
```

---

## Validation

Confiture validates configuration at load time using Pydantic.

### Common Validation Errors

#### Missing required field

```
ConfigurationError: Missing required field 'database_url' in db/environments/local.yaml
```

**Solution**: Add `database_url` field.

#### Invalid database URL

```
ConfigurationError: Invalid database_url: must start with postgresql:// or postgres://
```

**Solution**: Use correct format: `postgresql://user:pass@host/database`

#### Directory does not exist

```
ConfigurationError: Include directory does not exist: /path/to/project/db/schema/10_tables
Specified in db/environments/local.yaml
```

**Solution**: Create missing directory or fix path in config.

#### Invalid YAML syntax

```
ConfigurationError: Invalid YAML in db/environments/local.yaml: expected <block end>, but found ':'
```

**Solution**: Fix YAML syntax (check indentation, quotes, etc.).

---

## Configuration Best Practices

### 1. Use Environment Variables for Secrets

❌ **Bad** (credentials in config file):

```yaml
database_url: postgresql://admin:MySecretPassword123@db.example.com/myapp
```

✅ **Good** (credentials from environment):

```yaml
database_url: ${DATABASE_URL}
```

```bash
export DATABASE_URL=postgresql://admin:secret@db.example.com/myapp
```

---

### 2. Separate Concerns by Environment

```yaml
# local.yaml - Fast iteration, include seeds
include_dirs:
  - db/schema
  - db/seeds

# production.yaml - Safety first, no seeds
include_dirs:
  - db/schema
```

---

### 3. Use Descriptive Environment Names

✅ **Good**:
- `local` - Developer's local machine
- `development` - Shared dev environment
- `staging` - Pre-production testing
- `production` - Live production database

❌ **Bad**:
- `env1`, `env2`, `env3` (unclear purpose)
- `prod`, `stg` (abbreviations can be ambiguous)

---

### 4. Document Custom Settings

```yaml
# db/environments/production.yaml

# Production environment for customer-facing application
# Owner: DevOps team (devops@example.com)
# Database: AWS RDS PostgreSQL 15.3
# Backup: Automated via AWS (daily snapshots)
# Access: VPN required

name: production
database_url: ${DATABASE_URL}
# ... rest of config
```

---

### 5. Version Control Configuration

✅ **Commit**:
- `db/environments/*.yaml` (configuration structure)
- Example values (non-sensitive)

❌ **Don't commit**:
- Actual production credentials
- API keys or tokens
- Sensitive connection details

**Use `.gitignore`**:

```gitignore
# .gitignore
db/environments/production.yaml  # If it contains secrets
.env                              # Environment variables
```

**Alternative**: Commit templates:

```yaml
# db/environments/production.yaml.template
name: production
database_url: ${DATABASE_URL}  # Placeholder, replaced at runtime
# ...
```

---

## Schema Reference

### Environment YAML Schema

```yaml
# Required fields
name: string                    # Environment name
database_url: string            # PostgreSQL URL (postgresql://...)
include_dirs: array[string]     # Directories to include

# Optional fields
exclude_dirs: array[string]     # Directories to exclude (default: [])

# Migration section (nested)
migration:
  view_helpers: string          # "auto" | "manual" | "off" (default: "auto")
  strict_mode: boolean          # Fail on warnings/notices (default: false)
  tracking_table: string        # Tracking table name (default: tb_confiture)
  snapshot_history: boolean     # Write schema snapshots (default: true)
```

### Database URL Format

```
postgresql://[user[:password]@][netloc][:port]/dbname[?option=value]

Components:
  user       - Database user (default: postgres)
  password   - User password (default: empty)
  netloc     - Host/IP address (default: localhost)
  port       - TCP port (default: 5432)
  dbname     - Database name (required)
  option     - Query parameters (optional, e.g., sslmode=require)
```

**Examples**:

```
postgresql:///mydb                                    # Minimal (localhost, postgres user)
postgresql://localhost/mydb                           # Explicit host
postgresql://user:pass@localhost/mydb                 # With credentials
postgresql://db.example.com:5433/mydb                 # Custom port
postgresql://user:pass@db.example.com:5433/mydb      # Full URL
postgresql://localhost/mydb?sslmode=require           # With SSL
```

---

## Troubleshooting

### Cannot connect to database

**Error**:

```
❌ Error: could not connect to server: Connection refused
```

**Solutions**:

1. **Check PostgreSQL is running**:

```bash
pg_isready -h localhost -p 5432
```

2. **Test connection manually**:

```bash
psql postgresql://user:pass@localhost:5432/mydb
```

3. **Verify configuration**:

```bash
cat db/environments/local.yaml
```

4. **Check firewall/network**:

```bash
nc -zv localhost 5432
```

---

### Configuration file not found

**Error**:

```
ConfigurationError: Environment config not found: db/environments/prod.yaml
Expected: db/environments/prod.yaml
```

**Solutions**:

1. **List available configs**:

```bash
ls db/environments/
```

2. **Use correct environment name** (without `.yaml` extension):

```bash
confiture build --env production  # Not "production.yaml"
```

---

### Include directory does not exist

**Error**:

```
ConfigurationError: Include directory does not exist: /path/to/db/schema/10_tables
```

**Solutions**:

1. **Create missing directory**:

```bash
mkdir -p db/schema/10_tables
```

2. **Fix typo in config**:

```yaml
# Fix: db/schema/10_table -> db/schema/10_tables
include_dirs:
  - db/schema/10_tables
```

---

## Further Reading

- **[CLI Reference](./cli.md)** - Command-line usage
- **[Getting Started](../getting-started.md)** - Project setup tutorial
- **[Migration Decision Tree](../guides/migration-decision-tree.md)** - Choosing the right approach
- **[API Reference](../api/index.md)** - Python API documentation

---

**Last Updated**: October 12, 2025
**Version**: 1.0
