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

from bisect import bisect_left
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from fnmatch import fnmatch
from string.templatelib import Template
from typing import Any

import psycopg

from confiture.core import live_catalog
from confiture.core.linting.extensions import BuiltExtension
from confiture.core.linting.inventory import KIND_KEYWORD, SchemaObject
from confiture.core.linting.references import (
    AT_CREATE_IF_CHECKED,
    AT_RUN,
    RELATION,
    ROUTINE,
    Reference,
    ReferenceScan,
)
from confiture.core.linting.schema_linter import LintViolation, RuleSeverity, first_line
from confiture.core.schema_identity import DEFAULT_SCHEMA
from confiture.core.temp_database import maintenance_url
from confiture.exceptions import ConfiturError
from confiture.url_redaction import redact_url

RULE_ID = "build_003"
FORWARD_RULE_ID = "build_004"

#: What a ``RangeVar`` can name: everything that occupies a relation's namespace, a pg_tviews
#: TVIEW among them, in either spelling (#651).
RELATION_KINDS: frozenset[str] = frozenset({"table", "view", "matview", "sequence", "tview"})

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


def _finding(
    file: str | None, reference: Reference, note: str = "", provided: str = ""
) -> LintViolation:
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
            + provided
            + ("" if reference.line_is_exact else INEXACT_LINE)
            + (f"; {note}" if note else "")
        ),
        file_path=file,
        line_number=reference.line if reference.line_is_exact else reference.referrer_line,
        suggested_fix=(
            f"If an extension provides it: {note}. Otherwise create '{reference.qualified}' "
            "in the schema tree, or correct the name."
            if note
            else f"Create '{reference.qualified}' in the schema tree, or correct the name."
        ),
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


def _schemas(reference: Reference, search_path: Sequence[str]) -> list[str]:
    return [schema for schema, _name in candidates_for(reference, search_path)]


def split_by_extension(
    candidates: Iterable[tuple[str | None, Reference]],
    extensions: Sequence[BuiltExtension],
    search_path: Sequence[str] = (),
) -> tuple[list[tuple[str | None, Reference]], list[tuple[str | None, Reference]]]:
    """``(maybe_extension, missing)``: which outstanding references *extensions* may answer.

    A reference may be an extension's when a schema it could mean hosts one of
    *extensions*. Schemas compare in the parser's spelling, as
    :class:`BuildCatalogue` compares. Which extensions may loosen a verdict is
    the caller's choice: with no server to ask, only those whose ``SCHEMA`` is
    written, because where an unwritten one lands is not a fact the tree states.
    """
    hosts = {ext.schema for ext in extensions}
    maybe: list[tuple[str | None, Reference]] = []
    missing: list[tuple[str | None, Reference]] = []
    for pair in candidates:
        bucket = maybe if hosts.intersection(_schemas(pair[1], search_path)) else missing
        bucket.append(pair)
    return maybe, missing


def _creates(extensions: Sequence[BuiltExtension]) -> str:
    """``extensions ltree (f:1) and unaccent (f:2)``, CASCADE said where it was written."""
    named = [
        f"{ext.name} ({ext.where})" + (" (and what CASCADE installs)" if ext.cascade else "")
        for ext in extensions
    ]
    listed = named[0] if len(named) == 1 else f"{', '.join(named[:-1])} and {named[-1]}"
    return f"{'extension' if len(named) == 1 else 'extensions'} {listed}"


def unchecked_reason(
    unchecked: Sequence[tuple[str | None, Reference]],
    extensions: Sequence[BuiltExtension],
    why: str,
    search_path: Sequence[str] = (),
) -> str:
    """The one ``degraded`` reason for every reference an extension may answer and none checked.

    Grouped by schema, each reference under the first schema it could mean that
    hosts one of *extensions*, so one run says one thing however many schemas.
    """
    counts: dict[str, int] = {}
    for _file, reference in unchecked:
        schema = next(s for s in _schemas(reference, search_path) if _hosted(s, extensions))
        counts[schema] = counts.get(schema, 0) + 1
    groups = [
        f"{count} {'reference' if count == 1 else 'references'} into {schema}, where the build "
        f"creates {_creates([e for e in extensions if e.schema == schema])}"
        for schema, count in counts.items()
    ]
    verb = "was" if len(unchecked) == 1 else "were"
    return f"{', and '.join(groups)}, {verb} not checked: {why}"


def _hosted(schema: str, extensions: Sequence[BuiltExtension]) -> bool:
    return any(ext.schema == schema for ext in extensions)


def unwritten_note(
    reference: Reference,
    unwritten: Sequence[BuiltExtension],
    search_path: Sequence[str] = (),
    *,
    answered: bool = False,
) -> str:
    """What a finding adds when an extension with no ``SCHEMA`` clause might hold the name.

    The schema it lands in is the applying role's, so it never loosens a
    verdict; the finding says which extensions they are and how to have them
    asked. It names no schema to write: ``plpgsql`` belongs in ``pg_catalog``.
    *answered* says a scratch server was asked and could not create them.
    """
    if not unwritten or DEFAULT_SCHEMA not in _schemas(reference, search_path):
        return ""
    named = ", ".join(f"{ext.name} ({ext.where})" for ext in unwritten)
    if answered:
        return (
            f"the scratch server could not create extension(s) {named}, which have no SCHEMA "
            "clause, so confiture cannot tell whether one provides this (see the degraded entry)"
        )
    return (
        f"the build creates extension(s) {named} with no SCHEMA clause: write the schema each "
        "is installed in (SCHEMA …), or give a scratch server (--server-url, or scratch_url), "
        "so confiture can tell whether one provides this"
    )


def _not_provided(
    reference: Reference, asked: Sequence[BuiltExtension], search_path: Sequence[str]
) -> str:
    """``(not provided by extension(s) ltree, unaccent in public)``: the scratch was asked."""
    schemas = _schemas(reference, search_path)
    here = [ext for ext in asked if ext.schema in schemas]
    if not here:
        return ""
    where = ", ".join(dict.fromkeys(ext.schema for ext in here))
    return f" (not provided by extension(s) {', '.join(e.name for e in here)} in {where})"


def reference_findings(
    candidates: Iterable[tuple[str | None, Reference]],
    *,
    unwritten: Sequence[BuiltExtension] = (),
    asked: Sequence[BuiltExtension] = (),
    search_path: Sequence[str] = (),
    answered: bool = False,
) -> list[LintViolation]:
    """One ``build_003`` per unresolved name per referring object, in source order.

    *unwritten* are the extensions the build creates with no ``SCHEMA`` clause
    that no server answered for; a finding they might answer says so. *asked*
    are the extensions a scratch database created; a finding in their schema
    says the scratch was asked, and they do not provide it.
    """
    return [
        _finding(
            file,
            reference,
            unwritten_note(reference, unwritten, search_path, answered=answered),
            _not_provided(reference, asked, search_path),
        )
        for file, reference in candidates
    ]


#: Why the extension tier could not ask what the build's extensions provide.
NO_SCRATCH_SERVER = (
    "no scratch server is configured (--server-url, or scratch_url in the environment) "
    "to say what they provide"
)


class ScratchUnavailable(ConfiturError):
    """No scratch database could be built to ask; the message is the reason, credentials masked."""


@dataclass(frozen=True)
class ScratchAnswer:
    """What a scratch database holding the build's extensions says.

    ``failed`` maps each extension the scratch could not create to PostgreSQL's
    first error line: its references are not answered by ``catalogue``.
    ``after[i]`` is what the scratch held once the *i*-th extension's statement
    had run, so a name is attributed to the statement that made it exist
    (``build_004``, #747).
    """

    catalogue: LiveCatalogue
    failed: Mapping[str, str] = field(default_factory=dict)
    after: tuple[LiveCatalogue, ...] = ()


def scratch_names(
    server_url: str,
    extensions: Sequence[BuiltExtension],
    schemas: Iterable[str],
    candidates: Iterable[tuple[str | None, Reference]],
    search_path: Sequence[str] = (),
    *,
    connect_timeout: int,
) -> ScratchAnswer:
    """Build a scratch database holding only *schemas* and *extensions*, and ask it.

    The schemas are created by name, and each extension's own statement runs
    on its own, in build order, so one that fails costs only its own
    references; the scratch is asked again after each. The question is
    :func:`probe_live`'s: no catalog SQL here.

    Raises:
        ScratchUnavailable: the server did not answer within *connect_timeout*
            seconds, or would not create the scratch database.
    """
    # Reason: CLI start-up: the scratch lifecycle reads the builder, and is wanted only when an extension's reference is outstanding
    from confiture.core.expected_db import ExpectedSchemaDB

    masked = redact_url(server_url)
    try:
        # `TempDatabase` connects with no timeout: a server that is not there must cost seconds.
        # The maintenance database, as `TempDatabase` connects: only the server is used.
        with psycopg.connect(maintenance_url(server_url), connect_timeout=connect_timeout):
            pass
    except (psycopg.Error, OSError) as exc:
        raise ScratchUnavailable(
            f"no scratch server answered at {masked}: {first_line(exc)}"
        ) from exc
    try:
        with ExpectedSchemaDB(server_url).from_source(schema_sql="") as connection:
            for schema in sorted(schemas):
                connection.execute(t"CREATE SCHEMA IF NOT EXISTS {schema:i}")
            asked = list(candidates)
            failed: dict[str, str] = {}
            after: list[LiveCatalogue] = []
            for ext in extensions:
                try:
                    connection.execute(Template(ext.create_sql))
                except psycopg.Error as exc:
                    failed[ext.name] = first_line(exc)
                after.append(probe_live(connection, asked, search_path))
            final = after[-1] if after else probe_live(connection, asked, search_path)
            return ScratchAnswer(final, failed, tuple(after))
    except (psycopg.Error, OSError, ConfiturError) as exc:
        raise ScratchUnavailable(
            f"could not build a scratch database on {masked}: {first_line(exc)}"
        ) from exc


@dataclass(frozen=True)
class ExtensionTier:
    """What the extension tier leaves: findings, who was asked, and what it could not check."""

    missing: list[tuple[str | None, Reference]]
    asked: tuple[BuiltExtension, ...] = ()
    unwritten: tuple[BuiltExtension, ...] = ()
    reason: str | None = None
    #: A scratch database was built and asked: ``unwritten`` then failed in it.
    answered: bool = False


#: Asks a scratch database about the references it is handed, or raises ScratchUnavailable.
Ask = Callable[[list[tuple[str | None, Reference]]], ScratchAnswer]


def extension_tier(
    candidates: list[tuple[str | None, Reference]],
    extensions: Sequence[BuiltExtension],
    search_path: Sequence[str],
    ask: Ask | None,
) -> ExtensionTier:
    """The references still unresolved once the build's extensions have been accounted for.

    With *ask* (a scratch server is configured), every extension is asked,
    ``SCHEMA`` written or not, and a reference only reaches the scratch when one
    of its schemas hosts an extension. Without it, or when the scratch cannot be
    built, only an extension whose ``SCHEMA`` is written makes a reference
    unchecked rather than missing.
    """
    unwritten = tuple(ext for ext in extensions if not ext.schema_written)
    why = NO_SCRATCH_SERVER
    if ask is not None:
        maybe, _missing = split_by_extension(candidates, extensions, search_path)
        if not maybe:
            return ExtensionTier(candidates, unwritten=unwritten)
        try:
            answer = ask(maybe)
        except ScratchUnavailable as exc:
            why = str(exc)
        else:
            return _answered(candidates, maybe, extensions, answer, search_path)
    written = [ext for ext in extensions if ext.schema_written]
    unchecked, _missing = split_by_extension(candidates, written, search_path)
    return ExtensionTier(
        _without(candidates, unchecked),
        unwritten=unwritten,
        reason=unchecked_reason(unchecked, written, why, search_path) if unchecked else None,
    )


def _without(
    candidates: list[tuple[str | None, Reference]], gone: Iterable[tuple[str | None, Reference]]
) -> list[tuple[str | None, Reference]]:
    dropped = {id(pair) for pair in gone}
    return [pair for pair in candidates if id(pair) not in dropped]


def _answered(
    candidates: list[tuple[str | None, Reference]],
    maybe: list[tuple[str | None, Reference]],
    extensions: Sequence[BuiltExtension],
    answer: ScratchAnswer,
    search_path: Sequence[str],
) -> ExtensionTier:
    """A scratch answered: a name it holds resolves, and one it lacks is a finding.

    Unless an extension whose ``SCHEMA`` is written, in a schema the name could
    mean, failed to install: then the scratch never had the chance to hold it,
    and it is unchecked. One with no ``SCHEMA`` clause that failed never
    loosens a verdict: its references stay findings, carrying the hint.
    """
    failed = [ext for ext in extensions if ext.name in answer.failed]
    unchecked: list[tuple[str | None, Reference]] = []
    resolved: list[tuple[str | None, Reference]] = []
    for pair in maybe:
        schemas = _schemas(pair[1], search_path)
        if answer.catalogue.holds(pair[1], search_path):
            resolved.append(pair)
        elif any(ext.schema_written and ext.schema in schemas for ext in failed):
            unchecked.append(pair)
    hosting = {s for _f, ref in maybe for s in _schemas(ref, search_path)}
    named = [ext for ext in failed if ext.schema in hosting]
    return ExtensionTier(
        _without(candidates, [*resolved, *unchecked]),
        asked=tuple(ext for ext in extensions if ext.name not in answer.failed),
        unwritten=tuple(ext for ext in failed if not ext.schema_written),
        reason=_failure_reason(unchecked, named, answer.failed, search_path),
        answered=True,
    )


def _failure_reason(
    unchecked: Sequence[tuple[str | None, Reference]],
    failed: Sequence[BuiltExtension],
    errors: Mapping[str, str],
    search_path: Sequence[str],
) -> str | None:
    """The degraded reason when the scratch could not create an extension, verbatim."""
    if not failed:
        return None
    why = "the scratch server could not create " + "; ".join(
        f"{ext.name} ({ext.where}): {errors[ext.name]}" for ext in failed
    )
    written = [ext for ext in failed if ext.schema_written]
    if unchecked:
        return unchecked_reason(unchecked, written, why, search_path)
    return f"{why}, so a reference it might provide is reported as missing"


#: Where a statement is in the build: its file's place in build order, and its line.
Position = tuple[int, int]


@dataclass(frozen=True)
class _Created:
    position: Position
    file: str | None
    line: int
    #: The extension whose ``CREATE EXTENSION`` creates it, when no file spells it out.
    extension: str | None = None


@dataclass(frozen=True)
class _Need:
    """A name a statement needs when it is created, which the build does not create before it."""

    file: str | None
    reference: Reference
    position: Position
    #: Where a file of the build first creates it (after *position*), if one does.
    tree: _Created | None


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


def _needs(
    scans: Sequence[tuple[str | None, ReferenceScan]],
    objects: Sequence[SchemaObject],
    order: dict[str | None, int],
    *,
    search_path: Sequence[str],
    two_pass: bool,
) -> list[_Need]:
    """Every name a statement needs when it runs that no file creates before it, once per statement."""
    first = _first_created(objects, order)
    checks = _bodies_checked(scans)
    needs: list[_Need] = []
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
            earliest = min(created, key=lambda c: c.position) if created else None
            # The same statement creates what it names: a table's foreign key
            # to itself, a routine that calls itself. PostgreSQL accepts both.
            if earliest is not None and earliest.position <= position:
                continue
            seen.add(pair)
            needs.append(_Need(label, reference, position, earliest))
    return needs


def _later_extensions(
    need: _Need,
    extensions: Sequence[BuiltExtension],
    order: dict[str | None, int],
    search_path: Sequence[str],
) -> list[BuiltExtension]:
    """The extensions created after *need*'s statement in a schema its name could mean."""
    schemas = _schemas(need.reference, search_path)
    return [
        ext
        for ext in extensions
        if ext.file in order
        and (order[ext.file], ext.line) > need.position
        and ext.schema in schemas
    ]


@dataclass(frozen=True)
class ForwardReferences:
    """``build_004``'s findings, and why some references could not be ordered, if any were not."""

    findings: list[LintViolation]
    reason: str | None = None


def forward_references(
    scans: Sequence[tuple[str | None, ReferenceScan]],
    objects: Sequence[SchemaObject],
    *,
    search_path: Sequence[str] = (),
    two_pass: bool = False,
    extensions: Sequence[BuiltExtension] = (),
    ask: Ask | None = None,
) -> ForwardReferences:
    """``build_004``: every name a statement needs when it runs that the build creates later.

    *scans* is each file's :class:`ReferenceScan` in build order, labelled as a
    finding names the file; *objects* the whole build's inventory, each object
    carrying its file's label. *two_pass* is ``build.two_pass``: the builder
    then moves every foreign key written in a ``CREATE TABLE`` to the end.

    A name no file creates may be an extension's, created at its ``CREATE
    EXTENSION`` (#747). *ask* is the scratch tier: asked once, about every such
    name made before an extension in a schema it could mean. With no scratch,
    or one that cannot answer, those names are not ordered, and ``reason`` says
    so: only an extension whose ``SCHEMA`` is written counts then, as for
    ``build_003``.
    """
    order = {label: index for index, (label, _scan) in enumerate(scans)}
    needs = _needs(scans, objects, order, search_path=search_path, two_pass=two_pass)
    ordering = [
        need
        for need in needs
        if need.tree is None and _later_extensions(need, extensions, order, search_path)
    ]
    by_extension, reason = _extension_creations(ordering, extensions, order, search_path, ask)
    findings = [
        _forward_finding(need.file, need.reference, min(created, key=lambda c: c.position))
        for need in needs
        if (created := [c for c in (need.tree, by_extension.get(id(need))) if c is not None])
    ]
    return ForwardReferences(findings, reason)


def _extension_creations(
    ordering: list[_Need],
    extensions: Sequence[BuiltExtension],
    order: dict[str | None, int],
    search_path: Sequence[str],
    ask: Ask | None,
) -> tuple[dict[int, _Created], str | None]:
    """Which extension's statement creates each of *ordering*'s names, and what stayed unknown."""
    if not ordering:
        return {}, None
    why = NO_SCRATCH_SERVER
    answer: ScratchAnswer | None = None
    if ask is not None:
        try:
            answer = ask([(need.file, need.reference) for need in ordering])
        except ScratchUnavailable as exc:
            why = str(exc)
    created: dict[int, _Created] = {}
    unknown: dict[int, list[BuiltExtension]] = {}
    for need in ordering:
        later = _later_extensions(need, extensions, order, search_path)
        if answer is None or len(answer.after) != len(extensions):
            if written := [ext for ext in later if ext.schema_written]:
                unknown[id(need)] = written
            continue
        for ext in later:
            if ext.name in answer.failed:
                unknown.setdefault(id(need), []).append(ext)
            elif answer.after[extensions.index(ext)].holds(need.reference, search_path):
                position = (order[ext.file], ext.line)
                created[id(need)] = _Created(position, ext.file, ext.line, ext.name)
                break
    if answer is not None and answer.failed:
        why = "the scratch server could not create " + "; ".join(
            f"{name}: {error}" for name, error in answer.failed.items()
        )
    unordered = [need for need in ordering if id(need) in unknown and id(need) not in created]
    if not unordered:
        return created, None
    named = sorted(
        {ext for need in unordered for ext in unknown[id(need)]}, key=_build_order(order)
    )
    count = len(unordered)
    return created, (
        f"could not order {count} reference{'' if count == 1 else 's'} made before "
        f"{_creates(named)}, which may create {'it' if count == 1 else 'them'}: {why}"
    )


def _build_order(order: dict[str | None, int]) -> Callable[[BuiltExtension], Position]:
    return lambda ext: (order.get(ext.file, -1), ext.line)


def _forward_finding(file: str | None, reference: Reference, created: _Created) -> LintViolation:
    referrer_noun = KIND_KEYWORD.get(reference.referrer_kind, reference.referrer_kind).capitalize()
    where = f"{created.file}:{created.line}" if created.file else f"line {created.line}"
    if created.extension:
        where = f"{where} (extension {created.extension})"
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
