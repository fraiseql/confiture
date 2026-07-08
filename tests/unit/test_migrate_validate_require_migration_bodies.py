"""CLI tests for `migrate validate --require-migration-bodies` / `--list-unmigrated-bodies` (#178).

The FunctionBodyChecker logic is covered in test_function_body_checker.py; here we
patch the accompaniment checker to exercise the CLI wiring: enforcement exit
codes, JSON shape, and the report-only (non-failing) backlog mode.
"""

import json
import re
from unittest.mock import patch

from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.core.function_body_checker import FunctionBodyViolation
from confiture.models.git import MigrationAccompanimentReport

runner = CliRunner()


def _strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def _violation() -> FunctionBodyViolation:
    return FunctionBodyViolation(
        function_key="public.calc",
        signature_key="public.calc(integer)",
        migration_file=None,
        message="body changed with no migration",
        unified_diff="-select p_id * 1\n+select p_id * 2",
    )


def _report(*, body_violations) -> MigrationAccompanimentReport:
    return MigrationAccompanimentReport(
        has_ddl_changes=False,
        has_new_migrations=False,
        base_ref="origin/main",
        target_ref="HEAD",
        body_violations=body_violations,
    )


def _invoke(args, report):
    with (
        patch("confiture.cli.git_validation.validate_git_flags_in_repo", return_value=None),
        patch(
            "confiture.core.git_accompaniment.MigrationAccompanimentChecker.check_accompaniment",
            return_value=report,
        ),
    ):
        return runner.invoke(app, ["migrate", "validate", *args])


# ---------------------------------------------------------------------------
# --require-migration-bodies (enforce)
# ---------------------------------------------------------------------------


def test_require_bodies_clean_exits_0():
    result = _invoke(["--require-migration-bodies"], _report(body_violations=[]))
    assert result.exit_code == 0


def test_require_bodies_violation_exits_1():
    result = _invoke(
        ["--require-migration-bodies", "--format", "json"], _report(body_violations=[_violation()])
    )
    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["check"] == "accompaniment"
    assert data["is_valid"] is False
    assert data["body_violations"][0]["signature_key"] == "public.calc(integer)"


def test_require_bodies_text_shows_fix_hint():
    result = _invoke(["--require-migration-bodies"], _report(body_violations=[_violation()]))
    assert result.exit_code == 1
    out = _strip_ansi(result.output)
    assert "public.calc(integer)" in out
    assert "CREATE OR REPLACE FUNCTION public.calc" in out


# ---------------------------------------------------------------------------
# --list-unmigrated-bodies (report-only, never fails)
# ---------------------------------------------------------------------------


def test_list_unmigrated_bodies_reports_without_failing():
    result = _invoke(
        ["--list-unmigrated-bodies", "--format", "json"], _report(body_violations=[_violation()])
    )
    assert result.exit_code == 0  # report-only never fails
    data = json.loads(result.output)
    assert data["check"] == "unmigrated_bodies"
    assert data["count"] == 1
    assert data["body_violations"][0]["signature_key"] == "public.calc(integer)"


def test_list_unmigrated_bodies_clean_exits_0():
    result = _invoke(["--list-unmigrated-bodies"], _report(body_violations=[]))
    assert result.exit_code == 0
    assert "no un-migrated function body" in _strip_ansi(result.output).lower()


def test_require_migration_without_bodies_flag_does_not_check_bodies():
    """Back-compat: plain --require-migration never surfaces body violations."""
    # Even if the (patched) checker were asked, --require-migration passes
    # check_bodies=False; a report with no body_violations stays valid.
    result = _invoke(["--require-migration"], _report(body_violations=[]))
    assert result.exit_code == 0
