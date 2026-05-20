# Prerequisites

What Confiture needs from the world to do its job.

## PostgreSQL version

**Minimum: PostgreSQL 12.**

Confiture's day-to-day commands (`build`, `migrate up | down | status | preflight`, `sync`) work against any modern PostgreSQL. The schema-to-schema medium uses **`postgres_fdw`**, which requires a PostgreSQL that ships the extension (all supported versions do).

Confiture is tested in CI against PostgreSQL 14, 15, 16, and 17.

## Python

Python **3.11, 3.12, or 3.13**. Older versions are not supported.

Install with `uv` (recommended) or `pip`:

```bash
uv pip install fraiseql-confiture          # core
uv pip install "fraiseql-confiture[ast]"   # + pglast (recommended for large schemas)
```

## Required PostgreSQL role permissions

Confiture connects with a single role per environment. The minimum it needs varies by command:

| Command | Required privilege |
|---|---|
| `migrate up` / `down` / `status` / `preflight` | Whatever the migration SQL needs, plus `CREATE` on the schema that holds `tb_confiture` |
| `build` (against a target database) | `CREATEDB` (creates a fresh database) or full ownership of an existing target database |
| `migrate generate --live-snapshot` | Permission to read the live schema you're snapshotting |
| `sync` (production-sync) | Read on the source, write on the destination |
| `schema-to-schema` (FDW) | `CREATE EXTENSION postgres_fdw` (superuser), then `USAGE` on the FDW server for app roles |

For most setups the migration role is a per-application user with table-creation permissions inside its own schema(s). Avoid using `postgres`/superuser in production except for the one-shot `CREATE EXTENSION` calls.

### Advisory-lock permission

Confiture's distributed locking uses `pg_advisory_lock` (session-level) and `pg_try_advisory_lock`. These do not require any extra grants — any role that can connect can take advisory locks.

## Optional extensions

| Extension | When needed | Install |
|---|---|---|
| `postgres_fdw` | Schema-to-schema migration (Medium 4) | `CREATE EXTENSION postgres_fdw;` as superuser |
| `pg_stat_statements` | Performance tuning queries in `docs/operations/performance-tuning.md` | Configure in `postgresql.conf` |
| `pgcrypto` | Some anonymization strategies use `gen_random_uuid()` from this extension on PG < 13 | `CREATE EXTENSION pgcrypto;` |

Confiture itself does not require any extensions to be installed.

## Managed-PostgreSQL providers

| Provider | Notes |
|---|---|
| **AWS RDS** | Superuser is the `rds_superuser` role, not `postgres`. `CREATE EXTENSION postgres_fdw` works. Advisory locks work normally. |
| **GCP Cloud SQL** | The `cloudsqlsuperuser` role can install `postgres_fdw`. App roles need `cloudsql.iam_authentication` only if you use IAM auth. |
| **Supabase** | Connects on port `6543` (pooler) or `5432` (direct). For migrations, **use port 5432** — the pooler drops the session that holds the advisory lock between statements. |
| **Neon** | Branching is independent of Confiture's branching; the two compose. Use a direct (non-pooled) connection for migrations. |
| **Aiven** | The `avnadmin` user has effective superuser. Extensions installable from the console. |
| **Azure Database for PostgreSQL** | The admin user is whatever you set at provisioning. `postgres_fdw` is in the allow-list. |

**General rule**: any pooled (transaction-mode) connection breaks Confiture's session-scoped advisory locks. Always migrate via a direct connection.

## Secrets and environment variables

Confiture does **not** read secrets from the environment on its own. Two patterns work:

### 1. Shell substitution before running (recommended)

Use `direnv`, `sops exec-env`, `doppler run`, `vault kv get`, or plain `export` to put the DSN into your shell, then pass it explicitly:

```bash
# direnv (.envrc)
export DATABASE_URL="postgresql://app:$(sops -d --extract '[\"db_password\"]' secrets.yaml)@db.example.com/app"

# Then either:
confiture migrate up --database-url "$DATABASE_URL"

# …or set it once in YAML:
#   database_url: postgresql://app:HERE/app
# and substitute the password via a templating step (envsubst, sops exec-env).
```

```bash
# sops exec-env
sops exec-env secrets.yaml 'confiture migrate up -c db/environments/production.yaml'
```

```bash
# doppler
doppler run -- confiture migrate up -c db/environments/production.yaml
```

```bash
# vault
DATABASE_URL=$(vault kv get -field=url secret/myapp/db) confiture migrate up
```

### 2. `envsubst` over the YAML at deploy time

If you keep your environment YAML in git but the DSN is a secret, render the file just-in-time:

```bash
envsubst < db/environments/production.template.yaml > /run/confiture-production.yaml
confiture migrate up -c /run/confiture-production.yaml
```

This stays compatible with any secret store — the secret only has to land in a shell variable that `envsubst` can read.

### Anti-pattern: committing the production DSN

Don't put the production password in `db/environments/production.yaml` and commit it. Use one of the patterns above so the YAML in git is a template, not a secret.

### Caveat — literal `${VAR}` in YAML

If you write `database_url: ${DATABASE_URL}` in a YAML file and load it directly with `confiture --config`, the literal string `${DATABASE_URL}` is passed to `psycopg.connect()` and the connection will fail. Substitute the variable before Confiture reads the file (via shell + `envsubst`, `sops exec-env`, or `doppler run`), or pass `--database-url` on the command line.

## Networking

- Outbound TCP to your PostgreSQL host on the configured port (default `5432`).
- If using SSH tunnels, set up the tunnel config in your environment YAML (see [the configuration reference](configuration.md)).
- Notification hooks (Slack, Discord, Teams, webhook) require outbound HTTPS to the respective service. SMTP-based notifications need outbound TCP to your mail server.

## Disk

- Schema files (`db/schema/`) and migration files (`db/migrations/`) — usually a few KB to a few MB.
- Schema snapshots (`db/schema_history/`) — one snapshot per migration applied; each snapshot is roughly the size of `db/schema/`. Plan for ~Nx the size of `db/schema/` where N is your migration count over the lifetime of the project.
- Confiture itself: <10 MB installed (the wheel is small; psycopg's binary wheel is the biggest dependency).

## See also

- [Configuration reference](configuration.md) — full YAML schema.
- [Tracking table reference](tracking-table.md) — the one PostgreSQL object Confiture creates automatically.
- [Legacy bootstrap guide](../guides/legacy-bootstrap.md) — adopting Confiture on a database that already has tables.
