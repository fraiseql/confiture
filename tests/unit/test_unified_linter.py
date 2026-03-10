"""Unit tests for UnifiedLinter."""

from __future__ import annotations

import shutil
from unittest.mock import MagicMock, patch

import pytest

from confiture.models.lint import LintSeverity
from confiture.models.unified_lint import UnifiedLintIssue, UnifiedLintResult


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


def test_squawk_runner_parses_json_output(tmp_path):
    from confiture.core.unified_linter import SquawkRunner

    output = '[{"filename": "test.sql", "violations": [{"line": 5, "message": "ban-drop-column", "rule": "ban-drop-column"}]}]'
    runner = SquawkRunner()
    issues = runner._parse(output)
    assert len(issues) == 1
    assert issues[0].tool == "squawk"
    assert issues[0].line == 5
    assert issues[0].rule == "ban-drop-column"


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
