"""A threshold no selected rule can reach is reported, not obeyed quietly.

`--fail-on-error` was the default and no registered rule emitted at `error`, so
a pipeline that set it got exit 0 forever and read that as "clean" (#247). The
gate now answers a second question beside "did anything fail": *could* anything
have failed. Reachability is computed from the registry's declared severities
plus the escalations the environment config makes, so a project that has
escalated `sec_002` is told the truth rather than a generic warning.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.core.linting.gate import Threshold, compute_gate

runner = CliRunner()

_ENV = "database_url: postgresql://localhost/test\ninclude_dirs:\n  - path: db/schema\n"
#: Deliberately clean: reachability is a property of the *selection*, not of
#: whether this particular schema happens to trip the rule.
_PINNED_DEFINER = """CREATE SCHEMA IF NOT EXISTS app;

CREATE FUNCTION app.fn_widget() RETURNS int
LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog AS $$ SELECT 1 $$;
"""


@pytest.fixture
def project(tmp_path: Path) -> Iterator[Path]:
    (tmp_path / "db" / "schema").mkdir(parents=True)
    (tmp_path / "db" / "environments").mkdir(parents=True)
    (tmp_path / "db" / "environments" / "local.yaml").write_text(_ENV)
    (tmp_path / "db" / "schema" / "010_widget.sql").write_text(_PINNED_DEFINER)

    old_cwd = Path.cwd()
    os.chdir(tmp_path)
    try:
        yield tmp_path
    finally:
        os.chdir(old_cwd)


def _lint(*args: str):  # type: ignore[no-untyped-def]
    return runner.invoke(app, ["lint", *args])


def _gate(*args: str) -> dict:
    result = _lint("--format", "json", *args)
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)["gate"]


class TestTheNotice:
    def test_the_default_selection_cannot_reach_error(self, project: Path) -> None:
        result = _lint("--fail-on", "error")

        assert result.exit_code == 0
        assert "no selected rule emits at 'error'" in result.output
        assert "this gate cannot fail" in result.output

    def test_json_says_the_same_thing(self, project: Path) -> None:
        gate = _gate("--fail-on", "error")

        assert gate["threshold"] == "error"
        assert gate["reachable"] is False
        assert "no selected rule emits at 'error'" in gate["reason"]
        assert gate["max_selectable_severity"] == "warning"

    def test_a_reachable_threshold_says_nothing(self, project: Path) -> None:
        result = _lint("--fail-on", "warning")

        assert "this gate cannot fail" not in result.output

    def test_never_is_reported_as_deliberate_not_as_a_trap(self, project: Path) -> None:
        gate = _gate("--fail-on", "never")

        assert gate["reachable"] is False
        assert "--fail-on never" in gate["reason"]


class TestEscalations:
    """Reachability reads the config, so an escalated project is told the truth."""

    def test_security_lint_severity_error_makes_error_reachable(self, project: Path) -> None:
        (project / "db" / "environments" / "local.yaml").write_text(
            _ENV + "security_lint:\n  enabled: true\n  severity: error\n"
        )

        gate = _gate("--fail-on", "error", "--select", "default,security-definer")

        assert gate["reachable"] is True
        assert gate["max_selectable_severity"] == "error"

    def test_without_the_escalation_the_same_selection_cannot_reach_error(
        self, project: Path
    ) -> None:
        (project / "db" / "environments" / "local.yaml").write_text(
            _ENV + "security_lint:\n  enabled: true\n"
        )

        gate = _gate("--fail-on", "error", "--select", "default,security-definer")

        assert gate["reachable"] is False
        assert gate["max_selectable_severity"] == "warning"


class TestComputeGate:
    """The unit behind the two payloads."""

    def test_a_baseline_run_can_always_fail(self) -> None:
        gate = compute_gate(threshold=Threshold.ERROR, selected=["doc_001"], baseline_active=True)

        assert gate.reachable is True
        assert gate.reason is None

    def test_an_empty_selection_is_unreachable_and_says_why(self) -> None:
        gate = compute_gate(threshold=Threshold.INFO, selected=[])

        assert gate.reachable is False
        assert gate.max_selectable_severity is None
        assert "no rule is selected" in (gate.reason or "")

    def test_info_is_reachable_from_an_info_rule(self) -> None:
        gate = compute_gate(threshold=Threshold.INFO, selected=["doc_001"])

        assert gate.reachable is True
        assert gate.max_selectable_severity == "info"

    def test_an_escalation_raises_the_ceiling(self) -> None:
        gate = compute_gate(
            threshold=Threshold.ERROR,
            selected=["sec_002"],
            escalations={"sec_002": "error"},
        )

        assert gate.reachable is True
        assert gate.max_selectable_severity == "error"
