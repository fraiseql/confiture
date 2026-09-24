"""``build_003``: a body names an object the build does not create (#246);
``build_004``: a statement needs, when it runs, an object the build creates later (#383).

:mod:`confiture.core.linting.references` says what a body names.
:mod:`confiture.core.linting.inventory` says what the build creates. This is
the subtraction: a routine that reads ``app.tv_summary`` and calls
``app.fn_refresh_summary`` when no file creates either still builds, and fails
on its first call.

The inventory is the *whole build*, not one file, so an object created three
files later resolves: file order is build order, not resolution order. Only a
name absent from the entire build reports.

A finding is one unresolved name in one referring object — its identity carries
both, because six unresolved names in one routine are six things to fix and one
of them being fixed must not retire the other five from a ``--baseline``.

An unqualified name is not judged unless ``lint.search_path`` says where to
look, and an unqualified *routine* call is not judged even then: ``pg_catalog``
is on every search path, so ``now()`` and ``count()`` would be findings and the
rule would be unusable (#246).

``build_004`` asks the same question with order added, over the same references
and the same inventory: not "does the build create it" but "does it create it
before the statement that needs it". A view, a ``LANGUAGE sql`` body, a
default, a check, an index expression, a trigger's function and a foreign key
are resolved when their statement runs; a PL/pgSQL body is resolved when it
first runs, so it may name anything the build creates. The order is the one the
build emits — its files in build order, each top to bottom — and a foreign key
the builder's two-pass mode moves to the end is not a forward reference. Only
an object the build creates is judged; one it never creates is ``build_003``'s.
Which of these PostgreSQL refuses was settled by applying each case to an empty
database (``tests/integration/test_forward_reference_oracle.py``), not assumed.
"""

from __future__ import annotations

from bisect import bisect_left
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from fnmatch import fnmatch
from typing import Any

from confiture.core import live_catalog
from confiture.core.linting.inventory import KIND_KEYWORD, SchemaObject
from confiture.core.linting.references import (
    AT_CREATE_IF_CHECKED,
    AT_RUN,
    RELATION,
    ROUTINE,
    Reference,
    ReferenceScan,
)
from confiture.core.linting.schema_linter import LintViolation, RuleSeverity

RULE_ID = "build_003"
FORWARD_RULE_ID = "build_004"

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

#: What the message adds when the line is the routine's rather than the
#: statement's. Said, not implied: a reader who opens that line and finds a
#: ``CREATE`` there would otherwise conclude the rule is simply wrong.
INEXACT_LINE = (
    " — the line given is the routine's, not the statement's: "
    "the body's position in the file could not be established"
)


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

    def creates(self, reference: Reference, search_path: Sequence[str]) -> bool:
        """Whether the build creates any of the objects this reference could mean."""
        names = self.relations if reference.kind == RELATION else self.routines
        return any(
            pair in names or (None, pair[1]) in names
            for pair in candidates_for(reference, search_path)
        )


def candidates_for(reference: Reference, search_path: Sequence[str]) -> tuple[tuple[str, str], ...]:
    """``(schema, name)`` for every object this reference could mean.

    Empty means "do not judge it": an unqualified name with no declared search
    path could be anything, and an unqualified routine could always be a
    ``pg_catalog`` built-in, which no configuration makes enumerable.
    """
    if reference.schema is not None:
        return ((reference.schema, reference.name),)
    if reference.kind != RELATION or not search_path:
        return ()
    return tuple((schema, reference.name) for schema in search_path)


def _qualified(pair: tuple[str, str]) -> str:
    return f"{pair[0]}.{pair[1]}"


def _reportable(reference: Reference, search_path: Sequence[str]) -> bool:
    """Whether this reference is one the build could ever have created."""
    if reference.dynamic or reference.schema in BUILTIN_SCHEMAS:
        return False
    return bool(candidates_for(reference, search_path))


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
            + ("" if reference.line_is_exact else INEXACT_LINE)
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
    search_path: Sequence[str] = (),
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
        if _reportable(reference, search_path)
        and not catalogue.creates(reference, search_path)
        and not _ignored(reference, patterns=ignore, search_path=search_path)
    ]


def _ignored(reference: Reference, *, patterns: Sequence[str], search_path: Sequence[str]) -> bool:
    names = [reference.qualified, *(_qualified(p) for p in candidates_for(reference, search_path))]
    return any(fnmatch(name, pattern) for name in names for pattern in patterns)


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

    def holds(self, reference: Reference, search_path: Sequence[str] = ()) -> bool:
        names = self.relations if reference.kind == RELATION else self.routines
        return any(_qualified(p) in names for p in candidates_for(reference, search_path))


def probe_live(
    connection: Any,
    candidates: Iterable[tuple[str | None, Reference]],
    search_path: Sequence[str] = (),
) -> LiveCatalogue:
    """Ask an open connection which of *candidates* it actually has."""
    wanted: dict[str, set[str]] = {RELATION: set(), ROUTINE: set()}
    for _file, reference in candidates:
        bucket = wanted[RELATION if reference.kind == RELATION else ROUTINE]
        bucket.update(_qualified(p) for p in candidates_for(reference, search_path))
    relations, routines = live_catalog.existing_names(
        connection, relations=wanted[RELATION], routines=wanted[ROUTINE]
    )
    return LiveCatalogue(relations=relations, routines=routines)


def reference_findings(
    candidates: Iterable[tuple[str | None, Reference]],
) -> list[LintViolation]:
    """One ``build_003`` per unresolved name per referring object, in source order."""
    return [_finding(file, reference) for file, reference in candidates]


#: Where a statement is in the build: its file's place in build order, and its line.
Position = tuple[int, int]


@dataclass(frozen=True)
class _Created:
    position: Position
    file: str | None
    line: int


def _first_created(
    objects: Sequence[SchemaObject], order: dict[str | None, int]
) -> dict[tuple[str, str | None, str], _Created]:
    """Where the build first creates each relation and routine, by kind, schema and name.

    The first ``CREATE`` is the one that counts: an ``OR REPLACE`` or
    ``IF NOT EXISTS`` later in the build does not make an object exist sooner.
    """
    first: dict[tuple[str, str | None, str], _Created] = {}
    for obj in objects:
        bucket = (
            RELATION
            if obj.kind in RELATION_KINDS
            else ROUTINE
            if obj.kind in ROUTINE_KINDS
            else None
        )
        if bucket is None or obj.file not in order:
            continue
        created = _Created((order[obj.file], obj.statement_line), obj.file, obj.statement_line)
        key = (bucket, obj.folded_schema, obj.folded_name)
        if key not in first or created.position < first[key].position:
            first[key] = created
    return first


def _bodies_checked(
    scans: Sequence[tuple[str | None, ReferenceScan]],
) -> tuple[list[Position], list[bool]]:
    """Every ``SET check_function_bodies`` in build order, and what it set."""
    events = sorted(
        ((index, line), on)
        for index, (_label, scan) in enumerate(scans)
        for line, on in scan.body_checks
    )
    return [position for position, _ in events], [on for _, on in events]


def _checked_at(position: Position, events: tuple[list[Position], list[bool]]) -> bool:
    """Whether ``check_function_bodies`` is on when the statement at *position* runs."""
    at = bisect_left(events[0], position)
    return True if at == 0 else events[1][at - 1]


def _needs_at_create(reference: Reference, *, two_pass: bool) -> bool:
    return (
        reference.resolves != AT_RUN
        and not reference.dynamic
        and reference.schema not in BUILTIN_SCHEMAS
        and not (reference.movable and two_pass)
    )


def forward_references(
    scans: Sequence[tuple[str | None, ReferenceScan]],
    objects: Sequence[SchemaObject],
    *,
    search_path: Sequence[str] = (),
    two_pass: bool = False,
) -> list[LintViolation]:
    """``build_004``: every name a statement needs when it runs that the build creates later.

    *scans* is each file's :class:`ReferenceScan` in build order, labelled as a
    finding names the file; *objects* the whole build's inventory, each object
    carrying its file's label. *two_pass* is ``build.two_pass``: the builder
    then moves every foreign key written in a ``CREATE TABLE`` to the end.
    """
    order = {label: index for index, (label, _scan) in enumerate(scans)}
    first = _first_created(objects, order)
    checks = _bodies_checked(scans)
    findings: list[LintViolation] = []
    seen: set[tuple[str | None, str, str, str]] = set()
    for index, (label, scan) in enumerate(scans):
        for reference in [*scan.references, *scan.clauses]:
            if not _needs_at_create(reference, two_pass=two_pass):
                continue
            # One finding per name per referring statement, as `build_003` has.
            pair = (label, reference.referrer, reference.kind, reference.qualified)
            if pair in seen:
                continue
            position = (index, reference.referrer_line)
            if reference.resolves == AT_CREATE_IF_CHECKED and not _checked_at(position, checks):
                continue
            bucket = RELATION if reference.kind == RELATION else ROUTINE
            created = [
                found
                for schema, name in candidates_for(reference, search_path)
                for found in (first.get((bucket, schema, name)), first.get((bucket, None, name)))
                if found is not None
            ]
            if not created:
                continue
            earliest = min(created, key=lambda c: c.position)
            # The same statement creates what it names: a table's foreign key
            # to itself, a routine that calls itself. PostgreSQL accepts both.
            if earliest.position <= position:
                continue
            seen.add(pair)
            findings.append(_forward_finding(label, reference, earliest))
    return findings


def _forward_finding(file: str | None, reference: Reference, created: _Created) -> LintViolation:
    referrer_noun = KIND_KEYWORD.get(reference.referrer_kind, reference.referrer_kind).capitalize()
    where = f"{created.file}:{created.line}" if created.file else f"line {created.line}"
    clause = f" (its {reference.clause})" if reference.clause else ""
    why = (
        " A LANGUAGE sql body is resolved when the function is created, while "
        "check_function_bodies is on; a LANGUAGE plpgsql body is resolved when it first runs."
        if reference.resolves == AT_CREATE_IF_CHECKED
        else ""
    )
    return LintViolation(
        rule_id=FORWARD_RULE_ID,
        rule_name="Forward Reference",
        severity=RuleSeverity.ERROR,
        object_type=reference.referrer_kind,
        object_name=f"{reference.referrer}{JOIN}{reference.qualified}",
        message=(
            f"{referrer_noun} '{reference.referrer}' needs {_noun(reference)} "
            f"'{reference.qualified}' when it is created{clause}, but the build first "
            f"creates it later, at {where}.{why}"
            + ("" if reference.line_is_exact else INEXACT_LINE)
        ),
        file_path=file,
        line_number=reference.line if reference.line_is_exact else reference.referrer_line,
        suggested_fix=(
            f"Create '{reference.qualified}' earlier in the build order than this statement, "
            "or move this statement after it."
        ),
    )
