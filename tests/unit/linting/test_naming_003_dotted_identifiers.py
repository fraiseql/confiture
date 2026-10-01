"""``naming_003``: no identifier holds a dot (#476).

PostgreSQL accepts ``app."a.b"``, but confiture reads names back from one
dotted ``schema.name`` string in many places — a foreign key's target most of
all — so a dot inside a name is read as the separator. A dotted name is an
error, reported once per object, spelled as SQL writes it.
"""

from __future__ import annotations

import pytest

from confiture.core.linting.gate import Threshold
from confiture.core.linting.rule_registry import LINT_RULES
from confiture.core.linting.schema_linter import LintViolation, SchemaLinter
from confiture.core.linting.selection import linter_config


def _findings(sql: str, *, code: str | None = None) -> list[LintViolation]:
    report = SchemaLinter(env="local").lint(sql)
    found = [*report.errors, *report.warnings, *report.info]
    return [v for v in found if code is None or v.rule_id == code]


def _dotted(sql: str) -> list[tuple[str, str]]:
    return sorted((v.object_type, v.object_name) for v in _findings(sql, code="naming_003"))


@pytest.mark.parametrize(
    ("statement", "kind", "spelled"),
    [
        ('CREATE TABLE app."a.b" (id int PRIMARY KEY);', "table", 'app."a.b"'),
        ('CREATE VIEW app."v.w" AS SELECT 1 AS n;', "view", 'app."v.w"'),
        ('CREATE MATERIALIZED VIEW app."m.v" AS SELECT 1 AS n;', "matview", 'app."m.v"'),
        ("CREATE TYPE app.\"e.n\" AS ENUM ('a');", "type", 'app."e.n"'),
        ('CREATE DOMAIN app."d.m" AS int;', "domain", 'app."d.m"'),
        ('CREATE SEQUENCE app."s.q";', "sequence", 'app."s.q"'),
        (
            'CREATE FUNCTION app."f.n"() RETURNS int LANGUAGE sql AS $$ SELECT 1 $$;',
            "function",
            'app."f.n"',
        ),
        (
            "SELECT tviews.pg_tviews_create_or_replace('app.\"tv_a.b\"', 'SELECT 1 AS id');",
            "tview",
            'app."tv_a.b"',
        ),
    ],
)
def test_an_object_whose_name_holds_a_dot_is_an_error(
    statement: str, kind: str, spelled: str
) -> None:
    (finding,) = _findings(f"CREATE SCHEMA app;\n{statement}\n", code="naming_003")

    assert (finding.object_type, finding.object_name) == (kind, spelled)
    assert finding.severity.value == "error"
    assert finding.line_number == 2
    assert spelled in finding.message


def test_a_column_whose_name_holds_a_dot_is_an_error() -> None:
    sql = 'CREATE SCHEMA app;\nCREATE TABLE app.t (id int PRIMARY KEY,\n  "x.y" int);\n'

    (finding,) = _findings(sql, code="naming_003")

    assert (finding.object_type, finding.object_name) == ("column", 'app.t."x.y"')
    assert finding.line_number == 3


def test_an_index_whose_name_holds_a_dot_is_an_error() -> None:
    sql = (
        "CREATE SCHEMA app;\nCREATE TABLE app.t (id int PRIMARY KEY);\n"
        'CREATE INDEX "i.x" ON app.t (id);\n'
    )

    (finding,) = _findings(sql, code="naming_003")

    assert (finding.object_type, finding.object_name) == ("index", 'app."i.x"')
    assert finding.line_number == 3


def test_a_declared_schema_is_reported_once_and_its_objects_not_for_it() -> None:
    sql = 'CREATE SCHEMA "my.s";\nCREATE TABLE "my.s".t (id int PRIMARY KEY);\n'

    assert _dotted(sql) == [("schema", '"my.s"')]


def test_a_schema_only_used_as_a_qualifier_is_reported_once_where_first_used() -> None:
    sql = (
        'CREATE TABLE "my.s".t (id int PRIMARY KEY);\nCREATE TABLE "my.s".u (id int PRIMARY KEY);\n'
    )

    (finding,) = _findings(sql, code="naming_003")

    assert (finding.object_type, finding.object_name, finding.line_number) == (
        "schema",
        '"my.s"',
        1,
    )


def test_the_snake_case_rules_do_not_report_it_again() -> None:
    sql = 'CREATE SCHEMA app;\nCREATE TABLE app."a.b" (id int PRIMARY KEY, "x.y" int);\n'

    assert [v.rule_id for v in _findings(sql) if v.rule_id.startswith("naming")] == [
        "naming_003",
        "naming_003",
    ]


def test_a_tree_without_a_dotted_name_has_no_finding() -> None:
    sql = (
        "CREATE SCHEMA app;\n"
        'CREATE TABLE app."Order Line" (id int PRIMARY KEY, "Mixed Case" int);\n'
        'CREATE VIEW app.v AS SELECT id FROM app."Order Line";\n'
    )

    assert _findings(sql, code="naming_003") == []


def test_naming_003_is_registered_default_on_at_error() -> None:
    (rule,) = [r for r in LINT_RULES if r.code == "naming_003"]

    assert (rule.family, rule.severity, rule.default_on) == ("naming", "error", True)


def test_selecting_naming_003_alone_runs_it() -> None:

    config = linter_config(frozenset({"naming_003"}), Threshold.ERROR)

    assert config.check_naming
