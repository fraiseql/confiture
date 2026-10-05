"""``softdel_001`` / ``softdel_002``: unique keys on a table that soft-deletes (#597).

A table carrying the tombstone column ``db/project.yaml``'s ``soft_delete:`` names
keeps its deleted rows. A ``UNIQUE`` that does not exclude them keeps reserving a
deleted row's value, so re-creating the same thing fails with ``23505``. The key
should be a partial unique index whose predicate implies ``<column> IS NULL``.
"""

from pathlib import Path

import pytest

from confiture.core.linting.rule_registry import LINT_RULES, resolve_selection
from confiture.core.linting.schema_linter import (
    LintConfig,
    LintReport,
    LintViolation,
    RuleSeverity,
    SchemaLinter,
)
from confiture.core.linting.selection import linter_config

SOFT_DELETE = "soft_delete:\n  column: deleted_at\n"

#: The issue's table.
ORDER_LINE = """CREATE SCHEMA app;
CREATE TABLE app.tb_order (pk_order BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY);
CREATE TABLE app.tb_product (pk_product BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY);
CREATE TABLE app.tb_order_line (
    pk_order_line BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id            UUID NOT NULL UNIQUE,
    fk_order      BIGINT NOT NULL REFERENCES app.tb_order,
    fk_product    BIGINT NOT NULL REFERENCES app.tb_product,
    deleted_at    TIMESTAMPTZ,
    CONSTRAINT tb_order_line_order_product_key UNIQUE (fk_order, fk_product)
);
"""

#: The same table with its natural key left out, for the index cases.
BARE_LINE = """CREATE SCHEMA app;
CREATE TABLE app.tb_order_line (
    pk_order_line BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id            UUID NOT NULL UNIQUE,
    fk_order      BIGINT NOT NULL,
    fk_product    BIGINT NOT NULL,
    kind          TEXT,
    deleted_at    TIMESTAMPTZ
);
"""


def _project(tmp_path: Path, project_yaml: str | None) -> Path:
    (tmp_path / "db" / "schema").mkdir(parents=True)
    (tmp_path / "db" / "environments").mkdir()
    (tmp_path / "db" / "environments" / "local.yaml").write_text(
        "name: local\ndatabase_url: postgresql://localhost:1/app\n"
        f"include_dirs:\n  - {tmp_path / 'db' / 'schema'}\n"
    )
    if project_yaml is not None:
        (tmp_path / "db" / "project.yaml").write_text(project_yaml)
    return tmp_path


def _lint(
    tmp_path: Path, sql: str, project_yaml: str | None = SOFT_DELETE, **switches: bool
) -> LintReport:
    switches = switches or {"check_softdel_reserved_keys": True, "check_softdel_null_keys": True}
    linter = SchemaLinter(
        env="local", project_dir=_project(tmp_path, project_yaml), config=LintConfig(**switches)
    )
    return linter.lint(sql)


def _found(report: LintReport, code: str) -> list[LintViolation]:
    return [v for v in (*report.errors, *report.warnings, *report.info) if v.rule_id == code]


def _reserved(tmp_path: Path, sql: str, project_yaml: str | None = SOFT_DELETE):
    return _found(_lint(tmp_path, sql, project_yaml), "softdel_001")


def test_the_issues_natural_key_is_reported_and_nothing_else(tmp_path: Path) -> None:
    """The identity primary key and the uuid key are not reported: no author reuses them."""
    (finding,) = _reserved(tmp_path, ORDER_LINE)

    assert finding.severity is RuleSeverity.WARNING
    assert finding.object_name == "app.tb_order_line"
    assert "tb_order_line_order_product_key" in finding.message
    assert finding.line_number == 10
    fix = finding.suggested_fix or ""
    assert "DROP CONSTRAINT tb_order_line_order_product_key" in fix
    assert (
        "CREATE UNIQUE INDEX tb_order_line_order_product_key ON app.tb_order_line "
        "(fk_order, fk_product) WHERE deleted_at IS NULL" in fix
    )
    assert "ON CONFLICT ON CONSTRAINT" in fix


@pytest.mark.parametrize(
    ("index", "reported"),
    [
        ("CREATE UNIQUE INDEX ux ON app.tb_order_line (fk_order, fk_product);", True),
        (
            "CREATE UNIQUE INDEX ux ON app.tb_order_line (fk_order, fk_product) "
            "WHERE deleted_at IS NULL;",
            False,
        ),
        (
            "CREATE UNIQUE INDEX ux ON app.tb_order_line (fk_order, fk_product) "
            "WHERE deleted_at IS NULL AND kind = 'x';",
            False,
        ),
        (
            "CREATE UNIQUE INDEX ux ON app.tb_order_line (fk_order, fk_product) "
            "WHERE kind = 'x' AND (fk_order > 0 AND deleted_at IS NULL);",
            False,
        ),
        (
            "CREATE UNIQUE INDEX ux ON app.tb_order_line (fk_order, fk_product) "
            "WHERE deleted_at IS NULL OR kind = 'x';",
            True,
        ),
        (
            "CREATE UNIQUE INDEX ux ON app.tb_order_line (fk_order, fk_product) "
            "WHERE deleted_at IS NOT NULL;",
            True,
        ),
        (
            "CREATE UNIQUE INDEX ux ON app.tb_order_line (fk_order, fk_product) "
            "WHERE kind IS NULL;",
            True,
        ),
        ("CREATE INDEX ix ON app.tb_order_line (fk_order, fk_product);", False),
    ],
    ids=[
        "whole",
        "partial",
        "partial-and",
        "nested-and",
        "partial-or",
        "is-not-null",
        "other-column",
        "not-unique",
    ],
)
def test_a_unique_index_must_imply_the_tombstone_is_null(
    tmp_path: Path, index: str, reported: bool
) -> None:
    found = _reserved(tmp_path, BARE_LINE + index + "\n")

    assert bool(found) is reported


def test_an_index_finding_points_at_its_statement(tmp_path: Path) -> None:
    sql = BARE_LINE + "\nCREATE UNIQUE INDEX ux\n    ON app.tb_order_line (fk_order, fk_product);\n"

    (finding,) = _reserved(tmp_path, sql)

    assert finding.line_number == 11
    fix = finding.suggested_fix or ""
    assert "DROP CONSTRAINT" not in fix
    assert "WHERE deleted_at IS NULL" in fix


def test_a_key_added_by_alter_table_is_judged(tmp_path: Path) -> None:
    sql = BARE_LINE + (
        "ALTER TABLE app.tb_order_line ADD CONSTRAINT k UNIQUE (fk_order, fk_product);\n"
    )

    (finding,) = _reserved(tmp_path, sql)

    assert finding.line_number == 10
    assert "ALTER TABLE app.tb_order_line DROP CONSTRAINT k" in (finding.suggested_fix or "")


def test_an_index_dropped_later_is_not_judged(tmp_path: Path) -> None:
    sql = BARE_LINE + (
        "CREATE UNIQUE INDEX ux ON app.tb_order_line (fk_order, fk_product);\nDROP INDEX app.ux;\n"
    )

    assert _reserved(tmp_path, sql) == []


@pytest.mark.parametrize(
    "key",
    [
        "code TEXT NOT NULL UNIQUE",  # an author picks the code: reported
        "pk BIGSERIAL UNIQUE",  # a sequence does: not
        "ref UUID DEFAULT gen_random_uuid() UNIQUE",  # a generated uuid: not
    ],
)
def test_a_single_column_key_no_author_chooses_is_exempt(tmp_path: Path, key: str) -> None:
    sql = f"CREATE TABLE tb_thing (id INT PRIMARY KEY, {key}, deleted_at TIMESTAMPTZ);\n"

    found = _reserved(tmp_path, sql)

    assert bool(found) is key.startswith("code")


def test_the_primary_key_is_exempt(tmp_path: Path) -> None:
    sql = "CREATE TABLE tb_thing (code TEXT PRIMARY KEY, deleted_at TIMESTAMPTZ);\n"

    assert _reserved(tmp_path, sql) == []


def test_a_table_without_the_tombstone_is_not_judged(tmp_path: Path) -> None:
    sql = "CREATE TABLE tb_thing (id INT PRIMARY KEY, code TEXT NOT NULL UNIQUE);\n"

    assert _reserved(tmp_path, sql) == []


def test_the_declared_column_is_the_tombstone(tmp_path: Path) -> None:
    sql = (
        "CREATE TABLE tb_a (id INT PRIMARY KEY, code TEXT UNIQUE, deleted_at TIMESTAMPTZ);\n"
        "CREATE TABLE tb_b (id INT PRIMARY KEY, code TEXT UNIQUE, removed_at TIMESTAMPTZ);\n"
    )

    found = _reserved(tmp_path, sql, "soft_delete:\n  column: removed_at\n")

    assert [f.object_name for f in found] == ["tb_b"]


def test_a_child_inheriting_the_tombstone_soft_deletes(tmp_path: Path) -> None:
    sql = (
        "CREATE TABLE tb_base (id INT PRIMARY KEY, deleted_at TIMESTAMPTZ);\n"
        "CREATE TABLE tb_child (code TEXT UNIQUE) INHERITS (tb_base);\n"
    )

    assert [f.object_name for f in _reserved(tmp_path, sql)] == ["tb_child"]


@pytest.mark.parametrize(
    "sql",
    [
        # Above a CREATE UNIQUE INDEX.
        BARE_LINE
        + "-- confiture:softdel-keep-reserved\n"
        + "CREATE UNIQUE INDEX ux ON app.tb_order_line (fk_order, fk_product);\n",
        # Above an ALTER TABLE … ADD CONSTRAINT.
        BARE_LINE
        + "-- confiture:softdel-keep-reserved\n"
        + "ALTER TABLE app.tb_order_line ADD CONSTRAINT k UNIQUE (fk_order, fk_product);\n",
        # Above a CREATE TABLE, naming the key written in it.
        ORDER_LINE.replace(
            "CREATE TABLE app.tb_order_line",
            "-- confiture:softdel-keep-reserved tb_order_line_order_product_key\n"
            "CREATE TABLE app.tb_order_line",
        ),
        # An unnamed key, by the name PostgreSQL gives it.
        "-- confiture:softdel-keep-reserved tb_thing_code_key\n"
        "CREATE TABLE tb_thing (id INT PRIMARY KEY, code TEXT UNIQUE, deleted_at TIMESTAMPTZ);\n",
    ],
    ids=["index", "alter", "inline-named", "inline-unnamed"],
)
def test_the_waiver_keeps_a_value_reserved(tmp_path: Path, sql: str) -> None:
    assert _reserved(tmp_path, sql) == []


def test_a_waiver_above_create_table_must_name_the_key(tmp_path: Path) -> None:
    sql = ORDER_LINE.replace(
        "CREATE TABLE app.tb_order_line",
        "-- confiture:softdel-keep-reserved some_other_key\nCREATE TABLE app.tb_order_line",
    )

    assert len(_reserved(tmp_path, sql)) == 1


def test_no_rule_runs_when_the_family_is_not_declared(tmp_path: Path) -> None:
    report = _lint(tmp_path, ORDER_LINE, project_yaml=None)

    assert _found(report, "softdel_001") == []
    assert [(s.code, s.state) for s in report.skipped] == [
        ("softdel_001", "skipped"),
        ("softdel_002", "skipped"),
    ]


def test_the_family_is_on_when_the_project_declares_soft_delete() -> None:
    rules = {r.code: r for r in LINT_RULES if r.family == "softdel"}

    assert sorted(rules) == ["softdel_001", "softdel_002"]
    assert rules["softdel_001"].severity == "warning"
    assert rules["softdel_002"].severity == "info"
    assert all(r.enabled_by == "soft_delete" and not r.default_on for r in rules.values())
    declared = resolve_selection(None, (), declared=frozenset({"soft_delete"}))
    assert {"softdel_001", "softdel_002"} <= declared
    assert "softdel_001" not in resolve_selection(None, ())


def test_selection_turns_on_each_switch() -> None:
    from confiture.core.linting.gate import Threshold

    config = linter_config(frozenset({"softdel_001"}), Threshold.NEVER)

    assert config.check_softdel_reserved_keys
    assert not config.check_softdel_null_keys


# softdel_002 ---------------------------------------------------------------

TREE = "CREATE TABLE tb_node (id INT PRIMARY KEY, fk_parent INT, name TEXT NOT NULL, kind TEXT NOT NULL, deleted_at TIMESTAMPTZ);\n"


def _nulls(tmp_path: Path, sql: str) -> list[LintViolation]:
    return _found(_lint(tmp_path, sql, check_softdel_null_keys=True), "softdel_002")


@pytest.mark.parametrize(
    ("key", "reported"),
    [
        (
            "CREATE UNIQUE INDEX ux ON tb_node (fk_parent, name) WHERE deleted_at IS NULL;",
            True,
        ),
        (
            "CREATE UNIQUE INDEX ux ON tb_node (fk_parent, name) NULLS NOT DISTINCT "
            "WHERE deleted_at IS NULL;",
            False,
        ),
        ("CREATE UNIQUE INDEX ux ON tb_node (kind, name) WHERE deleted_at IS NULL;", False),
        ("ALTER TABLE tb_node ADD CONSTRAINT k UNIQUE (fk_parent, name);", True),
        (
            "ALTER TABLE tb_node ADD CONSTRAINT k UNIQUE NULLS NOT DISTINCT (fk_parent, name);",
            False,
        ),
    ],
    ids=["partial-nullable", "nulls-not-distinct", "not-null-only", "constraint", "constraint-nnd"],
)
def test_a_nullable_key_column_needs_nulls_not_distinct(
    tmp_path: Path, key: str, reported: bool
) -> None:
    found = _nulls(tmp_path, TREE + key + "\n")

    assert bool(found) is reported
    if found:
        (finding,) = found
        assert finding.severity is RuleSeverity.INFO
        assert "fk_parent" in finding.message
        assert "NULLS NOT DISTINCT" in (finding.suggested_fix or "")


def test_softdel_002_reads_only_soft_deleting_tables(tmp_path: Path) -> None:
    sql = "CREATE TABLE tb_node (id INT PRIMARY KEY, fk_parent INT, name TEXT, UNIQUE (fk_parent, name));\n"

    assert _nulls(tmp_path, sql) == []


def test_a_constraint_dropped_later_is_not_judged(tmp_path: Path) -> None:
    """#624: the key ``ALTER TABLE … DROP CONSTRAINT`` drops is not one the table holds."""
    sql = ORDER_LINE + (
        "ALTER TABLE app.tb_order_line DROP CONSTRAINT tb_order_line_order_product_key;\n"
    )

    assert _reserved(tmp_path, sql) == []
