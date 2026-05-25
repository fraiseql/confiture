"""Back-compat contract tests for IdempotencyReport.to_dict() / IdempotencyViolation.to_dict().

Locks the additive-only serialization contract documented in CHANGELOG so a
future "let's rename ``scanned_files`` to ``files``" gets caught immediately.
"""

from __future__ import annotations

from confiture.core.idempotency.models import (
    IdempotencyPattern,
    IdempotencyReport,
    IdempotencyViolation,
)

# The frozen set of keys that must always be present on an empty report.
# Adding new keys here is fine (additive); removing or renaming is a break.
_REQUIRED_REPORT_KEYS = {
    "violations",
    "violation_count",
    "files_scanned",
    "scanned_files",
    "has_violations",
    # Added in 0.12.1:
    "warnings",
    "has_warnings",
    # Added in 0.13.0:
    "has_blocking_violations",
}

# Existing-key type signatures pinned to their 0.12.0 shapes (any newer key
# may co-exist; pinned keys must keep their types).
_REPORT_KEY_TYPES = {
    "violations": list,
    "violation_count": int,
    "files_scanned": int,
    "scanned_files": list,
    "has_violations": bool,
    "warnings": list,
    "has_warnings": bool,
    "has_blocking_violations": bool,
}

_REQUIRED_VIOLATION_KEYS = {
    "pattern",
    "sql_snippet",
    "line_number",
    "file_path",
    "suggestion",
    "fix_available",
    # Added in 0.13.0 (always present, defaults to "error"):
    "severity",
}

_VIOLATION_KEY_TYPES = {
    "pattern": str,
    "sql_snippet": str,
    "line_number": int,
    "file_path": str,
    "suggestion": str,
    "fix_available": bool,
    "severity": str,
}


def test_empty_report_has_required_keys():
    payload = IdempotencyReport().to_dict()
    missing = _REQUIRED_REPORT_KEYS - payload.keys()
    assert not missing, f"missing keys: {missing}"


def test_empty_report_key_types_pinned():
    payload = IdempotencyReport().to_dict()
    for key, expected_type in _REPORT_KEY_TYPES.items():
        assert isinstance(payload[key], expected_type), (
            f"{key!r} should be {expected_type.__name__}, got {type(payload[key]).__name__}"
        )


def test_sql_origin_violation_has_required_keys_no_source_line():
    v = IdempotencyViolation(
        pattern=IdempotencyPattern.CREATE_TABLE,
        sql_snippet="CREATE TABLE foo (id int);",
        line_number=1,
        file_path="001_init.up.sql",
    )
    payload = v.to_dict()
    missing = _REQUIRED_VIOLATION_KEYS - payload.keys()
    assert not missing, f"missing keys: {missing}"
    # SQL-origin: source_line is omitted entirely so byte-identity with
    # 0.12.0 holds for callers that didn't know about the new key.
    assert "source_line" not in payload


def test_python_origin_violation_emits_source_line():
    v = IdempotencyViolation(
        pattern=IdempotencyPattern.CREATE_TABLE,
        sql_snippet="CREATE TABLE foo (id int);",
        line_number=1,
        file_path="20260101_demo.py",
        source_line=9,
    )
    payload = v.to_dict()
    assert payload["source_line"] == 9


def test_violation_key_types_pinned():
    v = IdempotencyViolation(
        pattern=IdempotencyPattern.CREATE_TABLE,
        sql_snippet="CREATE TABLE foo (id int);",
        line_number=1,
        file_path="001_init.up.sql",
        severity="info",
    )
    payload = v.to_dict()
    for key, expected_type in _VIOLATION_KEY_TYPES.items():
        assert isinstance(payload[key], expected_type), (
            f"{key!r} should be {expected_type.__name__}, got {type(payload[key]).__name__}"
        )
    assert payload["severity"] == "info"
