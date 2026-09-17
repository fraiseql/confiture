"""Helpers shared by the AST walkers that read DDL.

The replica classifier (``core/replica/classifier.py``) and the change-set
walker (``core/change_set.py``) feed two verdicts — replica forward-compatibility
and risk tier — from the same pglast nodes. What "nullable", "has a default" and
"the type as written" mean must be one definition, so it lives here.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any, Literal

from pglast import ast as _pg_ast

from confiture.core._pglast_enums import member as _pg_member

_CONSTR_NOTNULL = _pg_member("ConstrType", "CONSTR_NOTNULL")
_CONSTR_DEFAULT = _pg_member("ConstrType", "CONSTR_DEFAULT")

# Resolved BY NAME, never by literal ordinal (#192).
_AT_ADD_COLUMN = _pg_member("AlterTableType", "AT_AddColumn")
_AT_DROP_COLUMN = _pg_member("AlterTableType", "AT_DropColumn")
_AT_ALTER_COLUMN_TYPE = _pg_member("AlterTableType", "AT_AlterColumnType")
_AT_ADD_CONSTRAINT = _pg_member("AlterTableType", "AT_AddConstraint")
_CONSTR_PRIMARY = _pg_member("ConstrType", "CONSTR_PRIMARY")


def walk_nodes(node: Any) -> Iterator[Any]:
    """Every parse node under ``node``, itself included, in source order.

    pglast nodes carry their children in ``__slots__``, singly or in a tuple,
    so "walk the tree" is the same three lines wherever it is needed. It lives
    here because it is the only piece the DDL walkers were still each writing
    for themselves.
    """
    if isinstance(node, list | tuple):
        for item in node:
            yield from walk_nodes(item)
        return
    if not isinstance(node, _pg_ast.Node):
        return
    yield node
    for slot in node.__slots__:
        child = getattr(node, slot, None)
        if child is not None and not isinstance(child, str | int | float | bool | bytes):
            yield from walk_nodes(child)


@dataclass(frozen=True)
class ColumnEdit:
    """What one ``AlterTableCmd`` does to a table's columns, in no reader's vocabulary.

    A build-from-DDL tree may append an ``ALTER TABLE`` rather than edit the
    ``CREATE TABLE``, so what a database ends up with is the two together — and
    two readers have to see it: the lint inventory (``core/linting/inventory.py``)
    and the differ (``core/differ.py``). Their object models share nothing, so
    what they share is this *decision*; each applies it to its own types.

    ``kind`` is the decision. ``column`` names the target for every kind but
    ``add``, where the name is inside ``coldef`` — ``AT_AlterColumnType`` puts it
    on ``cmd.name`` and leaves the ``ColumnDef`` anonymous, and
    ``AT_AddColumn`` does the opposite. ``default`` carries the expression of a
    ``SET DEFAULT``.

    ``ADD COLUMN IF NOT EXISTS`` is the same edit as ``ADD COLUMN``:
    ``cmd.missing_ok`` is deliberately not carried, because an expected schema
    records what a column *is*, not whether the tree guarded its creation. The
    day something needs to tell them apart, this is the docstring that was
    wrong.

    A cmd this module does not model yields ``None`` — never a silently-empty
    edit, which is how a renumbered enum member disappeared in #192.
    """

    kind: Literal["add", "drop", "retype"]
    column: str | None = None
    coldef: Any | None = None
    default: Any | None = None


def _is_column_def(definition: Any) -> bool:
    return definition is not None and type(definition).__name__ == "ColumnDef"


def _added_column(cmd: Any) -> ColumnEdit | None:
    definition = getattr(cmd, "def_", None)
    return ColumnEdit("add", coldef=definition) if _is_column_def(definition) else None


def _dropped_column(cmd: Any) -> ColumnEdit | None:
    name = getattr(cmd, "name", None)
    return ColumnEdit("drop", column=str(name)) if name else None


def _retyped_column(cmd: Any) -> ColumnEdit | None:
    definition = getattr(cmd, "def_", None)
    name = getattr(cmd, "name", None)
    if not name or not _is_column_def(definition):
        return None
    return ColumnEdit("retype", column=str(name), coldef=definition)


#: ``AlterTableType`` member -> how to read one cmd of that subtype. A table
#: rather than an ``elif`` chain so that adding a subtype is a row, and so that
#: the set of subtypes folded is something a reader can see at a glance.
_COLUMN_EDITS: dict[int, Callable[[Any], ColumnEdit | None]] = {
    _AT_ADD_COLUMN: _added_column,
    _AT_DROP_COLUMN: _dropped_column,
    _AT_ALTER_COLUMN_TYPE: _retyped_column,
}


def column_edit(cmd: Any) -> ColumnEdit | None:
    """What ``cmd`` does to a table's columns, or ``None`` for a subtype not modelled.

    Which subtypes those are, and why each of the other ~60 is not one, is
    :data:`FOLDED` / :data:`MODELLED_ELSEWHERE` / :data:`NOT_AN_EXPECTED_SCHEMA_FACT`
    below — enumerated against pglast's own enum by
    ``tests/unit/test_alter_subtypes_are_exhaustive.py``.
    """
    build = _COLUMN_EDITS.get(enum_int(getattr(cmd, "subtype", None)))
    return build(cmd) if build is not None else None


def adds_primary_key(cmd: Any) -> bool:
    """Whether ``cmd`` is an ``ADD CONSTRAINT … PRIMARY KEY``.

    Not a :class:`ColumnEdit`: a table-level constraint is the table's fact, not
    a column's, and folding it into the column vocabulary would make every
    reader unpack something it did not ask for. It lives here for the same
    reason ``column_edit`` does — one module knows what an ``AlterTableType``
    member means, because a literal ordinal silently stopped matching once
    already (#192).
    """
    if enum_int(getattr(cmd, "subtype", None)) != _AT_ADD_CONSTRAINT:
        return False
    definition = getattr(cmd, "def_", None)
    return enum_int(getattr(definition, "contype", None)) == _CONSTR_PRIMARY


def routine_body(stmt: Any) -> tuple[str | None, str | None]:
    """``(language, body text)`` of a ``CreateFunctionStmt``, both as written.

    The body of a ``LANGUAGE c`` routine is a shared-object symbol rather than
    SQL, which is why the language comes back with it: every caller has to
    decide what the text it is holding actually is.
    """
    language: str | None = None
    body: str | None = None
    for opt in getattr(stmt, "options", None) or ():
        args = opt.arg if isinstance(opt.arg, tuple | list) else [opt.arg]
        values = [getattr(a, "sval", None) for a in args]
        if opt.defname == "language":
            language = values[0].lower() if values and values[0] else None
        elif opt.defname == "as":
            body = values[0] if values else None
    return language, body


def enum_int(value: object) -> int | None:
    """The ordinal of a pglast enum value (or ``None`` when it is not one)."""
    if value is None:
        return None
    inner = getattr(value, "value", value)
    try:
        return int(inner)
    except (TypeError, ValueError):
        return None


def relation_parts(relation: object) -> tuple[str | None, str | None]:
    """``(schemaname, relname)`` of a pglast ``RangeVar``, as pglast spells them."""
    if relation is None:
        return (None, None)
    return (getattr(relation, "schemaname", None), getattr(relation, "relname", None))


def qualified_relname(relation: object) -> str | None:
    """``schema.name`` (schema only when present) of a ``RangeVar``, as pglast spells it."""
    if relation is None:
        return None
    relname = getattr(relation, "relname", None)
    if not relname:
        return None
    # pglast has already folded unquoted identifiers; a quoted "MyTable" keeps its case.
    schema = getattr(relation, "schemaname", None)
    return f"{schema}.{relname}" if schema else str(relname)


def name_parts(raw: Any) -> str | None:
    """Join a pglast list of ``String`` name parts into a dotted identifier."""
    parts = [str(getattr(part, "sval", part)) for part in raw or ()]
    return ".".join(part.lower() for part in parts if part) or None


def column_is_not_null(coldef: object) -> bool:
    if bool(getattr(coldef, "is_not_null", False)):
        return True
    for c in getattr(coldef, "constraints", None) or ():
        if enum_int(getattr(c, "contype", None)) == _CONSTR_NOTNULL:
            return True
    return False


def column_has_default(coldef: object) -> bool:
    if getattr(coldef, "raw_default", None) is not None:
        return True
    for c in getattr(coldef, "constraints", None) or ():
        if enum_int(getattr(c, "contype", None)) == _CONSTR_DEFAULT:
            return True
    return False


def type_name(type_node: Any) -> str | None:
    """Render a pglast ``TypeName`` back to ``varchar(50)`` / ``numeric(10,2)[]``.

    The ``pg_catalog`` qualifier the parser adds is dropped; the internal spelling
    (``int8``) is left alone, since :mod:`confiture.core.type_lattice` aliases it.

    The array bounds are **not** dropped. They live on ``arrayBounds`` rather
    than in ``names``, and reading only ``names`` made ``int[]`` render ``int4`` —
    the same string as ``int``. Both callers compose this with ``canonical_type``
    over an ``ALTER COLUMN … TYPE``, so a column going ``varchar(50)`` to
    ``text[]`` was captured as ``text`` and compared as a free, rewrite-less
    widening (#275).
    """
    if type_node is None:
        return None
    parts = [str(getattr(part, "sval", part)) for part in getattr(type_node, "names", None) or ()]
    names = [part for part in parts if part and part != "pg_catalog"]
    if not names:
        return None
    name = ".".join(names)
    mods = [
        str(ival)
        for ival in (
            getattr(getattr(mod, "val", None), "ival", None)
            for mod in getattr(type_node, "typmods", None) or ()
        )
        if ival is not None
    ]
    bounds = "[]" * len(getattr(type_node, "arrayBounds", None) or ())
    return (f"{name}({', '.join(mods)})" if mods else name) + bounds
