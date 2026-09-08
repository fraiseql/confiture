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

import pytest

from confiture.core.linting.schema_linter import LintConfig, LintReport, SchemaLinter

BODY = "RETURNS int LANGUAGE sql AS $$ select 1 $$;"


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
