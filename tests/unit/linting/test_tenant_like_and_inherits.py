"""A table that gets the discriminator through ``LIKE`` or ``INHERITS`` carries it (#467).

PostgreSQL gives the new table the column, and its ``NOT NULL``, either way; the
foreign key to the table of tenants it does not copy. So the finding on such a
table is the missing reference, never a missing column — and the table is tenant
data every other rule of the family judges.
"""

from __future__ import annotations

from pathlib import Path

from tests.unit.linting.tenant_projects import ROOT, SCOPED, findings, project

from confiture.core.linting.schema_linter import LintConfig, SchemaLinter

_ORDER = f"CREATE TABLE app.tb_order (id uuid NOT NULL, {SCOPED}, PRIMARY KEY (tenant_id, id));\n"
_REFERENCES = (
    "ALTER TABLE {table} ADD FOREIGN KEY (tenant_id) REFERENCES management.tb_organization (id);\n"
)


def _tables(tmp_path: Path, sql: str):
    found, _ = findings(tmp_path, _ORDER + sql, "tenant_002", "check_tenant_tables")
    return found


# -- LIKE ------------------------------------------------------------------------


def test_a_like_copy_has_the_column_but_not_the_foreign_key(tmp_path: Path) -> None:
    (finding,) = _tables(tmp_path, "CREATE TABLE app.tb_copy (LIKE app.tb_order INCLUDING ALL);\n")

    assert finding.object_name == "app.tb_copy"
    assert "does not reference management.tb_organization" in finding.message


def test_a_like_copy_that_references_the_root_is_clean(tmp_path: Path) -> None:
    sql = "CREATE TABLE app.tb_copy (LIKE app.tb_order EXCLUDING ALL);\n"

    assert _tables(tmp_path, sql + _REFERENCES.format(table="app.tb_copy")) == []


def test_a_like_copy_takes_the_columns_as_they_stand_at_its_create(tmp_path: Path) -> None:
    sql = (
        "CREATE TABLE app.tb_draft (id uuid);\n"
        "CREATE TABLE app.tb_copy (LIKE app.tb_draft);\n"
        f"ALTER TABLE app.tb_draft ADD COLUMN {SCOPED};\n"
    )

    assert [
        (f.object_name, "no tenant_id column" in f.message) for f in _tables(tmp_path, sql)
    ] == [("app.tb_copy", True)]


def test_a_like_copy_in_another_file_is_located_in_that_file(tmp_path: Path) -> None:
    root = project(tmp_path)
    schema = root / "db" / "schema"
    (schema / "010_tables.sql").write_text(ROOT + _ORDER)
    (schema / "020_copies.sql").write_text(
        "-- a copy\n\nCREATE TABLE app.tb_copy (LIKE app.tb_order INCLUDING ALL);\n"
    )

    report = SchemaLinter(
        env="local", project_dir=root, config=LintConfig(check_tenant_tables=True)
    ).lint()

    (finding,) = [
        v for v in (*report.errors, *report.warnings, *report.info) if v.rule_id == "tenant_002"
    ]
    assert (finding.file_path, finding.line_number) == ("db/schema/020_copies.sql", 3)


# -- INHERITS --------------------------------------------------------------------


def test_an_inheriting_table_has_the_column_but_not_the_foreign_key(tmp_path: Path) -> None:
    (finding,) = _tables(
        tmp_path, "CREATE TABLE app.tb_child (extra int) INHERITS (app.tb_order);\n"
    )

    assert finding.object_name == "app.tb_child"
    assert "does not reference management.tb_organization" in finding.message


def test_an_inheriting_table_that_references_the_root_is_clean(tmp_path: Path) -> None:
    sql = "CREATE TABLE app.tb_child (extra int) INHERITS (app.tb_order);\n"

    assert _tables(tmp_path, sql + _REFERENCES.format(table="app.tb_child")) == []


def test_an_inheriting_table_gets_a_column_its_parent_gains_later(tmp_path: Path) -> None:
    sql = (
        "CREATE TABLE app.tb_base (id uuid);\n"
        "CREATE TABLE app.tb_child (extra int) INHERITS (app.tb_base);\n"
        f"ALTER TABLE app.tb_base ADD COLUMN {SCOPED};\n" + _REFERENCES.format(table="app.tb_child")
    )

    assert _tables(tmp_path, sql) == []


def test_a_view_over_an_inheriting_table_publishes_its_discriminator(tmp_path: Path) -> None:
    found, _ = findings(
        tmp_path,
        _ORDER
        + "CREATE TABLE app.tb_child (extra int) INHERITS (app.tb_order);\n"
        + "CREATE VIEW app.v_child AS SELECT tenant_id, id FROM app.tb_child;\n",
        "tenant_003",
        "check_tenant_views",
    )

    assert found == []


def test_a_view_hiding_an_inheriting_tables_discriminator_is_reported(tmp_path: Path) -> None:
    found, _ = findings(
        tmp_path,
        _ORDER
        + "CREATE TABLE app.tb_child (extra int) INHERITS (app.tb_order);\n"
        + "CREATE VIEW app.v_child AS SELECT id FROM app.tb_child;\n",
        "tenant_003",
        "check_tenant_views",
    )

    assert [f.object_name for f in found] == ["app.v_child"]
