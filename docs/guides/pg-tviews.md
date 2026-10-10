# pg_tviews TVIEWs

[pg_tviews](https://github.com/fraiseql/pg_tviews) keeps a table in step with a query.
`CREATE TABLE tv_post AS SELECT …` becomes a table, a backing view, triggers on each
base table and a row in `tviews.registry`. Confiture reads a TVIEW as **one object**,
whose relation, query and pinned options are its whole definition.

## Where the backing view lives

From pg_tviews 0.1.0-beta.25 the backing view of `app.tv_post` is
`tviews.app__tv_post`, in pg_tviews' own schema (the name fitted to 63 bytes); it
follows `ALTER TABLE tv_post RENAME` and `SET SCHEMA`. Confiture reads it only from
`tviews.registry.view` and folds it into the TVIEW, whichever schemas it reads. The
application's `v_post` is now an ordinary view of the tree, as fraiseql's naming
convention has it (fraiseql/pg_tviews#181): a tree may declare `CREATE VIEW v_post AS
SELECT data FROM tv_post` beside its TVIEW, and it is built, compared and diffed like
any other view. A TVIEW whose definition embeds another TVIEW reads that TVIEW's
`tv_<entity>` table.

## What confiture does with one

| Where | What |
|---|---|
| `confiture build` | builds `CREATE TABLE tv_x AS …` as written |
| `confiture drift`, `migrate validate --check-live-drift` | `missing_tview` / `extra_tview` against a live database with `pg_tviews` installed, and `tview_option_mismatch` when an option the tree pins is not what `tviews.registry` holds |
| `migrate diff --generate` | writes `SELECT tviews.pg_tviews_create_or_replace('tv_x', $tview$…$tview$);` for an added or changed TVIEW and `SELECT tviews.pg_tviews_drop('tv_x', if_exists => true);` for a dropped one, with the matching down |
| `migrate fix --idempotent` | adds `IF NOT EXISTS` to a `tv_*` CTAS as to any table |
| `migrate preflight --against` | the finding below |
| `confiture lint --select tview` | the two storage rules below |

Confiture reads pg_tviews through its **read contract 1**: `tviews.registry` for what
a database registers, `tviews.pg_tviews_create_or_replace()` and
`tviews.pg_tviews_drop()` for what a migration writes, and `tviews.contract_version()`
to say which contract they keep. pg_tviews grows contract 1 by appending registry
columns, and confiture reads five of them (`view`, `uncascaded_policy`,
`function_reads`, `time_refresh`, `uncascaded_table_policies`), so it needs **pg_tviews 0.1.0-beta.26** or later.
Where confiture reads TVIEWs from a live database (drift, `schema dump-model`,
`migrate preflight --against`, the platform's `introspect`), a pg_tviews that answers
another contract, has none, or whose registry lacks one of those columns is refused
with `CONFIG_014` (exit 5), naming the release installed and what it lacks. `migrate up` refuses the same way, before applying anything, when a
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
`"fillfactor": n`, a call's `"uncascaded_policy"`, `"uncascaded_tables"`,
`"time_refresh"` and `"function_reads"` are passed as written (below), and a later `ALTER TABLE tv_x SET LOGGED` (or `SET UNLOGGED`) is
`"logged": true` (or `false`), the same pin drift compares and `tview_002` reads; a
later `ALTER TABLE tv_x SET (fillfactor = n)` is `"fillfactor": n`, and `RESET
(fillfactor)` is `"fillfactor": 100`, PostgreSQL's default, as pg_tviews' registry reads it. A key left out takes pg_tviews' default on
create and keeps its current value on replace, so a setting tuned on the database is
not reset by a migration that only changes the query.

A table named `tv_*` is a TVIEW only when it is created `AS SELECT`; `CREATE TABLE
tv_x (…)` with a column list is a plain table.

### `uncascaded_policy`: what a write no cascade reaches does

A TVIEW may read a table no cascade can trace back to its rows (a table read in a
subquery under `LIMIT`, a lookup joined on no key, …). From pg_tviews 0.1.0-beta.25
the TVIEW declares what a write to such a table does, and the
`pg_tviews.uncascaded_policy` setting defaults to **`error`**: a definition that reads
one is refused at create unless it declares a policy.

| Policy | A write to an uncascaded table |
|---|---|
| `error` | (the default) the TVIEW is refused at create |
| `warn` | leaves the TVIEW's rows stale, with a warning at create |
| `full_refresh` | refreshes every row of the TVIEW |

The policy is declared in the call's `options`, and stored with the TVIEW:

```sql
SELECT tviews.pg_tviews_create_or_replace('tv_post', $$SELECT …$$,
    options => '{"uncascaded_policy": "full_refresh"}');
```

Confiture reads the key as it reads `logged` and `fillfactor`: the tree pins it,
`migrate diff --generate` passes it in the call it writes (pg_tviews answers `altered`
when only the policy changes), and drift compares it with
`tviews.registry.uncascaded_policy` (not `options`, where pg_tviews does not keep it)
as `tview_option_mismatch`. A tree that names no policy pins none: never drift.

`CREATE TABLE … AS` and `pg_tviews_create()` take no options and read the session's
`pg_tviews.uncascaded_policy` instead (`SET pg_tviews.uncascaded_policy =
'full_refresh';` before the statement). Confiture does not model session settings, so
a policy set that way is no pin: drift does not compare it, and a migration
`migrate diff --generate` writes for that TVIEW passes none, which pg_tviews refuses
on a fresh database under the `error` default. Declare the policy in the call's
`options` when the TVIEW reads an uncascaded table.

`"uncascaded_tables"` gives one table its own policy, overriding the TVIEW's for a
write to that table: `{"public.tb_category": "full_refresh"}` rebuilds the TVIEW when a
category moves and keeps `error` for every other table. Confiture reads it as it reads
`uncascaded_policy` — the tree pins it, `migrate diff --generate` passes it, drift
compares it with `tviews.registry.uncascaded_table_policies` as `tview_option_mismatch`
(subject `uncascaded_tables`) — with each table compared by identity, since the
registry writes one on the read path unqualified. `uncascaded_tables: {}` pins none.

### `time_refresh` and `function_reads`: reads no write changes

Two reads change a TVIEW's rows with no write to a table it tracks
(fraiseql/pg_tviews#193): the time (`CURRENT_DATE`, `now()`, …, in the definition or
a view it reads), and a table read inside a non-immutable function outside
`pg_catalog`. From pg_tviews 0.1.0-beta.26, under the `error` and `full_refresh`
policies, a definition with either is refused at create unless it declares it:

```sql
SELECT tviews.pg_tviews_create_or_replace('tv_contract', $$SELECT …$$,
    options => '{"time_refresh": "external",
                 "uncascaded_policy": "full_refresh",
                 "function_reads": {"public.label_suffix()": ["public.tb_setting"]}}');
```

`"time_refresh": "external"` says the application or pg_cron calls
`tviews.pg_tviews_refresh_time_dependent()` at the boundary. `function_reads` names
each function with its argument types and the tables it reads (`[]` for none); those
tables are reads no cascade reaches, so the TVIEW's policy (or `uncascaded_tables`)
decides what a write to one does.

Confiture reads both keys as it reads `uncascaded_policy`: the tree pins them, `migrate
diff --generate` passes them, and drift compares them with `tviews.registry` as
`tview_option_mismatch`. The registry spells a declaration its own way (the function
qualified and its argument types as `format_type` writes them, a table on the read path
unqualified), so `function_reads` are compared by identity: `label_suffix()` and
`public.label_suffix()`, `price(int8)` and `public.price(bigint)` are one function,
`tb_setting` and `public.tb_setting` one table. A tree that declares neither pins
neither, and `function_reads: {}` pins none. `confiture lint` reports an undeclared
function (`tview_004`) and an undeclared time read (`tview_005`) before pg_tviews
refuses them.

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
`CREATE INDEX`, `ALTER TABLE … SET LOGGED` and `SET (fillfactor = n)` after the conversion, and `UNLOGGED` and
`WITH (fillfactor = n)` on the `CREATE`. See the [rule reference](../reference/lint-rules.md).

In a tree that also uses pg_treekey, `treekey_001` and `treekey_002` (on by default) report a
TVIEW whose chain walks a tree in a spelling pg_tviews cannot trace — a `WITH RECURSIVE`
reading it, or its path unnested `WITH ORDINALITY` — unless the policy a write to that tree
meets is `full_refresh` (`uncascaded_tables`, above): under `error` pg_tviews refuses the
TVIEW, under `warn` its rows go stale. See
[the `treekey` family](../reference/lint-rules.md#the-treekey-family--how-a-tviews-chain-walks-a-pg_treekey-tree).

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
