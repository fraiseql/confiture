"""``tenant_005``: a tenant table's keys lead with the discriminator.

``UNIQUE (email)`` on a tenant table lets one tenant's row block another's insert,
and the error tells the second tenant the value exists elsewhere. The primary key,
every ``UNIQUE`` and every unique index of a tenant table lead with the
discriminator; a uniqueness that is deliberately platform-wide is written as its
own ``CREATE UNIQUE INDEX`` under ``-- confiture:tenant-global <reason>``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.unit.linting.tenant_projects import SCOPED, TENANCY, findings

from confiture.core.linting.rule_registry import LINT_RULES, resolve_selection


def _keys(tmp_path: Path, sql: str, project_yaml: str | None = TENANCY):
    return findings(tmp_path, sql, "tenant_005", "check_tenant_unique_keys", project_yaml)


def _table(keys: str) -> str:
    return f"CREATE TABLE app.tb_user (id uuid NOT NULL, email text NOT NULL, {SCOPED}{keys});\n"


@pytest.mark.parametrize(
    ("keys", "reported"),
    [
        (", PRIMARY KEY (id)", True),
        (", PRIMARY KEY (tenant_id, id)", False),
        (", PRIMARY KEY (tenant_id, id), UNIQUE (email)", True),
        (", PRIMARY KEY (tenant_id, id), UNIQUE (tenant_id, email)", False),
        (", PRIMARY KEY (tenant_id, id), UNIQUE (email, tenant_id)", True),
    ],
)
def test_a_key_leads_with_the_discriminator(tmp_path: Path, keys: str, reported: bool) -> None:
    found, _ = _keys(tmp_path, _table(keys))

    assert bool(found) is reported


def test_a_primary_key_written_on_its_column_is_judged(tmp_path: Path) -> None:
    found, _ = _keys(
        tmp_path, f"CREATE TABLE app.tb_user (id uuid PRIMARY KEY, email text, {SCOPED});\n"
    )

    (finding,) = found
    assert finding.object_name == "app.tb_user"
    assert "PRIMARY KEY (tenant_id, id)" in (finding.suggested_fix or "")


def test_the_root_and_global_tables_are_not_judged(tmp_path: Path) -> None:
    found, _ = _keys(tmp_path, "CREATE TABLE catalog.tb_country (id int PRIMARY KEY);\n")

    assert found == []


def test_a_unique_index_on_an_expression_is_judged_by_its_first_key(tmp_path: Path) -> None:
    found, _ = _keys(
        tmp_path,
        _table(", PRIMARY KEY (tenant_id, id)")
        + "\n\nCREATE UNIQUE INDEX ux_user_email ON app.tb_user (lower(email));\n",
    )

    (finding,) = found
    assert "ux_user_email" in finding.message
    assert finding.line_number == 9


def test_a_partial_unique_index_is_judged_by_its_first_key(tmp_path: Path) -> None:
    found, _ = _keys(
        tmp_path,
        _table(", PRIMARY KEY (tenant_id, id)")
        + "CREATE UNIQUE INDEX ON app.tb_user (email) WHERE email <> '';\n"
        + "CREATE UNIQUE INDEX ON app.tb_user (tenant_id, lower(email)) WHERE email <> '';\n",
    )

    assert len(found) == 1


def test_a_plain_index_is_not_judged(tmp_path: Path) -> None:
    found, _ = _keys(
        tmp_path,
        _table(", PRIMARY KEY (tenant_id, id)") + "CREATE INDEX ON app.tb_user (email);\n",
    )

    assert found == []


def test_a_unique_index_declared_global_is_exempt(tmp_path: Path) -> None:
    found, _ = _keys(
        tmp_path,
        _table(", PRIMARY KEY (tenant_id, id)")
        + "-- confiture:tenant-global one login per address across the platform\n"
        + "CREATE UNIQUE INDEX ON app.tb_user (lower(email));\n",
    )

    assert found == []


def test_a_global_declaration_on_an_index_needs_a_reason(tmp_path: Path) -> None:
    found, _ = _keys(
        tmp_path,
        _table(", PRIMARY KEY (tenant_id, id)")
        + "-- confiture:tenant-global\n"
        + "CREATE UNIQUE INDEX ON app.tb_user (lower(email));\n",
    )

    (finding,) = found
    assert "reason" in finding.message


def test_a_global_declaration_on_an_index_that_leads_with_the_discriminator_is_stale(
    tmp_path: Path,
) -> None:
    found, _ = _keys(
        tmp_path,
        _table(", PRIMARY KEY (tenant_id, id)")
        + "-- confiture:tenant-global one login per address\n"
        + "CREATE UNIQUE INDEX ON app.tb_user (tenant_id, lower(email));\n",
    )

    (finding,) = found
    assert "stale" in finding.message


def test_an_index_in_another_file_is_located_in_that_file(tmp_path: Path) -> None:
    from tests.unit.linting.tenant_projects import ROOT, project

    from confiture.core.linting.schema_linter import LintConfig, SchemaLinter

    root = project(tmp_path)
    schema = root / "db" / "schema"
    (schema / "010_tables.sql").write_text(ROOT + _table(", PRIMARY KEY (tenant_id, id)"))
    (schema / "020_indexes.sql").write_text(
        "-- confiture:tenant-global one login per address\n"
        "CREATE UNIQUE INDEX ON app.tb_user (lower(email));\n"
        "\nCREATE UNIQUE INDEX ux_email ON app.tb_user (email);\n"
    )

    report = SchemaLinter(
        env="local", project_dir=root, config=LintConfig(check_tenant_unique_keys=True)
    ).lint()

    (finding,) = [v for v in report.warnings if v.rule_id == "tenant_005"]
    assert (finding.file_path, finding.line_number) == ("db/schema/020_indexes.sql", 4)


def test_a_table_defined_twice_is_judged_by_its_first_definition(tmp_path: Path) -> None:
    """The index folds onto the first definition, and tenant_005 reads that one."""
    table = _table(", PRIMARY KEY (tenant_id, id)").replace("TABLE", "TABLE IF NOT EXISTS")
    found, _ = _keys(
        tmp_path, table + table + "CREATE UNIQUE INDEX ux_email ON app.tb_user (email);\n"
    )

    assert [f.object_name for f in found] == ["app.tb_user"]


def test_without_a_tenancy_block_the_rule_says_it_did_not_run(tmp_path: Path) -> None:
    found, report = _keys(tmp_path, _table(", PRIMARY KEY (id)"), project_yaml=None)

    assert found == []
    assert [(s.code, s.state) for s in report.skipped] == [("tenant_005", "skipped")]


def test_tenant_005_is_on_when_the_project_declares_tenancy() -> None:
    (rule,) = [r for r in LINT_RULES if r.code == "tenant_005"]

    assert (rule.family, rule.severity, rule.default_on, rule.enabled_by) == (
        "tenant",
        "warning",
        False,
        "tenancy",
    )
    assert "tenant_005" in resolve_selection(None, (), declared=frozenset({"tenancy"}))
    assert "tenant_005" not in resolve_selection(
        None, ["tenant_005"], declared=frozenset({"tenancy"})
    )
