# pg_tviews TVIEWs

[pg_tviews](https://github.com/fraiseql/pg_tviews) keeps a table in step with a query.
`CREATE TABLE tv_post AS SELECT …` becomes a table, a backing view `v_post`, triggers
on each base table and a row in `pg_tview_meta`. Confiture reads a TVIEW as **one
object**, whose relation and query are its whole definition.

## What confiture does with one

| Where | What |
|---|---|
| `confiture build` | builds `CREATE TABLE tv_x AS …` as written |
| `confiture drift`, `migrate validate --check-live-drift` | `missing_tview` / `extra_tview` against a live database with `pg_tviews` installed |
| `migrate diff --generate` | writes `DROP TABLE IF EXISTS tv_x;` and `CREATE TABLE IF NOT EXISTS tv_x AS …;` for a changed TVIEW, with the matching down |
| `migrate fix --idempotent` | adds `IF NOT EXISTS` to a `tv_*` CTAS as to any table |
| `migrate preflight --against` | the finding below |
| `confiture lint --select tview` | the two storage rules below |

Confiture supports pg_tviews **0.1.0-beta.19 or later**. Where it reads TVIEWs from a
live database (drift, `schema dump-model`, `migrate preflight --against`, the platform's
`introspect`), an older build is refused with `CONFIG_014` (exit 5), naming the build
installed. It reads the build from `pg_tviews_version()`: `pg_extension.extversion`
is `0.1.0` on every 0.1.0 beta.

A table named `tv_*` is a TVIEW only when it is created `AS SELECT`; `CREATE TABLE
tv_x (…)` with a column list is a plain table.

## Preflight finding

| Code | When |
|---|---|
| `PFLIGHT_TVIEW_BASE_COLUMN` | `--against` only: the migration drops or retypes a column a registered TVIEW reads, or drops its base table, without dropping the TVIEW first |

## Lint rules

`confiture lint --select tview` (off by default) reads the tree:

- `tview_001`: an index over `data` or `updated_at`, which every refresh rewrites, so no update is HOT
- `tview_002`: replicas declared and the TVIEW never `SET LOGGED` (UNLOGGED is the default, and a standby cannot read it)

pg_tviews 0.1.0-beta.18 indexes each `fk_*` column and sets fillfactor 85 itself. It
accepts `CREATE INDEX` and `ALTER TABLE … SET LOGGED` after the conversion; `WITH (…)`
on the `CREATE` it refuses. See the [rule reference](../reference/lint-rules.md).

## Restore

`confiture restore` brings a TVIEW back registered, and it keeps following its base
tables, cascades included. Two conditions, both measured on pg_tviews 0.1.0-beta.19:

- **The source database's extension was created by pg_tviews 0.1.0-beta.19 or
  later.** From that release `pg_dump` carries `pg_tview_meta`; an extension created
  by an earlier build does not, even after the server is upgraded (both report
  version `0.1.0`, so there is no `ALTER EXTENSION … UPDATE`). A dump of such a
  database restores `tv_x` and its rows, and the TVIEW silently stops propagating.
  Check the source before you rely on its dumps:

  ```sql
  SELECT EXISTS (
      SELECT FROM pg_class c
      WHERE c.oid = ANY (e.extconfig) AND c.relname = 'pg_tview_meta'
  ) AS dumps_its_tviews
  FROM pg_extension e WHERE e.extname = 'pg_tviews';
  ```

  `false` means recreate the TVIEWs under a new extension, or rebuild them after
  the restore.
- **No `--disable-triggers`.** pg_tviews rebinds each OID it recorded in a trigger as
  `pg_tview_meta` loads; `pg_restore --section=data --disable-triggers` keeps the
  source database's OIDs, and the TVIEW stops following its base tables without an
  error. `confiture restore` never passes it; do not add it to a `pg_restore` of
  your own.

## Not supported yet

- **Benchmark data**: see [Realistic data for a pg_tviews TVIEW](./03-production-sync.md#realistic-data-for-a-pg_tviews-tview).
