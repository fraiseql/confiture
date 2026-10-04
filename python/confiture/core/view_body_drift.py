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
schema model's :class:`~confiture.core.schema_model.View` from both sides, each
read by ``live_catalog.views(…, definitions=True)``, and needs only trivial
normalisation (trailing-whitespace trim) before comparing — aggressive
normalisation is unnecessary and could mask real drift.
"""

import dataclasses
import difflib
import hashlib
import time
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

from confiture.core.ddl_objects import DDLObject
from confiture.core.differ import EXACT, SchemaDiffer, slot_side
from confiture.core.schema_change import ObjectAdded, ObjectReplaced
from confiture.core.schema_identity import DEFAULT_SCHEMA
from confiture.core.schema_model import view_ref

if TYPE_CHECKING:
    from confiture.core.schema_model import ObjectRef, View


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


def _view_key(view: View) -> str:
    """``schema.name`` — how a report names a view."""
    return f"{view.schema or DEFAULT_SCHEMA}.{view.name}"


def _statements(views: dict[ObjectRef, View]) -> dict[ObjectRef, list[DDLObject]]:
    """Each view as the one slot compared: its deparsed query, normalised."""
    return {
        ref: [DDLObject(ref, _normalize_viewdef(view.definition or ""), "")]
        for ref, view in views.items()
    }


def _drift(src: View, live_view: View) -> ViewBodyDrift:
    """The report of one view whose deparsed query is another on each side."""
    key = _view_key(live_view)
    src_def, live_def = src.definition or "", live_view.definition or ""
    unified = "\n".join(
        difflib.unified_diff(
            _normalize_viewdef(src_def).splitlines(),
            _normalize_viewdef(live_def).splitlines(),
            fromfile=f"{key} (expected)",
            tofile=f"{key} (live)",
            lineterm="",
        )
    )
    return ViewBodyDrift(
        schema=live_view.schema or DEFAULT_SCHEMA,
        name=live_view.name,
        relkind="m" if live_view.materialized else "v",
        source_hash=_hash_viewdef(src_def),
        db_hash=_hash_viewdef(live_def),
        expected_def=src_def,
        live_def=live_def,
        unified_diff=unified,
    )


class ViewBodyDriftDetector:
    """Compare deparsed view definitions between the expected and live schema.

    Usage::

        detector = ViewBodyDriftDetector()
        report = detector.compare(expected_views, live_views)
        for drift in report.body_drifts:
            print(f"{drift.schema}.{drift.name}", drift.unified_diff)
    """

    def compare(self, source: Iterable[View], live: Iterable[View]) -> ViewBodyDriftReport:
        """Detect definition drift for every view both sides hold.

        Only views present on *both* sides are compared: one present on one side
        only is ``confiture drift``'s ``missing_view`` / ``extra_view``. The
        comparison is the engine's (``SchemaDiffer.compare_sides``) over each
        view's query alone; a view it replaces is one that drifted.

        Args:
            source: The expected views, read back deparsed from the scratch DB.
            live: The live database's views, deparsed.

        Returns:
            A :class:`ViewBodyDriftReport` with drift details and timing.
        """
        start = time.monotonic()
        source_views = {view_ref(view): view for view in source}
        live_views = {view_ref(view): view for view in live}
        diff = SchemaDiffer().compare_sides(
            slot_side("views", _statements(live_views)),
            slot_side("views", _statements(source_views)),
            EXACT,
        )
        replaced = sorted(
            (c.ref for c in diff.changes if isinstance(c, ObjectReplaced)),
            key=lambda ref: _view_key(live_views[ref]),
        )
        drifts = [_drift(source_views[ref], live_views[ref]) for ref in replaced]
        added = sum(isinstance(c, ObjectAdded) for c in diff.changes)

        elapsed = (time.monotonic() - start) * 1000
        return ViewBodyDriftReport(
            body_drifts=drifts,
            views_checked=len(source_views) - added,
            has_drift=len(drifts) > 0,
            detection_time_ms=elapsed,
        )
