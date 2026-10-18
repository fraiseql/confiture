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
| 2 | A table in scope could not be compared (`not_compared`): the run is incomplete |
| 3 | A database did not answer (`CONFIG_006`) |

"Not checked" never reads as a pass. A table missing on one side, a table with no stable key, and
a seed side that could not be built each exit 2 and say why.

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

**Scope.** Every table a seed file writes: `INSERT … VALUES`, `COPY … FROM stdin`, and the
statements whose rows confiture does not read statically (`INSERT … SELECT`, a data-modifying CTE,
`MERGE`). A prep-seed staging table is replaced by the table its resolver moves the rows into. A
seed file PostgreSQL's parser rejects, or a staging table whose target is ambiguous, is listed as
not compared. A seed that writes through a function (`SELECT app.fn_load()`) writes tables no
static reader sees, so those tables are not in scope.

**The key.** Rows are matched by a key **the seed itself writes**: every statement that adds the
table's rows supplies it, and no seed row computes it. A surrogate key PostgreSQL generates (an
identity `pk_*`, a `gen_random_uuid()` default the seed leaves out) differs between the two
databases, so it can never match a row across them. In order:

1. a key declared in `seed_drift.tables.<table>.key`;
2. the primary key, if stable;
3. the one single-column `UNIQUE` + `NOT NULL` column that is stable. In the common layout of an
   identity `pk_x` beside an `id uuid UNIQUE NOT NULL`, that is `id`.

A table with none is not compared, and the message says which key to declare.

**The values.** The columns the seed writes, apart from the key, compared as PostgreSQL renders
each one as text. Both sides pin `TimeZone`, `DateStyle`, `IntervalStyle`, `extra_float_digits`
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
  max_rows: 100000          # a live table above this (pg_class.reltuples) is not read whole
  statement_timeout: 30s    # the live side's statement_timeout and lock_timeout
```

A difference accepted for production is not accepted for staging. A `--against` URL has no
accepted entries; name an environment to use them.

`seed_drift` refuses an unknown key inside the block. A misspelt block name at the top level
(`seed_drfit:`) is ignored, because environment files allow keys confiture does not read.

## Production safety

The live side is read in one `READ ONLY` transaction with `statement_timeout` and `lock_timeout`
set, and it is rolled back. Only the key and compared columns are selected. Nothing is ever
written to `--against`. `--against <environment>` opens that environment's `ssh_tunnel`, and every
URL in a message has its password masked. A table larger than `max_rows` is not scanned: it is
reported not compared, with `mode: subset` named as the remedy, which reads only the seed's keys.

## In CI

```bash
confiture seed drift --env ci --build --against staging --format json --output seed-drift.json
```

Exit 1 fails the job on drift; exit 2 fails it on an incomplete comparison. The JSON is
[seed-drift.schema.json](../reference/json-schemas/seed-drift.schema.json).
