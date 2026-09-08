"""`confiture lint-unified --check tree` over a real tree.

These used to mock `SchemaLinter` and assert that `lint_tree` was called with
the right arguments, which held the wiring in place and said nothing about what
the rules report. Both commands now resolve their tree the same way — through
the environment's own include configuration, or the `--schema-dir` an operator
names — so the tests run the rules against files on disk and read the findings.
"""

import json
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()

_ENV = "database_url: postgresql://localhost/test\ninclude_dirs:\n  - path: db/schema\n"


@pytest.fixture
def project(tmp_path: Path) -> Iterator[Path]:
    """A project whose `db/schema` is clean, cwd'd into for the duration."""
    schema = tmp_path / "db" / "schema"
    schema.mkdir(parents=True)
    (tmp_path / "db" / "environments").mkdir(parents=True)
    (tmp_path / "db" / "environments" / "local.yaml").write_text(_ENV)
    (schema / "00001_create.sql").write_text("CREATE TABLE tb_a (id INT PRIMARY KEY);\n")
    old_cwd = Path.cwd()
    os.chdir(tmp_path)
    try:
        yield tmp_path
    finally:
        os.chdir(old_cwd)


def _tree(directory: Path, **files: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    for stem, sql in files.items():
        (directory / f"{stem}.sql").write_text(sql)
    return directory


class TestLintUnifiedTree:
    def test_a_clean_tree_reports_nothing(self, project: Path) -> None:
        result = runner.invoke(app, ["lint-unified", "--check", "tree"])

        assert result.exit_code == 0
        assert "No issues found" in result.stdout

    def test_it_reports_a_duplicate_prefix(self, project: Path) -> None:
        _tree(
            project / "db" / "schema",
            **{
                "00002_foo": "CREATE TABLE tb_foo (id INT PRIMARY KEY);",
                "00002_bar": "CREATE TABLE tb_bar (id INT PRIMARY KEY);",
            },
        )

        result = runner.invoke(app, ["lint-unified", "--check", "tree"])

        assert result.exit_code == 1
        assert "tree_001" in result.stdout

    def test_it_reports_a_gap_in_the_sequence(self, project: Path) -> None:
        _tree(
            project / "db" / "schema",
            **{"00009_late": "CREATE TABLE tb_late (id INT PRIMARY KEY);"},
        )

        result = runner.invoke(app, ["lint-unified", "--check", "tree"])

        assert "tree_003" in result.stdout

    def test_json_output_carries_the_tree_tool_and_the_new_code(self, project: Path) -> None:
        _tree(
            project / "db" / "schema",
            **{
                "00002_foo": "CREATE TABLE tb_foo (id INT PRIMARY KEY);",
                "00002_bar": "CREATE TABLE tb_bar (id INT PRIMARY KEY);",
            },
        )

        result = runner.invoke(app, ["lint-unified", "--check", "tree", "--format", "json"])

        issues = json.loads(result.stdout)["issues"]
        assert [(i["tool"], i["rule"]) for i in issues] == [("tree", "tree_001")]

    def test_check_schema_does_not_run_the_tree_rules(self, project: Path) -> None:
        _tree(
            project / "db" / "schema",
            **{
                "00002_foo": "CREATE TABLE tb_foo (id INT PRIMARY KEY);",
                "00002_bar": "CREATE TABLE tb_bar (id INT PRIMARY KEY);",
            },
        )

        result = runner.invoke(app, ["lint-unified", "--check", "schema", "--format", "json"])

        tools = {i["tool"] for i in json.loads(result.stdout)["issues"]}
        assert "tree" not in tools

    def test_an_explicit_schema_dir_wins_over_the_environment(self, project: Path) -> None:
        elsewhere = _tree(
            project / "elsewhere",
            **{
                "00002_foo": "CREATE TABLE tb_foo (id INT PRIMARY KEY);",
                "00002_bar": "CREATE TABLE tb_bar (id INT PRIMARY KEY);",
            },
        )

        result = runner.invoke(
            app,
            ["lint-unified", "--check", "tree", "--schema-dir", str(elsewhere), "--format", "json"],
        )

        issues = json.loads(result.stdout)["issues"]
        assert [i["rule"] for i in issues] == ["tree_001"]

    def test_an_overrides_dir_brings_tree_004_with_it(self, project: Path) -> None:
        _tree(
            project / "db" / "overrides",
            **{"00099_gone": "-- override of a file that is not there"},
        )

        result = runner.invoke(
            app,
            [
                "lint-unified",
                "--check",
                "tree",
                "--overrides-dir",
                "db/overrides",
                "--format",
                "json",
            ],
        )

        issues = json.loads(result.stdout)["issues"]
        assert [i["rule"] for i in issues] == ["tree_004"]

    def test_without_an_overrides_dir_tree_004_is_not_run(self, project: Path) -> None:
        _tree(
            project / "db" / "overrides",
            **{"00099_gone": "-- override of a file that is not there"},
        )

        result = runner.invoke(app, ["lint-unified", "--check", "tree", "--format", "json"])

        assert json.loads(result.stdout)["issues"] == []
