# Named Schemas

PostgreSQL lets you organise tables, types, and functions across multiple schemas — `public`, `auth`, `metrics`, `billing`. Confiture treats schemas the same way it treats any other DDL: you write it once in `db/schema/`, and `build` plus `migrate` carry it through.

## Worked example: a `metrics` schema

### Step 1 — Declare the schema in DDL

Make the `CREATE SCHEMA` statement run before any table that lives in it. The simplest way is a numbered directory so it sorts first:

```text
db/schema/
├── 00_common/
│   └── 000_schemas.sql       ← CREATE SCHEMA … here
├── 10_tables/
│   ├── users.sql             ← public schema (no qualifier needed)
│   └── metrics_events.sql    ← references metrics.events
└── 20_views/
    └── metrics_recent.sql
```

```sql
-- db/schema/00_common/000_schemas.sql
CREATE SCHEMA IF NOT EXISTS metrics;

-- db/schema/10_tables/metrics_events.sql
CREATE TABLE metrics.events (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    payload     JSONB       NOT NULL
);

CREATE INDEX idx_metrics_events_occurred_at
    ON metrics.events (occurred_at DESC);
```

### Step 2 — Build

```bash
confiture build --env local
```

The builder concatenates `00_common/000_schemas.sql` first, then the table definitions. The output schema file (`db/generated/schema_local.sql`) has the `CREATE SCHEMA metrics` line above any `CREATE TABLE metrics.…`.

### Step 3 — Generate and apply a migration

```bash
confiture migrate generate --name "add_metrics_correlation_id"
```

Edit the generated `*.up.sql` file:

```sql
ALTER TABLE metrics.events ADD COLUMN correlation_id UUID;
CREATE INDEX idx_metrics_events_correlation_id
    ON metrics.events (correlation_id);
```

And the `*.down.sql`:

```sql
DROP INDEX metrics.idx_metrics_events_correlation_id;
ALTER TABLE metrics.events DROP COLUMN correlation_id;
```

Apply it:

```bash
confiture migrate up
```

That's the whole workflow. Confiture's diff detection, lint rules, and preflight checks all run against fully qualified names — they don't care which schema a table lives in.

## Where the tracking table lives

By default Confiture puts `tb_confiture` in the connection's `search_path` (usually `public`). To keep it inside a dedicated schema:

```yaml
# db/environments/local.yaml
migration:
  tracking_table: ops.tb_confiture
```

Then create the `ops` schema in your DDL (or by hand once) before any migration that references it. See [the tracking-table reference](../reference/tracking-table.md) for the column shape.

## Multiple schemas, one project

Nothing in Confiture caps the number of schemas. A typical layout:

```sql
-- db/schema/00_common/000_schemas.sql
CREATE SCHEMA IF NOT EXISTS auth;
CREATE SCHEMA IF NOT EXISTS billing;
CREATE SCHEMA IF NOT EXISTS metrics;
```

Then sub-directories per schema:

```text
db/schema/
├── 00_common/000_schemas.sql
├── 10_auth/
│   ├── users.sql
│   └── sessions.sql
├── 20_billing/
│   ├── plans.sql
│   └── invoices.sql
└── 30_metrics/
    └── events.sql
```

This is convention only — Confiture doesn't enforce it. The hard rules are:

1. `CREATE SCHEMA` must run before anything that references the schema.
2. Cross-schema foreign keys still need ordering — `billing.invoices(user_id)` referencing `auth.users(id)` requires `10_auth/` to sort before `20_billing/`.

## Search-path considerations

Confiture connects with whatever `search_path` PostgreSQL configures for the connecting role. If you rely on unqualified names resolving to a specific schema, set the role's `search_path` explicitly:

```sql
ALTER ROLE app SET search_path = metrics, public;
```

Or set it per-connection in your application code. Confiture's own SQL (the tracking table queries) is always schema-qualified internally — it doesn't depend on `search_path`.

## Linting and named schemas

`confiture lint` and `migrate validate` understand qualified table names natively. The schema linter rules apply equally to objects in any schema. If a rule needs to be relaxed for one schema, scope it in `confiture.toml`:

```toml
[[lint.ignore]]
schema = "metrics"
rule = "TBL003"  # example: relaxes naming convention inside metrics
```

(See [`docs/guides/schema-linting.md`](schema-linting.md) for the lint configuration reference.)

## See also

- [Build from DDL](01-build-from-ddl.md) — full builder reference.
- [Incremental migrations](02-incremental-migrations.md) — `migrate up` / `down` workflow.
- [Tracking table reference](../reference/tracking-table.md) — choose where `tb_confiture` lives.
