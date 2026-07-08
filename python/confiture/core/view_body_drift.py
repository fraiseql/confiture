"""View (and materialized-view) body-drift detection.

Compares view definitions between the committed source schema and the live
database, detecting a view whose predicate/projection was changed directly in
the database without updating the DDL.

Unlike functions — whose ``pg_proc.prosrc`` is stored verbatim — a view's
definition is not stored as text: PostgreSQL keeps the parsed query tree and
``pg_get_viewdef(oid, true)`` returns a *deparsed* rendering (schema-qualified,
``*``-expanded, reparenthesised, alias-normalised). Text-normalising the source
``CREATE VIEW`` against that deparsed live form yields false positives on
semantically-identical views.

The fix (see :mod:`confiture.core.expected_db`): build the expected views into a
scratch database and run the **same** ``pg_get_viewdef(oid, true)`` there, then
compare the two deparsed strings. Both sides pass through pg's identical deparser,
so string equality is semantic equality. This detector therefore takes the
already-deparsed definitions from both sides and needs only trivial
normalisation (trailing-whitespace trim) before comparing — aggressive
normalisation is unnecessary and could mask real drift.
"""

from __future__ import annotations

import dataclasses
import difflib
import hashlib
import time
from typing import Any


@dataclasses.dataclass(frozen=True)
class ViewDefinition:
    """A deparsed view definition, from either the scratch or the live DB.

    Attributes:
        schema: PostgreSQL schema name.
        name: View (or materialized view) name.
        relkind: ``'v'`` for a regular view, ``'m'`` for a materialized view.
        definition: ``pg_get_viewdef(oid, true)`` output (pretty-printed).
    """

    schema: str
    name: str
    relkind: str
    definition: str

    @property
    def view_key(self) -> str:
        """Canonical key — ``"schema.name"``."""
        return f"{self.schema}.{self.name}"


@dataclasses.dataclass(frozen=True)
class ViewBodyDrift:
    """A single view whose deparsed definition differs between source and DB.

    Attributes:
        schema: PostgreSQL schema name.
        name: View name.
        relkind: ``'v'`` (view) or ``'m'`` (materialized view).
        source_hash: 12-char hex of the normalised expected definition.
        db_hash: 12-char hex of the normalised live definition.
        expected_def: Deparsed expected definition (from the scratch DB).
        live_def: Deparsed live definition.
        unified_diff: ``difflib`` unified diff of the two definitions — empty when
            the definitions are not surfaced (e.g. constructed directly).
    """

    schema: str
    name: str
    relkind: str
    source_hash: str
    db_hash: str
    expected_def: str = ""
    live_def: str = ""
    unified_diff: str = ""

    def to_dict(self, *, include_defs: bool = False) -> dict[str, Any]:
        """Serialize this drift record.

        Args:
            include_defs: When ``True``, add ``expected_def``, ``live_def``, and
                ``unified_diff``. Defaults to ``False`` so the terse hash-only
                shape matches ``--check-body``'s default output.
        """
        payload: dict[str, Any] = {
            "schema": self.schema,
            "name": self.name,
            "relkind": self.relkind,
            "source_hash": self.source_hash,
            "db_hash": self.db_hash,
        }
        if include_defs:
            payload["expected_def"] = self.expected_def
            payload["live_def"] = self.live_def
            payload["unified_diff"] = self.unified_diff
        return payload


@dataclasses.dataclass
class ViewBodyDriftReport:
    """Summary of the view body-drift comparison run.

    Attributes:
        body_drifts: Views whose normalised definition differs.
        views_checked: Number of views compared (intersection of source and live
            keys).
        has_drift: ``True`` iff at least one view drift was detected.
        detection_time_ms: Wall-clock time of the comparison in milliseconds.
    """

    body_drifts: list[ViewBodyDrift]
    views_checked: int
    has_drift: bool
    detection_time_ms: float

    def to_dict(self, *, include_defs: bool = False) -> dict[str, Any]:
        """Serialize the report to the CLI's ``view_drift`` JSON shape."""
        return {
            "has_drift": self.has_drift,
            "body_drifts": [d.to_dict(include_defs=include_defs) for d in self.body_drifts],
            "views_checked": self.views_checked,
            "detection_time_ms": self.detection_time_ms,
        }


def _normalize_viewdef(definition: str) -> str:
    """Trim trailing whitespace per line and surrounding blank lines.

    Both sides are already deparsed by the identical ``pg_get_viewdef`` call, so
    only cosmetic trailing-whitespace differences (rare) need suppressing. No
    lowercasing or internal-whitespace collapse — that could mask genuine drift.
    """
    return "\n".join(line.rstrip() for line in definition.strip().splitlines())


def _hash_viewdef(definition: str) -> str:
    """Return a 12-char hex digest of the normalised *definition*."""
    return hashlib.sha256(_normalize_viewdef(definition).encode()).hexdigest()[:12]


class ViewBodyDriftDetector:
    """Compare deparsed view definitions between the expected and live schema.

    Usage::

        detector = ViewBodyDriftDetector()
        report = detector.compare(source_defs, live_defs)
        for drift in report.body_drifts:
            print(f"{drift.schema}.{drift.name}", drift.unified_diff)
    """

    def compare(
        self,
        source_defs: dict[str, ViewDefinition],
        live_defs: dict[str, ViewDefinition],
    ) -> ViewBodyDriftReport:
        """Detect definition drift for all views present in both dicts.

        Only the *intersection* of keys is compared. Views present only on one
        side (added/removed) are outside this detector's scope.

        Args:
            source_defs: Mapping of ``view_key`` → expected :class:`ViewDefinition`
                (read back from the scratch DB, deparsed).
            live_defs: Mapping of ``view_key`` → live :class:`ViewDefinition`.

        Returns:
            A :class:`ViewBodyDriftReport` with drift details and timing.
        """
        start = time.monotonic()
        common_keys = set(source_defs) & set(live_defs)
        drifts: list[ViewBodyDrift] = []

        for key in sorted(common_keys):
            src = source_defs[key]
            live = live_defs[key]
            src_norm = _normalize_viewdef(src.definition)
            live_norm = _normalize_viewdef(live.definition)
            if src_norm != live_norm:
                unified = "\n".join(
                    difflib.unified_diff(
                        src_norm.splitlines(),
                        live_norm.splitlines(),
                        fromfile=f"{key} (expected)",
                        tofile=f"{key} (live)",
                        lineterm="",
                    )
                )
                drifts.append(
                    ViewBodyDrift(
                        schema=live.schema,
                        name=live.name,
                        relkind=live.relkind,
                        source_hash=_hash_viewdef(src.definition),
                        db_hash=_hash_viewdef(live.definition),
                        expected_def=src.definition,
                        live_def=live.definition,
                        unified_diff=unified,
                    )
                )

        elapsed = (time.monotonic() - start) * 1000
        return ViewBodyDriftReport(
            body_drifts=drifts,
            views_checked=len(common_keys),
            has_drift=len(drifts) > 0,
            detection_time_ms=elapsed,
        )
