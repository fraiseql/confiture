"""The object inventory the lint rules read.

Built once per lint run from ``pglast.parser.parse_sql``. Table and column names
are kept as written in the source — pglast folds unquoted identifiers to
lowercase, and ``naming_001`` / ``naming_002`` judge the spelling the author
typed — so each identifier is read back from the statement text at the node's
location. A schema qualifier is data on the object, never a reason to miss it.

Every ``CREATE`` is one entry: a second definition of the same key is a second
entry with its own offset, which is what the duplicate check reads. A function's
identity is its name *and* the types of its input parameters, so
``COMMENT ON FUNCTION f(integer)`` documents one overload and not its sibling.
Offsets and lines are character positions into the text that was parsed,
which is what pglast reports.
"""

from __future__ import annotations

import bisect
import copy
import functools
import re
from collections import defaultdict
from collections.abc import Callable, Hashable, Iterable, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, TypeVar

import pglast
from pglast.stream import RawStream

from confiture.core._pglast_enums import member as _pg_member
from confiture.core.ddl_walk import (
    ColumnEdit,
    ObjectEdit,
    added_constraint,
    column_edit,
    object_edits,
    object_kinds,
    read_column_constraints,
    read_constraint,
    read_index,
    render_default,
    written_type,
)
from confiture.core.ddl_walk import type_name as ddl_type_name

# The fold lives in its own module so a reader that needs it but not a parser
# can have it; imported here because this is where object identity is decided.
from confiture.core.schema_identity import DEFAULT_SCHEMA
from confiture.core.schema_model import (
    Column,
    Constraint,
    EnumType,
    Index,
    SchemaModel,
    Table,
    ref_for,
)
from confiture.core.schema_model import Sequence as SequenceModel
from confiture.core.type_lattice import canonical_type, parse_type

_T = TypeVar("_T")

_CONSTR_PRIMARY = _pg_member("ConstrType", "CONSTR_PRIMARY")
_CONSTR_DEFAULT = _pg_member("ConstrType", "CONSTR_DEFAULT")
_OBJECT_TABLE = _pg_member("ObjectType", "OBJECT_TABLE")
_OBJECT_FUNCTION = _pg_member("ObjectType", "OBJECT_FUNCTION")
_OBJECT_PROCEDURE = _pg_member("ObjectType", "OBJECT_PROCEDURE")
_OBJECT_ROUTINE = _pg_member("ObjectType", "OBJECT_ROUTINE")
_OBJECT_VIEW = _pg_member("ObjectType", "OBJECT_VIEW")
_OBJECT_MATVIEW = _pg_member("ObjectType", "OBJECT_MATVIEW")
_OBJECT_TYPE = _pg_member("ObjectType", "OBJECT_TYPE")
_OBJECT_DOMAIN = _pg_member("ObjectType", "OBJECT_DOMAIN")
_OBJECT_AGGREGATE = _pg_member("ObjectType", "OBJECT_AGGREGATE")

_PLAIN_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*")

#: Which inventory kinds a ``COMMENT ON <object type>`` statement documents.
_COMMENT_TARGETS: dict[int | None, tuple[str, ...]] = {
    _OBJECT_TABLE: ("table",),
    _OBJECT_FUNCTION: ("function",),
    _OBJECT_PROCEDURE: ("procedure",),
    _OBJECT_ROUTINE: ("function", "procedure"),
    _OBJECT_VIEW: ("view",),
    _OBJECT_MATVIEW: ("matview",),
    _OBJECT_TYPE: ("type",),
    _OBJECT_DOMAIN: ("domain",),
}

#: The SQL keyword that names each inventory kind: what ``COMMENT ON <kind>``
#: and ``CREATE <kind>`` are spelled with, and — capitalised — the noun a
#: finding calls the object. One table, because a rule that invented its own
#: would be free to disagree with the inventory about what a ``matview`` is.
KIND_KEYWORD: dict[str, str] = {
    "table": "TABLE",
    "function": "FUNCTION",
    "procedure": "PROCEDURE",
    "view": "VIEW",
    "matview": "MATERIALIZED VIEW",
    "type": "TYPE",
    "domain": "DOMAIN",
    "aggregate": "AGGREGATE",
    "sequence": "SEQUENCE",
}

#: Parameter modes that take part in a function's identity (IN, INOUT, VARIADIC
#: and the default mode); OUT and TABLE parameters do not.
_INPUT_MODES = frozenset({"d", "i", "b", "v"})
#: The schema pglast attaches to a type written in SQL-standard keyword form.
_CATALOG_SCHEMA = "pg_catalog"


#: A column, whole: the one model of it (``core/schema_model.py``). The name is
#: kept because the rules and ``drift.py`` have always read ``SchemaColumn``.
SchemaColumn = Column


#: A routine's input parameter types, each as ``(schema, canonical name)``.
#: ``None`` for every kind that is not a routine.
Signature = tuple[tuple[str | None, str], ...]


@dataclass
class SchemaObject:
    """One ``CREATE`` statement, with what the rules need to know about it.

    ``kind`` is one of ``table``, ``function``, ``procedure``, ``aggregate``,
    ``view``, ``matview``, ``type`` (composite or enum), ``domain`` or
    ``sequence`` — the keys of :data:`KIND_KEYWORD`. ``signature`` is the
    comma-joined input parameter types of a routine *as written*, which is what
    a finding prints; ``signature_key`` is the same types canonicalised, which
    is what decides whether two routines are the same routine. Both ``None``
    for every other kind. They are two fields because pglast renders a type the
    way it was written, so ``timestamptz`` and ``timestamp with time zone``
    print differently and must compare equal (#275). ``offset``
    is the character position of the statement in the parsed text; ``file`` is
    set by callers that inventory one file at a time. ``replace`` and
    ``if_not_exists`` record ``CREATE OR REPLACE`` / ``IF NOT EXISTS``, which
    decide what a second definition of the same object does at build time.
    ``line`` is where the object's *name* is written and ``statement_line``
    where its ``CREATE`` begins — the same line for most statements, and not
    for one whose name is on a continuation line. ``comment`` is the text a
    ``COMMENT ON`` left on the object, kept rather than reduced to a flag so a
    rule can ask what the comment *says* and not only that one exists (#250).
    """

    kind: str
    name: str
    schema: str | None
    folded_name: str
    folded_schema: str | None
    line: int
    columns: list[SchemaColumn] = field(default_factory=list)
    #: A table's primary key, UNIQUEs, CHECKs and foreign keys, wherever the
    #: grammar allowed them to be written — on a column, at table level, or in a
    #: later ``ALTER TABLE … ADD CONSTRAINT``.
    constraints: list[Constraint] = field(default_factory=list)
    #: A table's indexes, folded on from their own ``CREATE INDEX`` statements.
    indexes: list[Index] = field(default_factory=list)
    #: An enum's labels in declaration order; ``None`` for every other kind,
    #: a composite type included.
    enum_values: tuple[str, ...] | None = None
    #: A sequence's numeric options as written (``start``, ``increment``, …).
    sequence_options: dict[str, int | None] = field(default_factory=dict)
    has_primary_key: bool = False
    is_partition: bool = False
    is_temporary: bool = False
    comment: str | None = None
    signature: str | None = None
    signature_key: Signature | None = None
    offset: int = 0
    file: str | None = None
    replace: bool = False
    if_not_exists: bool = False
    parent: str | None = None
    statement_line: int = 1

    @property
    def documented(self) -> bool:
        """Whether a ``COMMENT`` on this object left anything behind.

        ``COMMENT ON TABLE t IS NULL`` *removes* a comment and ``IS ''`` stores
        an empty one; both satisfied the ``doc`` family while it counted the
        statement rather than what the statement left (#250).
        """
        return bool(self.comment and self.comment.strip())

    @property
    def qualified(self) -> str:
        return f"{self.schema}.{self.name}" if self.schema else self.name

    @property
    def identity(self) -> str:
        """``schema.name(signature)`` for routines, ``schema.name`` otherwise."""
        return (
            f"{self.qualified}({self.signature})" if self.signature is not None else self.qualified
        )


@dataclass
class Inventory:
    """The objects a text creates, and the schemas it declares.

    ``schemas`` is kept beside ``objects`` rather than in it: a schema is a
    namespace, not an object in one, and the rules that walk ``objects`` — the
    duplicate check above all — would read a schema re-declared with
    ``IF NOT EXISTS`` in a second file as a duplicate definition, which is
    idiomatic rather than a mistake.
    """

    objects: list[SchemaObject] = field(default_factory=list)
    schemas: list[SchemaObject] = field(default_factory=list)

    @property
    def tables(self) -> list[SchemaObject]:
        return [o for o in self.objects if o.kind == "table"]

    def find(self, folded_schema: str | None, folded_name: str) -> SchemaObject | None:
        """The table a statement refers to; a missing schema on either side matches any."""
        matches = self.find_all(("table",), folded_schema, folded_name)
        return matches[0] if matches else None

    def find_all(
        self,
        kinds: tuple[str, ...],
        folded_schema: str | None,
        folded_name: str,
        signature_key: Signature | None = None,
    ) -> list[SchemaObject]:
        """Every definition of the object a statement names, in source order.

        A missing schema on either side matches any schema; ``signature_key``
        narrows routines to one overload when given. It is the *canonical*
        argument types, never the text a finding prints: a ``COMMENT ON
        FUNCTION f(timestamp with time zone)`` documents ``f(timestamptz)``,
        because PostgreSQL resolves both to one function (#275). The same
        wildcard runs one level down, over each argument's own schema, so
        ``COMMENT ON FUNCTION app.f(custom_t)`` documents
        ``app.f(app.custom_t)``.
        """
        matches: list[SchemaObject] = []
        for obj in self.objects:
            if obj.kind not in kinds or obj.folded_name != folded_name:
                continue
            if (
                folded_schema is not None
                and obj.folded_schema is not None
                and obj.folded_schema != folded_schema
            ):
                continue
            if signature_key is not None and not signatures_match(obj.signature_key, signature_key):
                continue
            matches.append(obj)
        return matches


def _enum_value(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def identifier_at(sql: str, location: int | None, fallback: str) -> list[str]:
    """The (possibly qualified) identifier written at ``location``, quotes stripped.

    Returns one segment per dotted part; ``fallback`` (pglast's folded name) when
    the location is missing or does not start an identifier.
    """
    if location is None or location < 0 or location >= len(sql):
        return [fallback]
    segments: list[str] = []
    pos = location
    while pos < len(sql):
        if sql[pos] == '"':
            end = pos + 1
            text: list[str] = []
            while end < len(sql):
                if sql[end] == '"':
                    if end + 1 < len(sql) and sql[end + 1] == '"':
                        text.append('"')
                        end += 2
                        continue
                    break
                text.append(sql[end])
                end += 1
            segments.append("".join(text))
            pos = end + 1
        else:
            m = _PLAIN_IDENT.match(sql, pos)
            if not m:
                break
            segments.append(m.group(0))
            pos = m.end()
        if pos < len(sql) and sql[pos] == ".":
            pos += 1
            continue
        break
    return segments or [fallback]


@functools.lru_cache(maxsize=8)
def _newlines(sql: str) -> tuple[int, ...]:
    """Where every newline in *sql* is. Cached: one text is asked for thousands of lines."""
    positions: list[int] = []
    position = sql.find("\n")
    while position != -1:
        positions.append(position)
        position = sql.find("\n", position + 1)
    return tuple(positions)


def _line_of(sql: str, location: int | None) -> int:
    """The 1-based line *location* falls on.

    A binary search over the text's newlines, not a count from the start: every
    object and column asks, so counting made reading a tree quadratic in its size
    — a 2.9 MB schema spent 5 of its 11 seconds here.
    """
    if location is None or location < 0:
        return 1
    return bisect.bisect_left(_newlines(sql), min(location, len(sql))) + 1


def _statement_offset(sql: str, raw: Any) -> int:
    """Where the statement's first token starts, past any whitespace or comment.

    pglast reports character positions into the parsed text (verified against
    non-ASCII prefixes), so no byte-to-character conversion is applied.
    """
    pos = getattr(raw, "stmt_location", 0) or 0
    while pos < len(sql):
        if sql[pos].isspace():
            pos += 1
        elif sql.startswith("--", pos):
            newline = sql.find("\n", pos)
            pos = len(sql) if newline < 0 else newline + 1
        elif sql.startswith("/*", pos):
            close = sql.find("*/", pos + 2)
            pos = len(sql) if close < 0 else close + 2
        else:
            break
    return pos


def _sql_type(type_node: Any) -> str | None:
    """The type PostgreSQL will store for this column, spelled as SQL.

    ``RawStream`` gives the author's own spelling (``bigint``, ``varchar(255)``),
    not pglast's ``int8`` — which is what a finding should print. Two things it
    also gives are normalised away, both because PostgreSQL itself normalises
    them at DDL time and the live side therefore never reports them:

    * the ``pg_catalog.`` qualifier the parser attaches to ``json`` and ``bit``.
      It is the parser's, never the author's: no user schema can be called
      ``pg_catalog``, since the ``pg_`` prefix is reserved (#275).
    * array **dimensionality**. PostgreSQL records that a column is an array and
      never how many ``[]`` the DDL wrote, so ``INTEGER[][]`` *is* ``_int4`` and
      ``format_type`` returns ``integer[]``.

    The dimension collapse belongs here rather than in
    :func:`~confiture.core.type_lattice.canonical_type`: ``SqlType.dimensions``
    is part of a type's identity there, because ``text`` and ``text[]`` are two
    types, and a lattice that dropped the suffix answered IDENTICAL for a change
    that rewrites every page. Here the question is different — what will the
    database hold — and the answer is one array.

    A *user* schema qualifier stays: ``app.custom_t`` and ``other.custom_t`` are
    two types (D9).
    """
    if type_node is None:
        return None
    written = RawStream()(type_node).removeprefix(f"{_CATALOG_SCHEMA}.")
    return written[: -2 * (written.count("[]") - 1)] if written.count("[]") > 1 else written


def _column(sql: str, node: Any) -> tuple[SchemaColumn, tuple[Constraint, ...]]:
    """One ``ColumnDef``: the column, and the constraints its own clauses add to the table.

    What the clauses *mean* is ``ddl_walk.read_column_constraints``' answer — the
    one reader of a ``Constraint`` node. A primary key among them is applied to
    the column by :func:`_apply_primary_keys`, where a table-level one is too.
    """
    written = identifier_at(sql, getattr(node, "location", None), node.colname)[-1]
    fact, constraints = read_column_constraints(node)
    type_node = getattr(node, "typeName", None)
    column = SchemaColumn(
        name=written,
        folded=node.colname,
        line=_line_of(sql, getattr(node, "location", None)),
        type_text=_sql_type(type_node),
        type_key=canonical_type(ddl_type_name(type_node)),
        raw_sql_type=written_type(type_node),
        not_null=fact.not_null,
        default=fact.default,
        identity=fact.identity,
        generated=fact.generated,
        generated_kind=fact.generated_kind,
    )
    return column, constraints


def _add_constraints(table: SchemaObject, constraints: Iterable[Constraint]) -> None:
    """Record *constraints* on *table*; a primary key also marks the columns it covers.

    A primary key makes its columns ``NOT NULL`` whichever spelling declared it.
    ``PRIMARY KEY (id)`` at table level left the column nullable here while the
    differ read it ``NOT NULL`` — so ``confiture drift`` reported a database
    applied verbatim from its own DDL as drifted.
    """
    for constraint in constraints:
        table.constraints.append(constraint)
        if constraint.kind != "primary_key":
            continue
        table.has_primary_key = True
        covered = set(constraint.columns)
        table.columns = [
            replace(column, primary_key=True, not_null=True) if column.folded in covered else column
            for column in table.columns
        ]


def _append_column(sql: str, table: SchemaObject, node: Any) -> None:
    """Add the column *node* declares, unless the table already holds one of that name.

    A second ``ADD COLUMN a`` is what a database built from the tree never holds:
    with ``IF NOT EXISTS`` PostgreSQL skips it, and without it the build fails at
    that statement — so the column is the one declared first, either way.
    """
    column, constraints = _column(sql, node)
    if any(existing.folded == column.folded for existing in table.columns):
        return
    table.columns.append(column)
    _add_constraints(table, constraints)


# Two functions over one `TypeName`, and they answer different questions.
# Public, because `func_001` and `sec_002` walk their own files and each kept a
# pasted alias table of its own rather than asking (#275).
# `_type_text` is the **prose**: what a finding prints, spelled the way the
# author wrote it, so `app.fn_c(integer)` and never `app.fn_c(int4)`.
# `_type_key` is the **identity**: what decides whether two routines are the
# same routine. Do not unify them — pglast renders a type as it was written, so
# the prose is exactly what cannot be compared (#275).


def type_text(type_name: Any) -> str:
    """``integer[]`` for a ``TypeName``, typmods dropped — an argument, as written.

    A leading ``pg_catalog.`` is dropped too. ``RawStream`` prints the qualifier
    pglast attached, which for ``json`` and ``bit`` is the whole rendering:
    a ``doc_002`` finding read ``Function 'app.fn_j(pg_catalog.json)' should
    have a COMMENT`` and its suggested fix told the author to write that. No
    user schema can be called ``pg_catalog`` — the ``pg_`` prefix is reserved —
    so the qualifier is always the parser's.
    """
    bare = copy.deepcopy(type_name)
    bare.typmods = None
    rendered = RawStream()(bare)
    return rendered.removeprefix(f"{_CATALOG_SCHEMA}.")


def type_key(type_name: Any) -> tuple[str | None, str]:
    """``(schema, canonical name)`` — an argument's identity, not its spelling.

    Typmods are dropped first, because PostgreSQL ignores them in a routine
    signature *and* because pglast gives the keyword form ``char`` an implicit
    typmod of 1 that bare ``bpchar`` does not have: without the drop those two
    key as ``char(1)`` and ``char``.

    The schema is kept apart from the name rather than joined, so that "a
    missing schema matches any schema" — the rule ``find_all`` already applies
    to an object's own schema — can be expressed one level down.
    """
    bare = copy.deepcopy(type_name)
    bare.typmods = None
    rendered = ddl_type_name(bare) or ""
    schema, _, name = rendered.rpartition(".")
    return (schema or None), (canonical_type(name) or name)


def signature_from_type_names(written: Iterable[str]) -> Signature:
    """A routine's signature from argument types spelled as *text*.

    :func:`type_key` answers this for a parse node, and this is the only other
    way in. A ``DROP FUNCTION f(bigint)`` names its arguments as text, and so
    does a live catalogue; canonicalising them anywhere else would be a second
    idea of what makes two routines the same routine, which is exactly what
    ``signature`` and ``signature_key`` exist to keep apart (#275).

    Typmods are dropped for :func:`type_key`'s reason: PostgreSQL ignores them
    in a signature, and ``char`` carries an implicit one that ``bpchar`` does not.
    """
    return tuple(_type_key_from_text(name) for name in written)


def _type_key_from_text(written: str) -> tuple[str | None, str]:
    schema, _, name = written.rpartition(".")
    parsed = parse_type(name)
    bare = parsed.name + "[]" * parsed.dimensions if parsed is not None else name
    return (
        None if not schema or schema == _CATALOG_SCHEMA else schema,
        canonical_type(bare) or bare,
    )


def types_match(a: tuple[str | None, str], b: tuple[str | None, str]) -> bool:
    """Whether two argument types, as each side spelled them, are one type.

    The names must agree exactly — they are canonical by then, and the array
    suffix is part of the name — but a schema written on one side and left off
    the other matches, because PostgreSQL resolves the bare spelling through
    ``search_path`` and lands on the same type. Two schemas that are both
    present and disagree never match: ``app.custom_t`` and ``other.custom_t``
    are two types (D9).
    """
    if a[1] != b[1]:
        return False
    return a[0] is None or b[0] is None or a[0] == b[0]


def signatures_match(a: Signature | None, b: Signature | None) -> bool:
    """Whether two canonical signatures name one routine, argument by argument.

    ``None`` is not a signature but the absence of one — every kind that is not
    a routine — so it matches only itself and never an empty argument list.
    """
    if a is None or b is None:
        return a is None and b is None
    if len(a) != len(b):
        return False
    return all(types_match(x, y) for x, y in zip(a, b, strict=True))


def _signature(parameters: Any) -> str:
    return ", ".join(type_text(p.argType) for p in _input_parameters(parameters))


def _signature_key(parameters: Any) -> Signature:
    return tuple(type_key(p.argType) for p in _input_parameters(parameters))


def _input_parameters(parameters: Any) -> list[Any]:
    """The parameters that are part of the signature: ``OUT`` and ``TABLE`` are not."""
    return [p for p in parameters or [] if getattr(p.mode, "value", p.mode) in _INPUT_MODES]


def split_names(names: Any) -> tuple[str | None, str]:
    """``(schema, name)`` from a pglast name list; the schema is ``None`` when absent."""
    parts = [getattr(n, "sval", None) for n in names or []]
    parts = [p for p in parts if p is not None]
    return (parts[-2] if len(parts) >= 2 else None), parts[-1]


def _object(
    kind: str, schema: str | None, name: str, line: int, offset: int, **extra: Any
) -> SchemaObject:
    return SchemaObject(
        kind=kind,
        name=name,
        schema=schema,
        folded_name=name,
        folded_schema=schema,
        line=line,
        offset=offset,
        **extra,
    )


def _table_from_create(sql: str, stmt: Any, offset: int) -> SchemaObject:
    rv = stmt.relation
    parts = identifier_at(sql, rv.location, rv.relname)
    name = parts[-1]
    schema = parts[-2] if len(parts) >= 2 else None
    table = SchemaObject(
        kind="table",
        name=name,
        schema=schema,
        folded_name=rv.relname,
        folded_schema=rv.schemaname,
        line=_line_of(sql, rv.location),
        is_partition=stmt.partbound is not None,
        is_temporary=getattr(rv, "relpersistence", "p") == "t",
        offset=offset,
        if_not_exists=bool(getattr(stmt, "if_not_exists", False)),
        parent=_parent_name(stmt),
    )
    for elt in stmt.tableElts or []:
        kind = type(elt).__name__
        if kind == "ColumnDef":
            _append_column(sql, table, elt)
        elif kind == "Constraint":
            read = read_constraint(elt)
            if isinstance(read, Constraint):
                _add_constraints(table, (read,))
    return table


def _parent_name(stmt: Any) -> str | None:
    """``schema.parent`` of a ``PARTITION OF`` child (folded, as pglast spells it)."""
    if stmt.partbound is None:
        return None
    for rv in getattr(stmt, "inhRelations", None) or ():
        name = getattr(rv, "relname", None)
        if name:
            schema = getattr(rv, "schemaname", None)
            return f"{schema}.{name}" if schema else name
    return None


def _routine_from_create(sql: str, stmt: Any, offset: int) -> SchemaObject:
    schema, name = split_names(stmt.funcname)
    return _object(
        "procedure" if stmt.is_procedure else "function",
        schema,
        name,
        _line_of(sql, offset),
        offset,
        signature=_signature(stmt.parameters),
        signature_key=_signature_key(stmt.parameters),
        replace=bool(getattr(stmt, "replace", False)),
    )


def _aggregate_from_define(sql: str, stmt: Any, offset: int) -> SchemaObject | None:
    """``CREATE AGGREGATE``: a routine, identified like one by its input types.

    ``DefineStmt`` is also ``CREATE OPERATOR``, ``CREATE COLLATION`` and the
    rest, so the object type is checked first. ``args`` is ``(parameters,
    direct-argument count)`` in the modern spelling — with ``None`` parameters
    for ``(*)`` — and ``None`` for the ``basetype =`` one, whose types live in
    the definition list instead.
    """
    if _enum_value(stmt.kind) != _OBJECT_AGGREGATE:
        return None
    schema, name = split_names(stmt.defnames)
    args = getattr(stmt, "args", None)
    return _object(
        "aggregate",
        schema,
        name,
        _line_of(sql, offset),
        offset,
        signature=_signature(args[0] if args else None),
        signature_key=_signature_key(args[0] if args else None),
    )


def _relation_object(sql: str, kind: str, rv: Any, offset: int) -> SchemaObject:
    return _object(kind, rv.schemaname, rv.relname, _line_of(sql, rv.location), offset)


def _view_from_create(sql: str, stmt: Any, offset: int) -> SchemaObject:
    view = _relation_object(sql, "view", stmt.view, offset)
    view.replace = bool(getattr(stmt, "replace", False))
    return view


def _matview_from_create_table_as(sql: str, stmt: Any, offset: int) -> SchemaObject | None:
    """``CREATE TABLE AS`` also spells ``CREATE MATERIALIZED VIEW``; only the latter counts."""
    if _enum_value(stmt.objtype) != _OBJECT_MATVIEW:
        return None
    matview = _relation_object(sql, "matview", stmt.into.rel, offset)
    matview.if_not_exists = bool(getattr(stmt, "if_not_exists", False))
    return matview


def _composite_type_from_create(sql: str, stmt: Any, offset: int) -> SchemaObject:
    return _relation_object(sql, "type", stmt.typevar, offset)


def _enum_from_create(sql: str, stmt: Any, offset: int) -> SchemaObject:
    schema, name = split_names(stmt.typeName)
    labels = tuple(value.sval for value in stmt.vals or ())
    return _object("type", schema, name, _line_of(sql, offset), offset, enum_values=labels)


def _domain_from_create(sql: str, stmt: Any, offset: int) -> SchemaObject:
    schema, name = split_names(stmt.domainname)
    return _object("domain", schema, name, _line_of(sql, offset), offset)


def _sequence_from_create(sql: str, stmt: Any, offset: int) -> SchemaObject:
    sequence = _relation_object(sql, "sequence", stmt.sequence, offset)
    for option in stmt.options or ():
        arg = getattr(option, "arg", None)
        sequence.sequence_options[option.defname] = getattr(arg, "ival", None)
    sequence.if_not_exists = bool(getattr(stmt, "if_not_exists", False))
    return sequence


#: Which builder reads which parse node. A statement whose node is absent here
#: creates nothing the rules inventory; a builder that returns ``None`` saw a
#: node it shares with another statement (``DefineStmt``, ``CreateTableAsStmt``).
_BUILDERS: dict[str, Callable[[str, Any, int], SchemaObject | None]] = {
    "CreateStmt": _table_from_create,
    "CreateFunctionStmt": _routine_from_create,
    "DefineStmt": _aggregate_from_define,
    "ViewStmt": _view_from_create,
    "CreateTableAsStmt": _matview_from_create_table_as,
    "CompositeTypeStmt": _composite_type_from_create,
    "CreateEnumStmt": _enum_from_create,
    "CreateDomainStmt": _domain_from_create,
    "CreateSeqStmt": _sequence_from_create,
}


def object_from_statement(sql: str, raw: Any) -> SchemaObject | None:
    """The one entry this statement creates, or ``None`` when it creates none."""
    stmt = raw.stmt
    builder = _BUILDERS.get(type(stmt).__name__)
    if builder is None:
        return None
    offset = _statement_offset(sql, raw)
    obj = builder(sql, stmt, offset)
    if obj is not None:
        obj.statement_line = _line_of(sql, offset)
    return obj


def _schema_declaration(sql: str, raw: Any) -> SchemaObject | None:
    """``CREATE SCHEMA app``, or ``None`` for any other statement.

    ``CREATE SCHEMA AUTHORIZATION bob`` names the role, not the schema, so
    there is nothing to record.
    """
    stmt = raw.stmt
    if type(stmt).__name__ != "CreateSchemaStmt" or not getattr(stmt, "schemaname", None):
        return None
    offset = _statement_offset(sql, raw)
    declared = _object("schema", None, stmt.schemaname, _line_of(sql, offset), offset)
    declared.statement_line = declared.line
    return declared


def _added(sql: str, table: SchemaObject, edit: ColumnEdit) -> None:
    _append_column(sql, table, edit.coldef)


def _dropped(_sql: str, table: SchemaObject, edit: ColumnEdit) -> None:
    table.columns = [column for column in table.columns if column.folded != edit.column]


def _retyped(_sql: str, table: SchemaObject, edit: ColumnEdit) -> None:
    """The type as the ``ALTER`` wrote it, on the column the ``CREATE`` declared.

    A retype never invents a column: naming one the tree has not created is an
    ``ALTER`` against a schema built elsewhere, which both readers ignore.
    """
    type_node = getattr(edit.coldef, "typeName", None)
    _edited(
        table,
        edit.column,
        type_text=_sql_type(type_node),
        type_key=canonical_type(ddl_type_name(type_node)),
        raw_sql_type=written_type(type_node),
    )


def _edited(table: SchemaObject, column_name: str | None, **changes: Any) -> None:
    """Replace one column with a copy carrying *changes*; a name not there is ignored."""
    table.columns = [
        replace(column, **changes) if column.folded == column_name else column
        for column in table.columns
    ]


def _set_not_null(_sql: str, table: SchemaObject, edit: ColumnEdit) -> None:
    _edited(table, edit.column, not_null=True)


def _drop_not_null(_sql: str, table: SchemaObject, edit: ColumnEdit) -> None:
    _edited(table, edit.column, not_null=False)


def _set_default(_sql: str, table: SchemaObject, edit: ColumnEdit) -> None:
    _edited(table, edit.column, default=render_default(edit.default))


def _drop_default(_sql: str, table: SchemaObject, edit: ColumnEdit) -> None:
    _edited(table, edit.column, default=None)


#: ``ColumnEdit.kind`` -> how the inventory applies it to its own model. The
#: decision itself is ``ddl_walk.column_edit``, shared with the differ, which
#: applies the same edits to a model that shares none of these types (#301).
_COLUMN_APPLIERS: dict[str, Callable[[str, SchemaObject, ColumnEdit], None]] = {
    "add": _added,
    "drop": _dropped,
    "retype": _retyped,
    "set_not_null": _set_not_null,
    "drop_not_null": _drop_not_null,
    "set_default": _set_default,
    "drop_default": _drop_default,
}


def _apply_alter(sql: str, stmt: Any, inventory: Inventory) -> None:
    """Fold one ``ALTER TABLE`` into the table the tree already created.

    An ``ALTER`` naming a table this tree never creates has nothing to fold into
    and is ignored: it belongs to a schema built elsewhere.
    """
    rv = stmt.relation
    table = inventory.find(rv.schemaname, rv.relname)
    if table is None:
        return
    for cmd in stmt.cmds or []:
        node = added_constraint(cmd)
        if node is not None:
            # A table-level constraint, so it lands on the table — which is why
            # it is not a `ColumnEdit`.
            read = read_constraint(node)
            if isinstance(read, Constraint):
                _add_constraints(table, (read,))
            continue
        edit = column_edit(cmd)
        apply = _COLUMN_APPLIERS.get(edit.kind) if edit is not None else None
        if apply is not None and edit is not None:
            apply(sql, table, edit)


def _renamed_object(obj: SchemaObject, edit: ObjectEdit) -> None:
    obj.name = edit.new_name or obj.name
    obj.folded_name = (edit.new_name or obj.folded_name).lower()


def _moved_object(obj: SchemaObject, edit: ObjectEdit) -> None:
    obj.schema = edit.new_schema or obj.schema
    obj.folded_schema = (edit.new_schema or obj.folded_schema or "").lower() or None


def _renamed_column(obj: SchemaObject, edit: ObjectEdit) -> None:
    obj.columns = [
        replace(column, name=edit.new_name or column.name, folded=(edit.new_name or "").lower())
        if column.folded == edit.column
        else column
        for column in obj.columns
    ]


#: ``ObjectEdit.kind`` -> how the inventory applies it to one object it holds.
#: ``drop`` is not here: it removes the object from the inventory rather than
#: editing it, so it is the one case that needs the list.
_OBJECT_APPLIERS: dict[str, Callable[[SchemaObject, ObjectEdit], None]] = {
    "rename": _renamed_object,
    "rename_column": _renamed_column,
    "set_schema": _moved_object,
}


def _targets(inventory: Inventory, edit: ObjectEdit, offset: int) -> list[SchemaObject]:
    """Every object the edit names that the tree had already declared *at* ``offset``.

    ``find_all`` decides what "the same object" means — a missing schema on
    either side matches any, and a routine is narrowed to one overload by its
    canonical argument types. A statement naming a kind the inventory does not
    model (a trigger, a policy, an extension) matches nothing here, and is
    ``ddl_objects``' to answer for.

    The offset is what makes ``DROP TABLE IF EXISTS x; CREATE TABLE x (…);`` —
    an everyday idiom — declare ``x``. :func:`build_inventory` collects every
    ``CREATE`` before it folds anything, so without it a drop would reach a table
    written after it and delete something the tree really does declare.
    """
    if edit.object_kind == "schema":
        candidates = [obj for obj in inventory.schemas if obj.folded_name == edit.name.lower()]
    else:
        signature_key = (
            signature_from_type_names(edit.arg_types) if edit.arg_types is not None else None
        )
        candidates = inventory.find_all(
            object_kinds(edit.object_kind), edit.schema, edit.name, signature_key
        )
    return [obj for obj in candidates if obj.offset < offset]


def _apply_index(stmt: Any, inventory: Inventory) -> None:
    """Fold a ``CREATE INDEX`` onto the table the tree declared."""
    relation = stmt.relation
    table = inventory.find(relation.schemaname, relation.relname)
    if table is None:
        return
    table.indexes.append(read_index(stmt, table=table.qualified))


def _drop_index(inventory: Inventory, edit: ObjectEdit) -> None:
    """``DROP INDEX``: an index name is unique per schema, and the statement names no table."""
    for table in inventory.tables:
        if edit.schema is None or table.folded_schema in (None, edit.schema):
            table.indexes = [ix for ix in table.indexes if ix.name != edit.name]


def _apply_object_edit(inventory: Inventory, edit: ObjectEdit, offset: int) -> None:
    """Fold one statement's edit into the objects the tree has declared so far.

    A statement naming something the tree never created changes nothing — the
    rule ``_apply_alter`` follows for the same reason: it belongs to a schema
    built elsewhere.
    """
    if edit.object_kind == "index":
        if edit.kind == "drop":
            _drop_index(inventory, edit)
        return
    targets = _targets(inventory, edit, offset)
    if not targets:
        return
    if edit.kind == "drop":
        dropped = {id(obj) for obj in targets}
        inventory.objects = [obj for obj in inventory.objects if id(obj) not in dropped]
        inventory.schemas = [obj for obj in inventory.schemas if id(obj) not in dropped]
        return
    apply = _OBJECT_APPLIERS.get(edit.kind)
    if apply is None:
        return
    for obj in targets:
        apply(obj, edit)


def _comment_target(
    stmt: Any,
) -> tuple[str | None, str, tuple[tuple[str | None, str], ...] | None] | None:
    """``(schema, name, signature key)`` the comment names; key ``None`` = any overload."""
    obj = stmt.object
    node_kind = type(obj).__name__
    if node_kind == "ObjectWithArgs":
        schema, name = split_names(obj.objname)
        if getattr(obj, "args_unspecified", False) or obj.objargs is None:
            return schema, name, None
        return schema, name, tuple(type_key(t) for t in obj.objargs)
    if node_kind == "TypeName":
        schema, name = split_names(obj.names)
        return schema, name, None
    names = [getattr(o, "sval", None) for o in (obj or [])]
    names = [n for n in names if n is not None]
    if not names:
        return None
    return (names[-2] if len(names) >= 2 else None), names[-1], None


def _apply_comment(stmt: Any, inventory: Inventory) -> None:
    """Record what a ``COMMENT ON`` leaves on the objects it names.

    The last statement wins, as it does in PostgreSQL, so a later
    ``IS NULL`` really does undocument the object.
    """
    kinds = _COMMENT_TARGETS.get(_enum_value(stmt.objtype))
    if kinds is None:
        return
    target = _comment_target(stmt)
    if target is None:
        return
    schema, name, signature_key = target
    for obj in inventory.find_all(kinds, schema, name, signature_key):
        obj.comment = getattr(stmt, "comment", None)


def build_inventory(sql: str, raws: Sequence[Any] | None = None) -> Inventory:
    """Parse ``sql`` and collect its objects. Raises ``pglast.parser.ParseError``.

    *raws* are ``sql``'s statements when the caller has parsed it already — the
    differ parses once and hands the same statements to ``ddl_objects``.
    """
    inventory = Inventory()
    raws = list(pglast.parse_sql(sql) or []) if raws is None else list(raws)
    for raw in raws:
        obj = object_from_statement(sql, raw) or _schema_declaration(sql, raw)
        if obj is not None:
            (inventory.schemas if obj.kind == "schema" else inventory.objects).append(obj)
    for raw in raws:
        stmt = raw.stmt
        kind = type(stmt).__name__
        if kind == "AlterTableStmt":
            _apply_alter(sql, stmt, inventory)
        elif kind == "IndexStmt":
            _apply_index(stmt, inventory)
        elif kind == "CommentStmt":
            _apply_comment(stmt, inventory)
        else:
            # A drop, a rename or a schema move: not `ALTER TABLE` at all, and
            # invisible to every reader of a DDL tree before #301.
            edits = object_edits(stmt)
            offset = _statement_offset(sql, raw) if edits else 0
            for edit in edits:
                _apply_object_edit(inventory, edit, offset)
    return inventory


def _model_ref(obj: SchemaObject) -> Any:
    return ref_for(obj.kind, obj.folded_schema, obj.folded_name)


def _model_table(obj: SchemaObject) -> Table:
    qualified = f"{obj.folded_schema}.{obj.folded_name}" if obj.folded_schema else obj.folded_name
    return Table(
        name=obj.folded_name,
        schema=obj.folded_schema,
        columns=tuple(obj.columns),
        constraints=tuple(obj.constraints),
        indexes=tuple(replace(ix, table=qualified) for ix in obj.indexes),
    )


def _model_sequence(obj: SchemaObject) -> SequenceModel:
    """Start and increment default to 1, as PostgreSQL defaults an ascending sequence."""
    options = obj.sequence_options
    start, increment = options.get("start"), options.get("increment")
    return SequenceModel(
        name=obj.folded_name,
        schema=obj.folded_schema,
        start=1 if start is None else start,
        increment=1 if increment is None else increment,
        min_value=options.get("minvalue"),
        max_value=options.get("maxvalue"),
    )


def schema_model(inventory: Inventory) -> SchemaModel:
    """The schema *inventory* declares, each object under its identity.

    The first definition of an object is the one the model holds, because it is
    the one a build keeps: a later ``IF NOT EXISTS`` is a no-op and a later plain
    ``CREATE`` fails the build at that statement. ``build_001`` reports the rest.
    """
    tables: dict[Any, Table] = {}
    enum_types: dict[Any, EnumType] = {}
    sequences: dict[Any, SequenceModel] = {}
    for obj in distinct(inventory.objects):
        if obj.kind == "table":
            tables[_model_ref(obj)] = _model_table(obj)
        elif obj.kind == "type" and obj.enum_values is not None:
            enum_types[_model_ref(obj)] = EnumType(
                name=obj.folded_name, schema=obj.folded_schema, values=obj.enum_values
            )
        elif obj.kind == "sequence":
            sequences[_model_ref(obj)] = _model_sequence(obj)
    return SchemaModel(tables=tables, enum_types=enum_types, sequences=sequences)


def build_model(sql: str) -> SchemaModel:
    """Parse ``sql`` into the schema model. Raises ``pglast.parser.ParseError``."""
    return schema_model(build_inventory(sql))


def label_for(path: Path, root: Path | None) -> str:
    """How a finding names a file: relative to the project root when it is under it.

    An absolute path in a report is noise a reader has to strip and a diff has
    to ignore, and it differs between the machine that ran the lint and the one
    reading it. A path outside the root keeps its own spelling — being wrong
    about where a file is would be worse than being verbose.
    """
    if root is not None:
        try:
            return path.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            pass
    return path.as_posix()


#: What identifies one object: kind, schema, name, and — for a routine — the
#: canonical *names* of its input parameter types. A dict key cannot express a
#: wildcard, so the types' own schemas are left out of it and
#: :func:`group_definitions` decides which entries in a bucket really are one
#: object; see :func:`types_match`.
ObjectKey = tuple[str, str | None, str, tuple[str, ...] | None]


def signature_bucket(signature: Signature | None) -> tuple[str, ...] | None:
    """The part of a signature every spelling of one routine shares."""
    return None if signature is None else tuple(name for _schema, name in signature)


def object_key(obj: SchemaObject) -> ObjectKey:
    """What makes two ``CREATE`` statements candidates for the same object.

    The folded spelling, so ``app."TbWidget"`` and ``app.tbwidget`` are one
    object; the name *and* the input parameter types for a routine, so two
    overloads are two; and :data:`DEFAULT_SCHEMA` for a statement that names
    none, so ``f()`` and ``public.f()`` are one and ``tenant.f()`` is another.

    Candidates, not certainties: an argument type's schema is not in the key,
    so ``app.f(app.custom_t)`` and ``app.f(other.custom_t)`` share a bucket and
    are separated by :func:`group_definitions`. Group through that function
    rather than through this key.
    """
    return (
        obj.kind,
        (obj.folded_schema or DEFAULT_SCHEMA).lower(),
        obj.folded_name,
        signature_bucket(obj.signature_key),
    )


def group_by_signature(
    items: Iterable[_T],
    key: Callable[[_T], Hashable],
    signature: Callable[[_T], Signature | None],
) -> list[list[_T]]:
    """Group ``items`` that define one routine, in first-seen order.

    ``key`` buckets what could be the same — it cannot be the whole answer,
    because a dict key cannot express "a missing schema matches any schema" —
    and ``signature`` is then compared within a bucket.

    A definition joins a group only when it matches *every* member. The
    relation is not an equivalence: ``app.f(custom_t)`` matches both
    ``app.f(app.custom_t)`` and ``app.f(other.custom_t)``, which do not match
    each other, so matching one member is not enough. Requiring all of them
    stops the bare spelling chaining the two qualified ones together and
    reporting three definitions of one routine where PostgreSQL has two of one
    and one of another.
    """
    buckets: dict[Hashable, list[list[_T]]] = defaultdict(list)
    order: list[list[_T]] = []
    for item in items:
        groups = buckets[key(item)]
        item_signature = signature(item)
        for group in groups:
            if all(signatures_match(item_signature, signature(member)) for member in group):
                group.append(item)
                break
        else:
            new_group = [item]
            groups.append(new_group)
            order.append(new_group)
    return order


def group_definitions(objects: Iterable[SchemaObject]) -> list[list[SchemaObject]]:
    """Every definition of one object, grouped, in source order.

    The one answer to "are these the same object": ``build_001`` reports a group
    of more than one, and the rules that report a property of an object once
    (LINT-10) keep the first of each group. They must agree, or a duplicate
    would silence a documentation finding it did not cover.
    """
    return group_by_signature(objects, object_key, lambda obj: obj.signature_key)


def distinct(objects: Iterable[SchemaObject]) -> list[SchemaObject]:
    """The first definition of each object, in source order.

    A rule that reports a property of the *object* — it has no primary key, it
    carries no ``COMMENT``, its name is not snake_case — reports it once
    however many times the object is defined. The second definition is
    ``build_001``'s finding and nobody else's: repeating every other rule
    against it turned one mistake into N identical ones, halved a project's
    documentation backlog the day it deduplicated a file, and put identities in
    baselines that existed only because of the duplication (LINT-10).

    A rule whose subject is the *statement* rather than the object — which
    schema does this ``CREATE`` land in — reads the objects directly, because
    for it a second definition really is a second thing to answer for.
    """
    return [group[0] for group in group_definitions(objects)]


def _statement_key(obj: SchemaObject) -> tuple[str, str | None, str, Signature | None]:
    """What makes two inventory entries the same ``CREATE`` statement.

    Not :func:`object_key`: its caller walks two parses of the *same* text, so
    the exact signature is available on both sides and the wildcard that keeps
    ``object_key`` a bucket would only make this laxer. What it wants is the
    opposite — to stop at the first pair that disagrees.
    """
    return (obj.kind, obj.folded_schema, obj.folded_name, obj.signature_key)


def attribute_files(inventory: Inventory, located: Sequence[SchemaObject]) -> None:
    """Tell a whole-build inventory which file each of its objects came from.

    :func:`build_inventory` reads the concatenated build as one string, so a
    ``COMMENT ON`` in one file resolves against a ``CREATE`` in another — and
    no object knows its file, only its line in a generated artefact nobody
    edits. ``duplicates.inventory_files`` knows every file and nothing about
    the others. Both walk the same statements in the same order, so this copies
    the file and the in-file line across, and stops at the first pair that
    disagrees rather than guessing: a finding with no location is honest, a
    finding pointing at the wrong file is not.

    The columns are matched **by name**, not by position. The two inventories
    walk the same statements but do not hold the same columns: an
    ``ALTER TABLE … DROP COLUMN`` in a *second* file is folded into the
    whole-build table and not into that file's own, so the whole-build table is
    a column shorter and a positional copy hands every column after the dropped
    one its predecessor's line. A column the creating file has not got — one an
    ``ALTER`` elsewhere added — keeps the line it already has, which is a line
    in a generated artefact and the most this can honestly say about it.
    """
    for obj, source in zip(inventory.objects, located, strict=False):
        if _statement_key(obj) != _statement_key(source):
            return
        obj.file = source.file
        obj.line = source.line
        obj.statement_line = source.statement_line
        source_lines = {column.folded: column.line for column in source.columns}
        obj.columns = [
            replace(column, line=source_lines[column.folded])
            if column.folded in source_lines
            else column
            for column in obj.columns
        ]
