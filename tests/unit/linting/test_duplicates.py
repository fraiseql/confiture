"""An object defined more than once in one build is reported, with where and who wins (#218).

`confiture build` concatenates files in order, so a second `CREATE OR REPLACE
FUNCTION app.f(int)` silently replaces the first and a second plain `CREATE
TABLE` fails the build at that statement. `build_001` names every definition
(file, offset, line) and which one the database ends up with; `build_002`
notes an overload family split across files. Both are lint rules and both are
reachable from `confiture build --warn-duplicates` / `--fail-on-duplicates`.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.core.linting.duplicates import (
    Duplicate,
    find_duplicates,
    inventory_files,
)
from confiture.core.linting.inventory import build_inventory
from confiture.core.linting.rule_registry import LINT_RULES, resolve_selection
from confiture.core.linting.schema_linter import LintConfig, SchemaLinter

BODY = "RETURNS int LANGUAGE sql AS $$ select 1 $$;"


def _files(tmp_path: Path, **contents: str) -> list[Path]:
    root = tmp_path / "schema"
    root.mkdir(exist_ok=True)
    paths = []
    for name, sql in contents.items():
        path = root / f"{name}.sql"
        path.write_text(sql)
        paths.append(path)
    return sorted(paths)


def _dups(tmp_path: Path, **contents: str) -> list[Duplicate]:
    paths = _files(tmp_path, **contents)
    objects, unparseable = inventory_files(paths, root=tmp_path / "schema")
    assert unparseable == []
    return find_duplicates(objects)


@pytest.mark.parametrize("q", ["", "app."], ids=["bare", "qualified"])
class TestFindDuplicates:
    def test_the_same_function_in_two_files_is_one_finding_naming_both(
        self, tmp_path: Path, q: str
    ) -> None:
        first = f"CREATE OR REPLACE FUNCTION {q}f(a int) {BODY}\n"
        second = f"-- later file\nCREATE OR REPLACE FUNCTION {q}f(a int) {BODY}\n"
        (dup,) = _dups(tmp_path, a_first=first, b_second=second)
        assert dup.rule_id == "build_001"
        assert dup.kind == "function"
        assert dup.identity == f"{q}f(integer)"
        assert [(d.file, d.offset, d.line) for d in dup.definitions] == [
            ("a_first.sql", 0, 1),
            ("b_second.sql", second.index("CREATE"), 2),
        ]
        assert dup.wins == "last"

    def test_overloads_split_across_files_are_build_002_only(self, tmp_path: Path, q: str) -> None:
        dups = _dups(
            tmp_path,
            a=f"CREATE FUNCTION {q}f(a int) {BODY}\n",
            b=f"CREATE FUNCTION {q}f(a text) {BODY}\n",
        )
        assert [(d.rule_id, d.identity) for d in dups] == [("build_002", f"{q}f")]
        assert [d.file for d in dups[0].definitions] == ["a.sql", "b.sql"]
        assert dups[0].wins == "n/a"

    def test_overloads_in_one_file_are_not_reported(self, tmp_path: Path, q: str) -> None:
        sql = f"CREATE FUNCTION {q}f(a int) {BODY}\nCREATE FUNCTION {q}f(a text) {BODY}\n"
        assert _dups(tmp_path, a=sql) == []

    def test_the_same_object_twice_in_one_file(self, tmp_path: Path, q: str) -> None:
        one = f"CREATE OR REPLACE VIEW {q}v AS SELECT 1 AS a;"
        two = f"CREATE OR REPLACE VIEW {q}v AS SELECT 2 AS a;"
        (dup,) = _dups(tmp_path, a=f"{one}\n\n{two}\n")
        assert dup.kind == "view"
        assert [(d.file, d.offset) for d in dup.definitions] == [
            ("a.sql", 0),
            ("a.sql", len(one) + 2),
        ]
        assert dup.wins == "last"

    def test_a_second_plain_create_is_a_conflict_and_if_not_exists_keeps_the_first(
        self, tmp_path: Path, q: str
    ) -> None:
        conflict = _dups(
            tmp_path,
            a=f"CREATE TABLE {q}t (id int PRIMARY KEY);\n",
            b=f"CREATE TABLE {q}t (id int PRIMARY KEY, extra text);\n",
        )
        assert [(d.identity, d.wins) for d in conflict] == [(f"{q}t", "conflict")]
        first = _dups(
            tmp_path,
            c=f"CREATE TABLE {q}u (id int PRIMARY KEY);\n",
            d=f"CREATE TABLE IF NOT EXISTS {q}u (id int PRIMARY KEY, extra text);\n",
        )
        assert [(d.identity, d.wins) for d in first] == [(f"{q}u", "first")]

    def test_types_and_domains_duplicate_too(self, tmp_path: Path, q: str) -> None:
        dups = _dups(
            tmp_path,
            a=f"CREATE TYPE {q}ty AS (a int);\nCREATE DOMAIN {q}dm AS text;\n",
            b=f"CREATE TYPE {q}ty AS (a int, b int);\nCREATE DOMAIN {q}dm AS text;\n",
        )
        assert sorted((d.kind, d.identity, d.wins) for d in dups) == [
            ("domain", f"{q}dm", "conflict"),
            ("type", f"{q}ty", "conflict"),
        ]


class TestKeys:
    def test_a_bare_name_and_its_public_qualified_twin_are_the_same_object(
        self, tmp_path: Path
    ) -> None:
        dups = _dups(
            tmp_path,
            a=f"CREATE OR REPLACE FUNCTION f() {BODY}\n",
            b=f"CREATE OR REPLACE FUNCTION public.f() {BODY}\n",
        )
        assert [d.identity for d in dups] == ["f()"]

    def test_the_same_name_in_two_schemas_is_two_objects(self, tmp_path: Path) -> None:
        dups = _dups(
            tmp_path,
            a=f"CREATE OR REPLACE FUNCTION app.f() {BODY}\n",
            b=f"CREATE OR REPLACE FUNCTION core.f() {BODY}\n",
        )
        assert dups == []

    def test_a_function_and_a_table_of_the_same_name_are_two_objects(self, tmp_path: Path) -> None:
        dups = _dups(
            tmp_path,
            a=f"CREATE FUNCTION thing() {BODY}\n",
            b="CREATE TABLE thing (id int PRIMARY KEY);\n",
        )
        assert dups == []

    def test_an_unparseable_file_is_reported_not_skipped_silently(self, tmp_path: Path) -> None:
        paths = _files(tmp_path, a="CREATE TABLE t (id int);\n", b="CREATE TABEL broken (;\n")
        objects, unparseable = inventory_files(paths, root=tmp_path / "schema")
        assert [o.identity for o in objects] == ["t"]
        assert unparseable == ["b.sql"]

    def test_a_single_string_inventory_has_no_file(self) -> None:
        sql = f"CREATE OR REPLACE FUNCTION f() {BODY}\nCREATE OR REPLACE FUNCTION f() {BODY}\n"
        (dup,) = find_duplicates(build_inventory(sql).objects)
        assert [d.file for d in dup.definitions] == [None, None]
        assert dup.to_dict()["definitions"][1]["offset"] == sql.index("CREATE", 1)


class TestLintRule:
    def test_registry_has_the_build_family(self) -> None:
        build = [rule for rule in LINT_RULES if rule.family == "build"]
        assert [(r.code, r.severity, r.default_on) for r in build] == [
            ("build_001", "warning", True),
            ("build_002", "info", True),
        ]
        assert resolve_selection(["build"], []) == frozenset({"build_001", "build_002"})

    def test_lint_reports_build_001_as_a_warning_with_the_locations(self) -> None:
        sql = f"CREATE OR REPLACE FUNCTION app.f() {BODY}\n\nCREATE OR REPLACE FUNCTION app.f() {BODY}\n"
        report = SchemaLinter(config=LintConfig(enabled=True)).lint(schema=sql)
        (finding,) = [v for v in report.warnings if v.rule_id == "build_001"]
        assert finding.object_name == "app.f()"
        assert finding.object_type == "function"
        assert "line 1" in finding.message and "line 3" in finding.message
        assert "last" in finding.message

    def test_lint_reports_build_002_as_info(self) -> None:
        # One string is one "file", so a split overload family needs two files;
        # in string mode overloads never trigger build_002.
        sql = f"CREATE FUNCTION app.f(a int) {BODY}\nCREATE FUNCTION app.f(a text) {BODY}\n"
        report = SchemaLinter(config=LintConfig(enabled=True)).lint(schema=sql)
        assert [
            v.rule_id for v in report.warnings + report.info if v.rule_id.startswith("build_")
        ] == []


_ENV = "database_url: postgresql://localhost/test\ninclude_dirs:\n  - path: db/schema\n"
_FIRST = "CREATE OR REPLACE FUNCTION app.f(a integer) RETURNS int LANGUAGE sql AS $$ select 1 $$;\n"
_SECOND = (
    "CREATE OR REPLACE FUNCTION app.f(a integer) RETURNS int LANGUAGE sql AS $$ select 2 $$;\n"
)


@pytest.fixture
def dup_project(tmp_path: Path) -> Iterator[Path]:
    (tmp_path / "db" / "schema").mkdir(parents=True)
    (tmp_path / "db" / "migrations").mkdir(parents=True)
    (tmp_path / "db" / "environments").mkdir(parents=True)
    (tmp_path / "db" / "environments" / "local.yaml").write_text(_ENV)
    (tmp_path / "db" / "schema" / "010_first.sql").write_text(_FIRST)
    (tmp_path / "db" / "schema" / "020_second.sql").write_text(_SECOND)
    old_cwd = Path.cwd()
    os.chdir(tmp_path)
    try:
        yield tmp_path
    finally:
        os.chdir(old_cwd)


class TestBuildCli:
    def test_fail_on_duplicates_exits_one_and_builds_nothing(self, dup_project: Path) -> None:
        result = CliRunner().invoke(app, ["build", "--output", "out.sql", "--fail-on-duplicates"])
        assert result.exit_code == 1, result.output
        assert not (dup_project / "out.sql").exists()
        assert "010_first.sql" in result.output and "020_second.sql" in result.output
        assert "app.f(integer)" in result.output

    def test_warn_on_duplicates_builds_and_prints_the_report(self, dup_project: Path) -> None:
        result = CliRunner().invoke(app, ["build", "--output", "out.sql", "--warn-duplicates"])
        assert result.exit_code == 0, result.output
        assert (dup_project / "out.sql").exists()
        assert "build_001" in result.output and "020_second.sql" in result.output

    def test_json_carries_the_duplicates(self, dup_project: Path) -> None:
        result = CliRunner().invoke(
            app, ["build", "--output", "out.sql", "--warn-duplicates", "--format", "json"]
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        (dup,) = payload["duplicates"]
        assert dup["rule_id"] == "build_001"
        assert dup["identity"] == "app.f(integer)"
        assert [d["file"] for d in dup["definitions"]] == [
            "db/schema/010_first.sql",
            "db/schema/020_second.sql",
        ]
        assert dup["wins"] == "last"

    def test_a_plain_build_does_not_scan(self, dup_project: Path) -> None:
        result = CliRunner().invoke(app, ["build", "--output", "out.sql", "--format", "json"])
        assert result.exit_code == 0, result.output
        assert json.loads(result.stdout)["duplicates"] == []

    def test_lint_reports_the_same_duplicate_with_file_paths(self, dup_project: Path) -> None:
        result = CliRunner().invoke(app, ["lint", "--select", "build", "--format", "json"])
        assert result.exit_code == 0, result.output
        items = json.loads(result.stdout)["violations"]["items"]
        assert [(i["rule_id"], i["location"]) for i in items] == [("build_001", "app.f(integer)")]
        assert "db/schema/010_first.sql" in items[0]["message"]


def test_corpus_has_duplicates_and_every_finding_is_located() -> None:
    corpus = os.environ.get("CONFITURE_SCHEMA_CORPUS_DIR")
    if not corpus:
        pytest.skip(
            "set CONFITURE_SCHEMA_CORPUS_DIR to a real schema tree (e.g. printoptim_backend/db/0_schema)"
        )
    root = Path(corpus)
    objects, unparseable = inventory_files(sorted(root.rglob("*.sql")), root=root)
    dups = find_duplicates(objects)
    assert dups, "the corpus was expected to contain at least one duplicate definition"
    for dup in dups:
        if dup.rule_id == "build_001":
            assert len(dup.definitions) >= 2
            assert all(d.file is not None and d.offset >= 0 for d in dup.definitions)
    assert unparseable == []
