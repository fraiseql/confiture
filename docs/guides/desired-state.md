# Desired-state ingest: from a FraiseQL artifact to a migration

`confiture migrate diff --generate` turns the difference between the current schema and a
**desired-state artifact** into a migration file. The artifact is what
`fraiseql compile --emit-ddl <dir>` writes — a directory of DDL files, one per type — so the
loop spec → schema → migration closes without a hand-authored target.

## The pipeline

```bash
fraiseql compile schema.json -o schema.compiled.json --emit-ddl build/ddl
confiture migrate diff --from db --to build/ddl --generate --name sync_from_spec
confiture migrate preflight
confiture migrate up
```

- `--from` is the current state: a schema file, a directory of `.sql` files, `-` for stdin, or
  `db` — the database of `--config` (default `db/environments/local.yaml`), read with
  `pg_dump --schema-only`.
- `--to` is the desired state: a schema file, a directory of `.sql` files (read in name order), or
  `-` for stdin, so `fraiseql compile … --emit-ddl - | confiture migrate diff --from db --to -` is
  one pipeline when the emitter writes to stdout.
- The positional form `migrate diff OLD.sql NEW.sql` still works; the two forms do not mix.

## What the migration contains

The differ compares tables, columns, indexes, constraints, enum types and sequences. With
`--from`/`--to`, `--generate` writes a SQL pair — `<version>_<name>.up.sql` and `.down.sql` — which
is the form every reader of a migration understands: `migrate preflight` classifies its statements
and reports their risk tier (a Python migration is unclassified by contract), `migrate validate
--idempotent` walks them. The up file carries one statement per change — `CREATE TABLE IF NOT
EXISTS` for a new table (its columns from the artifact), `ALTER TABLE` for column changes — and the
down file the reverse, in reverse order. Every statement is preceded by `-- confiture:tier <tier>`,
the risk tier the change-set classifier behind `migrate preflight` assigns it (`additive`,
`reversible`, `lock_risky`, `destructive`, `irreversible`), so the file says what preflight will say. A
change the generator cannot express is written as a `-- WARNING:` comment rather than silently dropped. The positional form `migrate diff OLD NEW
--generate` keeps writing a Python migration.

The round trip closes with `drift`: `confiture drift --schema <dir>` accepts the same directory of
`.sql` files and reports nothing once the migration is applied.

## Output

`--format json` reports the changes and, under `source`, where the desired state came from:

```json
{"kind": "sql", "path": "build/ddl"}
```

The payload's schema is `migrate-diff.schema.json` (see [JSON schemas](../reference/json-schemas.md)).

## What the ingest does not read

A structured export (a JSON or SpecQL schema) is not a source at 1.1.0. FraiseQL's compiled JSON
describes GraphQL types, not tables; the mapping to DDL is fraiseql's own `--emit-ddl`, and that DDL
is what confiture reads. `source.kind` in the JSON output is `sql` today and stays open for a
structured source when one exists.

## The external generator

`--generator` (the shell-out configured under `migration.generator`) remains the fallback for
teams with their own generator; the built-in path above needs no configuration.
