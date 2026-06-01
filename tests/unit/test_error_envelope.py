"""Tests for the structured error envelope serializer (issue #145).

The `error` object IS the unified inner issue object from
.phases/.../shared-issue-schema.md: {severity, code, message, actionable,
details, migration, file, line}. Required keys are always present (nullable).
"""

from __future__ import annotations

from pathlib import Path

from confiture.cli.error_json import coerce_to_confiture_error, emit_error_json
from confiture.exceptions import ConfiturError, MigrationConflictError, MigrationError


def test_envelope_shape_for_duplicate_version() -> None:
    err = MigrationConflictError(
        "Migration version 20260531_1430 is defined twice: foo.sql and bar.sql.",
        conflicting_files=["foo.sql", "bar.sql"],
    )
    env = emit_error_json(err)
    assert env == {
        "ok": False,
        "error": {
            "code": "MIGR_106",
            "message": "Migration version 20260531_1430 is defined twice: foo.sql and bar.sql.",
            "severity": "error",
            "details": {"conflicting_files": ["foo.sql", "bar.sql"]},
            "migration": None,
            "file": None,
            "line": None,
            "actionable": err.resolution_hint,
        },
    }


def test_migration_version_promoted_to_migration_field() -> None:
    err = MigrationError("boom", version="20260531_1430", migration_name="add_bio")
    env = emit_error_json(err)
    assert env["error"]["migration"] == "20260531_1430"


def test_inner_object_always_has_all_keys() -> None:
    env = emit_error_json(ConfiturError("plain", error_code="CONFIG_001"))
    inner = env["error"]
    for key in (
        "severity",
        "code",
        "message",
        "actionable",
        "details",
        "migration",
        "file",
        "line",
    ):
        assert key in inner, f"missing required key {key}"


def test_file_and_line_promoted_from_context() -> None:
    err = ConfiturError(
        "bad",
        error_code="LINT_1500",
        context={"file": "db/schema/10_tables/users.sql", "line": 42, "rule": "R1"},
    )
    inner = emit_error_json(err)["error"]
    assert inner["file"] == "db/schema/10_tables/users.sql"
    assert inner["line"] == 42
    assert inner["details"] == {"rule": "R1"}  # file/line promoted out of details


def test_critical_severity_folds_to_error() -> None:
    err = ConfiturError("severe", error_code="ROLLBACK_600")  # CRITICAL severity
    assert emit_error_json(err)["error"]["severity"] == "error"


def test_details_are_json_serializable_paths_become_str() -> None:
    err = MigrationConflictError("dup", conflicting_files=[Path("a.sql"), Path("b.sql")])
    details = emit_error_json(err)["error"]["details"]
    assert details["conflicting_files"] == ["a.sql", "b.sql"]


def test_non_confiture_exception_coerced_to_envelope() -> None:
    err = coerce_to_confiture_error(KeyError("surprise"))
    env = emit_error_json(err)
    assert env["ok"] is False
    assert env["error"]["code"] == "INTERNAL_ERROR"
    assert err.exit_code == 1  # generic failure


def test_coerce_passes_through_confiture_error() -> None:
    original = MigrationError("x", error_code="MIGR_100")
    assert coerce_to_confiture_error(original) is original
