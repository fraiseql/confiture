"""Unit tests for FunctionBodyDriftDetector and FunctionBodyDriftReport."""

from confiture.core.function_body_drift import (
    FunctionBodyDrift,
    FunctionBodyDriftDetector,
    FunctionBodyDriftReport,
)

# ---------------------------------------------------------------------------
# Cycle 1: No drift cases
# ---------------------------------------------------------------------------


def test_no_drift_identical_bodies():
    source = {"public.foo(integer)": "SELECT $1 + 1;"}
    live = {"public.foo(integer)": "SELECT $1 + 1;"}
    report = FunctionBodyDriftDetector().compare(source, live)
    assert not report.has_drift
    assert report.body_drifts == []
    assert report.functions_checked == 1


def test_no_drift_whitespace_difference():
    """Whitespace-only difference must not produce drift."""
    source = {"public.foo(integer)": "SELECT   $1  +  1;"}
    live = {"public.foo(integer)": "SELECT $1 + 1;"}
    report = FunctionBodyDriftDetector().compare(source, live)
    assert not report.has_drift


def test_no_drift_comment_difference():
    """Comment-only difference must not produce drift."""
    source = {"public.foo(integer)": "-- returns n+1\nSELECT $1 + 1;"}
    live = {"public.foo(integer)": "SELECT $1 + 1;"}
    report = FunctionBodyDriftDetector().compare(source, live)
    assert not report.has_drift


def test_no_drift_case_difference():
    """Case-only difference must not produce drift."""
    source = {"public.foo(integer)": "SELECT $1 + 1;"}
    live = {"public.foo(integer)": "select $1 + 1;"}
    report = FunctionBodyDriftDetector().compare(source, live)
    assert not report.has_drift


# ---------------------------------------------------------------------------
# Cycle 2: Drift detected
# ---------------------------------------------------------------------------


def test_drift_detected_different_logic():
    source = {"public.foo(integer)": "SELECT $1 + 1;"}
    live = {"public.foo(integer)": "SELECT $1 + 2;"}  # +2 vs +1
    report = FunctionBodyDriftDetector().compare(source, live)
    assert report.has_drift
    assert len(report.body_drifts) == 1
    drift = report.body_drifts[0]
    assert drift.schema == "public"
    assert drift.name == "foo"
    assert drift.signature_key == "public.foo(integer)"
    assert drift.source_hash != drift.db_hash
    assert len(drift.source_hash) == 12
    assert len(drift.db_hash) == 12


def test_drift_detected_only_changed_functions_listed():
    source = {
        "public.foo(integer)": "SELECT $1 + 1;",
        "public.bar(text)": "SELECT upper($1);",
    }
    live = {
        "public.foo(integer)": "SELECT $1 + 99;",  # drifted
        "public.bar(text)": "SELECT upper($1);",  # unchanged
    }
    report = FunctionBodyDriftDetector().compare(source, live)
    assert report.has_drift
    assert len(report.body_drifts) == 1
    assert report.body_drifts[0].name == "foo"
    assert report.functions_checked == 2


# ---------------------------------------------------------------------------
# Cycle 2b (#177): drift record carries both bodies + a unified diff
# ---------------------------------------------------------------------------


def test_drift_record_includes_bodies_and_unified_diff():
    """A drifted function exposes both raw bodies and a line-oriented diff."""
    source = {"public.foo(integer)": "SELECT $1 + 1;"}
    live = {"public.foo(integer)": "SELECT $1 + 2;"}
    report = FunctionBodyDriftDetector().compare(source, live)

    assert report.has_drift
    drift = report.body_drifts[0]
    # Raw bodies preserved verbatim.
    assert drift.expected_body == "SELECT $1 + 1;"
    assert drift.live_body == "SELECT $1 + 2;"
    # Unified diff mentions both changed lines and is line-oriented.
    assert "-select $1 + 1;" in drift.unified_diff
    assert "+select $1 + 2;" in drift.unified_diff


def test_unified_diff_is_line_oriented_not_collapsed():
    """Multi-line bodies produce a per-line diff, not one collapsed line."""
    source = {"public.f()": "SELECT a\nFROM t\nWHERE x = 1;"}
    live = {"public.f()": "SELECT a\nFROM t\nWHERE x = 2;"}
    report = FunctionBodyDriftDetector().compare(source, live)

    drift = report.body_drifts[0]
    # Only the WHERE line changed; the unchanged lines must not appear as +/-.
    assert "-where x = 1;" in drift.unified_diff
    assert "+where x = 2;" in drift.unified_diff
    assert "-select a" not in drift.unified_diff
    assert "-from t" not in drift.unified_diff


def test_no_drift_produces_no_record_with_bodies():
    """A non-drifted function still yields no record (bodies not surfaced)."""
    source = {"public.foo(integer)": "SELECT $1 + 1;  -- comment"}
    live = {"public.foo(integer)": "select $1 + 1;"}
    report = FunctionBodyDriftDetector().compare(source, live)
    assert not report.has_drift
    assert report.body_drifts == []


def test_drift_to_dict_hash_only_by_default():
    """to_dict() omits bodies/diff unless include_bodies=True (back-compat)."""
    source = {"public.foo(integer)": "SELECT $1 + 1;"}
    live = {"public.foo(integer)": "SELECT $1 + 2;"}
    drift = FunctionBodyDriftDetector().compare(source, live).body_drifts[0]

    terse = drift.to_dict()
    assert set(terse) == {"schema", "name", "signature_key", "source_hash", "db_hash"}

    verbose = drift.to_dict(include_bodies=True)
    assert verbose["expected_body"] == "SELECT $1 + 1;"
    assert verbose["live_body"] == "SELECT $1 + 2;"
    assert "unified_diff" in verbose


def test_report_to_dict_matches_inline_shape():
    """FunctionBodyDriftReport.to_dict() reproduces the historical JSON keys."""
    source = {"public.foo(integer)": "SELECT $1 + 1;"}
    live = {"public.foo(integer)": "SELECT $1 + 2;"}
    report = FunctionBodyDriftDetector().compare(source, live)

    payload = report.to_dict()
    assert payload["has_drift"] is True
    assert payload["functions_checked"] == 1
    assert "detection_time_ms" in payload
    assert len(payload["body_drifts"]) == 1
    # Hash-only by default — no bodies leak.
    assert "expected_body" not in payload["body_drifts"][0]

    verbose = report.to_dict(include_bodies=True)
    assert verbose["body_drifts"][0]["expected_body"] == "SELECT $1 + 1;"


# ---------------------------------------------------------------------------
# Cycle 3: None-body handling
# ---------------------------------------------------------------------------


def test_none_source_body_skipped():
    """C/internal functions with no extractable source body are skipped."""
    source = {"public.foo(cstring)": None}
    live = {"public.foo(cstring)": "int4in"}
    report = FunctionBodyDriftDetector().compare(source, live)
    assert not report.has_drift
    assert report.functions_checked == 1  # counted, not drifted


def test_none_db_body_skipped():
    source = {"public.foo(cstring)": "SELECT 1;"}
    live = {"public.foo(cstring)": None}
    report = FunctionBodyDriftDetector().compare(source, live)
    assert not report.has_drift
    assert report.functions_checked == 1


def test_both_none_skipped():
    source = {"public.foo(cstring)": None}
    live = {"public.foo(cstring)": None}
    report = FunctionBodyDriftDetector().compare(source, live)
    assert not report.has_drift
    assert report.functions_checked == 1


# ---------------------------------------------------------------------------
# Cycle 4: Keys only in source or only in live are not compared
# ---------------------------------------------------------------------------


def test_source_only_key_not_compared():
    """Signature in source but not live is already handled by signature drift."""
    source = {
        "public.foo(integer)": "SELECT $1 + 1;",
        "public.ghost(text)": "SELECT $1;",  # not in live
    }
    live = {"public.foo(integer)": "SELECT $1 + 1;"}
    report = FunctionBodyDriftDetector().compare(source, live)
    assert not report.has_drift
    assert report.functions_checked == 1  # only the intersection


def test_live_only_key_not_compared():
    source = {"public.foo(integer)": "SELECT $1 + 1;"}
    live = {
        "public.foo(integer)": "SELECT $1 + 1;",
        "public.extra(text)": "SELECT $1;",  # not in source
    }
    report = FunctionBodyDriftDetector().compare(source, live)
    assert not report.has_drift
    assert report.functions_checked == 1


# ---------------------------------------------------------------------------
# Structural checks on report and drift objects
# ---------------------------------------------------------------------------


def test_report_detection_time_is_positive():
    source = {"public.foo(integer)": "SELECT 1;"}
    live = {"public.foo(integer)": "SELECT 1;"}
    report = FunctionBodyDriftDetector().compare(source, live)
    assert report.detection_time_ms >= 0


def test_drift_is_frozen_dataclass():
    drift = FunctionBodyDrift(
        schema="public",
        name="foo",
        signature_key="public.foo(integer)",
        source_hash="aabbccddeeff",
        db_hash="112233445566",
    )
    assert drift.schema == "public"
    assert drift.name == "foo"


def test_report_dataclass_fields():
    report = FunctionBodyDriftReport(
        body_drifts=[],
        functions_checked=0,
        has_drift=False,
        detection_time_ms=0.0,
    )
    assert report.body_drifts == []
    assert report.functions_checked == 0
    assert not report.has_drift
