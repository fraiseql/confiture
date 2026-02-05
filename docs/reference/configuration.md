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

# Migration tracking table name (optional, default: confiture_migrations)
migration_table: confiture_migrations

# Auto-backup before migrations (optional, default: true)
auto_backup: true

# Require confirmation for risky operations (optional, default: true)
require_confirmation: true
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
    order: 10                # Processing order (optional)
    auto_discover: false     # Default: false
```

**Configuration Options**:

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `path` | string | required | Directory path (relative or absolute) |
| `recursive` | boolean | `true` | Recursively discover files in subdirectories |
| `include` | array[string] | `["**/*.sql"]` | Glob patterns for files to include |
| `exclude` | array[string] | `[]` | Glob patterns for files to exclude |
| `order` | integer | auto | Processing order (lower numbers first) |
| `auto_discover` | boolean | `false` | Skip missing directories silently |

**Path resolution**:
- **Relative paths**: Resolved from project root (where `db/` directory is located)
- **Absolute paths**: Used as-is
- **Validation**: Confiture checks directory existence unless `auto_discover: true`

**Pattern syntax**: Uses glob patterns with `**` for recursive matching:
- `*` - Match any characters (non-recursive)
- `**` - Match any characters (recursive)
- `?` - Match single character
- `[abc]` - Match any character in set

**Ordering strategy**:

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

```yaml
# local.yaml (includes seeds)
include_dirs:
  - path: db/schema
    recursive: true
  - path: db/seeds/common
    order: 20
  - path: db/seeds/development
    order: 30

# production.yaml (excludes development seeds)
include_dirs:
  - path: db/schema
    recursive: true
  - path: db/seeds/common
    order: 20
    exclude:
      - "**/development/**"
```

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
- Files with `0x{HH}_` prefixes sort by hex value
- Non-hex files sort alphabetically after hex files
- Supports 255 possible categories (0x00-0xFF)

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

### `migration_table`

**Type**: String
**Default**: `confiture_migrations`
**Description**: Table name for tracking applied migrations

```yaml
migration_table: confiture_migrations
```

**Schema**:

```sql
CREATE TABLE confiture_migrations (
    version TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    applied_at TIMESTAMP DEFAULT NOW()
);
```

**Custom table name** (if default conflicts):

```yaml
migration_table: my_custom_migrations
```

---

### `auto_backup`

**Type**: Boolean
**Default**: `true`
**Description**: Automatically backup database before applying migrations

```yaml
auto_backup: true
```

**Behavior**:
- **`true`**: Run `pg_dump` before each `confiture migrate up`
- **`false`**: No automatic backups (you manage backups manually)

**Backup location**: `db/backups/{env}_{timestamp}.sql`

**Example backup**:

```
db/backups/
└── production_20251012_143000.sql
```

**Production recommendation**: Use external backup systems (AWS RDS automated backups, pg_basebackup, etc.) and set `auto_backup: false`.

---

### `require_confirmation`

**Type**: Boolean
**Default**: `true`
**Description**: Require user confirmation for risky operations

```yaml
require_confirmation: true
```

**Operations requiring confirmation**:
- Applying migrations to production
- Rolling back migrations
- Dropping tables or columns

**Behavior**:
- **`true`**: Prompt user: "Apply 3 migrations to production? [y/N]"
- **`false`**: Apply immediately without prompt

**CI/CD usage**: Set to `false` for automated pipelines:

```yaml
# production.yaml (manual deployments)
require_confirmation: true

# ci.yaml (automated tests)
require_confirmation: false
```

---

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

migration_table: confiture_migrations
auto_backup: false          # No backups needed locally
require_confirmation: false # Fast iteration
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

migration_table: confiture_migrations
auto_backup: true           # Backup before migrations
require_confirmation: false # Automated deployments OK
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

migration_table: confiture_migrations
auto_backup: true               # Extra safety
require_confirmation: true      # Manual approval required
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

migration_table: confiture_migrations
auto_backup: false          # No backups in CI
require_confirmation: false # Fully automated
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
env.require_confirmation = False  # Override for automated deployment

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
require_confirmation: false
auto_backup: false
include_dirs:
  - db/schema
  - db/seeds

# production.yaml - Safety first, no seeds
require_confirmation: true
auto_backup: true
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
migration_table: string         # Migration tracking table (default: confiture_migrations)
auto_backup: boolean            # Auto-backup before migrations (default: true)
require_confirmation: boolean   # Require user confirmation (default: true)
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
- **[API Reference](./api.md)** - Python API documentation

---

**Last Updated**: October 12, 2025
**Version**: 1.0
