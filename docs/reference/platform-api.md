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
sequence of paths is read in its order. *env* reads the project's build
instead: the files `confiture build --env <env> --schema-only` selects, in
build order. `COPY … FROM stdin` data is blanked before parsing, so a tree
that seeds inline still reads.

**Raises**

- `ValueError`: unless exactly one of *source* and *env* is given.
- `SchemaError`: `DIFFER_400` when PostgreSQL's parser rejects the DDL, `SCHEMA_201` for a path that does not exist.

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

### `diff`

```python
def diff(old: SchemaSource, new: SchemaSource) -> SchemaDiff
```

What changed from the schema *old* declares to the one *new* declares.

Every kind `migrate diff` reports, views, routines and triggers included, and
the warnings it reports beside them — two definitions of one object, resolved
the way the build resolves them (`DIFFER_402`).

**Raises**

- `SchemaError`: `DIFFER_400` when PostgreSQL's parser rejects either side, `SCHEMA_201` for a path that does not exist.

### `SchemaSource`

```python
SchemaSource = str | Path | Sequence[Path]
```

### `Connection`

```python
class Connection(Protocol)
```

What confiture calls on a connection a caller hands it; a psycopg 3 connection is one.

A library entry point that takes a connection takes this rather than the
driver's class, so its signature does not make the driver its caller's
dependency. The transaction is the caller's: confiture neither commits nor
rolls back a connection it did not open.

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
Keying on the full signature reported an added and a dropped function where
one routine had been respelled (CLAUDE.md, #275).

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

**Raises**

- `DependencyCycle`: tables whose foreign keys form a cycle, named.
- `KeyError`: a table in *tables* the model does not hold.

### `DependencyCycle`

```python
class DependencyCycle(SchemaError)
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

- `KeyError`: when *model* holds no such table.

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

- `KeyError`: when *model* holds no such table, or the table no such column.

### `naming_hints`

```python
def naming_hints(model: SchemaModel, table: ObjectRef | str) -> TableHints
```

The surrogate-key / natural-id convention *table*'s names show.

`confiture introspect`'s own rule, over the model: the first primary-key
column named `pk_*`, and a column named `id`. Heuristic signals, not facts
— both `None` where the table shows neither.

**Raises**

- `KeyError`: when *model* holds no such table.

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
    path: Path,
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

- `SeedError`: a table or column the model does not hold, a column PostgreSQL fills, a row missing a column or carrying another, a value the column's type cannot take as given.

### `write_insert_seed`

```python
def write_insert_seed(
    path: Path,
    table: ObjectRef | str,
    columns: Sequence[str],
    rows: Iterable[Mapping[str, object]],
    *,
    model: SchemaModel,
) -> SeedFile
```

Write *rows* of *table* to *path* as one multi-row `INSERT`.

The same rows, values and refusals as `write_copy_seed`; every value a
literal PostgreSQL types by its column.

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
    seeds: Path | Sequence[Path],
    *,
    profile: SeedProfile | None = None,
    continue_on_error: bool = False,
) -> ApplyResult
```

Apply seed files in order: one transaction, a savepoint per file.

*seeds* is a directory — its top-level `.sql` files, sorted, filtered by
*profile*'s filename globs — or the files themselves, in the order given. A
file is a script as `psql` reads one: statements, and `COPY … FROM stdin`
blocks streamed through the driver's COPY protocol.

The transaction: each file runs in a savepoint of its own
(`SeedExecutor`), so a failed file is undone and nothing before it.
Then the first failure raises, unless *continue_on_error* keeps going and
reports the failed files in the result. For a URL the transaction is this
call's — committed when it returns, rolled back when it raises, so a run is
all or nothing unless *continue_on_error* says otherwise. For a connection it
is the caller's, and nothing is committed or rolled back here: a caller that
wants seeds and its own statements in one transaction opens it. Nothing here
changes an object's owner.

**Raises**

- `SeedError`: the first file that failed, when *continue_on_error* is off.

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
    seeds_dir: Path,
    *,
    schema_dir: Path,
    max_level: int = 3,
    database_url: str | None = None,
    prep_seed_schema: str = 'prep_seed',
    catalog_schema: str = 'catalog',
) -> PrepSeedReport
```

Run prep-seed validation levels 1 through *max_level* over *seeds_dir*.

Levels 1-3 read files and need no database; 4 and 5 load the seeds and run
the resolvers against *database_url*, in a transaction they roll back.
Nothing is printed: the report is the answer.

**Raises**

- `ValueError`: *max_level* of 4 or 5 without a *database_url*.

### `PrepSeedReport`

```python
class PrepSeedReport
```

Report of prep_seed validation results.

Attributes:
    violations: List of violations found
    scanned_files: List of files scanned

| Field | Type | Default |
|---|---|---|
| `violations` | `list[PrepSeedViolation]` | empty |
| `scanned_files` | `list[str]` | empty |

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

### `RiskTier`

What kind of risk a single schema change carries.

Declared least- to most-severe; `severity` is the declaration index.

Members: `additive`, `reversible`, `lock_risky`, `destructive`, `irreversible`.

### `TableAdded`

```python
class TableAdded(_Change)
```

A table only the new tree declares.

| Field | Type | Default |
|---|---|---|
| `table` | `Table` | required |

### `TableDropped`

```python
class TableDropped(_Change)
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
class ColumnAdded(_Change)
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
class ColumnDropped(_Change)
```

A column only the old tree declares — carried whole, so a down can restore it.

| Field | Type | Default |
|---|---|---|
| `table` | `str` | required |
| `column` | `Column` | required |

### `ColumnRenamed`

```python
class ColumnRenamed(_Change)
```

One column under two names, on one table.

| Field | Type | Default |
|---|---|---|
| `table` | `str` | required |
| `old` | `str` | required |
| `new` | `str` | required |

### `ColumnTypeChanged`

```python
class ColumnTypeChanged(_Change)
```

A column whose type differs, typmod included — both declarations travel.

| Field | Type | Default |
|---|---|---|
| `table` | `str` | required |
| `old` | `Column` | required |
| `new` | `Column` | required |

### `ColumnNullabilityChanged`

```python
class ColumnNullabilityChanged(_Change)
```

A column that became nullable, or stopped being; `nullable` is the new tree's.

| Field | Type | Default |
|---|---|---|
| `table` | `str` | required |
| `column` | `str` | required |
| `nullable` | `bool` | required |

### `ColumnDefaultChanged`

```python
class ColumnDefaultChanged(_Change)
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
class IndexAdded(_Change)
```

An index only the new tree declares on a table both hold.

| Field | Type | Default |
|---|---|---|
| `table` | `str` | required |
| `index` | `Index` | required |

### `IndexDropped`

```python
class IndexDropped(_Change)
```

An index only the old tree declares on a table both hold.

| Field | Type | Default |
|---|---|---|
| `table` | `str` | required |
| `index` | `Index` | required |

### `ForeignKeyAdded`

```python
class ForeignKeyAdded(_Change)
```

A foreign key only the new tree declares.

| Field | Type | Default |
|---|---|---|
| `table` | `str` | required |
| `constraint` | `Constraint` | required |

### `ForeignKeyDropped`

```python
class ForeignKeyDropped(_Change)
```

A foreign key only the old tree declares.

| Field | Type | Default |
|---|---|---|
| `table` | `str` | required |
| `constraint` | `Constraint` | required |

### `CheckConstraintAdded`

```python
class CheckConstraintAdded(_Change)
```

A CHECK only the new tree declares, or one whose predicate changed (after a drop).

| Field | Type | Default |
|---|---|---|
| `table` | `str` | required |
| `constraint` | `Constraint` | required |

### `CheckConstraintDropped`

```python
class CheckConstraintDropped(_Change)
```

A CHECK only the old tree declares, or one whose predicate changed (before an add).

| Field | Type | Default |
|---|---|---|
| `table` | `str` | required |
| `constraint` | `Constraint` | required |

### `UniqueConstraintAdded`

```python
class UniqueConstraintAdded(_Change)
```

A UNIQUE constraint only the new tree declares.

| Field | Type | Default |
|---|---|---|
| `table` | `str` | required |
| `constraint` | `Constraint` | required |

### `UniqueConstraintDropped`

```python
class UniqueConstraintDropped(_Change)
```

A UNIQUE constraint only the old tree declares.

| Field | Type | Default |
|---|---|---|
| `table` | `str` | required |
| `constraint` | `Constraint` | required |

### `EnumTypeAdded`

```python
class EnumTypeAdded(_Change)
```

An enum type only the new tree declares.

| Field | Type | Default |
|---|---|---|
| `enum` | `EnumType` | required |

### `EnumTypeDropped`

```python
class EnumTypeDropped(_Change)
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
class SequenceAdded(_Change)
```

A sequence only the new tree declares.

| Field | Type | Default |
|---|---|---|
| `sequence` | `Sequence` | required |

### `SequenceDropped`

```python
class SequenceDropped(_Change)
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

## Errors

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

<!-- END GENERATED: platform-api -->
