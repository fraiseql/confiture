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
import time
from collections import defaultdict
from typing import Any

from confiture.core.function_signature_parser import FunctionSignature


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
        missing_from_db: Source signatures not yet deployed to DB (informational)
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

    @property
    def has_critical_drift(self) -> bool:
        """Alias for has_drift — used by CLI for consistent exit-code pattern."""
        return self.has_drift

    def summary(self) -> str:
        if not self.has_drift:
            return (
                f"No stale function overloads detected "
                f"({self.functions_checked} functions checked)"
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
            "schemas_checked": self.schemas_checked,
            "functions_checked": self.functions_checked,
            "detection_time_ms": self.detection_time_ms,
        }


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
        )
