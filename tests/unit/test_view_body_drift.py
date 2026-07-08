"""Unit tests for ViewBodyDriftDetector and ViewBodyDriftReport.

Mirrors ``test_function_body_drift.py``. The detector compares *already-deparsed*
view definitions (``pg_get_viewdef`` output from both the scratch/expected DB and
the live DB), so the inputs here are the pg-normalised strings the catalog yields.
"""

from confiture.core.view_body_drift import (
    ViewBodyDrift,
    ViewBodyDriftDetector,
    ViewBodyDriftReport,
    ViewDefinition,
)


def _v(schema: str, name: str, relkind: str, definition: str) -> ViewDefinition:
    return ViewDefinition(schema=schema, name=name, relkind=relkind, definition=definition)


# ---------------------------------------------------------------------------
# No drift
# ---------------------------------------------------------------------------


def test_no_drift_identical_definitions():
    src = {"public.v": _v("public", "v", "v", "SELECT a\n   FROM t;")}
    live = {"public.v": _v("public", "v", "v", "SELECT a\n   FROM t;")}
    report = ViewBodyDriftDetector().compare(src, live)
    assert not report.has_drift
    assert report.body_drifts == []
    assert report.views_checked == 1


def test_no_drift_trailing_whitespace_only():
    """Trailing whitespace per line must not register as drift."""
    src = {"public.v": _v("public", "v", "v", "SELECT a  \nFROM t;   ")}
    live = {"public.v": _v("public", "v", "v", "SELECT a\nFROM t;")}
    report = ViewBodyDriftDetector().compare(src, live)
    assert not report.has_drift


# ---------------------------------------------------------------------------
# Drift detected
# ---------------------------------------------------------------------------


def test_drift_detected_changed_predicate():
    src = {"public.v": _v("public", "v", "v", "SELECT a\nFROM t\nWHERE x > y;")}
    live = {"public.v": _v("public", "v", "v", "SELECT a\nFROM t\nWHERE x > (y + 1);")}
    report = ViewBodyDriftDetector().compare(src, live)
    assert report.has_drift
    assert len(report.body_drifts) == 1
    drift = report.body_drifts[0]
    assert drift.schema == "public"
    assert drift.name == "v"
    assert drift.relkind == "v"
    assert drift.source_hash != drift.db_hash
    assert len(drift.source_hash) == 12
    assert len(drift.db_hash) == 12


def test_drift_record_carries_defs_and_unified_diff():
    src = {"public.v": _v("public", "v", "v", "SELECT a\nFROM t\nWHERE x > y;")}
    live = {"public.v": _v("public", "v", "v", "SELECT a\nFROM t\nWHERE x > (y + 1);")}
    drift = ViewBodyDriftDetector().compare(src, live).body_drifts[0]
    assert drift.expected_def == "SELECT a\nFROM t\nWHERE x > y;"
    assert drift.live_def == "SELECT a\nFROM t\nWHERE x > (y + 1);"
    assert "-WHERE x > y;" in drift.unified_diff
    assert "+WHERE x > (y + 1);" in drift.unified_diff
    # Unchanged lines are not reported as +/- churn.
    assert "-SELECT a" not in drift.unified_diff


def test_only_changed_views_listed():
    src = {
        "public.v1": _v("public", "v1", "v", "SELECT 1;"),
        "public.v2": _v("public", "v2", "v", "SELECT 2;"),
    }
    live = {
        "public.v1": _v("public", "v1", "v", "SELECT 1;"),
        "public.v2": _v("public", "v2", "v", "SELECT 99;"),
    }
    report = ViewBodyDriftDetector().compare(src, live)
    assert len(report.body_drifts) == 1
    assert report.body_drifts[0].name == "v2"
    assert report.views_checked == 2


def test_materialized_view_covered():
    src = {"public.mv": _v("public", "mv", "m", "SELECT sum(x) AS s\nFROM t;")}
    live = {"public.mv": _v("public", "mv", "m", "SELECT avg(x) AS s\nFROM t;")}
    report = ViewBodyDriftDetector().compare(src, live)
    assert report.has_drift
    assert report.body_drifts[0].relkind == "m"


# ---------------------------------------------------------------------------
# Intersection-only comparison
# ---------------------------------------------------------------------------


def test_source_only_view_not_compared():
    src = {
        "public.v": _v("public", "v", "v", "SELECT 1;"),
        "public.ghost": _v("public", "ghost", "v", "SELECT 2;"),
    }
    live = {"public.v": _v("public", "v", "v", "SELECT 1;")}
    report = ViewBodyDriftDetector().compare(src, live)
    assert not report.has_drift
    assert report.views_checked == 1


def test_live_only_view_not_compared():
    src = {"public.v": _v("public", "v", "v", "SELECT 1;")}
    live = {
        "public.v": _v("public", "v", "v", "SELECT 1;"),
        "public.extra": _v("public", "extra", "v", "SELECT 2;"),
    }
    report = ViewBodyDriftDetector().compare(src, live)
    assert not report.has_drift
    assert report.views_checked == 1


# ---------------------------------------------------------------------------
# to_dict shapes
# ---------------------------------------------------------------------------


def test_drift_to_dict_hash_only_by_default():
    src = {"public.v": _v("public", "v", "v", "SELECT a\nWHERE x > y;")}
    live = {"public.v": _v("public", "v", "v", "SELECT a\nWHERE x > (y + 1);")}
    drift = ViewBodyDriftDetector().compare(src, live).body_drifts[0]
    terse = drift.to_dict()
    assert set(terse) == {"schema", "name", "relkind", "source_hash", "db_hash"}
    verbose = drift.to_dict(include_defs=True)
    assert verbose["expected_def"] == "SELECT a\nWHERE x > y;"
    assert verbose["live_def"] == "SELECT a\nWHERE x > (y + 1);"
    assert "unified_diff" in verbose


def test_report_to_dict_shape():
    src = {"public.v": _v("public", "v", "v", "SELECT a\nWHERE x > y;")}
    live = {"public.v": _v("public", "v", "v", "SELECT a\nWHERE x > (y + 1);")}
    report = ViewBodyDriftDetector().compare(src, live)
    payload = report.to_dict()
    assert payload["has_drift"] is True
    assert payload["views_checked"] == 1
    assert "detection_time_ms" in payload
    assert len(payload["body_drifts"]) == 1
    assert "expected_def" not in payload["body_drifts"][0]  # hash-only by default
    verbose = report.to_dict(include_defs=True)
    assert verbose["body_drifts"][0]["expected_def"] == "SELECT a\nWHERE x > y;"


def test_report_dataclass_fields_directly_constructable():
    report = ViewBodyDriftReport(
        body_drifts=[],
        views_checked=0,
        has_drift=False,
        detection_time_ms=0.0,
    )
    assert report.body_drifts == []
    assert not report.has_drift


def test_drift_is_frozen_dataclass():
    drift = ViewBodyDrift(
        schema="public",
        name="v",
        relkind="v",
        source_hash="aabbccddeeff",
        db_hash="112233445566",
    )
    assert drift.schema == "public"
    assert drift.relkind == "v"
