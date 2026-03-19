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
