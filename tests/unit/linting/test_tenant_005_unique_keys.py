"""``tenant_005``: a tenant table's keys cannot let one tenant's row collide with another's.

``UNIQUE (email)`` on a tenant table lets one tenant's row block another's insert,
and the error tells the second tenant the value exists elsewhere. The primary key,
every ``UNIQUE`` and every unique index of a tenant table lead with the
discriminator; a uniqueness that is deliberately platform-wide is written as its
own ``CREATE UNIQUE INDEX`` under ``-- confiture:tenant-global <reason>``.
"""

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
        # A key that contains the discriminator cannot collide across tenants:
        # column order matters to an index's use, not to uniqueness (#559).
        (", PRIMARY KEY (tenant_id, id), UNIQUE (email, tenant_id)", False),
        (", PRIMARY KEY (id, tenant_id)", False),
    ],
)
def test_a_key_contains_the_discriminator(tmp_path: Path, keys: str, reported: bool) -> None:
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


@pytest.mark.parametrize(
    ("column", "reported"),
    [
        ("pk_order bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY", False),
        ("pk_order bigserial PRIMARY KEY", False),
        ("id uuid NOT NULL DEFAULT gen_random_uuid() UNIQUE", False),
        ("id uuid NOT NULL DEFAULT uuidv7() PRIMARY KEY", False),
        ("id uuid NOT NULL UNIQUE", True),
        ("code text NOT NULL DEFAULT 'x' UNIQUE", True),
    ],
)
def test_a_key_whose_one_column_generates_its_value_cannot_collide(
    tmp_path: Path, column: str, reported: bool
) -> None:
    """#559's other half: an identity or a generated uuid is unique whoever writes the row."""
    found, _ = _keys(tmp_path, f"CREATE TABLE app.tb_order ({column}, {SCOPED});\n")

    assert bool(found) is reported


def test_a_two_column_key_with_one_generated_column_is_judged_by_containment(
    tmp_path: Path,
) -> None:
    found, _ = _keys(
        tmp_path,
        "CREATE TABLE app.tb_order (id uuid DEFAULT gen_random_uuid(), code text, "
        f"{SCOPED}, UNIQUE (id, code));\n",
    )

    assert len(found) == 1


def test_a_unique_index_that_contains_the_discriminator_is_not_reported(tmp_path: Path) -> None:
    found, _ = _keys(
        tmp_path,
        _table(", PRIMARY KEY (tenant_id, id)")
        + "CREATE UNIQUE INDEX ux_user_email ON app.tb_user (email, tenant_id);\n",
    )

    assert found == []


def test_the_message_speaks_of_containing_the_discriminator(tmp_path: Path) -> None:
    (finding,), _ = _keys(tmp_path, _table(", PRIMARY KEY (tenant_id, id), UNIQUE (email)"))

    assert "does not contain tenant_id" in finding.message


def test_a_key_dropped_later_is_not_judged(tmp_path: Path) -> None:
    """#624: the key ``ALTER TABLE … DROP CONSTRAINT`` drops is not one the table holds."""
    sql = _table(", PRIMARY KEY (tenant_id, id), CONSTRAINT tb_user_email_key UNIQUE (email)")
    found, _ = _keys(tmp_path, sql + "ALTER TABLE app.tb_user DROP CONSTRAINT tb_user_email_key;\n")

    assert found == []
