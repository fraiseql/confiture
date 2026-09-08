"""`confiture lint --fail-on <severity>`: the gate a CI pipeline can actually set.

`--fail-on-error` is on by default and, before this release, no rule that ran by
default emitted at `error` — so the flag a pipeline reaches for to make lint
block was a flag that could not block (#247). The threshold is one value now,
not two booleans that between them express three of the four useful settings and
none of the fifth; `build_001` is the default-on rule that reaches it.

Two fixtures, because a threshold only means something when findings sit on both
sides of it: one schema whose worst finding is an `error`, one whose worst is a
`warning`.
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
#: `pk_001`, a warning, and nothing above it.
_NO_PRIMARY_KEY = "CREATE TABLE app.tb_gadget (id BIGINT, label TEXT);\n"


def _project(tmp_path: Path, files: dict[str, str]) -> Iterator[Path]:
    (tmp_path / "db" / "schema").mkdir(parents=True)
    (tmp_path / "db" / "environments").mkdir(parents=True)
    (tmp_path / "db" / "environments" / "local.yaml").write_text(
        "database_url: postgresql://localhost/test\ninclude_dirs:\n  - path: db/schema\n"
    )
    for name, sql in files.items():
        (tmp_path / "db" / "schema" / name).write_text(sql)

    old_cwd = Path.cwd()
    os.chdir(tmp_path)
    try:
        yield tmp_path
    finally:
        os.chdir(old_cwd)


@pytest.fixture
def duplicate_project(tmp_path: Path) -> Iterator[Path]:
    """The #247 reproduction: one `build_001` error and some `doc_001` info."""
    yield from _project(
        tmp_path,
        {
            "010_widget.sql": "CREATE SCHEMA IF NOT EXISTS app;\n" + _DEFINED_ONCE,
            "020_widget.sql": _DEFINED_AGAIN,
        },
    )


@pytest.fixture
def warning_project(tmp_path: Path) -> Iterator[Path]:
    """The other side of the threshold: `pk_001` and `doc_001`, nothing worse."""
    yield from _project(
        tmp_path,
        {"010_gadget.sql": "CREATE SCHEMA IF NOT EXISTS app;\n" + _NO_PRIMARY_KEY},
    )


def _lint(*args: str):  # type: ignore[no-untyped-def]
    return runner.invoke(app, ["lint", *args])


class TestThreshold:
    def test_fail_on_warning_fails_on_the_duplicate(self, duplicate_project: Path) -> None:
        assert _lint("--fail-on", "warning").exit_code == 1

    def test_fail_on_error_fails_on_the_duplicate(self, duplicate_project: Path) -> None:
        """`build_001` is an error, so the threshold every pipeline sets reaches it."""
        assert _lint("--fail-on", "error").exit_code == 1

    def test_fail_on_error_passes_a_schema_whose_worst_finding_is_a_warning(
        self, warning_project: Path
    ) -> None:
        """The threshold still discriminates; it is the rule that moved, not it."""
        assert _lint("--fail-on", "error").exit_code == 0

    def test_fail_on_warning_fails_on_that_same_schema(self, warning_project: Path) -> None:
        assert _lint("--fail-on", "warning").exit_code == 1

    def test_fail_on_info_fails_on_an_info_finding(self, duplicate_project: Path) -> None:
        assert _lint("--fail-on", "info", "--select", "doc").exit_code == 1

    def test_the_default_threshold_is_still_error(self, warning_project: Path) -> None:
        """Unchanged: no flag means `--fail-on error`, and a warning is not one."""
        assert _lint().exit_code == 0

    def test_the_boolean_aliases_still_mean_what_they_meant(self, warning_project: Path) -> None:
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
