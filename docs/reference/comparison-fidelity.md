# Comparison fidelity: how drift and diff compare expressions

`confiture drift` and `confiture migrate diff` ask one comparison the same question, and
the answer depends on who wrote each side. A tree is what an author wrote. A database is
what PostgreSQL stored, and PostgreSQL stores an expression **analysed**: it adds implicit
casts, parenthesises, writes `IN (…)` back as `= ANY (ARRAY[…])`, deparses a view's query,
and prints each constant in its type's output spelling (`'2024-1-1'` comes back
`'2024-01-01'`, a `jsonb` object with its keys sorted). The text an author wrote and the
text PostgreSQL holds are different strings for one expression.

So every comparison runs at one of three **fidelities**, and says which.

| Fidelity | When | An expression is compared |
|---|---|---|
| `as_written` | two trees (`migrate diff OLD.sql NEW.sql`, `--from tree --to tree`) | as each author wrote it, through PostgreSQL's parser |
| `structural` | a tree and a database, no scratch server | a default as a value, its constants spelled by the database's server; every other expression only as existing |
| `materialised` | a tree and a database, with a scratch server | exactly, as PostgreSQL stores it: the tree is built into a scratch database and read back |

## Choosing the materialised tier

Name a writable PostgreSQL server that confiture may create a throwaway database on:

```yaml
# db/environments/production.yaml
database_url: ${DATABASE_URL}
scratch_url: postgresql://localhost/postgres
```

or pass `--scratch-url` to `confiture drift` or `confiture migrate diff --from db` (the flag
wins over the key). `migrate validate --check-live-drift` reads the key as well. The scratch
server is never the environment's own `database_url`, and it does not have to be the server
the database runs on: a read-only production replica is compared at the materialised tier
from a CI or local server. The scratch database is dropped when the comparison ends, whatever
happens.

The scratch server must be able to build the tree: the extensions it creates must be
installed there, and a tree with pg_tviews TVIEWs needs a pg_tviews confiture reads
(`CONFIG_014` otherwise). A tree the scratch server cannot build is an error, never a quiet
fall back to the structural tier.

Use a scratch server of the database's PostgreSQL major version. Both sides are compared as
PostgreSQL's deparser prints them, and two majors may print one expression differently.

## What each tier compares

| Slot | `as_written` | `structural` | `materialised` |
|---|---|---|---|
| column default | parse tree | value: parse tree, constants spelled by the database's server | as stored |
| CHECK constraint | parse tree | exists (unnamed ones paired by position) | as stored (unnamed ones paired by what they say) |
| index key that is a column | as written | as written | as stored |
| index expression key | parse tree | exists | as stored |
| partial index predicate | parse tree | exists | as stored |
| view / materialized view query | as written | exists | as stored (deparsed) |
| routine body | as written | as written (PostgreSQL keeps it verbatim) | as written |
| generated column expression | not compared | not compared | not compared |

A named index whose keys, uniqueness or predicate change is dropped and created again, at
every tier: `migrate diff` writes `DROP INDEX` then `CREATE INDEX`, and drift reports
`missing_index` plus `extra_index`, as for a named index rebuilt with another access method.

No tier compares a generated column's expression: no change says how one changed.

## What drift reports at each tier

The drift kinds and severities are the same at every tier; the materialised tier reports
more of them.

- A changed CHECK is `constraint_mismatch` (critical) when PostgreSQL gave it one name on
  both sides, as it does for an unnamed CHECK built from one statement, and
  `missing_constraint` plus `extra_constraint` otherwise. At the structural tier, the
  CHECK's text is not compared.
- A changed partial index predicate or expression key is `missing_index` plus
  `extra_index`.
- A view whose query changed is not a drift item at any tier: drift reports that a view
  exists (`missing_view`, `extra_view`). Compare view bodies with `migrate validate
  --check-body-views`, or ask `migrate diff --from db` with a scratch server, which writes
  the `CREATE OR REPLACE VIEW`.
- A finding names an object the way the tree side spells it. At the materialised tier that
  side is PostgreSQL's reading of the tree, so every name is schema-qualified
  (`public.tv_post`).

## What a migration generated at the materialised tier contains

`migrate diff --from db --to tree --generate` with a scratch server compares PostgreSQL's
reading of the tree, and writes that reading: qualified names, PostgreSQL's names for the
tree's unnamed constraints, deparsed view queries. It applies to the database exactly; it is
not the tree's text. Without a scratch server the migration is written from the tree as
authored.

## The payload

`confiture drift --format json` and `confiture migrate diff --format json` carry
`"fidelity": "materialised"` when a scratch server read the tree back. The field is absent at
each command's default tier (`structural` for drift and `migrate diff --from db`,
`as_written` for two trees), so a payload from before the field existed reads the same.
