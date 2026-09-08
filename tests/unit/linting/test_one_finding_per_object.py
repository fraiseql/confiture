"""A property of an object is reported once, however many times it is defined.

A table defined in two files is one mistake — ``build_001``'s — and before 1.4.0
every other inventory-reading rule repeated itself against each definition:
``app.tb_widget`` defined twice yielded two identical ``doc_001`` findings, two
``pk_001``, two ``naming_001`` and two ``naming_002`` per column (LINT-10). A
project fixing the duplicate saw its documentation backlog halve as a
side-effect, and a baseline recorded identities that existed only because of the
duplication.

The rules that judge the *statement* rather than the object are deliberately not
deduplicated: ``qual_001`` asks which schema this ``CREATE`` lands in, and a
second unqualified definition is a second answer.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from confiture.core.linting.schema_linter import LintConfig, LintReport, SchemaLinter

_TWICE = """CREATE SCHEMA IF NOT EXISTS app;
CREATE TABLE app."TbWidget" ("SomeCol" TEXT);
CREATE TABLE app."TbWidget" ("SomeCol" TEXT);
"""


def _codes(report: LintReport) -> Counter[str]:
    return Counter(v.rule_id for v in report.errors + report.warnings + report.info)


def _lint(sql: str) -> LintReport:
    return SchemaLinter(config=LintConfig(enabled=True)).lint(schema=sql)


def test_a_table_defined_twice_is_one_documentation_finding() -> None:
    assert _codes(_lint(_TWICE))["doc_001"] == 1


def test_a_table_defined_twice_is_one_primary_key_finding() -> None:
    assert _codes(_lint(_TWICE))["pk_001"] == 1


def test_a_table_defined_twice_is_one_naming_finding_per_name() -> None:
    codes = _codes(_lint(_TWICE))

    assert (codes["naming_001"], codes["naming_002"]) == (1, 1)


def test_the_duplicate_itself_is_still_reported_once() -> None:
    assert _codes(_lint(_TWICE))["build_001"] == 1


def test_the_surviving_finding_points_at_the_first_definition(tmp_path: Path) -> None:
    """The location ``build_001`` names, so the two findings agree about where to look."""
    project = _project(tmp_path)

    report = SchemaLinter(config=LintConfig(enabled=True), project_dir=project).lint()

    doc = [v for v in report.info if v.rule_id == "doc_001"]
    assert [(v.file_path, v.line_number) for v in doc] == [("db/schema/010_first.sql", 3)]


def test_a_second_unqualified_create_is_still_its_own_qualification_finding() -> None:
    """``qual_001`` is about the statement: two unqualified CREATEs are two answers."""
    sql = (
        "CREATE FUNCTION fn_f() RETURNS int LANGUAGE sql AS $$ SELECT 1 $$;\n"
        "CREATE FUNCTION fn_f() RETURNS int LANGUAGE sql AS $$ SELECT 2 $$;\n"
    )

    assert _codes(_lint(sql))["qual_001"] == 2


def _project(tmp_path: Path) -> Path:
    (tmp_path / "db" / "schema").mkdir(parents=True)
    (tmp_path / "db" / "environments").mkdir(parents=True)
    (tmp_path / "db" / "environments" / "local.yaml").write_text(
        "database_url: postgresql://localhost/test\ninclude_dirs:\n  - path: db/schema\n"
    )
    (tmp_path / "db" / "schema" / "010_first.sql").write_text(
        "CREATE SCHEMA IF NOT EXISTS app;\n\nCREATE TABLE app.tb_widget (id INT PRIMARY KEY);\n"
    )
    (tmp_path / "db" / "schema" / "020_again.sql").write_text(
        "CREATE TABLE app.tb_widget (id INT PRIMARY KEY);\n"
    )
    return tmp_path
