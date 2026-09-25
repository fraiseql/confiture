"""``confiture lint-unified``, run by its command line on a small project.

``lint-unified`` puts four linters in one report: Squawk (``--check safety``) and
SQLFluff (``--check format``), which are external tools confiture does not
install, and the schema linter and tree rules, which are its own. The project
here holds one migration that both external tools flag — an index built without
``CONCURRENTLY``, a ``NOT NULL`` column added without a default, keywords in two
cases — and a two-table schema tree.

With the external tools taken away (``squawk`` off ``PATH``, ``sqlfluff``
unimportable), the file pins what the command reports: no issue from either tool,
exit 0, while the schema linter and the tree rules still run and still fail the
run on an error. Where a tool is installed, the file pins that its findings reach
the report; those tests skip where it is not.

Five tests are strict ``xfail``s, each a defect this file found:

- a missing tool is reported as a clean run, naming neither tool;
- a schema finding names the environment (``local``) instead of its file;
- no finding from Squawk 2.x reaches the report: its JSON is not the shape
  ``SquawkRunner`` parses;
- a SQLFluff finding carries no line: SQLFluff calls it ``start_line_no``;
- without FILES, the tool checks lint nothing, though ``--help`` says the default
  is all schema files.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.error_codes import FINDINGS

pytestmark = pytest.mark.integration

runner = CliRunner()

MIGRATION = "db/migrations/001_index_widget_label.sql"

_HAS_SQUAWK = shutil.which("squawk") is not None
_HAS_SQLFLUFF = importlib.util.find_spec("sqlfluff") is not None

needs_squawk = pytest.mark.skipif(not _HAS_SQUAWK, reason="squawk is not installed on PATH")
needs_sqlfluff = pytest.mark.skipif(not _HAS_SQLFLUFF, reason="sqlfluff is not installed")


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A project with a ``widget`` schema and one migration both external tools flag."""
    schema = tmp_path / "db" / "schema"
    schema.mkdir(parents=True)
    (schema / "10_widget.sql").write_text(
        "create TABLE widget (id BIGINT PRIMARY KEY, label TEXT);\n"
    )
    environments = tmp_path / "db" / "environments"
    environments.mkdir(parents=True)
    (environments / "local.yaml").write_text(
        "name: local\ndatabase_url: postgresql://localhost/nonexistent\ninclude_dirs: [db/schema]\n"
    )
    migration = tmp_path / MIGRATION
    migration.parent.mkdir(parents=True)
    migration.write_text(
        "create index idx_widget_label on widget (label);\n"
        "ALTER TABLE widget ADD COLUMN rank int NOT NULL;\n"
    )
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def without_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    """Take squawk off ``PATH`` and make ``import sqlfluff`` fail, installed or not."""
    path = os.environ.get("PATH", "").split(os.pathsep)
    monkeypatch.setenv(
        "PATH", os.pathsep.join(d for d in path if not (Path(d) / "squawk").exists())
    )
    monkeypatch.setitem(sys.modules, "sqlfluff", None)
    assert shutil.which("squawk") is None


def _json(stdout: str) -> dict:
    """The payload, which must be all of stdout: a consumer parses the stream."""
    return json.loads(stdout)


def _by_tool(payload: dict, tool: str) -> list[dict]:
    return [issue for issue in payload["issues"] if issue["tool"] == tool]


# ---------------------------------------------------------------------------
# The external tools missing
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("without_tools")
def test_the_tool_checks_report_no_issue_when_squawk_and_sqlfluff_are_missing(
    project: Path,
) -> None:
    result = runner.invoke(
        app,
        ["lint-unified", "--check", "safety", "--check", "format", MIGRATION, "--format", "json"],
    )

    assert result.exit_code == 0, result.output
    payload = _json(result.stdout)
    assert payload["summary"] == {"total": 0, "errors": 0, "warnings": 0, "info": 0}
    assert payload["issues"] == []


@pytest.mark.usefixtures("without_tools")
@pytest.mark.xfail(
    strict=True,
    reason="#358: a missing squawk/sqlfluff is reported as 'No issues found.', naming neither tool",
)
def test_a_missing_tool_is_named_rather_than_reported_clean(project: Path) -> None:
    result = runner.invoke(
        app, ["lint-unified", "--check", "safety", "--check", "format", MIGRATION]
    )

    assert result.exit_code == 0, result.output
    assert "squawk" in result.output
    assert "sqlfluff" in result.output


@pytest.mark.usefixtures("without_tools")
def test_the_schema_linter_and_tree_rules_run_without_the_external_tools(project: Path) -> None:
    (project / "db" / "schema" / "10_gadget.sql").write_text(
        "CREATE TABLE gadget (id BIGINT PRIMARY KEY);\n"
    )

    result = runner.invoke(app, ["lint-unified", MIGRATION, "--format", "json"])

    assert result.exit_code == FINDINGS, result.output
    payload = _json(result.stdout)
    assert {issue["tool"] for issue in payload["issues"]} == {"schema", "tree"}
    assert sorted(issue["message"] for issue in _by_tool(payload, "schema")) == [
        "Table 'gadget' should have a COMMENT describing its purpose",
        "Table 'widget' should have a COMMENT describing its purpose",
    ]
    (tree,) = _by_tool(payload, "tree")
    assert (tree["rule"], tree["severity"]) == ("tree_001", "error")
    assert "10_gadget.sql, 10_widget.sql" in tree["message"]


@pytest.mark.usefixtures("without_tools")
def test_a_schema_finding_names_the_file_it_is_in(project: Path) -> None:
    result = runner.invoke(app, ["lint-unified", "--check", "schema", "--format", "json"])

    assert result.exit_code == 0, result.output
    (finding,) = _by_tool(_json(result.stdout), "schema")
    assert (finding["file"], finding["line"]) == ("db/schema/10_widget.sql", 1)


# ---------------------------------------------------------------------------
# The external tools present
# ---------------------------------------------------------------------------


@needs_squawk
@pytest.mark.xfail(
    strict=True,
    reason="#358: SquawkRunner parses {filename, violations[]}; squawk 2.x emits a flat list",
)
def test_squawk_findings_reach_the_report(project: Path) -> None:
    result = runner.invoke(
        app, ["lint-unified", "--check", "safety", MIGRATION, "--format", "json"]
    )

    assert result.exit_code == 0, result.output
    rules = {issue["rule"] for issue in _by_tool(_json(result.stdout), "squawk")}
    assert {"require-concurrent-index-creation", "adding-required-field"} <= rules


@needs_sqlfluff
def test_sqlfluff_findings_reach_the_report(project: Path) -> None:
    result = runner.invoke(
        app, ["lint-unified", "--check", "format", MIGRATION, "--format", "json"]
    )

    assert result.exit_code == 0, result.output
    payload = _json(result.stdout)
    issues = _by_tool(payload, "sqlfluff")
    assert issues
    assert len(issues) == payload["summary"]["total"] == payload["summary"]["warnings"]
    assert {issue["file"] for issue in issues} == {MIGRATION}
    assert "CP01" in {issue["rule"] for issue in issues}


@needs_sqlfluff
@pytest.mark.xfail(
    strict=True, reason="#358: SQLFluffRunner reads 'line_no'; sqlfluff reports 'start_line_no'"
)
def test_a_sqlfluff_finding_carries_its_line(project: Path) -> None:
    result = runner.invoke(
        app, ["lint-unified", "--check", "format", MIGRATION, "--format", "json"]
    )

    assert result.exit_code == 0, result.output
    issues = _by_tool(_json(result.stdout), "sqlfluff")
    assert issues
    assert all(isinstance(issue["line"], int) for issue in issues), issues


@needs_sqlfluff
@pytest.mark.xfail(
    strict=True,
    reason="#358: without FILES the tool checks lint nothing; --help says all schema files",
)
def test_without_files_the_format_check_lints_the_schema_files(project: Path) -> None:
    result = runner.invoke(app, ["lint-unified", "--check", "format", "--format", "json"])

    assert result.exit_code == 0, result.output
    files = {issue["file"] for issue in _by_tool(_json(result.stdout), "sqlfluff")}
    assert any(file.endswith("db/schema/10_widget.sql") for file in files), files
