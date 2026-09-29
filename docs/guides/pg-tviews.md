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
| `migrate diff --generate` | writes `DROP TABLE IF EXISTS tv_x;` and `CREATE TABLE tv_x AS …;` for a changed TVIEW, never `IF NOT EXISTS`, with the matching down |
| `migrate fix --idempotent` | leaves a `tv_*` CTAS alone, and writes the `DROP TABLE IF EXISTS` before it |
| `migrate preflight` | the three findings below |
| `confiture lint --select tview` | the four storage rules below |

A table named `tv_*` is a TVIEW only when it is created `AS SELECT`; `CREATE TABLE
tv_x (…)` with a column list is a plain table.

## Preflight findings

| Code | When |
|---|---|
| `PFLIGHT_TVIEW_SAME_BATCH` | a transactional `.up.sql` creates the extension and a `tv_*` table: it is sent as one script, and the result is a plain table even with the library preloaded (pg_tviews#80) |
| `PFLIGHT_TVIEW_IF_NOT_EXISTS` | `CREATE TABLE IF NOT EXISTS tv_x AS`: applied again it deletes the TVIEW (pg_tviews#79) |
| `PFLIGHT_TVIEW_BASE_COLUMN` | `--against` only: the migration drops or retypes a column a registered TVIEW reads, or drops its base table, without dropping the TVIEW first |

Create the extension in an earlier migration than the first TVIEW. The first two
findings exist because of the pg_tviews issues named and go when those are fixed.

## Lint rules

`confiture lint --select tview` (off by default) reads the tree:

- `tview_001`: an `fk_*` column with no index leading with it, so each cascade step scans the TVIEW
- `tview_002`: an index over `data` or `updated_at`, which every refresh rewrites, so no update is HOT
- `tview_003`: no `fillfactor` below 100
- `tview_004`: replicas declared and the TVIEW never `SET LOGGED` (UNLOGGED is the default, and a standby cannot read it)

pg_tviews accepts `CREATE INDEX`, `ALTER TABLE … SET (fillfactor = 85)` and
`ALTER TABLE … SET LOGGED` after the conversion; `WITH (…)` on the `CREATE` it
refuses. See the [rule reference](../reference/lint-rules.md).

## Not supported yet

- **`confiture restore`** of a database that holds a TVIEW: `pg_restore` cannot
  recreate one on pg_tviews 0.1.0-beta.17 (fraiseql/pg_tviews#96). Confiture waits for
  the fix rather than working around it.
- **Benchmark data**: see [Realistic data for a pg_tviews TVIEW](./03-production-sync.md#realistic-data-for-a-pg_tviews-tview).
