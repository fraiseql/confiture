"""A file pglast cannot parse is a finding, never a clean result (Phase 05, ANA-02).

``CREATE TABL x (`` used to make the idempotency check swap to its regex backend
and report *ok*, make preflight crash, and leave lint's report clean. Each
surface now says what happened: ``IDEM_UNPARSEABLE`` (counted as unanalyzed,
so ``--fail-on-unanalyzable`` fails the run), ``PFLIGHT_UNPARSEABLE`` (which
forces ``window_safe: false``), and lint's ``UNPARSEABLE`` notice.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.core.linting.schema_linter import RuleSeverity, SchemaLinter
from confiture.core.preflight import is_window_safe, run_preflight

runner = CliRunner()
BROKEN = "CREATE TABL x (\n"


@pytest.fixture
def migrations(tmp_path: Path) -> Path:
    d = tmp_path / "migrations"
    d.mkdir()
    (d / "001_broken.up.sql").write_text(BROKEN)
    (d / "001_broken.down.sql").write_text("DROP TABLE IF EXISTS x;\n")
    return d


def test_idempotency_reports_one_unparseable_finding_with_its_line(migrations: Path) -> None:
    result = runner.invoke(
        app,
        [
            "migrate",
            "validate",
            "--idempotent",
            "--migrations-dir",
            str(migrations),
            "--format",
            "json",
        ],
    )
    assert result.exit_code == 0, result.output  # unverified, but not failing without the flag
    data = json.loads(result.stdout)
    assert data["status"] == "unverified"
    findings = [w for w in data["warnings"] if w["reason_code"] == "IDEM_UNPARSEABLE"]
    assert len(findings) == 1, data["warnings"]
    assert findings[0]["source_line"] == 1
    assert findings[0]["source_file"].endswith("001_broken.up.sql")


def test_fail_on_unanalyzable_covers_unparseable_files(migrations: Path) -> None:
    result = runner.invoke(
        app,
        [
            "migrate",
            "validate",
            "--idempotent",
            "--migrations-dir",
            str(migrations),
            "--format",
            "json",
            "--fail-on-unanalyzable",
        ],
    )
    assert result.exit_code == 1, result.output


def test_preflight_reports_unparseable_and_denies_the_window(migrations: Path) -> None:
    result = run_preflight(migrations)
    codes = [i.code for i in result.issues]
    assert codes.count("PFLIGHT_UNPARSEABLE") == 1, codes
    issue = next(i for i in result.issues if i.code == "PFLIGHT_UNPARSEABLE")
    assert issue.line == 1
    assert issue.file == "001_broken.up.sql"
    assert is_window_safe(result.issues) is False


def test_preflight_cli_envelope_says_so(migrations: Path) -> None:
    result = runner.invoke(
        app, ["migrate", "preflight", "--migrations-dir", str(migrations), "--format", "json"]
    )
    data = json.loads(result.stdout)
    assert data["window_safe"] is False
    assert "PFLIGHT_UNPARSEABLE" in [i["code"] for i in data["issues"]]
    assert result.exit_code != 0


def test_lint_reports_an_unparseable_notice_not_a_clean_report() -> None:
    report = SchemaLinter(env="local").lint(BROKEN)
    notices = [v for v in report.info if v.rule_id == "UNPARSEABLE"]
    assert len(notices) == 1, [str(v) for v in report.errors + report.warnings + report.info]
    assert notices[0].severity is RuleSeverity.INFO
    assert notices[0].line_number == 1
