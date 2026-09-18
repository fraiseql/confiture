"""Detect stale function overloads by comparing source signatures against a live database.

A stale overload occurs when a function's parameter types were changed via
CREATE OR REPLACE (which silently creates a second overload) without a matching
DROP FUNCTION for the old signature.  This module compares:

  - Source signatures: parsed from the project's DDL SQL file
  - Live signatures: introspected from pg_proc via FunctionIntrospector

Functions present in the live DB but absent from source are only flagged when
the source defines *at least one* signature for that (schema, name) — this
avoids false positives for built-ins, extensions, and unmanaged functions.
"""

from __future__ import annotations

import dataclasses
import re
import time
from collections import defaultdict
from typing import Any

from confiture.core.function_signature_parser import FunctionSignature

# Trailing array suffix (one or more '[]', possibly sized) used to compare two
# param types ignoring array-ness — see the defensive guard in ``compare``.
_ARRAY_SUFFIX_RE = re.compile(r"(?:\s*\[\s*\d*\s*\])+\s*$")


def _strip_array(param_type: str) -> str:
    """Return ``param_type`` with any trailing array suffix removed."""
    return _ARRAY_SUFFIX_RE.sub("", param_type).strip()


def _array_only_difference(
    stale_params: tuple[str, ...], source_param_sets: set[tuple[str, ...]]
) -> bool:
    """True when a source signature of equal arity matches ``stale_params`` after
    stripping array suffixes from both sides.

    Guards against a normalisation gap emitting a destructive ``DROP FUNCTION``
    for a function that plainly exists in source, differing only by an array
    suffix (issue #176).  Conservative by design: suppressing a genuine
    scalar/array overload is non-destructive, whereas dropping a live function is
    catastrophic.
    """
    stale_base = tuple(_strip_array(p) for p in stale_params)
    return any(
        len(source_params) == len(stale_params)
        and tuple(_strip_array(p) for p in source_params) == stale_base
        for source_params in source_param_sets
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


def schemas_to_scan(requested: str | None, source_sigs: list[FunctionSignature]) -> list[str]:
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
    declared = sorted({sig.schema for sig in source_sigs if sig.schema})
    return declared or ["public"]


class FunctionSignatureDriftDetector:
    """Compare source-defined function signatures against a live database.

    Usage:
        detector = FunctionSignatureDriftDetector()
        report = detector.compare(source_sigs, live_sigs)
    """

    def compare(
        self,
        source_sigs: list[FunctionSignature],
        live_sigs: list[FunctionSignature],
        schemas_checked: list[str] | None = None,
        *,
        missing_is_drift: bool = False,
    ) -> FunctionSignatureDriftReport:
        """Detect stale overloads and missing functions.

        A stale overload is a (schema, name, param_types) tuple present in the
        live DB but absent from source, when source DOES define at least one
        signature for that (schema, name).

        If source has no signature for a (schema, name) at all, the live
        function is not flagged (it may be a built-in or installed extension).

        Args:
            source_sigs: Signatures parsed from DDL source files
            live_sigs: Signatures introspected from the live database
            schemas_checked: Which schemas were included (for reporting)
            missing_is_drift: Whether a routine the source declares and the
                database has not got makes ``has_critical_drift`` true

        Returns:
            FunctionSignatureDriftReport
        """
        t0 = time.monotonic()

        source_by_fn: dict[str, set[tuple[str, ...]]] = defaultdict(set)
        live_by_fn: dict[str, set[tuple[str, ...]]] = defaultdict(set)

        for sig in source_sigs:
            source_by_fn[sig.function_key()].add(sig.param_types)

        for sig in live_sigs:
            live_by_fn[sig.function_key()].add(sig.param_types)

        stale_overloads: list[StaleOverload] = []
        for fn_key, source_param_sets in source_by_fn.items():
            if fn_key not in live_by_fn:
                continue
            stale_param_sets = live_by_fn[fn_key] - source_param_sets
            for stale_params in sorted(stale_param_sets):
                # Never emit a destructive DROP for a base-name + arity match that
                # differs only by an array suffix (issue #176 safety net).
                if _array_only_difference(stale_params, source_param_sets):
                    continue
                schema, name = fn_key.split(".", 1)
                stale_overloads.append(
                    StaleOverload(
                        schema=schema,
                        name=name,
                        stale_signature=f"{fn_key}({','.join(stale_params)})",
                        source_signatures=sorted(
                            f"{fn_key}({','.join(p)})" for p in source_param_sets
                        ),
                    )
                )

        missing_from_db: list[str] = []
        for sig in source_sigs:
            fn_key = sig.function_key()
            if sig.param_types not in live_by_fn.get(fn_key, set()):
                missing_from_db.append(sig.signature_key())

        functions_checked = len(source_by_fn)
        detection_time_ms = (time.monotonic() - t0) * 1000

        return FunctionSignatureDriftReport(
            stale_overloads=stale_overloads,
            missing_from_db=missing_from_db,
            schemas_checked=schemas_checked or [],
            functions_checked=functions_checked,
            has_drift=len(stale_overloads) > 0,
            detection_time_ms=detection_time_ms,
            missing_is_drift=missing_is_drift,
        )
