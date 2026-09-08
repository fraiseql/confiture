"""The ``qual`` family: a ``CREATE`` written without a schema is reported (#248).

Where an unqualified ``CREATE`` lands is decided at apply time by the applying
role's ``search_path``, so the same file applied by two roles produces the
object in two schemas. ``qual_001`` covers routines — functions, procedures and
aggregates — at ``warning``, on by default; ``qual_002`` covers relations and
types, at ``warning``, opt-in, because the volume in an existing project is much
higher and the two codes let a project adopt one and baseline the other.

Every case runs on a bare name and on its schema-qualified twin: the qualified
one must be silent.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.core.linting.rule_registry import LINT_RULES, default_codes, resolve_selection
from confiture.core.linting.schema_linter import LintConfig, LintReport, SchemaLinter

BODY = "RETURNS int LANGUAGE sql AS $$ select 1 $$;"
QUAL_CODES = frozenset({"qual_001", "qual_002"})
RELATIONS = LintConfig(enabled=True, check_qualification_relations=True)


def _report(sql: str, **config: bool) -> LintReport:
    return SchemaLinter(config=LintConfig(enabled=True, **config)).lint(schema=sql)


def _findings(sql: str, **config: bool) -> list[tuple[str, str]]:
    report = _report(sql, **config)
    return sorted(
        (v.rule_id, v.object_name)
        for v in report.errors + report.warnings + report.info
        if v.rule_id.startswith("qual_")
    )


@pytest.mark.parametrize("q", ["", "app."], ids=["bare", "qualified"])
class TestQual001Routines:
    def test_the_issues_own_function(self, q: str) -> None:
        sql = (
            f"CREATE OR REPLACE FUNCTION {q}fn_slugify(value TEXT)\n"
            "RETURNS TEXT\nLANGUAGE sql\nIMMUTABLE\nAS $$ SELECT lower(value) $$;\n"
        )
        expected = [] if q else [("qual_001", "fn_slugify(text)")]
        assert _findings(sql) == expected

    def test_procedure(self, q: str) -> None:
        sql = f"CREATE PROCEDURE {q}p(x bigint) LANGUAGE sql AS $$ select 1 $$;\n"
        assert _findings(sql) == ([] if q else [("qual_001", "p(bigint)")])

    def test_aggregate(self, q: str) -> None:
        sql = f"CREATE AGGREGATE {q}agg_sum (int4) (sfunc = int4pl, stype = int4);\n"
        assert _findings(sql) == ([] if q else [("qual_001", "agg_sum(int4)")])


class TestQual001Details:
    def test_the_finding_is_a_warning_at_the_statements_line(self) -> None:
        sql = f"-- header\n\nCREATE FUNCTION fn_slugify(value TEXT) {BODY}\n"

        (finding,) = [v for v in _report(sql).warnings if v.rule_id == "qual_001"]

        assert finding.severity.value == "warning"
        assert finding.object_type == "function"
        assert finding.line_number == 3
        assert "search_path" in finding.message

    def test_relations_stay_quiet_under_the_default_selection(self) -> None:
        sql = "CREATE TABLE tb_t (id int PRIMARY KEY);\nCREATE VIEW v_t AS SELECT 1 AS a;\n"

        assert _findings(sql) == []


@pytest.mark.parametrize("q", ["", "app."], ids=["bare", "qualified"])
class TestQual002RelationsAndTypes:
    def test_table_view_and_materialized_view(self, q: str) -> None:
        sql = (
            f"CREATE TABLE {q}tb_t (id int PRIMARY KEY);\n"
            f"CREATE VIEW {q}v_t AS SELECT 1 AS a;\n"
            f"CREATE MATERIALIZED VIEW {q}mv_t AS SELECT 1 AS a;\n"
        )
        expected = [] if q else [("qual_002", "mv_t"), ("qual_002", "tb_t"), ("qual_002", "v_t")]
        assert _findings(sql, check_qualification_relations=True) == expected

    def test_composite_type_enum_domain_and_sequence(self, q: str) -> None:
        sql = (
            f"CREATE TYPE {q}ty_t AS (a int);\n"
            f"CREATE TYPE {q}en_t AS ENUM ('a');\n"
            f"CREATE DOMAIN {q}dm_t AS text;\n"
            f"CREATE SEQUENCE {q}sq_t;\n"
        )
        expected = (
            []
            if q
            else [
                ("qual_002", "dm_t"),
                ("qual_002", "en_t"),
                ("qual_002", "sq_t"),
                ("qual_002", "ty_t"),
            ]
        )
        assert _findings(sql, check_qualification_relations=True) == expected


class TestQual002Details:
    def test_a_temporary_table_has_no_schema_to_write(self) -> None:
        sql = "CREATE TEMPORARY TABLE tmp_t (id int);\n"

        assert _findings(sql, check_qualification_relations=True) == []

    def test_routines_are_still_reported_alongside(self) -> None:
        sql = f"CREATE TABLE tb_t (id int);\nCREATE FUNCTION f() {BODY}\n"

        assert _findings(sql, check_qualification_relations=True) == [
            ("qual_001", "f()"),
            ("qual_002", "tb_t"),
        ]


class TestRegistry:
    def test_the_qual_family_is_two_warnings_one_on_one_opt_in(self) -> None:
        qual = [rule for rule in LINT_RULES if rule.family == "qual"]
        assert [rule.code for rule in qual] == ["qual_001", "qual_002"]
        assert {rule.severity for rule in qual} == {"warning"}
        assert [rule.default_on for rule in qual] == [True, False]
        assert default_codes() & QUAL_CODES == {"qual_001"}

    def test_select_qual_takes_both_and_ignore_drops_one(self) -> None:
        assert resolve_selection(["qual"], []) == QUAL_CODES
        assert resolve_selection(["qual"], ["qual_002"]) == {"qual_001"}
        assert resolve_selection(None, ["qual"]) == default_codes() - QUAL_CODES


_SCHEMA = """
CREATE SCHEMA app;
CREATE TABLE tb_bare (id INT PRIMARY KEY);
COMMENT ON TABLE tb_bare IS 'documented';
CREATE FUNCTION fn_bare(a integer) RETURNS int LANGUAGE sql AS $$ select 1 $$;
COMMENT ON FUNCTION fn_bare(integer) IS 'documented';
"""


@pytest.fixture
def lint_project(tmp_path: Path) -> Iterator[Path]:
    """A project whose schema trips the qual family and nothing else."""
    (tmp_path / "db" / "schema").mkdir(parents=True)
    (tmp_path / "db" / "environments").mkdir(parents=True)
    (tmp_path / "db" / "environments" / "local.yaml").write_text(
        "database_url: postgresql://localhost/test\ninclude_dirs:\n  - path: db/schema\n"
    )
    (tmp_path / "db" / "schema" / "010_objects.sql").write_text(_SCHEMA)
    old_cwd = Path.cwd()
    os.chdir(tmp_path)
    try:
        yield tmp_path
    finally:
        os.chdir(old_cwd)


def _cli_items(*args: str) -> list[dict[str, object]]:
    result = CliRunner().invoke(app, ["lint", "--format", "json", "--fail-on", "never", *args])
    assert result.exit_code == 0, result.output
    items = json.loads(result.stdout)["violations"]["items"]
    return [i for i in items if str(i["rule_id"]).startswith("qual_")]


class TestCli:
    def test_a_default_run_reports_the_routine_only(self, lint_project: Path) -> None:
        assert [i["rule_id"] for i in _cli_items()] == ["qual_001"]

    def test_selecting_qual_002_adds_the_relations(self, lint_project: Path) -> None:
        codes = sorted(i["rule_id"] for i in _cli_items("--select", "default,qual_002"))
        assert codes == ["qual_001", "qual_002"]

    def test_every_finding_names_its_file_and_line(self, lint_project: Path) -> None:
        items = _cli_items("--select", "default,qual_002")

        assert {i["file"] for i in items} == {"db/schema/010_objects.sql"}
        assert sorted(int(i["line"]) for i in items) == [3, 5]

    def test_ignoring_the_family_silences_all_of_it(self, lint_project: Path) -> None:
        assert _cli_items("--ignore", "qual") == []
