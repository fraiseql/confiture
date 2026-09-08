"""`build_001` is an error, so the gate a pipeline sets by default can fire.

`--fail-on-error` is on by default and, until this release, no rule that runs by
default emitted at `error` — so the flag every pipeline reaches for was a flag
that could not block, and four real duplicate view definitions sat behind a green
tick for months (#247). Documenting the trap and adding `--fail-on` answered half
of it; the other half is a default-on rule that actually reaches the threshold.

`build_001` is that rule. A second definition of the same object is never what
the author meant, and which one survives depends on the order the files are
concatenated in — something no reader of either file can see. That is an error,
not a note, and this file is the contract: the registry declares it, the CLI
emits it, a plain `confiture lint` exits 1 on it, and the three ways to decline
it all work.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.core.linting.rule_registry import LINT_RULES

runner = CliRunner()

_ENV = "database_url: postgresql://localhost/test\ninclude_dirs:\n  - path: db/schema\n"
_FIRST = "CREATE SCHEMA IF NOT EXISTS app;\nCREATE TABLE app.tb_widget (id BIGINT PRIMARY KEY);\n"
_AGAIN = "CREATE TABLE app.tb_widget (id BIGINT PRIMARY KEY, label TEXT);\n"


@pytest.fixture
def duplicate_project(tmp_path: Path) -> Iterator[Path]:
    """One object, two definitions — #247's shape, at its smallest."""
    (tmp_path / "db" / "schema").mkdir(parents=True)
    (tmp_path / "db" / "environments").mkdir(parents=True)
    (tmp_path / "db" / "environments" / "local.yaml").write_text(_ENV)
    (tmp_path / "db" / "schema" / "010_widget.sql").write_text(_FIRST)
    (tmp_path / "db" / "schema" / "020_widget.sql").write_text(_AGAIN)

    old_cwd = Path.cwd()
    os.chdir(tmp_path)
    try:
        yield tmp_path
    finally:
        os.chdir(old_cwd)


def _lint(*args: str):  # type: ignore[no-untyped-def]
    return runner.invoke(app, ["lint", *args])


def _payload(*args: str) -> dict:
    result = _lint("--format", "json", "--fail-on", "never", *args)
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


class TestTheDeclaration:
    def test_the_registry_declares_it_an_error(self) -> None:
        rule = next(r for r in LINT_RULES if r.code == "build_001")

        assert rule.severity == "error"

    def test_and_it_still_runs_by_default(self) -> None:
        """A promotion nobody selects is a promotion nobody feels."""
        rule = next(r for r in LINT_RULES if r.code == "build_001")

        assert rule.default_on is True

    def test_the_overload_note_beside_it_stays_info(self) -> None:
        """`build_002` reports a legal shape; only the duplicate is an error."""
        rule = next(r for r in LINT_RULES if r.code == "build_002")

        assert rule.severity == "info"


class TestTheEmission:
    def test_the_finding_comes_back_at_error(self, duplicate_project: Path) -> None:
        items = _payload()["violations"]["items"]

        emitted = [i["severity"] for i in items if i["rule_id"] == "build_001"]
        assert emitted == ["error"]

    def test_the_counts_agree_with_it(self, duplicate_project: Path) -> None:
        violations = _payload("--select", "build_001")["violations"]

        assert (violations["errors"], violations["warnings"]) == (1, 0)


class TestTheGate:
    def test_a_plain_lint_now_fails(self, duplicate_project: Path) -> None:
        """The change #247 asked for: exit 0 → exit 1, with no flag at all."""
        assert _lint().exit_code == 1

    def test_and_the_gate_no_longer_reports_itself_unreachable(
        self, duplicate_project: Path
    ) -> None:
        gate = _payload()["gate"]

        assert gate["max_selectable_severity"] == "error"

    def test_the_default_selection_reaches_error_on_a_clean_schema_too(
        self, duplicate_project: Path
    ) -> None:
        """Reachability is a property of the selection, not of this schema."""
        (duplicate_project / "db" / "schema" / "020_widget.sql").unlink()

        result = _lint("--format", "json")

        assert result.exit_code == 0
        assert json.loads(result.stdout)["gate"]["reachable"] is True


class TestThreeWaysToDecline:
    """What the release notes name, each proven rather than asserted.

    `--fail-on warning` is deliberately not among them: `warning` is a *lower*
    threshold than `error`, so an error still trips it.
    """

    def test_fail_on_never_reports_without_failing(self, duplicate_project: Path) -> None:
        result = _lint("--fail-on", "never")

        assert result.exit_code == 0
        assert "build_001" in result.output

    def test_ignoring_the_rule_leaves_the_rest_of_the_lint_running(
        self, duplicate_project: Path
    ) -> None:
        result = _lint("--ignore", "build_001")

        assert result.exit_code == 0
        assert "build_001" not in result.output

    def test_a_baseline_absorbs_the_backlog_and_still_catches_the_next_one(
        self, duplicate_project: Path
    ) -> None:
        baseline = duplicate_project / "lint-baseline.json"

        assert _lint("--baseline", str(baseline), "--write-baseline").exit_code == 0
        assert _lint("--baseline", str(baseline)).exit_code == 0

        (duplicate_project / "db" / "schema" / "030_gadget.sql").write_text(
            "CREATE TABLE app.tb_gadget (id BIGINT PRIMARY KEY);\n"
            "CREATE TABLE app.tb_gadget (id BIGINT PRIMARY KEY, label TEXT);\n"
        )
        assert _lint("--baseline", str(baseline)).exit_code == 1

    def test_fail_on_warning_does_not_decline_it(self, duplicate_project: Path) -> None:
        """A lower threshold is not an exemption — the note the release makes."""
        assert _lint("--fail-on", "warning").exit_code == 1
