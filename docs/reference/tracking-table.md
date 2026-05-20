# Tracking Table Reference

Confiture records which migrations have been applied in a single table. By default this table is named **`tb_confiture`** and lives in the schema used by the connection's `search_path` (usually `public`).

The table is created automatically on the first migrator operation that needs it (`migrate up`, `migrate baseline`, `migrate status` against a fresh database). No manual setup is required.

## Schema

```sql
CREATE TABLE tb_confiture (
    id                UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    pk_confiture      BIGINT       GENERATED ALWAYS AS IDENTITY UNIQUE,
    slug              TEXT         NOT NULL UNIQUE,
    version           VARCHAR(255) NOT NULL UNIQUE,
    name              VARCHAR(255) NOT NULL,
    applied_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    execution_time_ms INTEGER,
    checksum          VARCHAR(64)
);

CREATE INDEX idx_tb_confiture_pk_confiture ON tb_confiture(pk_confiture);
CREATE INDEX idx_tb_confiture_slug         ON tb_confiture(slug);
CREATE INDEX idx_tb_confiture_version      ON tb_confiture(version);
CREATE INDEX idx_tb_confiture_applied_at   ON tb_confiture(applied_at DESC);
```

### Columns

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID` | External stable identifier. Survives backups, dumps, replication. |
| `pk_confiture` | `BIGINT` (identity) | Sequential internal key. Use for joins inside the same database. |
| `slug` | `TEXT` | Human-readable reference (e.g. `add_user_bio`). |
| `version` | `VARCHAR(255)` | Migration version — `YYYYMMDDHHMMSS` (e.g. `20260520143015`) or the legacy `001`-style. Unique. |
| `name` | `VARCHAR(255)` | The descriptive part of the filename (the bit after the version). |
| `applied_at` | `TIMESTAMPTZ` | When the migration was recorded. Defaults to `NOW()`. |
| `execution_time_ms` | `INTEGER` | Wall-clock time spent running the migration's SQL. `NULL` for rows inserted by `migrate baseline`. |
| `checksum` | `VARCHAR(64)` | SHA-256 of the migration file at apply time. Compared by `migrate validate` and `migrate preflight`. `NULL` for baselined rows. |

> The three-key identity pattern (`id` / `pk_confiture` / `slug`) is the same Trinity pattern Confiture recommends for application tables. See [ARCHITECTURE.md](../../ARCHITECTURE.md) for the rationale.

## Renaming the table

The table name is configurable per environment:

```yaml
# db/environments/local.yaml
migration:
  tracking_table: my_schema.confiture_history
```

If the name is schema-qualified, Confiture creates the table in that schema. Otherwise, it creates it in the connection's default `search_path`.

## Inspecting from psql

```text
$ psql $DATABASE_URL
\d tb_confiture
                                          Table "public.tb_confiture"
       Column        |           Type           | Nullable |              Default
---------------------+--------------------------+----------+-----------------------------------
 id                  | uuid                     | not null | gen_random_uuid()
 pk_confiture        | bigint                   | not null | generated always as identity
 slug                | text                     | not null |
 version             | character varying(255)   | not null |
 name                | character varying(255)   | not null |
 applied_at          | timestamp with time zone | not null | now()
 execution_time_ms   | integer                  |          |
 checksum            | character varying(64)    |          |
Indexes:
    "tb_confiture_pkey" PRIMARY KEY, btree (id)
    "tb_confiture_pk_confiture_key" UNIQUE CONSTRAINT, btree (pk_confiture)
    "tb_confiture_slug_key" UNIQUE CONSTRAINT, btree (slug)
    "tb_confiture_version_key" UNIQUE CONSTRAINT, btree (version)
    "idx_tb_confiture_applied_at" btree (applied_at DESC)
    "idx_tb_confiture_pk_confiture" btree (pk_confiture)
    "idx_tb_confiture_slug" btree (slug)
    "idx_tb_confiture_version" btree (version)
```

## Common queries

### What's applied, most recent first?

```sql
SELECT version, name, applied_at, execution_time_ms
FROM tb_confiture
ORDER BY applied_at DESC
LIMIT 20;
```

### Was a specific migration applied?

```sql
SELECT version, applied_at FROM tb_confiture WHERE version = '20260520143015';
```

The preferred way is `confiture migrate status --format=json`, which reads this table and reports it alongside the on-disk migration files.

## Manual fixup recipes

These should be rare. Reach for the CLI first (`migrate baseline`, `migrate rebuild`, `migrate reinit`) before editing the table by hand.

### Read-only inspection

Safe at any time:

```sql
SELECT version, name, applied_at, checksum
FROM tb_confiture
ORDER BY version;
```

### Deleting a row for a migration that was rolled back outside Confiture

If you ran `DROP TABLE users;` by hand to undo a botched migration but didn't use `confiture migrate down`, Confiture still thinks it's applied. Delete the row so the migration is re-applicable:

```sql
BEGIN;
DELETE FROM tb_confiture WHERE version = '20260520143015';
COMMIT;
```

Then re-run `confiture migrate up`. Verify with `confiture migrate status` first.

### Re-baselining after manual SQL

If you've been running migrations by hand with `psql` (the legacy bootstrap scenario), don't `DELETE` and re-insert. Use the dedicated command:

```bash
confiture migrate baseline --through 20260520143015
```

That walks `db/migrations/`, marks every file up through the given version as applied, and skips the SQL execution. See [the legacy bootstrap guide](../guides/legacy-bootstrap.md) for the full walkthrough.

## Checksum mismatches

`migrate validate` and `migrate preflight` re-hash each on-disk migration file and compare against the `checksum` column. A mismatch means the file changed after it was applied — usually accidental, occasionally tampering.

If the change was deliberate (e.g. you reformatted whitespace and you're sure the SQL semantics are identical), update the stored checksum explicitly:

```sql
UPDATE tb_confiture
SET checksum = encode(sha256(pg_read_binary_file('db/migrations/20260520143015_add_bio.up.sql')), 'hex')
WHERE version = '20260520143015';
```

In most cases the right answer is to revert the file change instead — applied migrations are immutable history.

## See also

- [Legacy bootstrap guide](../guides/legacy-bootstrap.md) — adopting Confiture on a database that already has migrations applied.
- [Incremental migrations guide](../guides/02-incremental-migrations.md) — the day-to-day `migrate up` / `migrate down` workflow.
- [`migrate status` reference](cli.md) — semantic exit codes for CI.
