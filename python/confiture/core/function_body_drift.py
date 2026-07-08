"""Function body drift detection.

Compares normalised function bodies between source SQL files and the live
database (pg_proc.prosrc) to detect cases where a function was modified
directly in the database (e.g. via an ad-hoc CREATE OR REPLACE) without
updating the corresponding source file.
"""

from __future__ import annotations

import dataclasses
import difflib
import time
from typing import Any

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
        expected_body: Raw function body from the source SQL (verbatim).
        live_body: Raw ``pg_proc.prosrc`` body from the live database (verbatim).
        expected_normalized: Line-oriented normalised source body (diff basis).
        live_normalized: Line-oriented normalised live body (diff basis).
        unified_diff: ``difflib`` unified diff of the two normalised bodies —
            empty when the bodies are not surfaced (e.g. constructed directly).
    """

    schema: str
    name: str
    signature_key: str
    source_hash: str
    db_hash: str
    expected_body: str = ""
    live_body: str = ""
    expected_normalized: str = ""
    live_normalized: str = ""
    unified_diff: str = ""

    def to_dict(self, *, include_bodies: bool = False) -> dict[str, Any]:
        """Serialize this drift record.

        Args:
            include_bodies: When ``True``, add ``expected_body``, ``live_body``,
                and ``unified_diff``. Defaults to ``False`` so the terse
                hash-only shape (the historical CLI output) is preserved.
        """
        payload: dict[str, Any] = {
            "schema": self.schema,
            "name": self.name,
            "signature_key": self.signature_key,
            "source_hash": self.source_hash,
            "db_hash": self.db_hash,
        }
        if include_bodies:
            payload["expected_body"] = self.expected_body
            payload["live_body"] = self.live_body
            payload["unified_diff"] = self.unified_diff
        return payload


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

    def to_dict(self, *, include_bodies: bool = False) -> dict[str, Any]:
        """Serialize the report to the CLI's ``body_drift`` JSON shape.

        Args:
            include_bodies: Forwarded to each drift's :meth:`FunctionBodyDrift.to_dict`
                so bodies/diff are emitted only when ``--show-diff`` is set.
        """
        return {
            "has_drift": self.has_drift,
            "body_drifts": [d.to_dict(include_bodies=include_bodies) for d in self.body_drifts],
            "functions_checked": self.functions_checked,
            "detection_time_ms": self.detection_time_ms,
        }


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
                exp_norm = self._normalizer.normalize_for_diff(src)
                live_norm = self._normalizer.normalize_for_diff(live)
                unified = "\n".join(
                    difflib.unified_diff(
                        exp_norm.splitlines(),
                        live_norm.splitlines(),
                        fromfile=f"{key} (expected)",
                        tofile=f"{key} (live)",
                        lineterm="",
                    )
                )
                drifts.append(
                    FunctionBodyDrift(
                        schema=schema,
                        name=name,
                        signature_key=key,
                        source_hash=src_hash,
                        db_hash=live_hash,
                        expected_body=src,
                        live_body=live,
                        expected_normalized=exp_norm,
                        live_normalized=live_norm,
                        unified_diff=unified,
                    )
                )

        elapsed = (time.monotonic() - start) * 1000
        return FunctionBodyDriftReport(
            body_drifts=drifts,
            functions_checked=len(common_keys),
            has_drift=len(drifts) > 0,
            detection_time_ms=elapsed,
        )
