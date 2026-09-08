"""`confiture lint --fail-on <severity>`: the gate a CI pipeline can actually set.

`--fail-on-error` is on by default and no rule in the registry emits at `error`,
so the flag a pipeline reaches for to make lint block is a flag that cannot
block (#247). The threshold is one value now, not two booleans that between them
express three of the four useful settings and none of the fifth.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.core.linting.schema_linter import LintReport, LintViolation, RuleSeverity

runner = CliRunner()

_DEFINED_ONCE = "CREATE TABLE app.tb_widget (id BIGINT PRIMARY KEY);\n"
_DEFINED_AGAIN = "CREATE TABLE app.tb_widget (id BIGINT PRIMARY KEY, label TEXT);\n"


@pytest.fixture
def duplicate_project(tmp_path: Path) -> Iterator[Path]:
    """The #247 reproduction: one `build_001` warning and some `doc_001` info."""
    (tmp_path / "db" / "schema").mkdir(parents=True)
    (tmp_path / "db" / "environments").mkdir(parents=True)
    (tmp_path / "db" / "environments" / "local.yaml").write_text(
        "database_url: postgresql://localhost/test\ninclude_dirs:\n  - path: db/schema\n"
    )
    (tmp_path / "db" / "schema" / "010_widget.sql").write_text(
        "CREATE SCHEMA IF NOT EXISTS app;\n" + _DEFINED_ONCE
    )
    (tmp_path / "db" / "schema" / "020_widget.sql").write_text(_DEFINED_AGAIN)

    old_cwd = Path.cwd()
    os.chdir(tmp_path)
    try:
        yield tmp_path
    finally:
        os.chdir(old_cwd)


def _lint(*args: str):  # type: ignore[no-untyped-def]
    return runner.invoke(app, ["lint", *args])


class TestThreshold:
    def test_fail_on_warning_fails_on_the_duplicate(self, duplicate_project: Path) -> None:
        assert _lint("--fail-on", "warning").exit_code == 1

    def test_fail_on_error_passes_the_duplicate(self, duplicate_project: Path) -> None:
        """The trap #247 was filed for, now something an operator can choose."""
        assert _lint("--fail-on", "error").exit_code == 0

    def test_fail_on_info_fails_on_an_info_finding(self, duplicate_project: Path) -> None:
        assert _lint("--fail-on", "info", "--select", "doc").exit_code == 1

    def test_the_default_threshold_is_still_error(self, duplicate_project: Path) -> None:
        """Unchanged behaviour: no flag means `--fail-on error`."""
        assert _lint().exit_code == 0

    def test_the_boolean_aliases_still_mean_what_they_meant(self, duplicate_project: Path) -> None:
        assert _lint("--fail-on-warning").exit_code == 1
        assert _lint("--fail-on-error").exit_code == 0


class TestNever:
    """`--fail-on never` is the setting the two booleans could not express."""

    @staticmethod
    def _report_with_an_error() -> LintReport:
        return LintReport(
            errors=[
                LintViolation(
                    rule_id="acl_001",
                    rule_name="Missing Grant",
                    severity=RuleSeverity.ERROR,
                    object_type="table",
                    object_name="app.tb_widget",
                    message="no grant",
                )
            ]
        )

    @patch("confiture.cli.commands.schema.SchemaLinter")
    def test_never_passes_even_when_errors_exist(self, linter_class: MagicMock) -> None:
        linter_class.return_value.lint.return_value = self._report_with_an_error()

        assert _lint("--select", "acl", "--fail-on", "never").exit_code == 0

    @patch("confiture.cli.commands.schema.SchemaLinter")
    def test_and_the_same_run_fails_at_error(self, linter_class: MagicMock) -> None:
        """So it is `never` that suppressed it, not the absence of a finding."""
        linter_class.return_value.lint.return_value = self._report_with_an_error()

        assert _lint("--select", "acl", "--fail-on", "error").exit_code == 1


class TestRejections:
    def test_an_unknown_severity_is_a_configuration_error(self, duplicate_project: Path) -> None:
        result = _lint("--fail-on", "bogus", "--format", "json")

        assert result.exit_code == 5, result.output
        envelope = json.loads(result.stdout)
        assert envelope["error"]["code"] == "CONFIG_010"
        for valid in ("error", "warning", "info", "never"):
            assert valid in json.dumps(envelope)

    def test_the_threshold_and_an_alias_together_are_a_usage_error(
        self, duplicate_project: Path
    ) -> None:
        assert _lint("--fail-on", "error", "--fail-on-warning").exit_code == 2
        assert _lint("--fail-on", "warning", "--fail-on-error").exit_code == 2
