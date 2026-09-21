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

Deliberately not read, each for a stated reason:

- objects an **extension** owns (``pg_depend.deptype = 'e'``) — they are the
  extension's, not the tree's;
- an index that exists only to back a PRIMARY KEY, UNIQUE or EXCLUDE constraint —
  the DDL declares the constraint, never the index;
- a sequence a **column** owns (``deptype`` ``a`` for ``serial``, ``i`` for an
  identity) — it is part of that column, and the tree never wrote it;
- a ``NOT NULL`` constraint row (PostgreSQL 18's ``contype = 'n'``) — it is
  ``attnotnull``, read on the column.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import replace
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
    SchemaModel,
    Table,
    qualified_name,
    ref_for,
)
from confiture.core.schema_model import Sequence as SequenceModel
from confiture.core.type_lattice import canonical_type

if TYPE_CHECKING:
    import psycopg

#: Not an object an extension created.
_NOT_EXTENSION_OWNED = """
    NOT EXISTS (
        SELECT 1 FROM pg_depend d
        WHERE d.classid = '{catalog}'::regclass AND d.objid = {oid} AND d.deptype = 'e'
    )
"""

_TABLES = f"""
SELECT c.oid, n.nspname, c.relname
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind IN ('r', 'p')
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
SELECT i.indrelid, pg_get_indexdef(i.indexrelid)
FROM pg_index i
JOIN pg_class ic ON ic.oid = i.indexrelid
WHERE i.indrelid = ANY(%s)
  AND NOT EXISTS (SELECT 1 FROM pg_constraint k WHERE k.conindid = i.indexrelid)
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


def _tables(conn: psycopg.Connection, schemas: list[str]) -> dict[Any, Table]:
    relations = conn.execute(_TABLES, (schemas,)).fetchall()
    oids = [oid for oid, _schema, _name in relations]
    rows: dict[int, list[tuple[Any, ...]]] = defaultdict(list)
    for row in conn.execute(_COLUMNS, (oids,)).fetchall():
        rows[row[0]].append(row)
    constraints: dict[int, list[Constraint]] = defaultdict(list)
    for relid, name, definition in conn.execute(_CONSTRAINTS, (oids,)).fetchall():
        read = _constraint(name, definition)
        if read is not None:
            constraints[relid].append(read)
    indexes: dict[int, list[Any]] = defaultdict(list)
    for relid, definition in conn.execute(_INDEXES, (oids,)).fetchall():
        indexes[relid].append(pglast.parse_sql(definition)[0].stmt)

    tables: dict[Any, Table] = {}
    for oid, schema, name in relations:
        qualified = qualified_name(schema, name)
        columns = [
            _column(row, node)
            for row, node in zip(rows[oid], _type_nodes([r[2] for r in rows[oid]]), strict=True)
        ]
        index_models: list[Index] = [read_index(stmt, table=qualified) for stmt in indexes[oid]]
        tables[ref_for("table", schema, name)] = Table(
            name=name,
            schema=schema,
            columns=_with_primary_keys(columns, constraints[oid]),
            constraints=tuple(constraints[oid]),
            indexes=tuple(index_models),
        )
    return tables


def read(conn: psycopg.Connection, *, schemas: Sequence[str]) -> SchemaModel:
    """The schema the database holds in *schemas*, in the model DDL is read into."""
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
    return SchemaModel(tables=_tables(conn, wanted), enum_types=enum_types, sequences=sequences)


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
    SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = %s AND c.relname = %s AND c.relkind IN ('i', 'I')
)
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

#: The ``relkind`` letters of a table, partitioned or not.
TABLE_KINDS = ("r", "p")

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


def index_exists(conn: psycopg.Connection, schema: str, name: str) -> bool:
    return bool(_scalar(conn, _INDEX_EXISTS, (schema, name)))


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
