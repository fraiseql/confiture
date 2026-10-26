# Seed Drift

`confiture seed drift` compares the reference rows your seed tree writes with the rows a live
database actually holds.

## The problem

A project usually has two kinds of environments:

- **rebuilt** ones (dev, test, CI), built from the schema tree and the seed tree, whose reference
  tables (currencies, units, statuses, lookup catalogues) get their rows from the seed files;
- **migrate-only** ones (staging, production), which never replay the seed and hold only the rows a
  migration inserted.

A seed change that ships without a matching migration reaches the rebuilt environments only.
Nothing fails: `migrate validate` reads schema files, `confiture drift` compares schema rather
than rows, and `seed validate` checks the seed files themselves. The gap shows up much later, as
a reference row missing in production, or as a row renamed on one side only.

## Usage

```bash
# What would be compared: tables, keys, columns. Reads no database.
confiture seed drift --env local --list-scope

# The seed side built from the tree on a scratch server, against production (the CI form)
confiture seed drift --env local --build --against production

# The seed side read from --env's own (seed-built) database, against a URL
confiture seed drift --env dev --against postgresql://readonly@prod-replica/app --format json
```

| Exit | Meaning |
|------|---------|
| 0 | No difference that nothing explains |
| 1 | Drift, or a `seed_drift` entry that matches nothing |
| 2 | A table in scope could not be compared (`not_compared`): the run is incomplete. This wins over 1 |
| 3 | A database did not answer (`CONFIG_006`): `--against`, `--env`'s, or the scratch server |
| 5 | Configuration: `--build` with no scratch server, an unknown environment, an invalid `seed_drift` block |

"Not checked" never reads as a pass. A table missing on one side, a table with no stable key, a
seed side that could not be built, a seed statement that may write rows confiture cannot see, and a
run that found no seeded table at all each exit 2 and say why. `--list-scope` exits 2 too when a
table in scope could not be compared.

`--output <file>` writes the JSON report to the file whatever `--format` prints.

## The two seed sides

- **`--env`'s database** (the default): the environment is seed-built, so its database is read as
  the seed side. It costs nothing, but it compares that database's history: a dev database that
  drifted from its own tree reports the dev database's drift.
- **`--build`**: a throwaway database on the scratch server (`--scratch-url`, else the
  environment's `scratch_url`, **never** its `database_url`). It is built the way confiture
  rebuilds an environment: the schema-only build, then each seed file on its own (the seed files
  in `include_dirs`, then the `--seeds-dir` files), then the prep-seed resolvers
  (`fn_resolve_*`), parents first. The comparison is then the tree's. Use it in CI. A seed file or
  resolver that fails is named, the run exits 2, and the scratch database is dropped.

The default side assumes that environment ran its resolvers too.

## What is compared

**Seed files.** The seed files in the environment's `include_dirs` are the ones `confiture build`
treats as seeds: any file under a directory whose name holds `seed` or `seeds` as a word
(`db/seeds/`, `30_seed_backend/`, `10-seeds/`), unless it only creates schema objects — the
prep-seed layout's `prep_seed/` staging tables are schema. With `--seeds-dir`, that directory's
files follow them, as `confiture seed apply` adds them.

**Scope.** Every table a seed file writes: `INSERT … VALUES`, `COPY … FROM stdin`, and the
statements whose rows confiture does not read statically (`INSERT … SELECT`, a data-modifying CTE,
`MERGE`). A prep-seed staging table is replaced by the table its resolver moves the rows into. A
seed file PostgreSQL's parser rejects, or a staging table whose target is ambiguous, is listed as
not compared. A seed that writes through a function (`SELECT app.fn_load()`) writes tables no
static reader sees, so those tables are not in scope. A `DO` block, a `CALL`, or a `COPY` that reads a
file or a program may write rows the reader cannot name, so a run that meets one says it is
incomplete.

**The key.** Rows are matched by a key **the seed itself writes**: every statement that adds the
table's rows supplies it, and no seed row computes it. A surrogate key PostgreSQL generates (an
identity `pk_*`, a `gen_random_uuid()` default the seed leaves out) differs between the two
databases, so it can never match a row across them. In order:

1. a key declared in `seed_drift.tables.<table>.key`;
2. the primary key, if stable;
3. the one single-column `UNIQUE` + `NOT NULL` column that is stable. In the common layout of an
   identity `pk_x` beside an `id uuid UNIQUE NOT NULL`, that is `id`.

A table with none is not compared, and the message says which key to declare.

**The values.** The columns every statement adding rows writes, apart from the key, compared as
PostgreSQL renders each one as text. A column only some statements write may hold its default in a
row, so it is not compared, and neither is `money`, which renders in each server's
`lc_monetary`. Both sides pin `TimeZone`, `DateStyle`, `IntervalStyle`, `extra_float_digits`
and `bytea_output`, so `2026-01-01 09:00+09` and `2026-01-01 00:00+00` are one value. A column a
seed row computes (`now()`) differs per database by construction and is not compared. A foreign
key to a key PostgreSQL generates (`fk_unit bigint → tb_unit.pk_unit`) is compared **through the
parent's stable key**: `fk_unit -> catalog.tb_unit.id`. So a parent whose rows were numbered in
another order on the live side is not reported as a change.

Each table reports three things:

- **seed only**: a key the seed has and the live side lacks, i.e. a seed change no migration shipped;
- **live only**: a key only the live side holds, i.e. a stale seed (not reported in `subset` mode);
- **changed**: a key both sides hold with different values, column by column. This catches a
  rename (`identifier: metre → meter`), a key reused for a different row, and a changed label or flag.

A compared column whose name says it holds a credential or personal data (`password_hash`,
`api_token`, `email`; the words `sec_003` reads names by) is never printed. It is compared through
a digest salted for that run alone, so a difference still shows, as `<redacted> → <redacted>`, and
no report holds the value or anything it could be recovered from. A key is never masked: it is how
you find the row, so key a table by a column that is not a secret. In `subset`
mode, "Live rows" counts the rows under the seed's keys only.

## Opt-outs

Every opt-out says why, and an entry that matches nothing in a run is itself reported (exit 1),
so an exception cannot outlive the table or row it was for.

```yaml
# db/environments/local.yaml
seed_drift:
  tables:
    catalog.tb_country: {key: [iso_code]}          # no key the seed writes: declare one
    app.tb_event_kind:
      mode: subset                                  # live may hold more; compare the seed's keys only
      reason: grows in production; the seed samples it
    app.tb_session: {skip: true, reason: ids are generated per environment}
  accepted:                                         # keyed by the --against environment
    production:
      - {table: catalog.tb_unit, key: [c3a1…], reason: "renamed in production on purpose"}
  max_rows: 100000          # a live table with more rows than this is not read whole
  statement_timeout: 30s    # how long one statement may run, on either side
  lock_timeout: 5s          # how long a read may wait for a lock (short: never queue behind a migration)
```

A difference accepted for production is not accepted for staging. A `--against` URL has no
accepted entries; name an environment to use them. An accepted entry names the table compared
(a staging table's final table) and the key as the report prints it, `null` for a NULL part. An
accepted entry for a table that was not compared in this run is not reported as unused. Both
timeouts must be positive: `0` would turn PostgreSQL's limit off.

`seed_drift` refuses an unknown key inside the block. A misspelt block name at the top level
(`seed_drfit:`) is ignored, because environment files allow keys confiture does not read.

## Production safety

The live side is read in one `READ ONLY` transaction with `statement_timeout` and `lock_timeout`
set and `search_path` pinned to `pg_catalog` (every relation is named with its schema), and it is
rolled back. Only the key and compared columns are selected. Nothing is ever
written to `--against`. `--against <environment>` opens that environment's `ssh_tunnel`, and every
URL in a message has its password masked. A table larger than `max_rows` is not scanned: it is
reported not compared, with `mode: subset` named as the remedy, which reads only the seed's keys.
The bound is a count capped at `max_rows + 1`, not the planner's estimate, which a partitioned or
never-analysed table does not have. `--against` takes a PostgreSQL URL (`postgresql://…`) or an
environment name; anything else is refused without being printed back, since a mistyped URL
carries its password.

## In CI

```bash
confiture seed drift --env ci --build --against staging --format json --output seed-drift.json
```

Exit 1 fails the job on drift; exit 2 fails it on an incomplete comparison. The JSON is
[seed-drift.schema.json](../reference/json-schemas/seed-drift.schema.json).
