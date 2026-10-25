"""Unit tests for the structured preflight report model (issue #148)."""

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
        assert {
            "severity",
            "code",
            "message",
            "migration",
            "file",
            "line",
            "actionable",
            "details",
        } == set(i)


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


def _irreversible(issues: list[PreflightIssue]) -> list[PreflightIssue]:
    return [i for i in issues if i.code == "PFLIGHT_IRREVERSIBLE"]


def test_irreversible_marker_reaches_the_report_ungated(tmp_path: Path) -> None:
    # A migration a down exists for, that declares the down does not restore its data (#754).
    _mig(
        tmp_path,
        "002",
        "overwrite_v",
        body="-- confiture:irreversible overwrites t.v\nUPDATE t SET v = 0;",
    )
    issues = run_preflight(tmp_path).issues
    (marked,) = _irreversible(issues)
    assert marked.severity == "info"
    assert marked.migration == "002"
    assert marked.file == "002_overwrite_v.up.sql"
    assert marked.details == {"irreversible": ["overwrites t.v"]}
    assert not [i for i in issues if i.code == "PFLIGHT_DESTRUCTIVE_GATED"]


def test_irreversible_marker_is_reported_beside_the_destructive_gate(tmp_path: Path) -> None:
    _mig(
        tmp_path,
        "002",
        "drop_c",
        body=(
            "-- confiture:destructive\n-- confiture:irreversible data\nALTER TABLE t DROP COLUMN c;"
        ),
    )
    issues = run_preflight(tmp_path).issues
    assert [i.details for i in _irreversible(issues)] == [{"irreversible": ["data"]}]
    (gated,) = [i for i in issues if i.code == "PFLIGHT_DESTRUCTIVE_GATED"]
    assert gated.details == {"irreversible": ["data"]}


def test_irreversible_marker_moves_no_exit_code(tmp_path: Path) -> None:
    _mig(tmp_path, "002", "m", body="-- confiture:irreversible why\nUPDATE t SET v = 0;")
    report = run_preflight(tmp_path).to_report_dict(strict=True)
    assert report["ok"] is True
    assert report["summary"]["info"] == 1


def _py(d: Path, version: str, name: str, down: str) -> None:
    (d / f"{version}_{name}.py").write_text(
        "from confiture.models.migration import Migration\n\n\n"
        f"class M(Migration):\n    version = {version!r}\n    name = {name!r}\n\n"
        "    def up(self):\n        self.execute('ALTER TABLE t ADD COLUMN u int')\n\n"
        f"    def down(self):\n        {down}\n"
    )


def _of(issues: list[PreflightIssue], code: str) -> list[PreflightIssue]:
    return [i for i in issues if i.code == code]


def test_a_python_down_that_is_pass_is_reported_empty(tmp_path: Path) -> None:
    _py(tmp_path, "002", "add_u", "pass")
    result = run_preflight(tmp_path)
    (empty,) = _of(result.issues, "PFLIGHT_DOWN_EMPTY")
    assert empty.severity == "warning"
    assert empty.migration == "002"
    assert empty.file == "002_add_u.py"
    assert not _of(result.issues, "PFLIGHT_MISSING_DOWN")
    assert not _of(result.issues, "PFLIGHT_DOWN_UNVERIFIED")
    assert result.migrations[0].has_down is True


def test_a_python_down_with_statements_is_unverified(tmp_path: Path) -> None:
    _py(tmp_path, "002", "add_u", "self.execute('ALTER TABLE t DROP COLUMN u')")
    issues = run_preflight(tmp_path).issues
    (unverified,) = _of(issues, "PFLIGHT_DOWN_UNVERIFIED")
    assert unverified.severity == "info"
    assert unverified.migration == "002"
    assert unverified.details == {"down": "present"}
    assert not _of(issues, "PFLIGHT_DOWN_EMPTY")


def test_a_python_down_confiture_cannot_place_is_unverified(tmp_path: Path) -> None:
    (tmp_path / "002_add_u.py").write_text("from base import Base\n\n\nclass M(Base):\n    pass\n")
    (unverified,) = _of(run_preflight(tmp_path).issues, "PFLIGHT_DOWN_UNVERIFIED")
    assert unverified.details == {"down": "unknown"}


def test_a_sql_migration_has_no_python_down_finding(tmp_path: Path) -> None:
    _mig(tmp_path, "001", "a")
    issues = run_preflight(tmp_path).issues
    assert not _of(issues, "PFLIGHT_DOWN_EMPTY") + _of(issues, "PFLIGHT_DOWN_UNVERIFIED")


def test_reversible_is_false_on_each_code_that_says_down_cannot_undo() -> None:
    from confiture.core.preflight import IRREVERSIBLE_CODES, is_reversible

    assert is_reversible([], ())
    assert is_reversible([PreflightIssue.of("PFLIGHT_REPLICA_DROP_COLUMN", "m")], ())
    for code in IRREVERSIBLE_CODES:
        issue = PreflightIssue(severity="info", code=code, message="m")
        assert not is_reversible([issue], ()), code
    assert set(IRREVERSIBLE_CODES) <= set(PFLIGHT_CODES)


def test_reversible_is_false_on_a_change_a_down_cannot_restore() -> None:
    from confiture.core.change_set.models import ChangeEntry
    from confiture.core.preflight import is_reversible
    from confiture.core.risk_tier import RiskTier

    def change(tier: RiskTier | None) -> ChangeEntry:
        return ChangeEntry(kind="k", object="public.t", migration="001", tier=tier)

    undoable = [RiskTier.ADDITIVE, RiskTier.REVERSIBLE, RiskTier.LOCK_RISKY]
    assert is_reversible([], [change(t) for t in undoable])
    for tier in (RiskTier.DESTRUCTIVE, RiskTier.IRREVERSIBLE, None):
        assert not is_reversible([], [change(RiskTier.ADDITIVE), change(tier)]), tier
