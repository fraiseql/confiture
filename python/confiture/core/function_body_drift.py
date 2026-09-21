"""Function body drift detection.

Compares normalised function bodies between two sets of the schema model's
:class:`~confiture.core.schema_model.Routine` — the source DDL's and the live
database's (``pg_proc.prosrc``), or a migration replay's and the live
database's — to detect a function modified directly in the database (e.g. via
an ad-hoc CREATE OR REPLACE) without updating the corresponding source.

The two sides are paired by ``schema.name`` and ``signature_key``, through the
one signature canonicaliser; a body is the text between the ``AS`` quotes on
both, so a comparison needs no PL/pgSQL compiler.
"""

from __future__ import annotations

import dataclasses
import difflib
import time
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

from confiture.core.function_body_normalizer import FunctionBodyNormalizer
from confiture.core.function_signature_drift import (
    by_function,
    function_key,
    matching,
    printed_signature,
)
from confiture.core.schema_identity import DEFAULT_SCHEMA

if TYPE_CHECKING:
    from confiture.core.schema_model import Routine


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
        functions_checked: Number of routines compared (those both sides hold,
            bodiless ones included).
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


def paired(source: Iterable[Routine], live: Iterable[Routine]) -> list[tuple[Routine, Routine]]:
    """Every source routine the live side also holds, with its live twin."""
    live_by_fn = by_function(live)
    pairs: list[tuple[Routine, Routine]] = []
    for routine in source:
        twin = matching(routine, live_by_fn.get(function_key(routine), []))
        if twin is not None:
            pairs.append((routine, twin))
    return pairs


class FunctionBodyDriftDetector:
    """Compare normalised function bodies between source SQL and a live DB.

    Usage::

        detector = FunctionBodyDriftDetector()
        report = detector.compare(declared_routines(sql), live_routines(conn, schemas))
        if report.has_drift:
            for drift in report.body_drifts:
                print(drift.signature_key, drift.source_hash, drift.db_hash)
    """

    def __init__(self) -> None:
        self._normalizer = FunctionBodyNormalizer()

    def compare(
        self,
        source: Iterable[Routine],
        live: Iterable[Routine],
    ) -> FunctionBodyDriftReport:
        """Detect body drift for every routine both sides hold.

        Only routines present on *both* sides are compared. One the source
        declares and the database has not got is the signature detector's
        (``missing_from_db``); one only the database holds is not in source —
        also outside this detector's scope.

        A routine with no body on either side is counted in ``functions_checked``
        but never reported as drift (a LANGUAGE C function's ``AS`` clause is a
        symbol, not a body).

        Args:
            source: The expected routines — the DDL's, or a migration replay's.
            live: The live database's routines.

        Returns:
            A :class:`FunctionBodyDriftReport` with drift details and timing.
        """
        start = time.monotonic()
        pairs = sorted(paired(source, live), key=lambda pair: printed_signature(pair[1]))
        drifts: list[FunctionBodyDrift] = []

        for expected, actual in pairs:
            src, live_body = expected.body, actual.body
            if src is None or live_body is None:
                continue  # cannot compare C/internal functions
            src_hash = self._normalizer.hash_body(src)
            live_hash = self._normalizer.hash_body(live_body)
            if src_hash != live_hash:
                key = printed_signature(actual)
                exp_norm = self._normalizer.normalize_for_diff(src)
                live_norm = self._normalizer.normalize_for_diff(live_body)
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
                        schema=actual.schema or DEFAULT_SCHEMA,
                        name=actual.name,
                        signature_key=key,
                        source_hash=src_hash,
                        db_hash=live_hash,
                        expected_body=src,
                        live_body=live_body,
                        expected_normalized=exp_norm,
                        live_normalized=live_norm,
                        unified_diff=unified,
                    )
                )

        elapsed = (time.monotonic() - start) * 1000
        return FunctionBodyDriftReport(
            body_drifts=drifts,
            functions_checked=len(pairs),
            has_drift=len(drifts) > 0,
            detection_time_ms=elapsed,
        )
