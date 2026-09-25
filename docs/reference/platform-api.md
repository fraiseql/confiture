# Platform API reference

`confiture.platform` is the library surface a tool builds on: a seed generator, a
parity fixture, anything that reads a schema, orders its tables, writes seeds and
checks them. [Building on confiture](../guides/building-on-confiture.md) is the
guide; this page lists every name.

The surface is closed. `tests/contract/test_platform_surface.py` pins each name,
signature and dataclass field by equality, and no signature names a pglast or
psycopg type. Everything below is generated from the package by
`scripts/gen_platform_reference.py`: edit the docstring, not this page.

<!-- BEGIN GENERATED: platform-api -->

Generated from `confiture.platform`; each description is the code's own.

## Reading a schema

### `parse_schema`

```python
def parse_schema(
    source: SchemaSource | None = None,
    *,
    env: str | None = None,
    project_dir: Path | None = None,
) -> SchemaModel
```

The model of the schema *source* declares — or *env*'s build, from *project_dir*.

A `str` is DDL text. A `Path` is a file, or a directory read the way a
bare `include_dirs` entry is — every `.sql` under it, sorted by path. A
sequence of paths is read in its order, a `str` in it being the path it
spells. *env* reads the project's build instead: the files `confiture build
--env <env> --schema-only` selects, in build order. `COPY … FROM stdin`
data is blanked before parsing, so a tree that seeds inline still reads.

**Raises**

- `ValueError`: unless exactly one of *source* and *env* is given.
- `SchemaError`: `DIFFER_400` when PostgreSQL's parser rejects the DDL, naming the file and line; `SCHEMA_201` for a path that does not exist, `SCHEMA_001` for a file that cannot be read as UTF-8 text.

### `introspect`

```python
def introspect(
    database: str | Connection,
    *,
    schemas: Sequence[str] | None = None,
) -> SchemaModel
```

The model of what *database* holds in *schemas* — every user schema when omitted.

Tables, enum types, sequences, routines, views and triggers, read through
`live_catalog`, the one reader of a live catalog; an extension's own objects
are left out, as they are when a tree is compared with a database. A URL is
connected to and closed here; a connection is the caller's, transaction and all.
A bare `str` is one schema name. A schema the database does not have holds
nothing, so it adds nothing: `schemas=["nope"]` is an empty model, not an
error.

**Raises**

- `ConfigurationError`: `CONFIG_006` when the URL does not connect.
- `TypeError`: a *database* that is neither a URL nor a `Connection`.

### `diff`

```python
def diff(
    old: SchemaSource | None,
    new: SchemaSource | None,
    *,
    env: str | None = None,
    project_dir: Path | None = None,
) -> SchemaDiff
```

What changed from the schema *old* declares to the one *new* declares.

Each side is anything `parse_schema` takes: a source, or — given as
`None` — *env*'s build from *project_dir*, so `diff(snapshot, None,
env="local")` is what changed from a snapshot to the current tree.

Every kind `migrate diff` reports, views, routines and triggers included, and
the warnings it reports beside them — two definitions of one object, resolved
the way the build resolves them (`DIFFER_402`).

**Raises**

- `ValueError`: unless exactly one side is `None` when *env* is given, and neither is when it is not.
- `SchemaError`: `DIFFER_400` when PostgreSQL's parser rejects either side, `SCHEMA_201` for a path that does not exist, `SCHEMA_001` for a file that cannot be read as UTF-8 text.

### `SchemaSource`

```python
SchemaSource = str | Path | Sequence[Path | str]
```

### `Connection`

```python
class Connection(Protocol)
```

What confiture calls on a connection a caller hands it; a psycopg 3 connection is one.

A library entry point that takes a connection takes this rather than the
driver's class, so its signature does not make the driver its caller's
dependency. The transaction is the caller's: confiture neither commits nor
rolls back a connection it did not open. `isinstance` answers whether an
object has the four methods, which is what the entry points check.

Nor does confiture change a caller's connection's mode. A call that needs a
transaction refuses a connection in autocommit, and one that needs autocommit
refuses one that is not, each with a `CONFIG_013` naming the call and why
(`require_mode`): switching the mode would change what the caller's
own statements do after the call returns.

#### `Connection.cursor`

```python
def cursor(self) -> typing.Any
```

A cursor on this connection.

#### `Connection.execute`

```python
def execute(self, query: typing.Any, params: typing.Any = None) -> typing.Any
```

Run *query* and return its cursor.

#### `Connection.commit`

```python
def commit(self) -> None
```

Commit the current transaction.

#### `Connection.rollback`

```python
def rollback(self) -> None
```

Roll the current transaction back.

## The model

### `SchemaModel`

```python
class SchemaModel
```

Everything one schema declares, each object under its `ObjectRef`.

A routine's reference is a bucket (see `routine_ref`), so
`routines` maps it to every overload in it, in declaration order.
Frozen through and through: each mapping is a read-only copy of the one it
was built from, so neither a reader nor the builder can change a model after
it is made.

| Field | Type | Default |
|---|---|---|
| `tables` | `Mapping[ObjectRef, Table]` | empty |
| `enum_types` | `Mapping[ObjectRef, EnumType]` | empty |
| `sequences` | `Mapping[ObjectRef, Sequence]` | empty |
| `routines` | `Mapping[ObjectRef, tuple[Routine, ...]]` | empty |
| `views` | `Mapping[ObjectRef, View]` | empty |
| `triggers` | `Mapping[ObjectRef, Trigger]` | empty |

#### `SchemaModel.all_routines`

```python
def all_routines(self) -> list[Routine]
```

Every routine, overloads included, in identity order.

#### `SchemaModel.to_dict`

```python
def to_dict(self) -> dict[str, Any]
```

A JSON-ready rendering, objects in identity order, for goldens and dumps.

#### `SchemaModel.to_json`

```python
def to_json(self) -> str
```

The model's wire: `to_dict`, keys sorted, so one model is one text.

`schema-model.schema.json` publishes its shape. Sorted keys make the bytes
a function of the model alone, not of the order fields are declared in.

#### `SchemaModel.from_json`

```python
def from_json(text: str) -> SchemaModel
```

The model `to_json` wrote *text* from.

Each object's reference is derived from the object, as every reader derives
it — a table's from its schema and name, a routine's from its signature — so
the wire carries no key a reader could disagree with.

### `ObjectRef`

```python
class ObjectRef
```

A **bucket**: what makes two `CREATE` statements *candidates* for one object.

`schema` is folded and defaulted, so an unqualified `CREATE VIEW v` and
`CREATE VIEW public.v` are one object — what
`DEFAULT_SCHEMA` is for. `name` is
folded for the same reason; `display` keeps the spelling a change
prints.

`signature` is the inventory's `signature_bucket`
— the canonical *names* of a routine's input parameter types, without their
own schemas. It is deliberately not the full signature: a dict key cannot
express "a type schema written on one side and left off the other still
matches", so `fn(bigint)` and `fn(int8)` must land in one bucket and
`signatures_match` decides inside it.
Keyed on the full signature, one respelled routine would report as an added
and a dropped function (#275).

| Field | Type | Default |
|---|---|---|
| `kind` | `str` | required |
| `schema` | `str` | required |
| `name` | `str` | required |
| `signature` | `tuple[str, ...] \| None` | required |
| `display` | `str` | required |

### `Table`

```python
class Table
```

A table: its columns, its constraints and its indexes.

| Field | Type | Default |
|---|---|---|
| `name` | `str` | required |
| `schema` | `str \| None` | `None` |
| `columns` | `tuple[Column, ...]` | `()` |
| `constraints` | `tuple[Constraint, ...]` | `()` |
| `indexes` | `tuple[Index, ...]` | `()` |

#### `Table.column`

```python
def column(self, folded: str) -> Column | None
```

The column the parser spells *folded*, or `None`.

#### `Table.constraints_of`

```python
def constraints_of(self, kind: ConstraintKind) -> tuple[Constraint, ...]
```

The table's constraints of one kind, in the order the tree declared them.

### `Column`

```python
class Column
```

A column, whole.

`name` keeps the author's case with quoting stripped, and `folded` is the
parser's spelling; `line` is where the name is written, which is what a
finding points at. `not_null` is what PostgreSQL will record: `NOT NULL`,
a primary key — on the column or at table level — and an identity column all
set it. `default` is the default expression's text, `identity` the kind
of `GENERATED … AS IDENTITY`, `generated` the expression of a
`GENERATED ALWAYS AS (…)` column and `generated_kind` how it is held.

| Field | Type | Default |
|---|---|---|
| `name` | `str` | required |
| `folded` | `str` | required |
| `line` | `int` | required |
| `type_text` | `str \| None` | `None` |
| `type_key` | `str \| None` | `None` |
| `raw_sql_type` | `str \| None` | `None` |
| `not_null` | `bool` | `False` |
| `default` | `str \| None` | `None` |
| `identity` | `IdentityKind \| None` | `None` |
| `generated` | `str \| None` | `None` |
| `generated_kind` | `GeneratedKind \| None` | `None` |
| `primary_key` | `bool` | `False` |

### `Constraint`

```python
class Constraint
```

A table constraint: a primary key, a UNIQUE, a CHECK or a foreign key.

`name` is empty when the schema wrote none — PostgreSQL generates one at
apply time, and nothing here invents it. `columns` are the columns it
covers, whichever of the three places the grammar allows it was written in;
`ref_table` / `ref_columns` / `on_delete` / `on_update` describe a
foreign key, and an empty `ref_columns` means the referenced primary key.
`expression` is a CHECK's condition, rendered.

| Field | Type | Default |
|---|---|---|
| `kind` | `ConstraintKind` | required |
| `name` | `str` | `''` |
| `columns` | `tuple[str, ...]` | `()` |
| `ref_table` | `str \| None` | `None` |
| `ref_columns` | `tuple[str, ...]` | `()` |
| `on_delete` | `str \| None` | `None` |
| `on_update` | `str \| None` | `None` |
| `expression` | `str \| None` | `None` |
| `deferrable` | `Deferral \| None` | `None` |

### `Index`

```python
class Index
```

An index on one table.

`columns` holds each key as written — a column name or a rendered
expression. `method` is the access method; PostgreSQL's grammar fills in
`btree` when the statement writes no `USING`, and so does the catalog.
`backs_constraint` is set on an index that exists only to back a PRIMARY KEY,
UNIQUE or EXCLUDE constraint — PostgreSQL's, never declared by DDL, so it is
never *extra* to it; only the catalog knows it.

| Field | Type | Default |
|---|---|---|
| `name` | `str \| None` | required |
| `table` | `str` | required |
| `columns` | `tuple[str, ...]` | required |
| `unique` | `bool` | `False` |
| `where` | `str \| None` | `None` |
| `method` | `str \| None` | `None` |
| `backs_constraint` | `bool` | `False` |

### `EnumType`

```python
class EnumType
```

`CREATE TYPE … AS ENUM`: its labels, in declaration order.

| Field | Type | Default |
|---|---|---|
| `name` | `str` | required |
| `schema` | `str \| None` | `None` |
| `values` | `tuple[str, ...]` | `()` |

### `Sequence`

```python
class Sequence
```

`CREATE SEQUENCE`, with the options a comparison reads.

| Field | Type | Default |
|---|---|---|
| `name` | `str` | required |
| `schema` | `str \| None` | `None` |
| `start` | `int \| None` | `None` |
| `increment` | `int \| None` | `None` |
| `min_value` | `int \| None` | `None` |
| `max_value` | `int \| None` | `None` |

### `Routine`

```python
class Routine
```

One routine — a function, a procedure or an aggregate — and one overload of it.

`signature` is the input argument types as the reader found them written —
the DDL's own words, or `format_type`'s — and `signature_key` the same
types canonicalised, which is what makes two routines one. `OUT` and
`TABLE` parameters are in neither: PostgreSQL does not resolve a call by them.

`body` is the text between the `AS` quotes, as written, and `None` where
that text is not SQL (`LANGUAGE c` / `internal`: a symbol). `returns` is
the result type as the reader spells it, `None` for a procedure.
`security_definer`, `search_path_pinned` and `volatility` are what
PostgreSQL records — invoker, unpinned and `volatile` when nothing is written.

| Field | Type | Default |
|---|---|---|
| `name` | `str` | required |
| `schema` | `str \| None` | `None` |
| `kind` | `RoutineKind` | `'function'` |
| `signature` | `str` | `''` |
| `signature_key` | `Signature` | `()` |
| `returns` | `str \| None` | `None` |
| `language` | `str \| None` | `None` |
| `body` | `str \| None` | `None` |
| `security_definer` | `bool` | `False` |
| `search_path_pinned` | `bool` | `False` |
| `volatility` | `Volatility` | `'volatile'` |

### `View`

```python
class View
```

A view or a materialized view.

`definition` is the query as the reader holds it: the DDL's `SELECT`
rendered, or `pg_get_viewdef`'s deparse — two spellings of one query, which
is why a definition is compared through one deparser or not at all.
`indexes` are a materialized view's; a view has none.

| Field | Type | Default |
|---|---|---|
| `name` | `str` | required |
| `schema` | `str \| None` | `None` |
| `materialized` | `bool` | `False` |
| `definition` | `str \| None` | `None` |
| `indexes` | `tuple[Index, ...]` | `()` |

### `Trigger`

```python
class Trigger
```

A trigger a user created, named with the table it fires on.

A trigger's name is unique per *table*, not per schema, so its identity is
`(schema, table, name)`: two tables may each carry a `trg_touch`.

| Field | Type | Default |
|---|---|---|
| `name` | `str` | required |
| `table` | `str` | required |
| `schema` | `str \| None` | `None` |

## Ordering

### `dependency_order`

```python
def dependency_order(
    model: SchemaModel,
    *,
    tables: Iterable[ObjectRef | str] | None = None,
) -> list[ObjectRef]
```

*model*'s tables, each after every table it references by foreign key.

Deterministic: among the tables ready at each step, the first by
`(schema, name)`. A table that references itself is ordered like any other.
*tables* orders just those — a reference or a name, resolved as DDL's is — and
reads through the tables they depend on, so a cycle elsewhere does not stop it.
A bare `str` is one name.

**Raises**

- `DependencyCycleError`: tables whose foreign keys form a cycle, named.
- `NotInModelError`: a table in *tables* the model does not hold — a `SchemaError` and a `KeyError`.

### `DependencyCycleError`

```python
class DependencyCycleError(SchemaError)
```

Tables whose foreign keys form a cycle: none of them can be loaded first.

## What a writer may supply

### `writable_columns`

```python
def writable_columns(model: SchemaModel, table: ObjectRef | str) -> list[Column]
```

*table*'s columns a writer supplies, in declaration order.

Every column but the ones PostgreSQL fills: an identity column (either kind), a
generated column, and a `serial` — which the catalog holds as a `nextval`
default. That is the `pk_*` / `id` split: a writer inserts `id` and lets
PostgreSQL generate `pk_language`.

**Raises**

- `NotInModelError`: when *model* holds no such table — a `SchemaError` and a `KeyError`.

### `column_facts`

```python
def column_facts(model: SchemaModel, table: ObjectRef | str, column: str) -> ColumnFacts
```

What a writer supplying *column* of *table* must respect.

*column* is the name as the parser folds it, or as the author wrote it. A
foreign key's target is found the way `resolve` finds a name, so a bare
`REFERENCES parent` names the `other.parent` that `search_path` put
there; a key that names no column references the target's primary key.

**Raises**

- `NotInModelError`: when *model* holds no such table, or the table no such column — a `SchemaError` and a `KeyError`.

### `naming_hints`

```python
def naming_hints(model: SchemaModel, table: ObjectRef | str) -> TableHints
```

The surrogate-key / natural-id convention *table*'s names show.

`confiture introspect`'s own rule, over the model: the first primary-key
column named `pk_*`, and a column named `id`. Heuristic signals, not facts
— both `None` where the table shows neither.

**Raises**

- `NotInModelError`: when *model* holds no such table — a `SchemaError` and a `KeyError`.

### `ColumnFacts`

```python
class ColumnFacts
```

What a writer supplying one column must respect.

`type_key` / `raw_sql_type` / `not_null` / `default` are the column's.
`unique` is true where one PRIMARY KEY, UNIQUE constraint or unique index
covers this column alone — declared on the column, at table level or as an
index. `checks` are the CHECK expressions that name it, `enum_values` the
labels of the enum its type is, `foreign_key` what it references.

| Field | Type | Default |
|---|---|---|
| `name` | `str` | required |
| `type_key` | `str \| None` | required |
| `raw_sql_type` | `str \| None` | required |
| `not_null` | `bool` | required |
| `default` | `str \| None` | required |
| `unique` | `bool` | required |
| `checks` | `tuple[str, ...]` | `()` |
| `enum_values` | `tuple[str, ...] \| None` | `None` |
| `foreign_key` | `ColumnReference \| None` | `None` |

### `ColumnReference`

```python
class ColumnReference
```

What a foreign key column points at: the table, found, and the column in it.

`table` is the table the model holds when it holds it — a bare name found
wherever `search_path` put it — and otherwise the reference as identity
reads it. `column` is the referenced column; `None` where the key names
none and the model does not hold the target's primary key to say which.

| Field | Type | Default |
|---|---|---|
| `table` | `ObjectRef` | required |
| `column` | `str \| None` | required |

### `TableHints`

```python
class TableHints
```

Non-prescriptive naming-convention hints detected in the table.

These are heuristic signals, not authoritative facts. Agents and developers
decide what to do with them.

Attributes:
    surrogate_pk: First primary-key column whose name starts with `pk_`,
        if any.
    natural_id: The column named `id` if present, regardless of type.

| Field | Type | Default |
|---|---|---|
| `surrogate_pk` | `str \| None` | required |
| `natural_id` | `str \| None` | required |

#### `TableHints.of`

```python
def of(primary_key: Iterable[str], columns: Collection[str]) -> TableHints
```

The convention a table's names show: its first `pk_*` key column, a column `id`.

## Seeds

### `write_copy_seed`

```python
def write_copy_seed(
    path: Path | str,
    table: ObjectRef | str,
    columns: Sequence[str],
    rows: Iterable[Mapping[str, object]],
    *,
    model: SchemaModel,
) -> SeedFile
```

Write *rows* of *table* to *path* as one `COPY … FROM stdin` block.

*columns* are written in the order given, each row a mapping of every one of
them to its value; `None` is NULL. A `dict` or `list` is JSON for a
`json`/`jsonb` column, and a `list` an array for an array column;
`bytes` is `bytea`. Nothing is written when anything is refused.

**Raises**

- `SeedError`: a table or column the model does not hold (a table's `NotInModelError` is its cause), a column named twice, a column PostgreSQL fills, a row missing a column or carrying another, a value the column's type cannot take as given, a value holding a NUL, a *path* that cannot be written.

### `write_insert_seed`

```python
def write_insert_seed(
    path: Path | str,
    table: ObjectRef | str,
    columns: Sequence[str],
    rows: Iterable[Mapping[str, object]],
    *,
    model: SchemaModel,
) -> SeedFile
```

Write *rows* of *table* to *path* as one multi-row `INSERT`.

The same rows, values and refusals as `write_copy_seed`; every value a
literal PostgreSQL types by its column. No rows is a file that says so — a
comment naming the table and columns, as the COPY writer's header does —
since an `INSERT` without a row is not SQL.

**Raises**

- `SeedError`: as `write_copy_seed` does.

### `SeedFile`

```python
class SeedFile
```

A seed file written: where, for which table, which columns, how many rows, how.

| Field | Type | Default |
|---|---|---|
| `path` | `Path` | required |
| `table` | `ObjectRef` | required |
| `columns` | `tuple[str, ...]` | required |
| `rows` | `int` | required |
| `format` | `SeedFormat` | required |

### `apply_seeds`

```python
def apply_seeds(
    database: str | Connection,
    seeds: Path | str | Sequence[Path | str],
    *,
    profile: SeedProfile | None = None,
    continue_on_error: bool = False,
) -> ApplyResult
```

Apply seed files in order: one transaction, a savepoint per file.

*seeds* is a directory — every `.sql` under it, recursively, sorted by
path as a build reads a tree, filtered by *profile*'s path globs — or the
files themselves, in the order given; a `str` is the path it spells. A
file is a script as `psql` reads one: statements, and `COPY … FROM
stdin` blocks streamed through the driver's COPY protocol. Every path is
checked before the database is reached, so a misspelt one applies nothing.

The transaction: each file runs in a savepoint of its own
(`SeedExecutor`), so a failed file is undone and nothing before it.
Then the first failure raises, unless *continue_on_error* keeps going and
reports the failed files in the result. For a URL the transaction is this
call's — committed when it returns, rolled back when it raises, so a run is
all or nothing unless *continue_on_error* says otherwise. For a connection it
is the caller's, and nothing is committed or rolled back here: a caller that
wants seeds and its own statements in one transaction opens it, and a
connection in autocommit is refused rather than switched: a savepoint needs a
transaction, and the mode is the caller's. Nothing here changes an object's
owner. The result's `seed_profile` is *profile*'s name when one applied.

**Raises**

- `SeedError`: a seed path that does not exist, before anything is applied; the first file that failed — its SQL, or a file that is not readable UTF-8 text — when *continue_on_error* is off; and, for a URL, a transaction that fails to commit, as a deferred constraint does.
- `ConfigurationError`: `CONFIG_006` when the URL does not connect; `CONFIG_013` for a connection in autocommit, before anything is applied.
- `TypeError`: a *database* that is neither a URL nor a `Connection`.

### `SeedProfile`

```python
class SeedProfile(BaseModel)
```

A named subset of seed files, selected by glob patterns.

Patterns are `include_dirs`' own gitignore globs over each seed file's path
relative to the seeds directory, which is read as a tree: a pattern with no
`/` matches the filename at any depth (`stats_*.sql`), one with a `/` is
anchored at the seeds directory (`stats/`, `core/*.sql`). Selection is
include-then-exclude: an empty `include` starts from all files; `exclude`
then removes matches. Lets CI apply a lean test seed (e.g. excluding large
ETL-statistics partitions) for faster, higher-parallel test databases.

Attributes:
    include: Globs a seed's path must match to be included (empty = all files).
    exclude: Globs over a seed's path that remove an otherwise-included file.
    name: The key it is configured under in `seed.profiles`, filled from
        that key; `None` for a profile built in code without one. What a
        run that applied it records as `ApplyResult.seed_profile`.

### `ApplyResult`

```python
class ApplyResult
```

Result of seed application.

Tracks successful and failed files during sequential execution.

| Field | Type | Default |
|---|---|---|
| `total` | `int` | `0` |
| `succeeded` | `int` | `0` |
| `failed` | `int` | `0` |
| `failed_files` | `list[str]` | empty |
| `seed_profile` | `str \| None` | `None` |

#### `ApplyResult.to_dict`

```python
def to_dict(self) -> dict
```

Convert to dictionary for JSON serialization.

**Returns**

Dictionary with all fields suitable for JSON output.

### `validate_seeds`

```python
def validate_seeds(
    seeds: Path | str,
    *,
    schema_dir: Path | str,
    max_level: int = 3,
    database: str | Connection | None = None,
    prep_seed_schema: str = 'prep_seed',
    catalog_schema: str = 'catalog',
) -> PrepSeedReport
```

Validate seeds written for the prep-seed pattern, levels 1 through *max_level*.

The prep-seed pattern loads UUID-keyed rows into *prep_seed_schema* and
resolves them into BIGINT-keyed rows in *catalog_schema*. Levels 1-3 read
files and need no database; 4 and 5 load the seeds and run the resolvers
against *database*, in a transaction nothing outlives: a URL's connection is
opened, rolled back and closed here, and a caller's connection runs inside a
savepoint rolled back on the way out. Nothing is printed: the report is the
answer, and a file the run could not read is an error rather than a file that
passed.

**Raises**

- `SeedError`: `SEED_001` for *seeds* that is not a directory, or a seed file that cannot be read as UTF-8 text.
- `SchemaError`: `SCHEMA_201` for a *schema_dir* that is not a directory when a level that reads it runs (2 and up), `SCHEMA_001` for a schema file that cannot be read as UTF-8 text.
- `ConfigurationError`: `CONFIG_001` for a *max_level* outside 1-5; `CONFIG_013` for a connection in autocommit at levels 4-5, which need a transaction to roll back.
- `TypeError`: a *database* that is neither a URL nor a `Connection`.
- `ValueError`: *max_level* of 4 or 5 without a *database*.

### `PrepSeedReport`

```python
class PrepSeedReport
```

Report of prep_seed validation results.

Attributes:
    violations: List of violations found
    scanned_files: List of files scanned
    uuid_basis: What decided which columns level 1 checked as UUIDs:
        `"schema"` (the columns it types `uuid`) or `"convention"`
        (`id` and `fk_*_id`); `None` when level 1 did not run
    rows_read: The rows level 1 read, per table as the seed statements name it

| Field | Type | Default |
|---|---|---|
| `violations` | `list[PrepSeedViolation]` | empty |
| `scanned_files` | `list[str]` | empty |
| `uuid_basis` | `str \| None` | `None` |
| `rows_read` | `dict[str, int]` | empty |

#### `PrepSeedReport.add_violation`

```python
def add_violation(self, violation: PrepSeedViolation) -> None
```

Add a violation to the report.

#### `PrepSeedReport.add_file_scanned`

```python
def add_file_scanned(self, file_path: str) -> None
```

Record that a file was scanned.

#### `PrepSeedReport.violations_by_severity`

```python
def violations_by_severity(self) -> dict[ViolationSeverity, list[PrepSeedViolation]]
```

Group violations by severity level.

#### `PrepSeedReport.to_dict`

```python
def to_dict(self) -> dict[str, Any]
```

Convert report to dictionary for serialization.

### `PrepSeedViolation`

```python
class PrepSeedViolation
```

Represents a single prep_seed validation violation.

Attributes:
    pattern: The type of prep_seed issue detected
    severity: Severity level (INFO, WARNING, ERROR, CRITICAL)
    message: Human-readable message describing the violation
    file_path: Path to the file containing the violation
    line_number: Line number where violation occurs
    impact: Optional description of impact if not fixed
    fix_available: Whether automatic fix is available
    suggestion: Optional suggestion for fixing the violation

| Field | Type | Default |
|---|---|---|
| `pattern` | `PrepSeedPattern` | required |
| `severity` | `ViolationSeverity` | required |
| `message` | `str` | required |
| `file_path` | `str` | required |
| `line_number` | `int` | required |
| `impact` | `str \| None` | `None` |
| `fix_available` | `bool` | `False` |
| `suggestion` | `str \| None` | `None` |

#### `PrepSeedViolation.to_dict`

```python
def to_dict(self) -> dict[str, Any]
```

Convert to dictionary for serialization.

### `PrepSeedPattern`

Patterns of prep_seed validation issues.

These patterns represent issues specific to the prep_seed transformation
pattern where UUID FKs in prep_seed schema transform to BIGINT FKs in
final tables via resolution functions.

Members: `SCHEMA_DRIFT_IN_RESOLVER`, `MISSING_FK_TRANSFORMATION`, `MISSING_RESOLVER_FUNCTION`, `MISSING_FK_MAPPING`, `PREP_SEED_TARGET_MISMATCH`, `INVALID_FK_NAMING`, `INVALID_UUID_FORMAT`, `UNION_TYPE_MISMATCH`, `NULL_FK_AFTER_RESOLUTION`, `UNIQUE_CONSTRAINT_VIOLATION`, `MISSING_SELF_REFERENCE_HANDLING`, `UNION_INLINE_COMMENT`, `UNION_UNCAST_NULL`, `RESOLVER_NOT_READ`, `SEED_UNPARSEABLE`, `SEED_NOT_CHECKED`, `SEED_ROW_WIDTH`.

### `ViolationSeverity`

Severity levels for violations.

Members: `INFO`, `WARNING`, `ERROR`, `CRITICAL`.

## What changed

### `SchemaDiff`

```python
class SchemaDiff
```

The difference between two schemas.

| Field | Type | Default |
|---|---|---|
| `changes` | `list[SchemaChange]` | empty |
| `warnings` | `list[BuildWarning]` | empty |

#### `SchemaDiff.has_changes`

```python
def has_changes(self) -> bool
```

Check if there are any changes.

#### `SchemaDiff.wire`

```python
def wire(self) -> list[WireChange]
```

Every change as the wire carries it.

#### `SchemaDiff.summary`

```python
def summary(self) -> dict[str, int]
```

How many changes of each counted kind — `confiture diff`'s `summary`.

### `BuildWarning`

```python
class BuildWarning
```

A build-time diagnostic that reaches the envelope, not only the console.

`confiture build` has diagnostics that do not fail it — a seed file that
failed under `--continue-on-error`, a file pglast could not parse during
the duplicate scan. Printed only, they would be invisible to a consumer doing
the right thing (reading the JSON, not the prose), so each is an entry here
(issue #268), keyed by an error-code registry entry so a consumer matches a
code rather than a sentence.

Attributes:
    code: The registry entry that names the situation.
    severity: That entry's severity — `warning` or `info`. Resolved from
        the registry by `of`, never written twice.
    message: What happened, in one line.
    file: The file the warning is about, named the way a finding names one;
        `None` when the warning is about the build rather than a file.

| Field | Type | Default |
|---|---|---|
| `code` | `str` | required |
| `severity` | `str` | required |
| `message` | `str` | required |
| `file` | `str \| None` | `None` |

#### `BuildWarning.of`

```python
def of(code: str, *, file: str | None = None, fields: object) -> BuildWarning
```

The registry's entry for *code*, filled in.

Severity *and* wording come from the registry, so the sentence a build
prints is the one the published codebook documents — neither can drift
from the other by being written twice.

**Args**

- `code`: A registered error code.
- `file`: The file the warning is about, when it is about one. Also available to the message template as `{file}`.
- `**fields`: The remaining placeholders of the code's message template.

**Returns**

The warning, ready for the envelope.

**Raises**

- `ValueError`: *code* is not registered — a warning no consumer could look up is a bug, not a payload.
- `KeyError`: The template has a placeholder *fields* does not fill.

#### `BuildWarning.to_dict`

```python
def to_dict(self) -> dict[str, Any]
```

Convert to the envelope's `warnings[]` entry.

### `SchemaChange`

```python
SchemaChange = (
    TableAdded
    | TableDropped
    | TableRenamed
    | ColumnAdded
    | ColumnDropped
    | ColumnRenamed
    | ColumnTypeChanged
    | ColumnNullabilityChanged
    | ColumnDefaultChanged
    | IndexAdded
    | IndexDropped
    | ForeignKeyAdded
    | ForeignKeyDropped
    | CheckConstraintAdded
    | CheckConstraintDropped
    | UniqueConstraintAdded
    | UniqueConstraintDropped
    | EnumTypeAdded
    | EnumTypeDropped
    | EnumValuesChanged
    | SequenceAdded
    | SequenceDropped
    | ObjectAdded
    | ObjectDropped
    | ObjectReplaced
)
```

### `tier_of`

```python
def tier_of(change: SchemaChange) -> RiskTier | None
```

The tier *change* carries, or `None` where the change set would classify nothing.

**Raises**

- `TypeError`: for anything that is not one of the `SchemaChange` variants.

### `RiskTier`

What kind of risk a single schema change carries.

Declared least- to most-severe; `severity` is the declaration index.

Members: `additive`, `reversible`, `lock_risky`, `destructive`, `irreversible`.

### `TableAdded`

```python
class TableAdded(_OfTable)
```

A table only the new tree declares.

| Field | Type | Default |
|---|---|---|
| `table` | `Table` | required |

### `TableDropped`

```python
class TableDropped(_OfTable)
```

A table only the old tree declares — carried whole, so a down can recreate it.

| Field | Type | Default |
|---|---|---|
| `table` | `Table` | required |

### `TableRenamed`

```python
class TableRenamed(_Change)
```

One table under two names, in one schema.

Both tables travel so the up and the down each have the spelling and the bare
name they need: `ALTER TABLE a.t RENAME TO a.t2` is a syntax error, since
the target of a `RENAME` is a bare name.

| Field | Type | Default |
|---|---|---|
| `old` | `Table` | required |
| `new` | `Table` | required |

### `ColumnAdded`

```python
class ColumnAdded(_OnTable)
```

A column only the new tree declares, on a table both hold.

`table` is the table's **spelling** — what a finding prints and what
generated DDL alters — never an identity.

| Field | Type | Default |
|---|---|---|
| `table` | `str` | required |
| `column` | `Column` | required |

### `ColumnDropped`

```python
class ColumnDropped(_OnTable)
```

A column only the old tree declares — carried whole, so a down can restore it.

| Field | Type | Default |
|---|---|---|
| `table` | `str` | required |
| `column` | `Column` | required |

### `ColumnRenamed`

```python
class ColumnRenamed(_OnTable)
```

One column under two names, on one table.

| Field | Type | Default |
|---|---|---|
| `table` | `str` | required |
| `old` | `str` | required |
| `new` | `str` | required |

### `ColumnTypeChanged`

```python
class ColumnTypeChanged(_OnTable)
```

A column whose type differs, typmod included — both declarations travel.

| Field | Type | Default |
|---|---|---|
| `table` | `str` | required |
| `old` | `Column` | required |
| `new` | `Column` | required |

### `ColumnNullabilityChanged`

```python
class ColumnNullabilityChanged(_OnTable)
```

A column that became nullable, or stopped being; `nullable` is the new tree's.

| Field | Type | Default |
|---|---|---|
| `table` | `str` | required |
| `column` | `str` | required |
| `nullable` | `bool` | required |

### `ColumnDefaultChanged`

```python
class ColumnDefaultChanged(_OnTable)
```

A column whose default differs; `None` is no default.

| Field | Type | Default |
|---|---|---|
| `table` | `str` | required |
| `column` | `str` | required |
| `old` | `str \| None` | required |
| `new` | `str \| None` | required |

### `IndexAdded`

```python
class IndexAdded(_OnTable)
```

An index only the new tree declares on a table both hold.

| Field | Type | Default |
|---|---|---|
| `table` | `str` | required |
| `index` | `Index` | required |

### `IndexDropped`

```python
class IndexDropped(_OnTable)
```

An index only the old tree declares on a table both hold.

| Field | Type | Default |
|---|---|---|
| `table` | `str` | required |
| `index` | `Index` | required |

### `ForeignKeyAdded`

```python
class ForeignKeyAdded(_OnTable)
```

A foreign key only the new tree declares.

| Field | Type | Default |
|---|---|---|
| `table` | `str` | required |
| `constraint` | `Constraint` | required |

### `ForeignKeyDropped`

```python
class ForeignKeyDropped(_OnTable)
```

A foreign key only the old tree declares.

| Field | Type | Default |
|---|---|---|
| `table` | `str` | required |
| `constraint` | `Constraint` | required |

### `CheckConstraintAdded`

```python
class CheckConstraintAdded(_OnTable)
```

A CHECK only the new tree declares, or one whose predicate changed (after a drop).

| Field | Type | Default |
|---|---|---|
| `table` | `str` | required |
| `constraint` | `Constraint` | required |

### `CheckConstraintDropped`

```python
class CheckConstraintDropped(_OnTable)
```

A CHECK only the old tree declares, or one whose predicate changed (before an add).

| Field | Type | Default |
|---|---|---|
| `table` | `str` | required |
| `constraint` | `Constraint` | required |

### `UniqueConstraintAdded`

```python
class UniqueConstraintAdded(_OnTable)
```

A UNIQUE constraint only the new tree declares.

| Field | Type | Default |
|---|---|---|
| `table` | `str` | required |
| `constraint` | `Constraint` | required |

### `UniqueConstraintDropped`

```python
class UniqueConstraintDropped(_OnTable)
```

A UNIQUE constraint only the old tree declares.

| Field | Type | Default |
|---|---|---|
| `table` | `str` | required |
| `constraint` | `Constraint` | required |

### `EnumTypeAdded`

```python
class EnumTypeAdded(_OfEnum)
```

An enum type only the new tree declares.

| Field | Type | Default |
|---|---|---|
| `enum` | `EnumType` | required |

### `EnumTypeDropped`

```python
class EnumTypeDropped(_OfEnum)
```

An enum type only the old tree declares.

| Field | Type | Default |
|---|---|---|
| `enum` | `EnumType` | required |

### `EnumValuesChanged`

```python
class EnumValuesChanged(_Change)
```

An enum both trees declare with different labels; each list is sorted.

| Field | Type | Default |
|---|---|---|
| `enum` | `str` | required |
| `added` | `tuple[str, ...]` | required |
| `removed` | `tuple[str, ...]` | required |

### `SequenceAdded`

```python
class SequenceAdded(_OfSequence)
```

A sequence only the new tree declares.

| Field | Type | Default |
|---|---|---|
| `sequence` | `Sequence` | required |

### `SequenceDropped`

```python
class SequenceDropped(_OfSequence)
```

A sequence only the old tree declares.

| Field | Type | Default |
|---|---|---|
| `sequence` | `Sequence` | required |

### `ObjectAdded`

```python
class ObjectAdded(_ObjectChange)
```

An object only the new tree defines.

| Field | Type | Default |
|---|---|---|
| `ref` | `ObjectRef` | required |
| `obj` | `DDLObject` | required |

### `ObjectDropped`

```python
class ObjectDropped(_ObjectChange)
```

An object only the old tree defines.

| Field | Type | Default |
|---|---|---|
| `ref` | `ObjectRef` | required |
| `obj` | `DDLObject` | required |

### `ObjectReplaced`

```python
class ObjectReplaced(_ObjectChange)
```

An object both trees define, whose canonical definition differs.

For a view or a routine that is the entire change a migration has to carry,
and it is invisible to a structural comparison because nothing about the
object's shape moved.

| Field | Type | Default |
|---|---|---|
| `ref` | `ObjectRef` | required |
| `old` | `DDLObject` | required |
| `new` | `DDLObject` | required |

### `DDLObject`

```python
class DDLObject
```

One tracked `CREATE`: what it defines, and two renderings of it.

`definition` is what decides whether the object *changed* — existence
clauses neutralised, so a view that gains `OR REPLACE` is the same view.
`create_sql` is what a generated migration carries — the same statement
with the existence clause its kind supports, so re-applying the migration
is not an error. `signature` is the routine's full canonical signature,
schemas included, which is what separates two definitions that share a
bucket.

| Field | Type | Default |
|---|---|---|
| `ref` | `ObjectRef` | required |
| `definition` | `str` | required |
| `create_sql` | `str` | required |
| `signature` | `Signature \| None` | `None` |
| `trigger` | `Trigger \| None` | `None` |

## Errors

### `ConfiturError`

```python
class ConfiturError(Exception)
```

Base exception for all Confiture errors.

All Confiture-specific exceptions inherit from this base class.
This allows catching all Confiture errors with:

    try:
        confiture.build()
    except ConfiturError as e:
        # Handle any Confiture error
        pass

Supports optional error codes for structured error handling:

    try:
        confiture.build()
    except ConfiturError as e:
        if e.error_code == "CONFIG_001":
            # Handle missing configuration
            pass

Attributes:
    error_code: Machine-readable error code (e.g., "CONFIG_001").
               All subclasses provide defaults; callers may override.

    severity: Error severity (INFO, WARNING, ERROR, CRITICAL).

    context: Structured context dict. Universal keys (all optional):
             - "file_path": str — path to the file that caused the error
             - "migration_version": str — version string (e.g., "20260228180602")
             - "database_name": str — target database name
             - "recovery_suggestions": list[str] — manual recovery steps

             Subclasses may add domain-specific keys; see their docstrings.

    resolution_hint: Human-readable suggestion for resolving the error.
                    Example: "Check database permissions for schema 'public'"
                    Rendered by `__str__` so it survives every consumer,
                    including library callers that only ever see the string
                    form of the exception (issue #211).

    message: The base message, without the resolution hint. Renderers and
             keyword classifiers read this; `str(self)` is for humans.

#### `ConfiturError.to_dict`

```python
def to_dict(self) -> dict[str, Any]
```

Get machine-readable representation of the error.

**Returns**

Dict with error_code, severity, message, context, resolution_hint

**Example**

>>> error = ConfiturError("test", error_code="CONFIG_001")
>>> error.to_dict()
{'error_code': 'CONFIG_001', 'severity': 'error', 'message': 'test', ...}

### `SchemaError`

```python
class SchemaError(ConfiturError)
```

Invalid schema DDL or schema build failure.

Raised when:
- SQL syntax error in DDL files
- Missing required schema directories
- Circular dependencies between schema files
- Schema hash computation fails

**Example**

>>> raise SchemaError("Syntax error in 10_tables/users.sql at line 15")

### `NotInModelError`

```python
class NotInModelError(SchemaError, KeyError)
```

A table or column the model does not hold, named as it was asked for.

A `SchemaError`, so `except ConfiturError`
sees it with a code and a hint, and a `KeyError`, because a lookup by name
that finds nothing is one in Python and `except KeyError` is how a caller
says so.

### `SeedError`

```python
class SeedError(ConfiturError)
```

Seed file execution error

Raised when:
- Seed file cannot be loaded
- Seed SQL execution fails
- Seed file contains invalid commands (BEGIN/COMMIT/ROLLBACK)
- Savepoint operations fail

Attributes:
    seed_file: Path to seed file that failed (if applicable)
    sql_error: Original SQL error (if applicable)

### `ConfigurationError`

```python
class ConfigurationError(ConfiturError)
```

Invalid configuration (YAML, environment, database connection).

Raised when:
- Environment YAML file is malformed or missing
- Required configuration fields are missing
- Database connection string is invalid
- Include/exclude directory patterns are invalid

**Example**

>>> raise ConfigurationError("Missing database_url in local.yaml")

<!-- END GENERATED: platform-api -->
