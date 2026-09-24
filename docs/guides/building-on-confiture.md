# Building on confiture

`confiture.platform` is the surface a tool builds on when it needs what confiture
knows about a schema. A seed generator, a parity fixture or a schema browser can
read a schema into one model, order its tables, and ask what each column
accepts. A seed generator can also write seeds the applier and the validator
accept. Everything here is re-exported from confiture's own modules, and nothing
else is promised: [the reference](../reference/platform-api.md) lists every name.
A contract test (`tests/contract/test_platform_surface.py`) pins each signature
and each field by equality.

Two rules shape every signature:

- **No parser or driver type crosses the seam.** A guard fails on any pglast or
  psycopg type in a platform signature, field or returned value.
- **A connection is a URL or yours.** Pass a URL and the call opens, commits and
  closes its own connection. Pass an object that meets `Connection` (a psycopg 3
  connection does) and the transaction stays yours: the call neither commits nor
  rolls back.

## A seed generator, end to end

```python
import random
from pathlib import Path

from confiture.platform import (
    apply_seeds,
    column_facts,
    dependency_order,
    parse_schema,
    validate_seeds,
    writable_columns,
    write_copy_seed,
)

model = parse_schema(Path("db/schema"))
rng = random.Random(42)
for number, table in enumerate(dependency_order(model), 1):
    columns = writable_columns(model, table)
    rows = [{c.name: my_value(column_facts(model, table, c.name), rng) for c in columns}]
    write_copy_seed(Path(f"db/seeds/prep/{number:02}_{table.name}.sql"), table,
                    [c.name for c in columns], rows, model=model)

apply_seeds("postgresql://localhost/dev", Path("db/seeds/prep"))
report = validate_seeds(Path("db/seeds/prep"), schema_dir=Path("db/schema"), max_level=3)
```

`my_value` is yours. [`examples/08-generated-seeds`](https://github.com/fraiseql/confiture/tree/main/examples/08-generated-seeds)
is the whole thing in 60 lines, run in CI against a real database at all five
validation levels.

## Reading a schema

`parse_schema` reads DDL into the model:

- a `str` is DDL text;
- a `Path` is a file, or a directory read the way a bare `include_dirs` entry is:
  every `.sql` under it, sorted by path;
- a list of paths is read in its order, each a `Path` or a `str` naming one;
- `env="local"` (with `project_dir=`) reads exactly what `confiture build --env
  local --schema-only` builds.

The model is order-aware: a later `ALTER TABLE` or `DROP` folds into what an
earlier file created, as the build applies it. A statement PostgreSQL's parser
rejects raises `SchemaError` with code `DIFFER_400`, a path that does not exist
`SCHEMA_201`, and a file that is not UTF-8 text a `SchemaError` naming it.

`introspect` reads a live database into the same model: tables, enum types,
sequences, routines, views and triggers, in the schemas you name or every user
schema. `schemas="app"` is the one schema `app`, and a schema the database does
not have adds nothing, so a misspelt name gives an empty model rather than an
error. The same model from both sides is what lets a tool compare them.

A model is frozen through and through: its mappings are read-only copies of
the ones it was built from, so `model.tables[ref] = table` is a `TypeError`. A
tool that wants a different model builds one, or `dataclasses.replace`s a
mapping. A model copies, deep-copies and pickles whole.

`SchemaModel.to_json()` writes the model with sorted keys, so one model is one
text. `SchemaModel.from_json()` reads it back, and
[`schema-model.schema.json`](../reference/json-schemas/schema-model.schema.json)
publishes its shape.

## Ordering tables

`dependency_order(model)` lists every table after each table it references by
foreign key. The order depends on the schema alone: among the tables ready at
each step, the first by `(schema, name)` goes first. The same schema gives the
same order on every run, whatever order its files declared it in. Two rules:

- A table that references itself is ordered like any other. Its rows are yours
  to order, parents first, or with the reference `NULL` and then updated.
- Tables whose keys form a cycle raise `DependencyCycleError` (`SCHEMA_202`), which
  names the tables on the cycle and not the ones merely downstream of it.

`tables=[...]` orders a subset, and walks through the tables the subset depends
on; `tables="app.item"` is that one table. A reference is resolved the way
PostgreSQL resolved it wherever the model can tell. A written schema is that
schema. A bare name is the default schema's table, or else the one schema that
holds a table of that name, since a parse cannot see `SET search_path`. A name
the model does not hold raises `NotInModelError`, as it does from
`writable_columns`, `column_facts` and `naming_hints`.

## What a writer may supply

`writable_columns(model, table)` is every column PostgreSQL does not fill. It
leaves out identity columns (either kind), generated columns and serials; a
serial is a `nextval` default in the catalog. That is the split between `id` and
`pk_*`: a writer supplies `id` and PostgreSQL generates `pk_language`.

`column_facts(model, table, column)` says what a value must respect:

| Field | What it holds |
|-------|---------------|
| `type_key`, `raw_sql_type` | the type's identity (`varchar(20)`) and its spelling (`VARCHAR(20)`) |
| `not_null`, `default` | what PostgreSQL records |
| `unique` | true when a PRIMARY KEY, UNIQUE constraint or unique index covers this column alone, wherever it was declared; a partial unique index (one with `WHERE`) does not count, since it leaves the rows outside its predicate free to repeat |
| `checks` | every CHECK expression that reads the column, written on it or at table level |
| `enum_values` | the labels of the enum the column's type is, or `None` |
| `foreign_key` | the table it references, resolved, and the column; a key naming no column references the primary key |

`naming_hints(model, table)` applies `confiture introspect`'s naming heuristic.
It reports the first primary-key column named `pk_*`, and a column named `id`.
Treat both as signals, not facts. The seam does not guess audit columns: a
generator that fills `created_by` knows why, and supplies it.

## Writing seeds

`write_copy_seed` and `write_insert_seed` take the same arguments: the table, the
columns in the order to write them, and rows as mappings of every column to its
value. They refuse at write time, and write nothing, when the model lacks the
table or the table a column, when a column is named twice, when PostgreSQL
fills one, when a row misses a
column or carries another, or when a value cannot be given as written. Every
refusal is a `SeedError`, a path that cannot be written included; for a table
the model lacks, its cause is the `NotInModelError` the lookup raised. NOT NULL
is not checked, because a trigger may fill a column and the model does not know
what a trigger writes; `column_facts` tells you which columns are NOT NULL.

Values: `None` is NULL; `True`/`False` are booleans; `bytes` is `bytea`; a
`dict` or `list` is JSON for a `json`/`jsonb` column, and a `list` is an array
for an array column. Anything else is written as `str(value)`, which PostgreSQL's
input function for the column then reads.

Which format:

- **COPY** is what `seed apply` loads fastest.
- **INSERT** is what a reader can run by hand. Every value is a literal typed by
  its column, written `E'…'` when it holds a backslash.
- Both load through `confiture seed apply`, and either one leaves a generated key
  to PostgreSQL: COPY honours the identity and the default of every column its
  list leaves out.
- No rows is a file either way that names its table and columns: COPY writes an
  empty block, INSERT a comment, since an `INSERT` without a row is not SQL.

`apply_seeds(database, seeds)` applies every `.sql` under a directory,
recursively, sorted by path — the tree a build reads — or a list of files in
the given order; a `str` is the path it
spells. Every path is checked before the database is reached, so a misspelt one
raises `SeedError` and applies nothing. It runs one transaction with a savepoint
per file: a failed file is undone and nothing before it. The first failure, a
file that is not UTF-8 text included, then raises `SeedError`, unless
`continue_on_error=True` keeps going and reports the failed files. With a URL
the run is all or nothing (unless `continue_on_error=True`), and a transaction
that fails to commit, as one with a deferred constraint violated does, is a
`SeedError` too; with a connection the transaction is yours, and a connection
in autocommit is refused before anything runs (`CONFIG_013`), not switched: a
savepoint needs a transaction, and the mode is yours too. A `COPY … FROM
stdin` block streams through the driver's COPY protocol. `profile=` takes a
`SeedProfile`, whose `include` / `exclude` are the path globs `include_dirs`
uses, over each file's path below the seeds directory: `stats_*.sql` matches the
file name at any depth, `stats/` a subdirectory; a profile read from
`seed.profiles` carries its key as `name`, which the result records as
`seed_profile`.

`validate_seeds(seeds, schema_dir=…, max_level=3)` validates seeds written for
the prep-seed pattern: UUID-keyed rows in `prep_seed`, resolved into BIGINT-keyed
rows in `catalog`. Levels 1 to 3 read files and need no database. Levels 4 and 5
load the seeds and run the resolvers against `database=`, a URL or a connection,
parents first, in a transaction nothing outlives: a URL's is rolled back, and a
connection's runs inside a savepoint rolled back on the way out. Level 1 reads `INSERT` statements only, so a COPY file
passes it unread (#366). The report's violations are `PrepSeedViolation`s, each
with a `PrepSeedPattern` and a `ViolationSeverity`. What the validator cannot run
it raises rather than reports: a `seeds` that is not a directory, or a seed
file that is not UTF-8 text, is a `SeedError`; a missing `schema_dir`, when a
level that reads it runs, is a `SchemaError`; a `max_level` outside 1 to 5 is a
`ConfigurationError`, and so is a connection in autocommit at level 4 or 5
(`CONFIG_013`); and 4 or 5 without `database=` is a `ValueError`.

## Ids

confiture does not generate ids and keeps no copy of any id convention. A
FraiseQL project takes its structured ids from **fraiseql-uuid**, which owns that
pattern. Level 1's `VALID_UUID_PATTERN` checks only the generic shape, eight,
four, four, four and twelve hex digits, as PostgreSQL's `uuid` input does.
Neither reads the version or variant nibble, so fraiseql-semis's 32|16|16|64
layout (`01234567-5001-0001-0000-000000000042`) loads and validates, although it
is not RFC-4122. Take ids from the library that owns them, not from a table of
codes copied into a generator: semis's own worked example uses a table code its
registry does not list.

## What changed between two schemas

`diff(old, new)` takes two sources, each anything `parse_schema` takes: a side
given as `None` is the build of `env=` from `project_dir=`, so
`diff(Path("snapshot.sql"), None, env="local")` is what changed from a snapshot
to the current tree. Exactly one side is `None` when `env=` is given, and
neither is when it is not; anything else is a `ValueError`. It returns a
`SchemaDiff`: `changes`, each one variant of the closed `SchemaChange` union,
and `warnings`, the duplicate definitions the comparison resolved (`DIFFER_402`),
each a `BuildWarning`. It compares DDL, not two models, because views, routines
and triggers are compared as the statements that create them, and the model does
not hold those; the variants that carry one hold it as a `DDLObject`.
`tier_of(change)` gives a change's `RiskTier`, the taxonomy `migrate preflight`
reports, or `None` where no tier applies.

Every change has a `ref`: the `ObjectRef` the model keys the changed object
under, so `model.tables[change.ref]` finds the table a column change is on. It is
the one field every variant spells alike. The others are named for what they
hold, so one name holds a model object in one variant and a spelling in another:

| Variant | Fields | `ref` |
|---------|--------|-------|
| `TableAdded`, `TableDropped` | `table: Table` | the table |
| `TableRenamed` | `old: Table`, `new: Table` | the old table |
| `ColumnAdded`, `ColumnDropped` | `table: str`, `column: Column` | the table |
| `ColumnRenamed` | `table: str`, `old: str`, `new: str` | the table |
| `ColumnTypeChanged` | `table: str`, `old: Column`, `new: Column` | the table |
| `ColumnNullabilityChanged` | `table: str`, `column: str`, `nullable: bool` | the table |
| `ColumnDefaultChanged` | `table: str`, `column: str`, `old: str \| None`, `new: str \| None` | the table |
| `IndexAdded`, `IndexDropped` | `table: str`, `index: Index` | the table |
| `ForeignKeyAdded`, `ForeignKeyDropped`, `CheckConstraintAdded`, `CheckConstraintDropped`, `UniqueConstraintAdded`, `UniqueConstraintDropped` | `table: str`, `constraint: Constraint` | the table |
| `EnumTypeAdded`, `EnumTypeDropped` | `enum: EnumType` | the type |
| `EnumValuesChanged` | `enum: str`, `added: tuple[str, ...]`, `removed: tuple[str, ...]` | the type |
| `SequenceAdded`, `SequenceDropped` | `sequence: Sequence` | the sequence |
| `ObjectAdded`, `ObjectDropped` | `ref: ObjectRef`, `obj: DDLObject` | the object |
| `ObjectReplaced` | `ref: ObjectRef`, `old: DDLObject`, `new: DDLObject` | the object |

A `table: str` or `enum: str` is the spelling the author wrote, which a finding
prints; `ref` is the identity. `ColumnAdded.column` is a `Column` and
`ColumnNullabilityChanged.column` a column's name; `EnumTypeAdded.enum` is an
`EnumType` and `EnumValuesChanged.enum` the type's name. Only `ref` reads the same
in all of them.

## Errors

What a call refuses it raises as confiture's own error: a `ConfiturError` with a
code and a hint, naming what it refused, with the driver's or the codec's
exception as its cause where there was one. Only two are Python's own, for a
mistake in the call itself rather than in what it was pointed at.

| Raised | When |
|--------|------|
| `SchemaError` | DDL PostgreSQL's parser rejects (`DIFFER_400`), a schema path that does not exist (`SCHEMA_201`), a schema file that is not UTF-8 text |
| `NotInModelError` | a table or column the model does not hold; a `SchemaError` and a `KeyError` both, so `except KeyError` catches it too |
| `DependencyCycleError` | tables whose foreign keys form a cycle (`SCHEMA_202`) |
| `SeedError` | anything a seed writer refuses, a seed path that does not exist, a seed file that fails or cannot be read, a seed transaction that fails to commit |
| `ConfigurationError` | a URL that does not connect (`CONFIG_006`, the driver's error as its cause), a `max_level` outside 1 to 5 |
| `TypeError` | an argument of the wrong type: a `database` that is neither a URL nor a `Connection`, a `tier_of` argument that is not a change |
| `ValueError` | arguments that cannot run together: `parse_schema` given both a source and `env=` or neither, `diff`'s sides and `env=`, `validate_seeds` levels 4 and 5 without `database=` |

Where names are expected, a bare `str` is one name: `introspect(url,
schemas="app")`, `dependency_order(model, tables="app.item")`. Where a path is
expected, a `str` is the path it spells: `apply_seeds(url, "db/seeds")`, or a
`str` in a list of paths. A bare `str` given to `parse_schema` or as a side of
`diff` is DDL text, as it always is there.

## Where existing code fits

`confiture seed generate` writes a commented-out `INSERT` template for one table.
It is a starting point for a hand-written seed, not a generator.

In printoptim_backend, `scripts/generate_frontend_seed_data.py` and
`scripts/generate_meter_seed_data.py` already draw from `Random(42)` and write
batched `INSERT` files. They are the first consumers to move onto this seam.
