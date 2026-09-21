"""The one reader of a live database's schema: ``pg_catalog`` in, the schema model out.

``read(conn, schemas=…)`` answers in the types ``core/schema_model.py`` defines — the
same ones the lint inventory builds from DDL — so a table read live and the same
table read from its DDL can be compared as values, not reconciled by whoever
compares them. Before it, thirty-eight modules issued catalog SQL of their own and
the live side of ``confiture drift`` was a dict keyed by strings.

Where PostgreSQL answers in text, the text is read by the **same** code that reads
DDL: ``pg_get_constraintdef`` through ``ddl_walk.read_constraint``,
``pg_get_indexdef`` through ``ddl_walk.read_index``, ``format_type`` through
``ddl_walk.written_type``. One reader on both sides is what makes a parity test
meaningful rather than two readers agreeing by luck.

An index that exists only to back a PRIMARY KEY, UNIQUE or EXCLUDE constraint is read
and flagged (``Index.backs_constraint``): the DDL declares the constraint, never the
index, so it is never *extra* — but it still answers to its name.

Deliberately not read, each for a stated reason:

- objects an **extension** owns (``pg_depend.deptype = 'e'``) — they are the
  extension's, not the tree's;
- a sequence a **column** owns (``deptype`` ``a`` for ``serial``, ``i`` for an
  identity) — it is part of that column, and the tree never wrote it;
- a ``NOT NULL`` constraint row (PostgreSQL 18's ``contype = 'n'``) — it is
  ``attnotnull``, read on the column.

That list is :func:`read`'s, the model a tree is compared with. The listings
below it answer narrower questions — which relations, which schemas, every index
a table carries — and each docstring says what it keeps. Views, triggers and
routines are not in the model yet, and they come back as catalog rows
(:class:`ViewRow`, :class:`TriggerRow`, :class:`RoutineRow`) rather than as a
second model of each: the model's names are reserved for the day the DDL side
reads them too. A row says whether an extension owns the object instead of
leaving it out, because the callers disagree on purpose — a drift check asks what
the *tree* holds, an introspector what the *database* holds.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

import pglast
from pglast.stream import RawStream

from confiture.core.ddl_walk import read_constraint, read_index, render_default, written_type
from confiture.core.ddl_walk import type_name as ddl_type_name
from confiture.core.schema_model import (
    Column,
    Constraint,
    EnumType,
    GeneratedKind,
    IdentityKind,
    Index,
    ObjectRef,
    SchemaModel,
    Table,
    qualified_name,
    ref_for,
)
from confiture.core.schema_model import Sequence as SequenceModel
from confiture.core.type_lattice import canonical_type

if TYPE_CHECKING:
    import psycopg

#: An object an extension created.
_EXTENSION_OWNED = """
    EXISTS (
        SELECT 1 FROM pg_depend d
        WHERE d.classid = '{catalog}'::regclass AND d.objid = {oid} AND d.deptype = 'e'
    )
"""

#: Not an object an extension created.
_NOT_EXTENSION_OWNED = "NOT " + _EXTENSION_OWNED

#: The ``relkind`` letters of a table, partitioned or not.
TABLE_KINDS = ("r", "p")

#: What ``information_schema.tables`` lists, which is what "a table exists" has
#: meant to its callers: a table, a partitioned table, a view, a foreign table.
TABLE_LIKE = ("r", "p", "v", "f")

_RELATIONS = f"""
SELECT c.oid, n.nspname, c.relname
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind = ANY(%s)
  AND n.nspname = ANY(%s)
  AND {_NOT_EXTENSION_OWNED.format(catalog="pg_class", oid="c.oid")}
ORDER BY n.nspname, c.relname
"""

_COLUMNS = """
SELECT
    a.attrelid,
    a.attname,
    format_type(a.atttypid, a.atttypmod),
    a.attnotnull,
    pg_get_expr(d.adbin, d.adrelid),
    a.attidentity,
    a.attgenerated
FROM pg_attribute a
LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
WHERE a.attrelid = ANY(%s) AND a.attnum > 0 AND NOT a.attisdropped
ORDER BY a.attrelid, a.attnum
"""

_CONSTRAINTS = """
SELECT conrelid, conname, pg_get_constraintdef(oid)
FROM pg_constraint
WHERE conrelid = ANY(%s) AND contype IN ('p', 'u', 'c', 'f')
ORDER BY conrelid, conname
"""

_INDEXES = """
SELECT
    i.indrelid,
    pg_get_indexdef(i.indexrelid),
    EXISTS (
        SELECT 1 FROM pg_constraint k
        WHERE k.conindid = i.indexrelid AND k.conrelid = i.indrelid
          AND k.contype IN ('p', 'u', 'x')
    )
FROM pg_index i
JOIN pg_class ic ON ic.oid = i.indexrelid
WHERE i.indrelid = ANY(%s)
ORDER BY i.indrelid, ic.relname
"""

_ENUMS = f"""
SELECT n.nspname, t.typname, array_agg(e.enumlabel ORDER BY e.enumsortorder)
FROM pg_type t
JOIN pg_namespace n ON n.oid = t.typnamespace
JOIN pg_enum e ON e.enumtypid = t.oid
WHERE n.nspname = ANY(%s)
  AND {_NOT_EXTENSION_OWNED.format(catalog="pg_type", oid="t.oid")}
GROUP BY n.nspname, t.typname
ORDER BY n.nspname, t.typname
"""

_SEQUENCES = f"""
SELECT n.nspname, c.relname, s.seqstart, s.seqincrement, s.seqmin, s.seqmax
FROM pg_sequence s
JOIN pg_class c ON c.oid = s.seqrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = ANY(%s)
  AND {_NOT_EXTENSION_OWNED.format(catalog="pg_class", oid="c.oid")}
  AND NOT EXISTS (
      SELECT 1 FROM pg_depend d
      WHERE d.classid = 'pg_class'::regclass AND d.objid = c.oid AND d.deptype IN ('a', 'i')
  )
ORDER BY n.nspname, c.relname
"""

#: ``attidentity`` / ``attgenerated`` codes, as the catalog stores them.
_IDENTITY: dict[str, IdentityKind] = {"a": "always", "d": "by default"}
_GENERATED: dict[str, GeneratedKind] = {"s": "stored", "v": "virtual"}


def _quoted(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _expression(text: str) -> Any:
    """A catalog expression's parse node — so it is rendered the way DDL is."""
    select: Any = pglast.parse_sql(f"SELECT {text}")[0].stmt
    return select.targetList[0].val


def _type_nodes(types: list[str]) -> list[Any]:
    """``format_type`` output, read back through the parser that reads DDL."""
    if not types:
        return []
    columns = ", ".join(f"c{i} {spelled}" for i, spelled in enumerate(types))
    create: Any = pglast.parse_sql(f"CREATE TABLE t ({columns})")[0].stmt
    return [elt.typeName for elt in create.tableElts]


def _column(row: tuple[Any, ...], type_node: Any) -> Column:
    _relid, name, spelled, not_null, stored, identity, generated = row
    generated_kind = _GENERATED.get(generated or "")
    return Column(
        name=name,
        folded=name,
        line=0,
        type_text=spelled,
        type_key=canonical_type(ddl_type_name(type_node)),
        raw_sql_type=written_type(type_node),
        not_null=bool(not_null),
        default=render_default(_expression(stored)) if stored and not generated_kind else None,
        identity=_IDENTITY.get(identity or ""),
        generated=RawStream()(_expression(stored)) if stored and generated_kind else None,
        generated_kind=generated_kind,
    )


def _constraint(name: str, definition: str) -> Constraint | None:
    """``pg_get_constraintdef``, read by the one constraint reader."""
    alter: Any = pglast.parse_sql(f"ALTER TABLE t ADD CONSTRAINT {_quoted(name)} {definition}")[
        0
    ].stmt
    read = read_constraint(alter.cmds[0].def_)
    return read if isinstance(read, Constraint) else None


def _with_primary_keys(columns: list[Column], constraints: list[Constraint]) -> tuple[Column, ...]:
    covered = {name for c in constraints if c.kind == "primary_key" for name in c.columns}
    return tuple(replace(c, primary_key=True) if c.folded in covered else c for c in columns)


def _tables(
    conn: psycopg.Connection, schemas: list[str], kinds: Sequence[str]
) -> dict[ObjectRef, Table]:
    relations = conn.execute(_RELATIONS, (list(kinds), schemas)).fetchall()
    oids = [oid for oid, _schema, _name in relations]
    rows: dict[int, list[tuple[Any, ...]]] = defaultdict(list)
    for row in conn.execute(_COLUMNS, (oids,)).fetchall():
        rows[row[0]].append(row)
    constraints: dict[int, list[Constraint]] = defaultdict(list)
    for relid, name, definition in conn.execute(_CONSTRAINTS, (oids,)).fetchall():
        read = _constraint(name, definition)
        if read is not None:
            constraints[relid].append(read)
    indexes: dict[int, list[tuple[Any, bool]]] = defaultdict(list)
    for relid, definition, backs in conn.execute(_INDEXES, (oids,)).fetchall():
        indexes[relid].append((pglast.parse_sql(definition)[0].stmt, bool(backs)))

    tables: dict[ObjectRef, Table] = {}
    for oid, schema, name in relations:
        qualified = qualified_name(schema, name)
        columns = [
            _column(row, node)
            for row, node in zip(rows[oid], _type_nodes([r[2] for r in rows[oid]]), strict=True)
        ]
        index_models: list[Index] = [
            replace(read_index(stmt, table=qualified), backs_constraint=backs)
            for stmt, backs in indexes[oid]
        ]
        tables[ref_for("table", schema, name)] = Table(
            name=name,
            schema=schema,
            columns=_with_primary_keys(columns, constraints[oid]),
            constraints=tuple(constraints[oid]),
            indexes=tuple(index_models),
        )
    return tables


def read(
    conn: psycopg.Connection, *, schemas: Sequence[str], kinds: Sequence[str] = TABLE_KINDS
) -> SchemaModel:
    """The schema the database holds in *schemas*, in the model DDL is read into.

    *kinds* are the ``relkind`` letters read as tables: a table and a partitioned
    table by default, which is what a tree declares with ``CREATE TABLE``. A
    caller that has always meant something else by "a table" says so —
    ``introspect`` reads ``('r',)``, the plugin's snapshot :data:`TABLE_LIKE`.
    """
    wanted = list(schemas)
    enum_types = {
        ref_for("type", schema, name): EnumType(name=name, schema=schema, values=tuple(labels))
        for schema, name, labels in conn.execute(_ENUMS, (wanted,)).fetchall()
    }
    sequences = {
        ref_for("sequence", schema, name): SequenceModel(
            name=name,
            schema=schema,
            start=start,
            increment=increment,
            min_value=minimum,
            max_value=maximum,
        )
        for schema, name, start, increment, minimum, maximum in conn.execute(
            _SEQUENCES, (wanted,)
        ).fetchall()
    }
    return SchemaModel(
        tables=_tables(conn, wanted, kinds), enum_types=enum_types, sequences=sequences
    )


# ---------------------------------------------------------------------------
# Probes: one fact about one object, for a caller that needs no whole model
# ---------------------------------------------------------------------------

_RELATION_EXISTS = f"""
SELECT EXISTS (
    SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = %s AND c.relname = %s AND c.relkind = ANY(%s)
      AND {_NOT_EXTENSION_OWNED.format(catalog="pg_class", oid="c.oid")}
)
"""

_SCHEMA_EXISTS = "SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = %s)"

_COLUMNS_OF = """
SELECT a.attname, format_type(a.atttypid, a.atttypmod), a.attnotnull,
       pg_get_expr(d.adbin, d.adrelid), a.attidentity, a.attgenerated
FROM pg_attribute a
JOIN pg_class c ON c.oid = a.attrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
WHERE n.nspname = %s AND c.relname = %s AND a.attnum > 0 AND NOT a.attisdropped
ORDER BY a.attnum
"""

_CONSTRAINT_EXISTS = """
SELECT EXISTS (
    SELECT 1 FROM pg_constraint k
    JOIN pg_class c ON c.oid = k.conrelid
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = %s AND c.relname = %s AND k.conname = %s
      AND (%s::text IS NULL OR k.contype = %s::"char")
)
"""

_INDEX_EXISTS = """
SELECT EXISTS (
    SELECT 1 FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    JOIN pg_index i ON i.indexrelid = c.oid
    JOIN pg_class t ON t.oid = i.indrelid
    WHERE n.nspname = %s AND c.relname = %s AND (%s::text IS NULL OR t.relname = %s::text)
)
"""

_CONSTRAINTS_OF = """
SELECT k.conname, pg_get_constraintdef(k.oid)
FROM pg_constraint k
JOIN pg_class c ON c.oid = k.conrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = %s AND c.relname = %s AND k.contype IN ('p', 'u', 'c', 'f')
ORDER BY k.conname
"""

#: Every relation a column can belong to: tables, views, matviews, foreign tables.
_COLUMN_TYPES = """
SELECT n.nspname, c.relname, a.attname, format_type(a.atttypid, a.atttypmod)
FROM pg_attribute a
JOIN pg_class c ON c.oid = a.attrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE a.attnum > 0
  AND NOT a.attisdropped
  AND c.relkind IN ('r', 'p', 'm', 'v', 'f')
  AND n.nspname NOT IN ('pg_catalog', 'information_schema')
  AND n.nspname NOT LIKE 'pg_toast%'
"""

#: ``pg_constraint.contype`` by the model's constraint kind.
_CONTYPE = {"primary_key": "p", "unique": "u", "check": "c", "foreign_key": "f"}


def _scalar(conn: psycopg.Connection, sql: str, params: tuple[Any, ...]) -> Any:
    with conn.cursor() as cursor:
        cursor.execute(sql, params)
        row = cursor.fetchone()
    return row[0] if row else None


def relation_exists(
    conn: psycopg.Connection, schema: str, name: str, kinds: Sequence[str] = TABLE_KINDS
) -> bool:
    """Whether *schema.name* exists as one of the ``relkind`` letters *kinds*."""
    return bool(_scalar(conn, _RELATION_EXISTS, (schema, name, list(kinds))))


def schema_exists(conn: psycopg.Connection, schema: str) -> bool:
    return bool(_scalar(conn, _SCHEMA_EXISTS, (schema,)))


def constraint_exists(
    conn: psycopg.Connection, schema: str, table: str, name: str, kind: str | None = None
) -> bool:
    """Whether *table* carries a constraint called *name*, of the model *kind* if given."""
    contype = _CONTYPE[kind] if kind is not None else None
    return bool(_scalar(conn, _CONSTRAINT_EXISTS, (schema, table, name, contype, contype)))


def index_exists(
    conn: psycopg.Connection, schema: str, name: str, table: str | None = None
) -> bool:
    """Whether an index called *name* exists in *schema*, on *table* if given."""
    return bool(_scalar(conn, _INDEX_EXISTS, (schema, name, table, table)))


def constraints(conn: psycopg.Connection, schema: str, table: str) -> tuple[Constraint, ...]:
    """One table's constraints, read the way :func:`read` reads them."""
    with conn.cursor() as cursor:
        cursor.execute(_CONSTRAINTS_OF, (schema, table))
        rows = cursor.fetchall()
    read_back = (_constraint(name, definition) for name, definition in rows)
    return tuple(c for c in read_back if c is not None)


def columns(conn: psycopg.Connection, schema: str, table: str) -> tuple[Column, ...]:
    """The columns of one relation, in order, read the way :func:`read` reads them."""
    with conn.cursor() as cursor:
        cursor.execute(_COLUMNS_OF, (schema, table))
        rows = cursor.fetchall()
    nodes = _type_nodes([row[1] for row in rows])
    return tuple(_column((None, *row), node) for row, node in zip(rows, nodes, strict=True))


def column(conn: psycopg.Connection, schema: str, table: str, name: str) -> Column | None:
    return next((c for c in columns(conn, schema, table) if c.folded == name), None)


def column_types(conn: psycopg.Connection) -> dict[str, str]:
    """``schema.table.column`` (case-folded) → ``format_type``, for every user relation."""
    with conn.cursor() as cursor:
        cursor.execute(_COLUMN_TYPES)
        rows = cursor.fetchall()
    return {f"{s}.{t}.{c}".lower(): spelled for s, t, c, spelled in rows}


def relations(
    conn: psycopg.Connection, schemas: Sequence[str], kinds: Sequence[str] = TABLE_KINDS
) -> list[tuple[str, str]]:
    """``(schema, name)`` of every relation of the ``relkind`` letters *kinds* in *schemas*.

    The relations :func:`read` would read, named and nothing more — for a caller
    that counts or lists them and would otherwise pay for every column's parse.
    """
    rows = conn.execute(_RELATIONS, (list(kinds), list(schemas))).fetchall()
    return [(schema, name) for _oid, schema, name in rows]


#: Every schema the current role can use: the rule ``information_schema.schemata``
#: applies, so a schema the role could not drop or read is not listed.
_SCHEMAS = """
SELECT n.nspname
FROM pg_namespace n
WHERE pg_has_role(n.nspowner, 'USAGE') OR has_schema_privilege(n.oid, 'CREATE, USAGE')
ORDER BY n.nspname
"""

#: PostgreSQL's own namespaces; every session's temporary ones are named by prefix.
_SYSTEM_SCHEMAS = frozenset({"pg_catalog", "information_schema", "pg_toast"})
_SESSION_SCHEMA_PREFIXES = ("pg_temp_", "pg_toast_temp_")


def schemas(conn: psycopg.Connection) -> list[str]:
    """Every schema the current role can use, PostgreSQL's own included, by name."""
    return [row[0] for row in conn.execute(_SCHEMAS).fetchall()]


def user_schemas(conn: psycopg.Connection) -> list[str]:
    """The schemas of :func:`schemas` that PostgreSQL did not make, by name."""
    return [
        name
        for name in schemas(conn)
        if name not in _SYSTEM_SCHEMAS and not name.startswith(_SESSION_SCHEMA_PREFIXES)
    ]


#: Every index on a table, a partitioned table or a materialized view — the ones
#: backing a constraint included, which :func:`read` leaves out. This is the set
#: ``pg_indexes`` lists.
_ALL_INDEXES = """
SELECT n.nspname, t.relname, pg_get_indexdef(i.indexrelid)
FROM pg_index i
JOIN pg_class ic ON ic.oid = i.indexrelid
JOIN pg_class t ON t.oid = i.indrelid
JOIN pg_namespace n ON n.oid = t.relnamespace
WHERE n.nspname = ANY(%s)
  AND t.relkind IN ('r', 'p', 'm')
  AND ic.relkind IN ('i', 'I')
ORDER BY n.nspname, t.relname, ic.relname
"""


def indexes(conn: psycopg.Connection, schemas: Sequence[str]) -> dict[ObjectRef, tuple[Index, ...]]:
    """Every index in *schemas*, by the table it is on, a constraint's own included.

    Read by the one index reader :func:`read` uses; each index's ``table`` is the
    relation's ``schema.name``.
    """
    found: dict[ObjectRef, list[Index]] = defaultdict(list)
    for schema, table, definition in conn.execute(_ALL_INDEXES, (list(schemas),)).fetchall():
        stmt = pglast.parse_sql(definition)[0].stmt
        found[ref_for("table", schema, table)].append(
            read_index(stmt, table=qualified_name(schema, table))
        )
    return {ref: tuple(found_on) for ref, found_on in found.items()}


# ---------------------------------------------------------------------------
# Views, triggers and routines: catalog rows, not yet the model's
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ViewRow:
    """A view (``relkind`` ``v``) or a materialized view (``m``).

    ``definition`` is ``pg_get_viewdef(oid, true)`` — PostgreSQL's deparse, so two
    databases compared through it pass through one deparser — when it was asked
    for, and ``None`` otherwise.
    """

    schema: str
    name: str
    relkind: str
    definition: str | None
    extension_owned: bool


@dataclass(frozen=True)
class TriggerRow:
    """A trigger a user created, named with the table it fires on."""

    schema: str
    table: str
    name: str


@dataclass(frozen=True)
class RoutineRow:
    """A ``pg_proc`` row, the catalog's letters kept as the catalog writes them.

    ``kind`` is ``prokind`` (``f`` function, ``p`` procedure, ``a`` aggregate,
    ``w`` window) and ``volatility`` ``provolatile``. ``arg_types`` spells every
    argument, ``OUT`` and ``TABLE`` ones included, in order, and ``arg_names`` /
    ``arg_modes`` run alongside it — empty when the catalog stores none, which for
    ``arg_modes`` means every argument is ``IN``. ``input_types`` are the
    arguments that decide which overload a call reaches, and
    ``identity_arguments`` is ``pg_get_function_identity_arguments`` — the text
    an ``ALTER FUNCTION name(…)`` names the routine by. ``result`` is
    ``pg_get_function_result``: ``None`` for a procedure.
    """

    oid: int
    schema: str
    name: str
    kind: str
    volatility: str
    language: str
    result: str | None
    returns_set: bool
    source: str | None
    cost: float
    arg_names: tuple[str, ...]
    arg_modes: tuple[str, ...]
    arg_types: tuple[str, ...]
    input_types: tuple[str, ...]
    identity_arguments: str
    comment: str | None
    security_definer: bool
    config: tuple[str, ...]
    extension_owned: bool

    @property
    def search_path_pinned(self) -> bool:
        """Whether ``proconfig`` holds a ``search_path=…`` entry.

        ``SET search_path = value`` and ``SET search_path FROM CURRENT`` both
        write one; ``RESET`` and ``SET DEFAULT`` do not — so the prefix is the
        test, matching the static reading of a ``CREATE FUNCTION``.
        """
        return any(entry.startswith("search_path=") for entry in self.config)


#: ``pg_get_viewdef`` runs only when asked for: a deparse per view is the
#: expensive half of the query, and an existence check does not need it.
_VIEWS = f"""
SELECT n.nspname,
       c.relname,
       c.relkind::text,
       CASE WHEN %s THEN pg_get_viewdef(c.oid, true) END,
       {_EXTENSION_OWNED.format(catalog="pg_class", oid="c.oid")}
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind IN ('v', 'm')
  AND n.nspname = ANY(%s)
ORDER BY n.nspname, c.relname
"""

# `NOT tgisinternal` is load-bearing: a FOREIGN KEY creates internal triggers on
# both tables, and reporting those would put two items on every FK in the schema.
_TRIGGERS = """
SELECT n.nspname, c.relname, t.tgname
FROM pg_trigger t
JOIN pg_class c ON c.oid = t.tgrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE NOT t.tgisinternal
  AND n.nspname = ANY(%s)
ORDER BY n.nspname, c.relname, t.tgname
"""

# The argument types are spelled inside the one query, in order: a round trip
# per parameter was what the introspector used to pay. `input_types` come from
# `proargtypes` — *not* `pg_get_function_identity_arguments`, which on
# PostgreSQL 18 returns `a integer, OUT b integer` for a routine with an OUT
# parameter, names and OUT parameters included.
_ROUTINES = f"""
SELECT p.oid,
       n.nspname,
       p.proname,
       p.prokind::text,
       p.provolatile::text,
       l.lanname,
       pg_get_function_result(p.oid),
       p.proretset,
       p.prosrc,
       p.procost,
       p.proargnames,
       p.proargmodes::text[],
       ARRAY(
           SELECT format_type(a.t, NULL)
           FROM unnest(COALESCE(p.proallargtypes::oid[], p.proargtypes::oid[]))
                WITH ORDINALITY AS a(t, ord)
           ORDER BY a.ord
       ),
       ARRAY(
           SELECT format_type(a.t, NULL)
           FROM unnest(p.proargtypes::oid[]) WITH ORDINALITY AS a(t, ord)
           ORDER BY a.ord
       ),
       pg_get_function_identity_arguments(p.oid),
       d.description,
       p.prosecdef,
       p.proconfig,
       {_EXTENSION_OWNED.format(catalog="pg_proc", oid="p.oid")}
FROM pg_proc p
JOIN pg_namespace n ON n.oid = p.pronamespace
JOIN pg_language l ON l.oid = p.prolang
LEFT JOIN pg_description d ON d.objoid = p.oid AND d.classoid = 'pg_proc'::regclass
WHERE n.nspname = ANY(%s)
  AND p.prokind = ANY(%s)
  {{filters}}
ORDER BY n.nspname, p.proname, p.oid
"""

#: A routine that is not a trigger function, by the result it declares.
_NOT_A_TRIGGER = "AND pg_get_function_result(p.oid) IS DISTINCT FROM 'trigger'"


def views(
    conn: psycopg.Connection, schemas: Sequence[str], *, definitions: bool = False
) -> list[ViewRow]:
    """Every view and materialized view in *schemas*, with its definition if asked."""
    rows = conn.execute(_VIEWS, (definitions, list(schemas))).fetchall()
    return [ViewRow(*row) for row in rows]


def triggers(conn: psycopg.Connection, schemas: Sequence[str]) -> list[TriggerRow]:
    """Every trigger a user created on a relation in *schemas*."""
    return [TriggerRow(*row) for row in conn.execute(_TRIGGERS, (list(schemas),)).fetchall()]


def routines(
    conn: psycopg.Connection,
    schemas: Sequence[str],
    *,
    kinds: Sequence[str] = ("f", "p"),
    include_triggers: bool = True,
    name_pattern: str | None = None,
    exact_name: bool = False,
) -> list[RoutineRow]:
    """Every routine of the ``prokind`` letters *kinds* in *schemas*.

    *include_triggers* ``False`` leaves out a function that ``RETURNS trigger``;
    *name_pattern* keeps the names it matches — ``LIKE`` it, or equal to it when
    *exact_name*. Ordered by schema, name, then ``oid``, so overloads keep the
    order they were created in.
    """
    filters = [] if include_triggers else [_NOT_A_TRIGGER]
    params: list[Any] = [list(schemas), list(kinds)]
    if name_pattern is not None:
        filters.append("AND p.proname = %s" if exact_name else "AND p.proname LIKE %s")
        params.append(name_pattern)
    sql = _ROUTINES.format(filters="\n  ".join(filters))
    return [
        RoutineRow(
            oid=oid,
            schema=schema,
            name=name,
            kind=kind,
            volatility=volatility,
            language=language,
            result=result,
            returns_set=bool(returns_set),
            source=source,
            cost=float(cost),
            arg_names=tuple(arg_names or ()),
            arg_modes=tuple(arg_modes or ()),
            arg_types=tuple(arg_types or ()),
            input_types=tuple(input_types or ()),
            identity_arguments=identity_arguments or "",
            comment=comment,
            security_definer=bool(security_definer),
            config=tuple(config or ()),
            extension_owned=bool(extension_owned),
        )
        for (
            oid,
            schema,
            name,
            kind,
            volatility,
            language,
            result,
            returns_set,
            source,
            cost,
            arg_names,
            arg_modes,
            arg_types,
            input_types,
            identity_arguments,
            comment,
            security_definer,
            config,
            extension_owned,
        ) in conn.execute(sql, tuple(params)).fetchall()
    ]


#: One statement, both kinds, each row tagged with which catalogue answered.
_EXISTING = """
SELECT 'relation' AS kind, name
  FROM unnest(%(relations)s::text[]) AS name
 WHERE to_regclass(name) IS NOT NULL
UNION ALL
SELECT 'routine' AS kind, n.nspname || '.' || p.proname
  FROM pg_proc p
  JOIN pg_namespace n ON n.oid = p.pronamespace
 WHERE n.nspname || '.' || p.proname = ANY(%(routines)s::text[])
"""


def existing_names(
    conn: psycopg.Connection, *, relations: Iterable[str], routines: Iterable[str]
) -> tuple[frozenset[str], frozenset[str]]:
    """Which of these ``schema.name`` spellings the database holds, in one round trip.

    A relation of any kind, as ``to_regclass`` resolves the text; a routine of any
    kind and any signature. An extension's own objects count: the question is
    whether a name resolves, not whether a tree declares it.
    """
    rows = conn.execute(
        _EXISTING, {"relations": sorted(relations), "routines": sorted(routines)}
    ).fetchall()
    return (
        frozenset(name for kind, name in rows if kind == "relation"),
        frozenset(name for kind, name in rows if kind == "routine"),
    )
