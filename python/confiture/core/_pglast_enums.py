"""Name-resolved PostgreSQL parse-node enum members (issue #192).

Confiture's AST visitors used to compare ``cmd.subtype`` against hardcoded
ordinals — ``_AT_DROP_COLUMN = 14`` and friends. PostgreSQL 18 inserted a member
into ``AlterTableType``, so pglast 8 renumbered everything at index >= 13 down by
one. Every comparison past that point missed, the ``elif`` chains fell through,
and the operation was **silently dropped** rather than misclassified:
``ALTER TABLE t DROP COLUMN c`` classified to ``[]``.

That is the worst available failure mode here. ``window_safe`` is computed from
the *presence* of ``PFLIGHT_REPLICA_*`` findings, so a dropped ``DropColumn``
turns a replica-unsafe migration into ``window_safe: true`` — a false safe
verdict from the safety gate.

Resolving by name makes the binding version-independent. The declarative
``REQUIRED_MEMBERS`` table below is the single place a new dependency is
declared, so ``tests/unit/test_pglast_enum_binding.py`` picks it up
automatically rather than needing to be kept in sync by hand.

The ``[ast]`` extra is optional, so nothing here may import pglast at module
scope unconditionally — a regex-fallback install must still import cleanly.
"""

from __future__ import annotations

import itertools
from typing import Final

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
    ),
    "ObjectType": (
        "OBJECT_TABLE",
        "OBJECT_VIEW",
        "OBJECT_MATVIEW",
        "OBJECT_INDEX",
        "OBJECT_FUNCTION",
        "OBJECT_PROCEDURE",
        "OBJECT_TYPE",
        "OBJECT_SCHEMA",
        "OBJECT_SEQUENCE",
        "OBJECT_COLUMN",
        "OBJECT_TRIGGER",
        "OBJECT_POLICY",
        "OBJECT_EXTENSION",
        "OBJECT_DOMAIN",
        "OBJECT_RULE",
    ),
}

# Members that could not be resolved *while pglast was importable* — i.e. an
# upstream release removed or renamed something confiture walks. Consumers gate
# their AST path on this being empty, so a partially-resolvable enum surface
# degrades to the regex backend instead of silently dropping operations.
MISSING_MEMBERS: Final[list[str]] = []

# Ordinals PostgreSQL will never use, handed out one per unresolved member so
# two sentinels can never compare equal to each other or to a real subtype.
_sentinels = itertools.count(-1000, -1)


def member(enum_name: str, member_name: str) -> int:
    """Resolve ``pglast.enums.<enum_name>.<member_name>`` to its ordinal.

    Returns a unique never-matching sentinel when pglast is not installed (the
    AST path is inert then anyway) or when the member has disappeared upstream.
    The latter case is also recorded in :data:`MISSING_MEMBERS`.
    """
    try:
        from pglast import enums
    except ImportError:
        # Regex-fallback install: the AST path never runs, so the value is
        # unobservable. Not a defect — do not record it as missing.
        return next(_sentinels)

    try:
        return int(getattr(getattr(enums, enum_name), member_name))
    except AttributeError:
        MISSING_MEMBERS.append(f"{enum_name}.{member_name}")
        return next(_sentinels)


def enums_are_usable() -> bool:
    """True when every declared member resolved against the installed pglast.

    A consumer whose AST path depends on these must check this before trusting
    it. Half-resolved enums mean silently-dropped operations, which is what
    #192 was.
    """
    return not MISSING_MEMBERS
