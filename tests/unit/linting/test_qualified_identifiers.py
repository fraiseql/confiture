"""The default lint rules read a pglast-built inventory, so a schema qualifier
changes nothing (Phase 05, #216).

Four of the five default rules matched ``CREATE TABLE (\\w+)`` and reported
zero violations on ``tenant.tb_x`` — a fail-open silence indistinguishable from
a clean schema. Every case below runs on the bare name and on its qualified
twin and must report the same rule codes.
"""

from __future__ import annotations

import pytest

from confiture.core.linting.schema_linter import LintConfig, SchemaLinter

# The issue's reproduction, verbatim.
QUALIFIED = """
CREATE TABLE tenant.tb_thing (
    pk_thing BIGINT PRIMARY KEY,
    BadColumnName TEXT,
    password TEXT
);
CREATE TABLE tenant.tb_other (
    id UUID
);
COMMENT ON TABLE tenant.tb_thing IS 'documented';
"""
UNQUALIFIED = QUALIFIED.replace("tenant.", "")


def _codes(sql: str) -> list[str]:
    report = SchemaLinter(config=LintConfig(enabled=True)).lint(schema=sql)
    return sorted(v.rule_id for v in report.errors + report.warnings + report.info)


def _objects(sql: str, rule_id: str) -> list[str]:
    report = SchemaLinter(config=LintConfig(enabled=True)).lint(schema=sql)
    return sorted(
        v.object_name for v in report.errors + report.warnings + report.info if v.rule_id == rule_id
    )


def test_issue_216_reproduction_reports_the_same_rules_qualified() -> None:
    assert _codes(UNQUALIFIED) == ["doc_001", "naming_002", "pk_001", "sec_001"]
    assert _codes(QUALIFIED) == _codes(UNQUALIFIED)


def test_a_comment_documents_only_the_table_it_names() -> None:
    """``COMMENT ON TABLE tenant.tb_thing`` must not mark ``tenant.tb_other`` documented."""
    assert _objects(QUALIFIED, "doc_001") == ["tenant.tb_other"]
    assert _objects(UNQUALIFIED, "doc_001") == ["tb_other"]


def test_naming_001_reads_the_identifier_as_written() -> None:
    sql = 'CREATE TABLE tenant."BadTable" (id INT PRIMARY KEY);\nCOMMENT ON TABLE tenant."BadTable" IS \'x\';\n'
    assert _codes(sql) == ["naming_001"]
    assert _objects(sql, "naming_001") == ["tenant.BadTable"]


CASES = {
    "camel_table": (
        'CREATE TABLE {q}"UserAccounts" (id INT PRIMARY KEY);\nCOMMENT ON TABLE {q}"UserAccounts" IS \'x\';\n',
        ["naming_001"],
    ),
    "camel_column": (
        "CREATE TABLE {q}tb_users (id INT PRIMARY KEY, firstName TEXT);\nCOMMENT ON TABLE {q}tb_users IS 'x';\n",
        ["naming_002"],
    ),
    "missing_pk": (
        "CREATE TABLE {q}tb_events (id INT, payload TEXT);\nCOMMENT ON TABLE {q}tb_events IS 'x';\n",
        ["pk_001"],
    ),
    "junction_table_needs_no_pk": (
        "CREATE TABLE {q}tb_user_role (user_id INT, role_id INT);\nCOMMENT ON TABLE {q}tb_user_role IS 'x';\n",
        [],
    ),
    "undocumented": (
        "CREATE TABLE {q}tb_orders (id INT PRIMARY KEY);\n",
        ["doc_001"],
    ),
    "documented_clean": (
        "CREATE TABLE {q}tb_orders (id INT PRIMARY KEY);\nCOMMENT ON TABLE {q}tb_orders IS 'orders';\n",
        [],
    ),
    "password_column": (
        "CREATE TABLE {q}tb_users (id INT PRIMARY KEY, password TEXT);\nCOMMENT ON TABLE {q}tb_users IS 'x';\n",
        ["sec_001"],
    ),
    "table_constraint_pk": (
        "CREATE TABLE {q}tb_pairs (a INT, b INT, CONSTRAINT pk_pairs PRIMARY KEY (a, b));\nCOMMENT ON TABLE {q}tb_pairs IS 'x';\n",
        [],
    ),
}


@pytest.mark.parametrize("qualifier", ["", "tenant."], ids=["bare", "qualified"])
@pytest.mark.parametrize("case", sorted(CASES), ids=sorted(CASES))
def test_every_case_reports_identically_qualified(case: str, qualifier: str) -> None:
    template, expected = CASES[case]
    assert _codes(template.format(q=qualifier)) == expected
