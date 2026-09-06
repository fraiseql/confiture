"""Helpers shared by the AST walkers that read DDL (Phase 05).

The replica classifier (``core/replica/classifier.py``) and the change-set
walker (``core/change_set.py``) feed two verdicts — replica forward-compatibility
and risk tier — from the same pglast nodes. What "nullable", "has a default" and
"the type as written" mean must be one definition, so it lives here.
"""

from __future__ import annotations

from typing import Any

from confiture.core._pglast_enums import member as _pg_member

_CONSTR_NOTNULL = _pg_member("ConstrType", "CONSTR_NOTNULL")
_CONSTR_DEFAULT = _pg_member("ConstrType", "CONSTR_DEFAULT")


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
    """Render a pglast ``TypeName`` back to ``varchar(50)`` / ``numeric(10,2)``.

    The ``pg_catalog`` qualifier the parser adds is dropped; the internal spelling
    (``int8``) is left alone, since :mod:`confiture.core.type_lattice` aliases it.
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
    return f"{name}({', '.join(mods)})" if mods else name
