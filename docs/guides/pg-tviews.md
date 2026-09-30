# pg_tviews TVIEWs

[pg_tviews](https://github.com/fraiseql/pg_tviews) keeps a table in step with a query.
`CREATE TABLE tv_post AS SELECT …` becomes a table, a backing view `v_post`, triggers
on each base table and a row in `tviews.registry`. Confiture reads a TVIEW as **one
object**, whose relation and query are its whole definition.

## What confiture does with one

| Where | What |
|---|---|
| `confiture build` | builds `CREATE TABLE tv_x AS …` as written |
| `confiture drift`, `migrate validate --check-live-drift` | `missing_tview` / `extra_tview` against a live database with `pg_tviews` installed, and `tview_option_mismatch` when an option the tree pins is not what `tviews.registry` holds |
| `migrate diff --generate` | writes `SELECT tviews.pg_tviews_create_or_replace('tv_x', $tview$…$tview$);` for an added or changed TVIEW and `SELECT tviews.pg_tviews_drop('tv_x', if_exists => true);` for a dropped one, with the matching down |
| `migrate fix --idempotent` | adds `IF NOT EXISTS` to a `tv_*` CTAS as to any table |
| `migrate preflight --against` | the finding below |
| `confiture lint --select tview` | the two storage rules below |

Confiture reads pg_tviews through its **read contract 1**, which pg_tviews
0.1.0-beta.20 and later offer: `tviews.registry` for what a database registers,
`tviews.pg_tviews_create_or_replace()` and `tviews.pg_tviews_drop()` for what a
migration writes, and `tviews.contract_version()` to say which contract they keep.
Where confiture reads TVIEWs from a live database (drift, `schema dump-model`,
`migrate preflight --against`, the platform's `introspect`), a pg_tviews that answers
another contract, or has none, is refused with `CONFIG_014` (exit 5), naming the
release installed. `migrate up` refuses the same way, before applying anything, when a
pending migration creates or drops a TVIEW. A migration that touches no TVIEW deploys
as before.

pg_tviews 0.1.0-beta.19 and earlier kept their objects wherever `search_path` put
them and have no contract. An extension created by one of them is moved with
pg_tviews' `scripts/migrate-from-0.1.0.sql`, not `ALTER EXTENSION … UPDATE`.

### What a generated migration writes

`pg_tviews_create_or_replace()` creates the TVIEW, replaces its query in place when
the columns stay the same, or rebuilds it when they change, and returns `unchanged`
when applied again, so the migration re-applies. A replacement keeps the table's
grants, comment and the indexes you added; the base tables' writers wait while the
rows are reconciled, which is why the change set reads the call as
`replace_materialized_view` (`lock_risky`). A rebuild pg_tviews cannot carry out
safely (a view reads the TVIEW, the table has RLS policies, …) is refused, naming the
reason.

The TVIEW is named as the tree names it (`tv_x` or `app.tv_x`). `options` holds only
what the tree pins: `UNLOGGED` is `"logged": false`, `WITH (fillfactor = n)` is
`"fillfactor": n`, and a later `ALTER TABLE tv_x SET LOGGED` (or `SET UNLOGGED`) is
`"logged": true` (or `false`), the same pin drift compares and `tview_002` reads. A key left out takes pg_tviews' default on
create and keeps its current value on replace, so a setting tuned on the database is
not reset by a migration that only changes the query.

A table named `tv_*` is a TVIEW only when it is created `AS SELECT`; `CREATE TABLE
tv_x (…)` with a column list is a plain table.

### Writing a TVIEW in the tree

The tree may declare a TVIEW either way, and confiture reads both as one object:

```sql
CREATE UNLOGGED TABLE tv_post WITH (fillfactor = 70) AS SELECT …;

SELECT tviews.pg_tviews_create_or_replace('tv_post', $$SELECT …$$,
    options => '{"logged": false, "fillfactor": 70}');
```

The call is read when its name and query are string constants (`tv_post`, `post` and
`app.tv_post` alike, arguments positional or named); `options` pins the keys it
passes. `SELECT tviews.pg_tviews_drop('tv_post')` drops a TVIEW the tree declared
before it, as `DROP TABLE tv_post` does. Moving a TVIEW from one spelling to the other
is no change: `migrate diff` generates nothing for it.

## Preflight finding

| Code | When |
|---|---|
| `PFLIGHT_TVIEW_BASE_COLUMN` | `--against` only: the migration drops or retypes a column a registered TVIEW reads, or drops its base table, without dropping the TVIEW first |

## Lint rules

`confiture lint --select tview` (off by default) reads the tree:

- `tview_001`: an index over `data` or `updated_at`, which every refresh rewrites, so no update is HOT
- `tview_002`: replicas declared and the TVIEW not pinned logged, by `SET LOGGED` or `options => '{"logged": true}'` (UNLOGGED is the default, and a standby cannot read it)

pg_tviews indexes each `fk_*` column and sets fillfactor 85 itself. It accepts
`CREATE INDEX` and `ALTER TABLE … SET LOGGED` after the conversion, and `UNLOGGED` and
`WITH (fillfactor = n)` on the `CREATE`. See the [rule reference](../reference/lint-rules.md).

## Restore

`confiture restore` brings a TVIEW back registered, and it keeps following its base
tables, cascades included, when the source database runs a pg_tviews confiture reads
(0.1.0-beta.20 or later): `pg_dump` carries pg_tviews' registration with the extension.
One condition, measured on pg_tviews 0.1.0-beta.19:

- **No `--disable-triggers`.** pg_tviews rebinds each OID it recorded in a trigger as
  `pg_tview_meta` loads; `pg_restore --section=data --disable-triggers` keeps the
  source database's OIDs, and the TVIEW stops following its base tables without an
  error. `confiture restore` never passes it; do not add it to a `pg_restore` of
  your own.

## Not supported yet

- **Benchmark data**: see [Realistic data for a pg_tviews TVIEW](./03-production-sync.md#realistic-data-for-a-pg_tviews-tview).
