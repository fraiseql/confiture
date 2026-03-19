"""Function body drift detection.

Compares normalised function bodies between source SQL files and the live
database (pg_proc.prosrc) to detect cases where a function was modified
directly in the database (e.g. via an ad-hoc CREATE OR REPLACE) without
updating the corresponding source file.
"""

from __future__ import annotations

import dataclasses
import time

from confiture.core.function_body_normalizer import FunctionBodyNormalizer

_NO_BODY_LANGUAGES = frozenset({"c", "internal"})


@dataclasses.dataclass(frozen=True)
class FunctionBodyDrift:
    """A single function whose normalised body differs between source and DB.

    Attributes:
        schema: PostgreSQL schema name.
        name: Function name.
        signature_key: Canonical key — ``"schema.name(type1,type2)"``.
        source_hash: 12-char hex of the normalised source body.
        db_hash: 12-char hex of the normalised live-DB body.
    """

    schema: str
    name: str
    signature_key: str
    source_hash: str
    db_hash: str


@dataclasses.dataclass
class FunctionBodyDriftReport:
    """Summary of the body drift comparison run.

    Attributes:
        body_drifts: Functions whose normalised body hash differs.
        functions_checked: Number of signatures compared (intersection of
            source and live keys; includes skipped None-body functions).
        has_drift: ``True`` iff at least one body drift was detected.
        detection_time_ms: Wall-clock time of the comparison in milliseconds.
    """

    body_drifts: list[FunctionBodyDrift]
    functions_checked: int
    has_drift: bool
    detection_time_ms: float


def _parse_schema_name(key: str) -> tuple[str, str]:
    """Extract (schema, name) from a signature_key like 'public.foo(integer)'."""
    schema, rest = key.split(".", 1)
    name = rest.split("(", 1)[0]
    return schema, name


class FunctionBodyDriftDetector:
    """Compare normalised function bodies between source SQL and a live DB.

    Usage::

        detector = FunctionBodyDriftDetector()
        report = detector.compare(source_bodies, live_bodies)
        if report.has_drift:
            for drift in report.body_drifts:
                print(drift.signature_key, drift.source_hash, drift.db_hash)
    """

    def __init__(self) -> None:
        self._normalizer = FunctionBodyNormalizer()

    def compare(
        self,
        source_bodies: dict[str, str | None],
        live_bodies: dict[str, str | None],
    ) -> FunctionBodyDriftReport:
        """Detect body drift for all signatures present in both dicts.

        Only the *intersection* of keys is compared.  Keys present only in
        ``source_bodies`` are already handled by the signature drift detector
        (``missing_from_db``).  Keys present only in ``live_bodies`` are extra
        DB functions not in source — also outside this detector's scope.

        Functions with ``None`` body on either side are counted in
        ``functions_checked`` but never reported as drift (e.g. LANGUAGE C
        functions have no extractable SQL body).

        Args:
            source_bodies: Mapping of signature_key → raw body from source SQL
                           (or None for non-SQL functions).
            live_bodies: Mapping of signature_key → raw prosrc from live DB
                         (or None for C/internal functions).

        Returns:
            A :class:`FunctionBodyDriftReport` with drift details and timing.
        """
        start = time.monotonic()
        common_keys = set(source_bodies) & set(live_bodies)
        drifts: list[FunctionBodyDrift] = []

        for key in sorted(common_keys):
            src = source_bodies[key]
            live = live_bodies[key]
            if src is None or live is None:
                continue  # cannot compare C/internal functions
            src_hash = self._normalizer.hash_body(src)
            live_hash = self._normalizer.hash_body(live)
            if src_hash != live_hash:
                schema, name = _parse_schema_name(key)
                drifts.append(
                    FunctionBodyDrift(
                        schema=schema,
                        name=name,
                        signature_key=key,
                        source_hash=src_hash,
                        db_hash=live_hash,
                    )
                )

        elapsed = (time.monotonic() - start) * 1000
        return FunctionBodyDriftReport(
            body_drifts=drifts,
            functions_checked=len(common_keys),
            has_drift=len(drifts) > 0,
            detection_time_ms=elapsed,
        )
