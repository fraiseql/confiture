"""Name-resolved PostgreSQL parse-node enum members (issue #192).

A hardcoded ordinal — ``_AT_DROP_COLUMN = 14`` — binds a visitor to one grammar.
PostgreSQL 18 inserted a member into ``AlterTableType``, so pglast 8 numbers
everything at index >= 13 one lower than earlier majors do. A comparison against a
literal past that point misses, the ``elif`` chain falls through, and the
operation is **silently dropped** rather than misclassified:
``ALTER TABLE t DROP COLUMN c`` classifies to ``[]``.

That is the worst available failure mode here. ``window_safe`` is computed from
the *presence* of ``PFLIGHT_REPLICA_*`` findings, so a dropped ``DropColumn``
turns a replica-unsafe migration into ``window_safe: true`` — a false safe
verdict from the safety gate.

Resolving by name makes the binding version-independent. The declarative
``REQUIRED_MEMBERS`` table below is the single place a new dependency is
declared, so ``tests/unit/test_pglast_enum_binding.py`` picks it up
automatically rather than needing to be kept in sync by hand.

pglast is a dependency (D13), so this module imports it at module scope.
"""

from __future__ import annotations

import itertools
from importlib import metadata
from typing import Final

from pglast import enums

from confiture.exceptions import ConfigurationError

__all__ = [
    "MISSING_MEMBERS",
    "REQUIRED_MEMBERS",
    "enums_are_usable",
    "member",
]

# Every parse-node enum member confiture's AST paths depend on, by enum.
# Adding a constant to a visitor means adding its name here — that is what
# keeps the guard test exhaustive without hand-maintained duplication.
REQUIRED_MEMBERS: Final[dict[str, tuple[str, ...]]] = {
    "AlterTableType": (
        "AT_AddColumn",
        "AT_DropColumn",
        "AT_AlterColumnType",
        "AT_AddConstraint",
        "AT_DropConstraint",
        "AT_ChangeOwner",
        "AT_ColumnDefault",
        "AT_SetNotNull",
        "AT_DropNotNull",
    ),
    "ConstrType": (
        "CONSTR_NOTNULL",
        "CONSTR_DEFAULT",
        "CONSTR_CHECK",
        "CONSTR_PRIMARY",
        "CONSTR_UNIQUE",
        "CONSTR_FOREIGN",
        "CONSTR_IDENTITY",
        "CONSTR_GENERATED",
        "CONSTR_ATTR_DEFERRABLE",
        "CONSTR_ATTR_NOT_DEFERRABLE",
        "CONSTR_ATTR_DEFERRED",
        "CONSTR_ATTR_IMMEDIATE",
    ),
    "ObjectType": (
        "OBJECT_TABLE",
        "OBJECT_VIEW",
        "OBJECT_MATVIEW",
        "OBJECT_INDEX",
        "OBJECT_FUNCTION",
        "OBJECT_PROCEDURE",
        "OBJECT_ROUTINE",
        "OBJECT_AGGREGATE",
        "OBJECT_TYPE",
        "OBJECT_SCHEMA",
        "OBJECT_SEQUENCE",
        "OBJECT_COLUMN",
        "OBJECT_TRIGGER",
        "OBJECT_POLICY",
        "OBJECT_EXTENSION",
        "OBJECT_DOMAIN",
        "OBJECT_RULE",
        "OBJECT_FOREIGN_TABLE",
    ),
    "SetOperation": ("SETOP_NONE",),
    "SortByDir": ("SORTBY_DEFAULT",),
    "SortByNulls": ("SORTBY_NULLS_DEFAULT",),
    "VariableSetKind": (
        "VAR_SET_VALUE",
        "VAR_SET_CURRENT",
    ),
}

# Members the installed pglast does not define — an upstream release removed or
# renamed something confiture walks. :func:`enums_are_usable` refuses to proceed
# while this is non-empty, so a partially-resolvable enum surface is a
# configuration error rather than silently dropped operations.
MISSING_MEMBERS: Final[list[str]] = []

# Ordinals PostgreSQL will never use, handed out one per unresolved member so
# two sentinels can never compare equal to each other or to a real subtype.
_sentinels = itertools.count(-1000, -1)


def member(enum_name: str, member_name: str) -> int:
    """Resolve ``pglast.enums.<enum_name>.<member_name>`` to its ordinal.

    Returns a unique never-matching sentinel when the member has disappeared
    upstream, which is also recorded in :data:`MISSING_MEMBERS`. pglast itself is
    a dependency (D13) and imported at module scope, so "not installed" is not a
    case this has to answer for.
    """
    try:
        return int(getattr(getattr(enums, enum_name), member_name))
    except AttributeError:
        MISSING_MEMBERS.append(f"{enum_name}.{member_name}")
        return next(_sentinels)


def enums_are_usable() -> bool:
    """True when every declared member resolved against the installed pglast.

    Half-resolved enums mean silently-dropped operations (#192), so a pglast
    that lacks a member confiture walks is a configuration error naming the
    version, not a degrade.

    Raises:
        ConfigurationError: the installed pglast lacks declared members.
    """
    if MISSING_MEMBERS:
        raise ConfigurationError(
            f"pglast {metadata.version('pglast')} does not expose "
            f"{', '.join(MISSING_MEMBERS)}; confiture cannot walk DDL with it.",
            error_code="CONFIG_011",
            resolution_hint="Install a pglast release confiture supports (pglast>=6.0, current major).",
        )
    return True
