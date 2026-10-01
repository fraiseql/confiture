"""``naming_004``: no identifier needs quotes (#484).

confiture does not support a name that only exists quoted: a space or other
punctuation, a capital letter, a reserved word, a leading digit. Each is an
error, reported once per object, spelled as SQL writes it, with a snake_case
name that needs no quotes as the fix. A dotted name is ``naming_003``'s.
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


def _quoted(sql: str) -> list[tuple[str, str]]:
    return sorted((v.object_type, v.object_name) for v in _findings(sql, code="naming_004"))


@pytest.mark.parametrize(
    ("statement", "kind", "spelled"),
    [
        ('CREATE TABLE app."Order Line" (id int PRIMARY KEY);', "table", 'app."Order Line"'),
        ('CREATE VIEW app."MyView" AS SELECT 1 AS n;', "view", 'app."MyView"'),
        ('CREATE MATERIALIZED VIEW app."m-v" AS SELECT 1 AS n;', "matview", 'app."m-v"'),
        ("CREATE TYPE app.\"Status\" AS ENUM ('a');", "type", 'app."Status"'),
        ('CREATE DOMAIN app."1dom" AS int;', "domain", 'app."1dom"'),
        ('CREATE SEQUENCE app."Seq";', "sequence", 'app."Seq"'),
        (
            'CREATE FUNCTION app."order"() RETURNS int LANGUAGE sql AS $$ SELECT 1 $$;',
            "function",
            'app."order"',
        ),
        ('CREATE TABLE app."tv_Q" AS SELECT 1 AS id;', "tview", 'app."tv_Q"'),
        (
            "SELECT tviews.pg_tviews_create_or_replace('app.\"tv_Q\"', 'SELECT 1 AS id');",
            "tview",
            'app."tv_Q"',
        ),
        ("SELECT pg_tviews_create('app.\"Q\"', 'SELECT 1 AS id');", "tview", 'app."tv_Q"'),
    ],
)
def test_an_object_whose_name_needs_quotes_is_an_error(
    statement: str, kind: str, spelled: str
) -> None:
    (finding,) = _findings(f"CREATE SCHEMA app;\n{statement}\n", code="naming_004")

    assert (finding.object_type, finding.object_name) == (kind, spelled)
    assert finding.severity.value == "error"
    assert finding.line_number == 2
    assert spelled in finding.message


@pytest.mark.parametrize(
    ("column", "spelled", "suggested"),
    [
        ('"user"', 'app.t."user"', "app.t.user_"),
        ('"Mixed Col"', 'app.t."Mixed Col"', "app.t.mixed_col"),
        ('"créé"', 'app.t."créé"', "app.t.cree"),
    ],
)
def test_a_column_whose_name_needs_quotes_is_an_error(
    column: str, spelled: str, suggested: str
) -> None:
    sql = f"CREATE SCHEMA app;\nCREATE TABLE app.t (id int PRIMARY KEY,\n  {column} int);\n"

    (finding,) = _findings(sql, code="naming_004")

    assert (finding.object_type, finding.object_name) == ("column", spelled)
    assert finding.line_number == 3
    assert finding.suggested_fix is not None
    assert finding.suggested_fix.endswith(suggested)


def test_an_index_whose_name_needs_quotes_is_an_error() -> None:
    sql = (
        "CREATE SCHEMA app;\nCREATE TABLE app.t (id int PRIMARY KEY);\n"
        'CREATE INDEX "Idx T" ON app.t (id);\n'
    )

    (finding,) = _findings(sql, code="naming_004")

    assert (finding.object_type, finding.object_name) == ("index", 'app."Idx T"')
    assert finding.line_number == 3


def test_a_declared_schema_is_reported_once_and_its_objects_not_for_it() -> None:
    sql = 'CREATE SCHEMA "App";\nCREATE TABLE "App".t (id int PRIMARY KEY);\n'

    assert _quoted(sql) == [("schema", '"App"')]


def test_a_schema_only_used_as_a_qualifier_is_reported_once_where_first_used() -> None:
    sql = 'CREATE TABLE "App".t (id int PRIMARY KEY);\nCREATE TABLE "App".u (id int PRIMARY KEY);\n'

    (finding,) = _findings(sql, code="naming_004")

    assert (finding.object_type, finding.object_name, finding.line_number) == (
        "schema",
        '"App"',
        1,
    )


def test_a_dotted_name_is_naming_003s_alone() -> None:
    sql = 'CREATE SCHEMA app;\nCREATE TABLE app."A.b" (id int PRIMARY KEY);\n'

    assert [v.rule_id for v in _findings(sql) if v.rule_id.startswith("naming")] == ["naming_003"]


def test_the_snake_case_rules_do_not_report_it_again() -> None:
    sql = 'CREATE SCHEMA app;\nCREATE TABLE app."Order Line" (id int PRIMARY KEY, "Mixed" int);\n'

    assert [v.rule_id for v in _findings(sql) if v.rule_id.startswith("naming")] == [
        "naming_004",
        "naming_004",
    ]


def test_an_unquoted_name_needs_no_quotes_whatever_its_case() -> None:
    """``CREATE TABLE BadName`` folds to ``badname``: naming_001's spelling, not this rule's."""
    sql = 'CREATE SCHEMA app;\nCREATE TABLE app.BadName (id int PRIMARY KEY, "ok_col" int);\n'

    assert _findings(sql, code="naming_004") == []


def test_naming_004_is_registered_default_on_at_error() -> None:
    (rule,) = [r for r in LINT_RULES if r.code == "naming_004"]

    assert (rule.family, rule.severity, rule.default_on) == ("naming", "error", True)


def test_selecting_naming_004_alone_runs_it() -> None:
    config = linter_config(frozenset({"naming_004"}), Threshold.ERROR)

    assert config.check_naming


def test_a_table_renamed_to_a_name_that_needs_quotes_is_an_error() -> None:
    sql = 'CREATE TABLE t (id int PRIMARY KEY);\nALTER TABLE t RENAME TO "BadT";\n'

    assert _quoted(sql) == [("table", '"BadT"')]
    assert [v.rule_id for v in _findings(sql) if v.rule_id.startswith("naming")] == ["naming_004"]


def test_a_column_renamed_to_a_name_that_needs_quotes_is_an_error() -> None:
    sql = 'CREATE TABLE t (id int PRIMARY KEY, x int);\nALTER TABLE t RENAME COLUMN x TO "Bad X";\n'

    assert _quoted(sql) == [("column", 't."Bad X"')]


def test_a_table_moved_to_a_schema_that_needs_quotes_is_an_error() -> None:
    sql = (
        'CREATE SCHEMA "App";\nCREATE TABLE t (id int PRIMARY KEY);\n'
        'ALTER TABLE t SET SCHEMA "App";\n'
    )

    assert _quoted(sql) == [("schema", '"App"')]


@pytest.mark.parametrize(
    ("clause", "spelled"),
    [
        ('CONSTRAINT "My Check" CHECK (id > 0)', 't."My Check"'),
        ('CONSTRAINT "PK" PRIMARY KEY (id)', 't."PK"'),
        ('CONSTRAINT "u q" UNIQUE (id)', 't."u q"'),
    ],
)
def test_a_constraint_whose_name_needs_quotes_is_an_error(clause: str, spelled: str) -> None:
    sql = f"CREATE TABLE t (id int,\n  {clause});\n"

    assert _quoted(sql) == [("constraint", spelled)]


def test_a_constraint_added_by_alter_is_read() -> None:
    sql = (
        'CREATE TABLE t (id int PRIMARY KEY);\nALTER TABLE t ADD CONSTRAINT "Pos" CHECK (id > 0);\n'
    )

    assert _quoted(sql) == [("constraint", 't."Pos"')]


def test_the_suggestion_keeps_an_accented_letter_as_its_base_letter() -> None:
    sql = 'CREATE TABLE t (id int PRIMARY KEY, "créé" int);\n'

    (finding,) = _findings(sql, code="naming_004")

    assert finding.suggested_fix is not None
    assert finding.suggested_fix.endswith("t.cree")
