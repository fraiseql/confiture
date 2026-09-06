"""The doc family covers every commentable object kind (#217, Phase 07).

``doc_001`` judged tables and nothing else, so an undocumented function, view
or type passed silently — and a partition child, which inherits its parent's
purpose, was asked for a comment of its own. ``doc_002`` (functions and
procedures, matched on name *and* argument types), ``doc_003`` (views and
materialized views) and ``doc_004`` (composite and enum types, domains) join
``doc_001`` in the ``doc`` family at ``info``; every case runs on a bare name
and on its schema-qualified twin.
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
from confiture.core.linting.schema_linter import LintConfig, SchemaLinter

BODY = "RETURNS int LANGUAGE sql AS $$ select 1 $$;"
DOC_CODES = frozenset({"doc_001", "doc_002", "doc_003", "doc_004"})


def _report(sql: str):  # type: ignore[no-untyped-def]
    return SchemaLinter(config=LintConfig(enabled=True)).lint(schema=sql)


def _doc_findings(sql: str) -> list[tuple[str, str]]:
    report = _report(sql)
    return sorted(
        (v.rule_id, v.object_name)
        for v in report.errors + report.warnings + report.info
        if v.rule_id.startswith("doc_")
    )


@pytest.mark.parametrize("q", ["", "app."], ids=["bare", "qualified"])
class TestDocRules:
    def test_undocumented_function_names_its_signature(self, q: str) -> None:
        sql = f"CREATE FUNCTION {q}f(a integer, b text) {BODY}\n"
        assert _doc_findings(sql) == [("doc_002", f"{q}f(integer, text)")]

    def test_a_comment_on_one_overload_does_not_cover_its_sibling(self, q: str) -> None:
        sql = (
            f"CREATE FUNCTION {q}f(a integer) {BODY}\n"
            f"CREATE FUNCTION {q}f(a text) {BODY}\n"
            f"COMMENT ON FUNCTION {q}f(integer) IS 'the integer one';\n"
        )
        assert _doc_findings(sql) == [("doc_002", f"{q}f(text)")]

    def test_undocumented_procedure(self, q: str) -> None:
        sql = f"CREATE PROCEDURE {q}p(x bigint) LANGUAGE sql AS $$ select 1 $$;\n"
        assert _doc_findings(sql) == [("doc_002", f"{q}p(bigint)")]

    def test_undocumented_view_and_materialized_view(self, q: str) -> None:
        sql = (
            f"CREATE VIEW {q}v AS SELECT 1 AS a;\n"
            f"CREATE MATERIALIZED VIEW {q}mv AS SELECT 1 AS a;\n"
            f"CREATE VIEW {q}v_ok AS SELECT 1 AS a;\n"
            f"COMMENT ON VIEW {q}v_ok IS 'documented';\n"
        )
        assert _doc_findings(sql) == [("doc_003", f"{q}mv"), ("doc_003", f"{q}v")]

    def test_undocumented_composite_type_enum_and_domain(self, q: str) -> None:
        sql = (
            f"CREATE TYPE {q}ty AS (a int);\n"
            f"CREATE TYPE {q}en AS ENUM ('a');\n"
            f"CREATE DOMAIN {q}dm AS text;\n"
            f"CREATE DOMAIN {q}dm_ok AS text;\n"
            f"COMMENT ON DOMAIN {q}dm_ok IS 'documented';\n"
        )
        assert _doc_findings(sql) == [
            ("doc_004", f"{q}dm"),
            ("doc_004", f"{q}en"),
            ("doc_004", f"{q}ty"),
        ]

    def test_partition_children_need_no_comment_but_their_parent_does(self, q: str) -> None:
        sql = (
            f"CREATE TABLE {q}parent (id int PRIMARY KEY) PARTITION BY RANGE (id);\n"
            f"CREATE TABLE {q}child PARTITION OF {q}parent FOR VALUES FROM (1) TO (10);\n"
        )
        assert _doc_findings(sql) == [("doc_001", f"{q}parent")]

    def test_a_fully_documented_schema_is_quiet(self, q: str) -> None:
        sql = (
            f"CREATE TABLE {q}t (id int PRIMARY KEY);\nCOMMENT ON TABLE {q}t IS 't';\n"
            f"CREATE FUNCTION {q}f(a int) {BODY}\nCOMMENT ON FUNCTION {q}f(integer) IS 'f';\n"
            f"CREATE VIEW {q}v AS SELECT 1 AS a;\nCOMMENT ON VIEW {q}v IS 'v';\n"
            f"CREATE TYPE {q}ty AS (a int);\nCOMMENT ON TYPE {q}ty IS 'ty';\n"
        )
        assert _doc_findings(sql) == []

    def test_doc_findings_are_info_and_point_at_the_statement(self, q: str) -> None:
        sql = f"-- header\nCREATE FUNCTION {q}f() {BODY}\n"
        report = _report(sql)
        (finding,) = [v for v in report.info if v.rule_id == "doc_002"]
        assert finding.severity.value == "info"
        assert finding.object_type == "function"
        assert finding.line_number == 2
        assert report.errors == [] and report.warnings == []


class TestRegistry:
    def test_the_doc_family_is_four_rules_at_info_on_by_default(self) -> None:
        doc = [rule for rule in LINT_RULES if rule.family == "doc"]
        assert [rule.code for rule in doc] == ["doc_001", "doc_002", "doc_003", "doc_004"]
        assert {rule.severity for rule in doc} == {"info"}
        assert all(rule.default_on for rule in doc)
        assert default_codes() >= DOC_CODES

    def test_select_doc_takes_all_four_and_ignore_drops_one(self) -> None:
        assert resolve_selection(["doc"], []) == DOC_CODES
        assert resolve_selection(["doc"], ["doc_002"]) == DOC_CODES - {"doc_002"}
        assert resolve_selection(None, ["doc"]) == default_codes() - DOC_CODES


_SCHEMA = """
CREATE TABLE tb_ok (id INT PRIMARY KEY);
COMMENT ON TABLE tb_ok IS 'documented';
CREATE FUNCTION fn_undocumented(a integer) RETURNS int LANGUAGE sql AS $$ select 1 $$;
CREATE VIEW v_undocumented AS SELECT 1 AS a;
"""


@pytest.fixture
def lint_project(tmp_path: Path) -> Iterator[Path]:
    """A project whose schema trips doc_002 and doc_003 and nothing else."""
    (tmp_path / "db" / "schema").mkdir(parents=True)
    (tmp_path / "db" / "migrations").mkdir(parents=True)
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


def _cli_codes(*args: str) -> list[str]:
    result = CliRunner().invoke(app, ["lint", "--format", "json", *args])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    return sorted({v["rule_id"] for v in payload["violations"]["items"]})


class TestCli:
    def test_a_default_run_reports_the_new_doc_rules(self, lint_project: Path) -> None:
        assert _cli_codes() == ["doc_002", "doc_003"]

    def test_select_one_doc_rule_reports_only_it(self, lint_project: Path) -> None:
        assert _cli_codes("--select", "doc_002") == ["doc_002"]

    def test_ignore_the_family_silences_all_of_it(self, lint_project: Path) -> None:
        assert _cli_codes("--ignore", "doc") == []
