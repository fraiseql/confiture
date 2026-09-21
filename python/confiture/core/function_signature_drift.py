"""Detect stale function overloads by comparing the routines a tree declares against a database.

A stale overload occurs when a function's parameter types were changed via
CREATE OR REPLACE (which silently creates a second overload) without a matching
DROP FUNCTION for the old signature. Both sides are the schema model's
:class:`~confiture.core.schema_model.Routine`:

  - declared: read from the project's DDL by the lint inventory (:func:`declared_routines`)
  - live: read from ``pg_proc`` by ``core/live_catalog`` (:func:`live_routines`)

Two routines are one when their names match and their ``signature_key`` does,
argument by argument (``type_lattice.signatures_match``) — one canonicaliser on
both sides, so ``int8`` and ``bigint`` are one routine and ``text[]`` and
``text`` are two. Functions present in the live DB but absent from source are
only flagged when the source defines *at least one* signature for that
(schema, name) — this avoids false positives for built-ins, extensions, and
unmanaged functions.

A report prints a routine as ``schema.name(type,type)``, each type in
PostgreSQL's own vocabulary (``type_lattice.catalog_spelling``), whichever side
it was read from: consumers key their alert state on these strings, and one
routine is one string.
"""

from __future__ import annotations

import dataclasses
import time
from collections import defaultdict
from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING, Any

from confiture.core import live_catalog
from confiture.core.linting.inventory import build_model
from confiture.core.schema_identity import DEFAULT_SCHEMA
from confiture.core.type_lattice import catalog_spelling, signatures_match

if TYPE_CHECKING:
    import psycopg

    from confiture.core.schema_model import Routine

#: The routine kinds a signature comparison reads: what ``CREATE FUNCTION`` and
#: ``CREATE PROCEDURE`` define, on both sides. An aggregate is created otherwise.
_SIGNATURE_KINDS = frozenset({"function", "procedure"})

#: The same kinds as ``pg_proc.prokind`` letters.
_SIGNATURE_PROKINDS = ("f", "p")


def declared_routines(sql: str) -> list[Routine]:
    """Every function and procedure *sql* declares, in declaration order.

    Read by the lint inventory into the schema model, so a routine the tree
    later drops or renames is folded the way a build folds it, and a routine
    redefined with ``CREATE OR REPLACE`` is its last definition.

    Raises:
        pglast.parser.ParseError: pglast rejects *sql*.
    """
    return [
        routine
        for found in build_model(sql).routines.values()
        for routine in found
        if routine.kind in _SIGNATURE_KINDS
    ]


def live_routines(conn: psycopg.Connection, schemas: Sequence[str]) -> list[Routine]:
    """Every function and procedure in *schemas*, a trigger function included.

    A trigger function is included because the declared side has no such filter,
    and a comparison whose two sides hold different kinds of thing is not a
    comparison (#303). So is an extension's own routine: a tree that declares one
    of the same name is comparing against it.
    """
    rows = live_catalog.routines(conn, schemas, kinds=_SIGNATURE_PROKINDS, include_triggers=True)
    return [live_catalog.routine_of(row) for row in rows]


def function_key(routine: Routine) -> str:
    """``schema.name`` — the routine without its arguments, schema defaulted."""
    return f"{routine.schema or DEFAULT_SCHEMA}.{routine.name}"


def printed_arguments(routine: Routine) -> tuple[str, ...]:
    """Each input argument type in PostgreSQL's vocabulary, its schema where it has one."""
    return tuple(
        f"{schema}.{catalog_spelling(name)}" if schema else catalog_spelling(name)
        for schema, name in routine.signature_key
    )


def printed_signature(routine: Routine) -> str:
    """``schema.name(type,type)``: how a report names one routine."""
    return f"{function_key(routine)}({','.join(printed_arguments(routine))})"


def by_function(routines: Iterable[Routine]) -> dict[str, list[Routine]]:
    """*routines* grouped by :func:`function_key`, each group in the order given."""
    grouped: dict[str, list[Routine]] = defaultdict(list)
    for routine in routines:
        grouped[function_key(routine)].append(routine)
    return grouped


def matching(routine: Routine, candidates: Iterable[Routine]) -> Routine | None:
    """The first of *candidates* that is *routine*, argument type by argument type."""
    return next(
        (
            other
            for other in candidates
            if signatures_match(routine.signature_key, other.signature_key)
        ),
        None,
    )


@dataclasses.dataclass
class StaleOverload:
    """A function overload present in the live DB but no longer in the source.

    Attributes:
        schema: Schema containing the function
        name: Function name
        stale_signature: Canonical form of the stale overload, e.g. "public.f(integer)"
        source_signatures: All signatures that source defines for this (schema, name)
    """

    schema: str
    name: str
    stale_signature: str
    source_signatures: list[str]

    @property
    def drop_sql(self) -> str:
        """DROP FUNCTION statement to remove this stale overload."""
        return f"DROP FUNCTION {self.stale_signature};"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "name": self.name,
            "stale_signature": self.stale_signature,
            "source_signatures": self.source_signatures,
            "drop_sql": self.drop_sql,
        }


@dataclasses.dataclass
class FunctionSignatureDriftReport:
    """Result of comparing source-defined function signatures against a live database.

    Attributes:
        stale_overloads: Overloads present in DB but not in source (for known functions)
        missing_from_db: Source signatures the live database has not got. Which of
            the two readings applies is the caller's to decide, and both are
            legitimate: **before** a deploy it says what is about to be applied;
            **after** one it is the failure a deploy gate is looking for. It was
            labelled "informational" when it could not be trusted either way — a
            trigger function was permanently in it, and so was every routine
            outside ``public`` (#303). ``--missing-is-drift`` is how a caller says
            which reading it means; :attr:`has_undeployed` is the answer either
            way.
        schemas_checked: List of schemas that were compared
        functions_checked: Total number of distinct functions checked
        has_drift: True when stale_overloads is non-empty
        detection_time_ms: Wall-clock time for the comparison
    """

    stale_overloads: list[StaleOverload]
    missing_from_db: list[str]
    schemas_checked: list[str]
    functions_checked: int
    has_drift: bool
    detection_time_ms: float
    #: Whether an undeployed routine counts as a failure for this run. A field
    #: rather than a branch in the CLI: a verdict computed in a formatter is a
    #: verdict a library consumer cannot get.
    missing_is_drift: bool = False

    @property
    def has_undeployed(self) -> bool:
        """Whether the source declares a routine the live database has not got.

        Always computed and always in :meth:`to_dict`, whatever flag the caller
        passed, so a consumer never has to reconstruct a verdict from an array
        (README D3). ``missing_is_drift`` decides whether it *fails* a run.
        """
        return len(self.missing_from_db) > 0

    @property
    def has_critical_drift(self) -> bool:
        """The verdict a gate reads: a stale overload, or — when the caller asked
        for it with ``--missing-is-drift`` — a routine that is not deployed.

        Computed here rather than in a CLI formatter so that
        ``FunctionSignatureDriftDetector.compare`` gives a library consumer the
        same answer the command gives.
        """
        return self.has_drift or (self.missing_is_drift and self.has_undeployed)

    def summary(self) -> str:
        if not self.has_drift:
            return (
                f"No stale function overloads detected ({self.functions_checked} functions checked)"
            )
        return (
            f"{len(self.stale_overloads)} stale overload(s) detected "
            f"({self.functions_checked} functions checked)"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "has_drift": self.has_drift,
            "has_critical_drift": self.has_critical_drift,
            "remediation_sql": [o.drop_sql for o in self.stale_overloads],
            "stale_overloads": [o.to_dict() for o in self.stale_overloads],
            "missing_from_db": self.missing_from_db,
            "has_undeployed": self.has_undeployed,
            "missing_is_drift": self.missing_is_drift,
            "schemas_checked": self.schemas_checked,
            "functions_checked": self.functions_checked,
            "detection_time_ms": self.detection_time_ms,
        }


def schemas_to_scan(requested: str | None, source: Iterable[Routine]) -> list[str]:
    """Which schemas a signature comparison covers.

    ``requested`` is a comma-separated ``--schemas`` value, or ``None`` when the
    caller did not name any. In that case the answer is **the schemas the source
    declares** — the same answer ``--check-live-drift`` derives from the DDL.
    The two halves of one gate disagreed before: this one defaulted to ``public``
    while the other read the tree, so every routine outside ``public`` was
    reported as not deployed on a database that had it (#303).

    A source that declares no routine at all has no schema to name, and
    ``public`` is the historical answer; there is nothing to compare either way.
    """
    named = [part.strip() for part in (requested or "").split(",") if part.strip()]
    if named:
        return named
    declared = sorted({routine.schema or DEFAULT_SCHEMA for routine in source})
    return declared or [DEFAULT_SCHEMA]


class FunctionSignatureDriftDetector:
    """Compare the routines a tree declares against the ones a database holds.

    Usage:
        detector = FunctionSignatureDriftDetector()
        report = detector.compare(declared_routines(sql), live_routines(conn, schemas))
    """

    def compare(
        self,
        source: Iterable[Routine],
        live: Iterable[Routine],
        schemas_checked: list[str] | None = None,
        *,
        missing_is_drift: bool = False,
    ) -> FunctionSignatureDriftReport:
        """Detect stale overloads and missing functions.

        A stale overload is a live routine no source routine of the same
        ``schema.name`` matches, when source DOES define at least one signature
        for that ``schema.name``. If source has no signature for it at all, the
        live function is not flagged (it may be a built-in or installed
        extension).

        Args:
            source: Routines the DDL declares
            live: Routines the live database holds
            schemas_checked: Which schemas were included (for reporting)
            missing_is_drift: Whether a routine the source declares and the
                database has not got makes ``has_critical_drift`` true

        Returns:
            FunctionSignatureDriftReport
        """
        t0 = time.monotonic()
        declared_in_order = list(source)
        source_by_fn = by_function(declared_in_order)
        live_by_fn = by_function(live)

        stale_overloads = [
            StaleOverload(
                schema=routine.schema or DEFAULT_SCHEMA,
                name=routine.name,
                stale_signature=printed_signature(routine),
                source_signatures=sorted(printed_signature(r) for r in declared),
            )
            for fn_key, declared in source_by_fn.items()
            for routine in sorted(
                (r for r in live_by_fn.get(fn_key, []) if matching(r, declared) is None),
                key=printed_arguments,
            )
        ]

        missing_from_db = [
            printed_signature(routine)
            for routine in declared_in_order
            if matching(routine, live_by_fn.get(function_key(routine), [])) is None
        ]

        return FunctionSignatureDriftReport(
            stale_overloads=stale_overloads,
            missing_from_db=missing_from_db,
            schemas_checked=schemas_checked or [],
            functions_checked=len(source_by_fn),
            has_drift=len(stale_overloads) > 0,
            detection_time_ms=(time.monotonic() - t0) * 1000,
            missing_is_drift=missing_is_drift,
        )
