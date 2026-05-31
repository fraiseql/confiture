"""Unit tests for the structured preflight report model (issue #148, Phase 1)."""

from __future__ import annotations

from pathlib import Path

from confiture.core.preflight import preflight_exit_code, run_preflight
from confiture.models.results import PFLIGHT_CODES, PreflightIssue


def _mig(d: Path, version: str, name: str, *, down: bool = True, body: str = "SELECT 1;") -> None:
    (d / f"{version}_{name}.up.sql").write_text(body)
    if down:
        (d / f"{version}_{name}.down.sql").write_text("SELECT 1;")


def test_missing_down_becomes_error_issue(tmp_path: Path) -> None:
    _mig(tmp_path, "20260531000001", "add_user_bio", down=False)
    issues = run_preflight(tmp_path).issues
    miss = [i for i in issues if i.code == "PFLIGHT_MISSING_DOWN"]
    assert len(miss) == 1
    assert miss[0].severity == "error"
    assert miss[0].migration == "20260531000001"
    assert miss[0].file.endswith("add_user_bio.up.sql")
    assert miss[0].actionable  # populated


def test_non_transactional_is_warning(tmp_path: Path) -> None:
    _mig(
        tmp_path,
        "20260531000002",
        "add_idx",
        body="CREATE INDEX CONCURRENTLY idx ON t (col);",
    )
    nt = [i for i in run_preflight(tmp_path).issues if i.code == "PFLIGHT_NON_TRANSACTIONAL"]
    assert nt and nt[0].severity == "warning"
    assert nt[0].migration == "20260531000002"
    assert nt[0].details["statements"]


def test_summary_counts(tmp_path: Path) -> None:
    _mig(tmp_path, "20260531000001", "a", down=False)  # 1 error
    _mig(tmp_path, "20260531000002", "b", body="CREATE INDEX CONCURRENTLY i ON t (c);")  # warn
    _mig(tmp_path, "20260531000003", "c", body="CREATE INDEX CONCURRENTLY j ON t (c);")  # warn
    summary = run_preflight(tmp_path).summary
    assert summary["errors"] == 1
    assert summary["warnings"] == 2
    assert summary["migrations_checked"] == 3


def test_report_dict_shape(tmp_path: Path) -> None:
    _mig(tmp_path, "20260531000001", "a", down=False)
    report = run_preflight(tmp_path).to_report_dict()
    assert report["ok"] is False
    assert set(report.keys()) == {"ok", "summary", "issues"}
    for i in report["issues"]:
        assert {"severity", "code", "message", "migration", "file", "line", "actionable", "details"} == set(i)


def test_report_ok_when_clean(tmp_path: Path) -> None:
    _mig(tmp_path, "20260531000001", "a")
    assert run_preflight(tmp_path).to_report_dict()["ok"] is True


def test_strict_marks_warnings_not_ok(tmp_path: Path) -> None:
    _mig(tmp_path, "20260531000002", "b", body="CREATE INDEX CONCURRENTLY i ON t (c);")
    assert run_preflight(tmp_path).to_report_dict(strict=False)["ok"] is True
    assert run_preflight(tmp_path).to_report_dict(strict=True)["ok"] is False


def test_preflight_exit_code_policy() -> None:
    assert preflight_exit_code({"errors": 0, "warnings": 0}, strict=False) == 0
    assert preflight_exit_code({"errors": 1, "warnings": 0}, strict=False) == 7
    assert preflight_exit_code({"errors": 0, "warnings": 2}, strict=False) == 0
    assert preflight_exit_code({"errors": 0, "warnings": 2}, strict=True) == 7
    assert preflight_exit_code({"errors": 1, "warnings": 2}, strict=True) == 7


def test_every_pflight_code_has_severity_and_actionable() -> None:
    for code, (severity, actionable) in PFLIGHT_CODES.items():
        assert severity in {"error", "warning", "info"}, code
        assert actionable, code


def test_issue_of_pulls_defaults() -> None:
    issue = PreflightIssue.of("PFLIGHT_MISSING_DOWN", "msg", migration="v1")
    assert issue.severity == "error"
    assert issue.actionable == PFLIGHT_CODES["PFLIGHT_MISSING_DOWN"][1]
