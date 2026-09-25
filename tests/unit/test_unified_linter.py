"""Unit tests for UnifiedLinter."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from confiture.models.lint import LintSeverity
from confiture.models.unified_lint import UnifiedLintIssue, UnifiedLintResult

RECORDINGS = Path(__file__).resolve().parents[1] / "fixtures" / "unified_lint"


def test_lint_result_aggregation():
    issues = [
        UnifiedLintIssue(
            tool="squawk",
            file="db/schema/tables.sql",
            line=10,
            message="Missing NOT NULL",
            severity=LintSeverity.WARNING,
        ),
        UnifiedLintIssue(
            tool="sqlfluff",
            file="db/schema/tables.sql",
            line=5,
            message="Trailing whitespace",
            severity=LintSeverity.INFO,
        ),
    ]
    result = UnifiedLintResult(issues=issues)
    assert result.has_warnings is True
    assert result.has_errors is False
    assert len(result.by_tool["squawk"]) == 1


def test_lint_result_to_dict():
    result = UnifiedLintResult(
        issues=[
            UnifiedLintIssue(
                tool="squawk", file="f.sql", line=1, message="msg", severity=LintSeverity.ERROR
            )
        ]
    )
    d = result.to_dict()
    assert d["summary"]["total"] == 1
    assert d["summary"]["errors"] == 1


def test_squawk_runner_not_available_returns_empty():
    from confiture.core.unified_linter import SquawkRunner

    runner = SquawkRunner()
    with patch("shutil.which", return_value=None):
        assert runner.available is False
        assert runner.run([]) == []


def _recorded(tool: str) -> dict:
    """What *tool* really emitted on the fixture files (``scripts/capture_linter_outputs.py``)."""
    (path,) = sorted(RECORDINGS.glob(f"{tool}-*.json"))
    return json.loads(path.read_text())


def test_squawk_2_findings_are_parsed_at_their_one_based_line():
    """#358: squawk 2.x emits a flat list, and counts lines from 0."""
    from confiture.core.unified_linter import SquawkRunner

    recorded = _recorded("squawk")
    issues = SquawkRunner()._parse(json.dumps(recorded["outputs"]["001_index_widget_label.sql"]))
    by_rule = {(i.rule, i.line) for i in issues}
    assert ("require-concurrent-index-creation", 1) in by_rule
    assert ("adding-required-field", 2) in by_rule
    assert {i.file for i in issues} == {"001_index_widget_label.sql"}
    assert all(i.tool == "squawk" and i.message for i in issues)


def test_a_sqlfluff_4_finding_carries_its_line():
    """#358: sqlfluff 4 names it start_line_no."""
    from confiture.core.unified_linter import SQLFluffRunner

    recorded = _recorded("sqlfluff")
    violations = recorded["outputs"]["002_two_statements_apart.sql"]
    issues = SQLFluffRunner.parse("002_two_statements_apart.sql", violations)
    assert {(i.rule, i.line) for i in issues} >= {("LT05", 1), ("CP01", 5)}


def test_an_older_sqlfluff_line_no_is_still_read():
    from confiture.core.unified_linter import SQLFluffRunner

    (issue,) = SQLFluffRunner.parse("f.sql", [{"code": "CP01", "line_no": 3, "description": "d"}])
    assert issue.line == 3


def test_squawk_runner_handles_invalid_json():
    from confiture.core.unified_linter import SquawkRunner

    runner = SquawkRunner()
    issues = runner._parse("not json")
    assert issues == []


def test_unified_linter_collects_from_squawk(tmp_path):
    from confiture.core.unified_linter import SquawkRunner, UnifiedLinter

    sql = tmp_path / "schema.sql"
    sql.write_text("CREATE TABLE users (id uuid);")

    mock_squawk = MagicMock(spec=SquawkRunner)
    mock_squawk.available = True
    mock_squawk.run.return_value = [
        UnifiedLintIssue(
            tool="squawk",
            file=str(sql),
            line=1,
            message="Missing primary key",
            severity=LintSeverity.WARNING,
        )
    ]

    linter = UnifiedLinter(squawk=mock_squawk)
    result = linter.run(files=[sql])
    assert len(result.issues) >= 1
    assert any(i.tool == "squawk" for i in result.issues)


def test_unified_linter_empty_when_no_tools():
    from confiture.core.unified_linter import SQLFluffRunner, SquawkRunner, UnifiedLinter

    mock_squawk = MagicMock(spec=SquawkRunner)
    mock_squawk.available = False
    mock_squawk.run.return_value = []
    mock_sqlfluff = MagicMock(spec=SQLFluffRunner)
    mock_sqlfluff.available = False
    mock_sqlfluff.run.return_value = []

    linter = UnifiedLinter(squawk=mock_squawk, sqlfluff=mock_sqlfluff)
    result = linter.run(files=[])
    assert result.issues == []


def test_a_check_whose_tool_is_missing_is_named_as_skipped():
    """#358: a missing squawk read as a clean run."""
    from confiture.core.unified_linter import SQLFluffRunner, SquawkRunner, UnifiedLinter

    squawk = MagicMock(spec=SquawkRunner)
    squawk.available = False
    sqlfluff = MagicMock(spec=SQLFluffRunner)
    sqlfluff.available = False
    result = UnifiedLinter(squawk=squawk, sqlfluff=sqlfluff).run(files=[Path("x.sql")])
    assert [(s.check, s.tool) for s in result.skipped] == [
        ("safety", "squawk"),
        ("format", "sqlfluff"),
    ]
    assert result.to_dict()["skipped"] == [
        {"check": "safety", "tool": "squawk", "reason": "squawk is not installed on PATH"},
        {"check": "format", "tool": "sqlfluff", "reason": "sqlfluff is not installed"},
    ]


def test_a_file_sqlfluff_fails_on_is_named_as_skipped(tmp_path):
    from confiture.core.unified_linter import SQLFluffRunner, SquawkRunner, UnifiedLinter

    squawk = MagicMock(spec=SquawkRunner)
    squawk.available = True
    squawk.run.return_value = []
    sqlfluff = MagicMock(spec=SQLFluffRunner)
    sqlfluff.available = True
    sqlfluff.run.return_value = []
    sqlfluff.failures = [("x.sql", "boom")]
    result = UnifiedLinter(squawk=squawk, sqlfluff=sqlfluff).run(files=[tmp_path / "x.sql"])
    assert [(s.check, s.reason) for s in result.skipped] == [("format", "x.sql: boom")]
