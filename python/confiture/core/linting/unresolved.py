"""``build_003``: a body names an object the build does not create (#246).

:mod:`confiture.core.linting.references` says what a body names.
:mod:`confiture.core.linting.inventory` says what the build creates. This is
the subtraction, and the answer to "then what did you miss": the reporter's
routine read ``app.tv_summary`` and called ``app.fn_refresh_summary``, no file
created either, and the routine had never completed a call.

The inventory is the *whole build*, not one file, so an object created three
files later resolves: file order is build order, not resolution order. Only a
name absent from the entire build reports.

A finding is one unresolved name in one referring object — its identity carries
both, because six unresolved names in one routine are six things to fix and one
of them being fixed must not retire the other five from a ``--baseline``.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from fnmatch import fnmatch
from typing import Any

from confiture.core.linting.inventory import KIND_KEYWORD, SchemaObject
from confiture.core.linting.references import RELATION, ROUTINE, Reference
from confiture.core.linting.schema_linter import LintViolation, RuleSeverity

RULE_ID = "build_003"

#: What a ``RangeVar`` can name: everything that occupies a relation's namespace.
RELATION_KINDS: frozenset[str] = frozenset({"table", "view", "matview", "sequence"})

#: What a call can name.
ROUTINE_KINDS: frozenset[str] = frozenset({"function", "procedure", "aggregate"})

#: Schemas PostgreSQL ships. No build creates them, so a reference into one is
#: never a finding — ``pg_catalog.now()`` is the whole point of writing it.
BUILTIN_SCHEMAS: frozenset[str] = frozenset({"pg_catalog", "information_schema"})

#: How a finding names the pair it is about: the object that refers, and the
#: name it refers to. ASCII, because the baseline file is JSON a human edits.
JOIN = " -> "


@dataclass(frozen=True)
class BuildCatalogue:
    """What one build creates, asked the way a reference asks.

    Names are pglast's folded spelling on both sides, so the comparison is the
    one PostgreSQL would make. An object created without a schema qualifier
    matches a qualified reference and vice versa — the same "a missing schema
    on either side matches any" rule :meth:`Inventory.find_all` applies, so a
    schema-less ``CREATE`` is reported once, by ``qual_002``, and not a second
    time here.
    """

    relations: frozenset[tuple[str | None, str]]
    routines: frozenset[tuple[str | None, str]]

    @classmethod
    def of(cls, objects: Iterable[SchemaObject]) -> BuildCatalogue:
        entries = [(o.kind, o.folded_schema, o.folded_name) for o in objects]
        return cls(
            relations=frozenset((s, n) for k, s, n in entries if k in RELATION_KINDS),
            routines=frozenset((s, n) for k, s, n in entries if k in ROUTINE_KINDS),
        )

    def creates(self, reference: Reference) -> bool:
        """Whether the build creates the object this reference names."""
        names = self.relations if reference.kind == RELATION else self.routines
        if reference.schema is None:
            return any(name == reference.name for _, name in names)
        return (reference.schema, reference.name) in names or (None, reference.name) in names


def _reportable(reference: Reference) -> bool:
    """Whether this reference is one the build could ever have created."""
    if reference.dynamic:
        return False
    return reference.schema not in BUILTIN_SCHEMAS


def _noun(reference: Reference) -> str:
    return "relation" if reference.kind == RELATION else "routine"


def _finding(file: str | None, reference: Reference) -> LintViolation:
    referrer_noun = KIND_KEYWORD.get(reference.referrer_kind, reference.referrer_kind).capitalize()
    return LintViolation(
        rule_id=RULE_ID,
        rule_name="Unresolved Reference",
        severity=RuleSeverity.WARNING,
        object_type=reference.referrer_kind,
        object_name=f"{reference.referrer}{JOIN}{reference.qualified}",
        message=(
            f"{referrer_noun} '{reference.referrer}' references "
            f"{_noun(reference)} '{reference.qualified}', and no file in the build creates it"
        ),
        file_path=file,
        line_number=reference.line if reference.line_is_exact else reference.referrer_line,
        suggested_fix=(f"Create '{reference.qualified}' in the schema tree, or correct the name."),
    )


def unresolved_references(
    located: Iterable[tuple[str | None, Reference]],
    objects: Sequence[SchemaObject],
    *,
    ignore: Sequence[str] = (),
) -> list[tuple[str | None, Reference]]:
    """The references tiers (a) and (c) could not answer, with their files.

    *located* is every reference with the file it was written in; *objects* is
    the whole build's inventory. *ignore* is ``lint.ignore_objects``, matched
    with :func:`fnmatch.fnmatch` against ``schema.name`` as written.

    What comes back is what the live tier is for. Handing it back rather than
    turning it straight into findings is what lets the caller consult a
    database *only when there is something to ask* — a clean tree opens no
    connection and reports no degradation, because none of its answers was
    missing.
    """
    catalogue = BuildCatalogue.of(objects)
    return [
        (file, reference)
        for file, reference in located
        if _reportable(reference)
        and not catalogue.creates(reference)
        and not _ignored(reference, ignore)
    ]


def _ignored(reference: Reference, patterns: Sequence[str]) -> bool:
    return any(fnmatch(reference.qualified, pattern) for pattern in patterns)


@dataclass(frozen=True)
class LiveCatalogue:
    """What a database says exists, for the names the build could not answer.

    Tier (b): an object created by a migration, or owned by an extension, is
    real and absent from the DDL tree. One round trip asks about every
    outstanding name at once — ``to_regclass`` for relations, ``pg_proc`` for
    routines — because a query per name would make the rule's cost a function
    of how wrong the schema is.
    """

    relations: frozenset[str]
    routines: frozenset[str]

    def holds(self, reference: Reference) -> bool:
        names = self.relations if reference.kind == RELATION else self.routines
        return reference.qualified in names


#: One statement, both kinds, each row tagged with which catalogue answered.
_LIVE_QUERY = """
SELECT 'relation' AS kind, name
  FROM unnest(%(relations)s::text[]) AS name
 WHERE to_regclass(name) IS NOT NULL
UNION ALL
SELECT 'routine' AS kind, n.nspname || '.' || p.proname
  FROM pg_proc p
  JOIN pg_namespace n ON n.oid = p.pronamespace
 WHERE n.nspname || '.' || p.proname = ANY(%(routines)s::text[])
"""


def probe_live(
    connection: Any, candidates: Iterable[tuple[str | None, Reference]]
) -> LiveCatalogue:
    """Ask an open connection which of *candidates* it actually has."""
    wanted: dict[str, set[str]] = {RELATION: set(), ROUTINE: set()}
    for _file, reference in candidates:
        wanted[RELATION if reference.kind == RELATION else ROUTINE].add(reference.qualified)
    rows = connection.execute(
        _LIVE_QUERY,
        {"relations": sorted(wanted[RELATION]), "routines": sorted(wanted[ROUTINE])},
    ).fetchall()
    return LiveCatalogue(
        relations=frozenset(name for kind, name in rows if kind == "relation"),
        routines=frozenset(name for kind, name in rows if kind == "routine"),
    )


def reference_findings(
    candidates: Iterable[tuple[str | None, Reference]],
) -> list[LintViolation]:
    """One ``build_003`` per unresolved name per referring object, in source order."""
    return [_finding(file, reference) for file, reference in candidates]
