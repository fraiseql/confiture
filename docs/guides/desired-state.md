# Desired-state ingest: from a FraiseQL artifact to a migration

`confiture migrate diff --generate` turns the difference between the current schema and a
**desired-state artifact** into a migration file. The artifact is what
`fraiseql compile --emit-ddl <dir>` writes — a directory of DDL files, one per type — so the
loop spec → schema → migration closes without a hand-authored target.

## The pipeline

An artifact is a **fragment** of the desired state, not the whole of it: FraiseQL contributes the
part only it knows — the indexes its queries need, on `tv_<type>` relations the project authors
itself. A desired state is whole, so the artifact is composed into the project's tree rather than
diffed alone. Emit it into a committed directory and list that directory in the environment's
`include_dirs`, after the files that declare its tables:

```yaml
# db/environments/local.yaml
include_dirs:
  - db/schema
  - path: db/fraiseql/indexes   # what fraiseql's --emit-ddl writes
    order: 900                  # after every table it indexes
    auto_discover: false        # a missing directory fails the build, never skips it
```

```bash
fraiseql compile schema.json -o schema.compiled.json --emit-ddl db/fraiseql/indexes
confiture migrate diff --from db --to-env local --generate --name sync_from_spec
confiture migrate preflight
confiture migrate up
```

`order` is required: every entry defaults to `0`, and inside one order block files sort by path,
so `db/fraiseql/…` would build before `db/schema/…` and its indexes before their tables.
`--to-env local` reads exactly what `confiture build --env local` selects — `order`, `include` and
`exclude` honoured — which is also the tree a deploy builds and checks for drift. A hand-written
copy of a generated index is a second definition (`confiture lint` reports it as `build_005`).

Diffed alone against a database, a fragment is refused: an index on a relation the fragment does
not declare is `DIFFER_406` (exit 5). The database holds the relation and the fragment does not, so
the migration would drop it; or the database does not hold it, so the index could not be created.
`--from db --to <dir>` is for a directory that is a whole schema.

- `--from` is the current state: a schema file, a directory of `.sql` files, `-` for stdin, or
  `db` — the database of `--config` (default `db/environments/local.yaml`), read from its
  catalog the way `confiture drift` reads it, in the schemas the desired tree names. A database
  built from a tree is no change from that tree: what PostgreSQL rewrites on the way in — a name
  it gives an unnamed constraint or index, the index behind a primary key, an analysed default or
  CHECK, a `serial` — is compared as the same thing, and a pg_tviews TVIEW is one object, dropped
  with `tviews.pg_tviews_drop`. Confiture's own tables (`tb_confiture`, …) are not the project's.
  An object the database holds that confiture reads only by existence (a domain, a policy, …) and
  the tree does not declare is a `DIFFER_404` warning: the diff cannot write its statement.
  With a scratch server (`--scratch-url`, or `scratch_url` in the environment) the tree is built
  there and read back first, so a CHECK, an index predicate or a view's query that changed is a
  change rather than an expression that exists on both sides; the payload says
  `"fidelity": "materialised"` ([Comparison fidelity](../reference/comparison-fidelity.md)).
- `--to` is the desired state: a schema file, a directory of `.sql` files (read in name order), or
  `-` for stdin — each a whole schema. `--to-env <env>` is the environment's build instead.
- The positional form `migrate diff OLD.sql NEW.sql` still works; the two forms do not mix.

## What the migration contains

The differ compares tables, columns, indexes, constraints, enum types and sequences, and the
objects a tree defines by statement — views, routines, domains and types, triggers, extensions,
schemas, policies, and the rest. With `--from`/`--to`, `--generate` writes a SQL pair — `<version>_<name>.up.sql` and `.down.sql` — which
is the form every reader of a migration understands: `migrate preflight` classifies its statements
and reports their risk tier (a Python migration is unclassified by contract), `migrate validate
--idempotent` walks them. The up file carries one statement per change — `CREATE TABLE IF NOT
EXISTS` for a new table (its columns, constraints and indexes from the artifact), `ALTER TABLE` for
column changes — and the down file the reverse, in reverse order. Each creation re-applies: `IF NOT
EXISTS` or `OR REPLACE` where PostgreSQL has one, and a `DO … EXCEPTION WHEN duplicate_object` guard
for a domain, a composite type or a policy, which have none. The changes run in an order PostgreSQL
accepts: schemas and extensions first, then types and sequences, tables in foreign-key order,
edits, routines, views, triggers and policies — and drops the other way round, what depends on a
table before the table. A foreign-key cycle among new tables is created without the keys that close
it, and those are added once every table exists. Every statement is preceded by `-- confiture:tier <tier>`,
the risk tier the change-set classifier behind `migrate preflight` assigns it (`additive`,
`reversible`, `lock_risky`, `destructive`, `irreversible`), so the file says what preflight will say. A
change the generator cannot express is written as a `-- WARNING:` comment rather than silently dropped. The positional form `migrate diff OLD NEW
--generate` keeps writing a Python migration.

Between two trees — an empty or earlier artifact on `--from` — an index on a table neither tree
declares is carried as written, `CREATE INDEX CONCURRENTLY IF NOT EXISTS` since the table exists
and is in use, under a comment naming the undeclared table, and the diff reports a `DIFFER_405`
warning (also in `--format json`) naming the index and the table. The down drops it the same way.
A table either side declares is that side's whole, so its indexes come and go with it; an index on
a relation only the current side declares is the contradiction `DIFFER_406` refuses.

An index on a TVIEW is built by `confiture build` and kept by pg_tviews across a rebuild, but
`migrate diff` does not carry it and drift does not check it yet: each one is a `DIFFER_407`
warning naming the index and the TVIEW. Write a change to one in a migration by hand.

The round trip closes with `drift`: `confiture drift --schema <dir>` accepts a directory of `.sql`
files that is a whole schema — the composed tree — and reports nothing once the migration is
applied. Given a fragment, it refuses with `DIFFER_406` as `migrate diff` does.

## Output

`--format json` reports the changes and, under `source`, where the desired state came from:

```json
{"kind": "env", "path": "local"}
```

`kind` is `env` for `--to-env`, `sql` for a file, a directory or stdin.

The payload's schema is `migrate-diff.schema.json` (see [JSON schemas](../reference/json-schemas.md)).

## The destructive gate

A spec that removes a table, a column, a view, a type or a sequence, or narrows a type, asks for
DDL that loses something. The
generator writes it — behind a gate. `migration.destructive` in the environment config sets the
policy, and `--allow-destructive` / `--forbid-destructive` on `migrate diff` override it per run:

| Policy | `migrate diff --generate` | `migrate up` |
|---|---|---|
| `gated` (default) | writes the DDL; the up file starts with `-- confiture:destructive` | refuses the file (`VALID_002`, exit 5) unless run with `--allow-destructive` |
| `allow` | writes the DDL unmarked | applies it |
| `forbid` | refuses (`DIFFER_401`, exit 5); nothing is written | — |

`migrate preflight` reports a gated file as `PFLIGHT_DESTRUCTIVE_GATED` (a warning: the tier is
already in the change set; the issue says the runner will want the flag). A Python migration
generated by the positional form carries the same gate as `destructive = True` on its class.

## What the down file can and cannot undo

The down file is derived from what the differ saw. A dropped column comes back as `ADD COLUMN` with
its type, nullability and default (the default as PostgreSQL prints it, casts and call arguments
included); a dropped table comes back as its `CREATE TABLE`; a narrowed type widens back; a
dropped enum type comes back with its labels, a dropped sequence with its options; an added
constraint is dropped by its name. A type change PostgreSQL has no assignment cast for (`text` →
`integer`) is written `USING column::type`, with a `-- review:` line saying a value that does not
cast fails the migration. Rows never
come back, nor a sequence's position: the up statement that loses them is preceded by
`-- confiture:irreversible data`, and
`migrate preflight` repeats the reason under the gate issue's `details.irreversible`. A change the
generator has no rollback for is written as `-- confiture:irreversible no rollback derived for …` in
the down file — and its up statement is tiered `irreversible`, whatever its DDL alone would say.
Nothing is commented out silently.

## What the ingest does not read

A structured export (a JSON or SpecQL schema) is not a source at 1.1.0. FraiseQL's compiled JSON
describes GraphQL types, not tables; the mapping to DDL is fraiseql's own `--emit-ddl`, and that DDL
is what confiture reads. `source.kind` in the JSON output is `sql` or `env` and stays open for a
structured source when one exists.

## The external generator

`--generator` (the shell-out configured under `migration.generator`) remains the fallback for
teams with their own generator; the built-in path above needs no configuration.
