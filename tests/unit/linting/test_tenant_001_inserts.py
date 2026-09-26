"""``tenant_001``: an ``INSERT`` into a tenant table supplies the discriminator.

A tenant table is what the family's one classification says it is
(:func:`~confiture.core.linting.tenant.scope.classify`) — nothing is inferred
from views or foreign keys. An ``INSERT`` in a routine body whose target columns
leave the discriminator out writes a row that belongs to no tenant, unless the
column has a default (``DEFAULT current_setting('app.tenant_id')::uuid`` is a
legitimate design). Bodies are read by the one fragment reader; what it cannot
read is reported, never passed.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.unit.linting.tenant_projects import SCOPED, TENANCY, findings

from confiture.core.linting.rule_registry import LINT_RULES, resolve_selection

_ORDER = f"CREATE TABLE app.tb_order (id uuid NOT NULL, total numeric, {SCOPED});\n"


def _inserts(tmp_path: Path, sql: str, project_yaml: str | None = TENANCY):
    return findings(tmp_path, sql, "tenant_001", "check_tenant_isolation", project_yaml)


def _not_judged(report) -> str:
    """The one ``degraded`` status that names every statement not judged."""
    (status,) = [s for s in report.degraded if s.code == "tenant_001"]
    assert status.state == "degraded"
    return status.reason


def _function(body: str, name: str = "app.fn_create_order") -> str:
    return (
        f"CREATE FUNCTION {name}(p_tenant uuid) RETURNS void LANGUAGE plpgsql AS $$\n"
        f"BEGIN\n{body}\nEND;\n$$;\n"
    )


def test_an_insert_that_omits_the_discriminator_is_reported(tmp_path: Path) -> None:
    found, _ = _inserts(
        tmp_path,
        _ORDER + _function("  INSERT INTO app.tb_order (id, total) VALUES (gen_random_uuid(), 1);"),
    )

    (finding,) = found
    assert finding.object_name == "app.fn_create_order -> app.tb_order"
    assert "app.tb_order" in finding.message
    assert "tenant_id" in finding.message
    assert finding.line_number == 9


def test_an_insert_that_supplies_the_discriminator_is_clean(tmp_path: Path) -> None:
    found, _ = _inserts(
        tmp_path,
        _ORDER
        + _function(
            "  INSERT INTO app.tb_order (id, tenant_id, total) VALUES (gen_random_uuid(), p_tenant, 1);"
        ),
    )

    assert found == []


def test_a_discriminator_with_a_default_need_not_be_supplied(tmp_path: Path) -> None:
    found, _ = _inserts(
        tmp_path,
        "CREATE TABLE app.tb_order (id uuid NOT NULL, total numeric,\n"
        "  tenant_id uuid NOT NULL DEFAULT current_setting('app.tenant_id')::uuid\n"
        "    REFERENCES management.tb_organization (id));\n"
        + _function("  INSERT INTO app.tb_order (id, total) VALUES (gen_random_uuid(), 1);"),
    )

    assert found == []


def test_a_default_set_by_a_later_alter_counts(tmp_path: Path) -> None:
    found, _ = _inserts(
        tmp_path,
        _ORDER + "ALTER TABLE app.tb_order ALTER COLUMN tenant_id "
        "SET DEFAULT current_setting('app.tenant_id')::uuid;\n"
        + _function("  INSERT INTO app.tb_order (id, total) VALUES (gen_random_uuid(), 1);"),
    )

    assert found == []


@pytest.mark.parametrize("schema", ["catalog", "management"], ids=["global", "undecided"])
def test_an_insert_into_a_table_that_is_not_tenant_scoped_is_not_judged(
    tmp_path: Path, schema: str
) -> None:
    found, _ = _inserts(
        tmp_path,
        f"CREATE TABLE {schema}.tb_order (id uuid NOT NULL, total numeric);\n"
        + _function(f"  INSERT INTO {schema}.tb_order (id, total) VALUES (gen_random_uuid(), 1);"),
    )

    assert found == []


def test_the_scope_is_the_classification_not_a_view(tmp_path: Path) -> None:
    """No view derives ``tenant_id`` here, and the INSERT is still judged."""
    found, _ = _inserts(
        tmp_path,
        _ORDER + _function("  INSERT INTO app.tb_order (id) VALUES (gen_random_uuid());"),
    )

    assert len(found) == 1


def test_the_configured_discriminator_is_the_one_asked_for(tmp_path: Path) -> None:
    found, _ = _inserts(
        tmp_path,
        "CREATE TABLE app.tb_order (id uuid NOT NULL,\n"
        "  workspace_id uuid NOT NULL REFERENCES management.tb_organization (id));\n"
        + _function("  INSERT INTO app.tb_order (id) VALUES (gen_random_uuid());"),
        project_yaml=TENANCY + "  discriminator: workspace_id\n",
    )

    (finding,) = found
    assert "workspace_id" in finding.message


def test_an_insert_outside_a_routine_is_not_judged(tmp_path: Path) -> None:
    """A seed row in the tree is data the build loads, not a routine's write path."""
    found, _ = _inserts(
        tmp_path,
        _ORDER + "INSERT INTO app.tb_order (id, total) VALUES (gen_random_uuid(), 1);\n",
    )

    assert found == []


def test_without_a_tenancy_block_the_rule_says_it_did_not_run(tmp_path: Path) -> None:
    found, report = _inserts(
        tmp_path,
        _ORDER + _function("  INSERT INTO app.tb_order (id) VALUES (gen_random_uuid());"),
        project_yaml=None,
    )

    assert found == []
    assert [(s.code, s.state) for s in report.skipped] == [("tenant_001", "skipped")]
    assert "db/project.yaml" in report.skipped[0].reason


def test_tenant_001_is_on_when_the_project_declares_tenancy() -> None:
    rule = next(r for r in LINT_RULES if r.code == "tenant_001")

    assert (rule.family, rule.severity, rule.default_on, rule.enabled_by) == (
        "tenant",
        "warning",
        False,
        "tenancy",
    )
    assert rule.title == "An INSERT into a tenant table supplies the discriminator"
    assert rule.legacy_flag == "--check-tenant-isolation"
    assert "tenant_001" in resolve_selection(None, (), declared=frozenset({"tenancy"}))
    assert "tenant_001" not in resolve_selection(None, ())


# -- Shapes -------------------------------------------------------------------


def test_insert_select_is_judged_by_its_column_list(tmp_path: Path) -> None:
    found, _ = _inserts(
        tmp_path / "missing",
        _ORDER
        + _function(
            "  INSERT INTO app.tb_order (id, total)\n"
            "  SELECT o.id, o.total FROM app.tb_order o WHERE o.tenant_id = p_tenant;"
        ),
    )
    clean, _ = _inserts(
        tmp_path / "supplied",
        _ORDER
        + _function(
            "  INSERT INTO app.tb_order (id, tenant_id, total)\n"
            "  SELECT o.id, o.tenant_id, o.total FROM app.tb_order o;"
        ),
    )

    assert len(found) == 1
    assert clean == []


def test_an_insert_with_no_column_list_supplies_the_first_columns(tmp_path: Path) -> None:
    """``id, total, tenant_id``: three values reach the discriminator, two do not."""
    clean, _ = _inserts(
        tmp_path / "three",
        _ORDER + _function("  INSERT INTO app.tb_order VALUES (gen_random_uuid(), 1, p_tenant);"),
    )
    short, _ = _inserts(
        tmp_path / "two",
        _ORDER + _function("  INSERT INTO app.tb_order VALUES (gen_random_uuid(), 1);"),
    )

    assert clean == []
    (finding,) = short
    assert "2 columns" in finding.message
    assert "column 3" in finding.message


def test_a_select_with_no_column_list_counts_its_outputs_from_the_model(tmp_path: Path) -> None:
    """``SELECT *`` over a table the model holds supplies every one of its columns."""
    found, _ = _inserts(
        tmp_path,
        _ORDER
        + "CREATE TABLE app.tb_order_archive (id uuid NOT NULL, total numeric, "
        + SCOPED
        + ");\n"
        + _function("  INSERT INTO app.tb_order_archive SELECT * FROM app.tb_order;"),
    )

    assert found == []


def test_a_select_whose_outputs_cannot_be_counted_is_reported_unread(tmp_path: Path) -> None:
    found, report = _inserts(
        tmp_path,
        _ORDER + _function("  INSERT INTO app.tb_order SELECT * FROM app.fn_rows(p_tenant);"),
    )

    assert found == []
    reason = _not_judged(report)
    assert "not judged" in reason
    assert "set-returning function" in reason


def test_default_values_supplies_no_column(tmp_path: Path) -> None:
    found, _ = _inserts(tmp_path, _ORDER + _function("  INSERT INTO app.tb_order DEFAULT VALUES;"))

    assert len(found) == 1


def test_an_insert_inside_a_data_modifying_cte_is_judged(tmp_path: Path) -> None:
    found, _ = _inserts(
        tmp_path,
        _ORDER + "CREATE FUNCTION app.fn_create_order() RETURNS uuid LANGUAGE plpgsql AS $$\n"
        "DECLARE v_id uuid;\n"
        "BEGIN\n"
        "  v_id := gen_random_uuid();\n"
        "  WITH created AS (INSERT INTO app.tb_order (id) VALUES (v_id) RETURNING id)\n"
        "  SELECT id INTO v_id FROM created;\n"
        "  RETURN v_id;\n"
        "END;\n$$;\n",
    )

    (finding,) = found
    assert finding.line_number == 11


def test_insert_returning_into_is_judged(tmp_path: Path) -> None:
    found, _ = _inserts(
        tmp_path,
        _ORDER + "CREATE FUNCTION app.fn_create_order() RETURNS uuid LANGUAGE plpgsql AS $$\n"
        "DECLARE v_id uuid;\n"
        "BEGIN\n"
        "  INSERT INTO app.tb_order (id) VALUES (gen_random_uuid()) RETURNING id INTO v_id;\n"
        "  RETURN v_id;\n"
        "END;\n$$;\n",
    )

    assert len(found) == 1


def test_a_language_sql_body_is_judged(tmp_path: Path) -> None:
    found, _ = _inserts(
        tmp_path,
        _ORDER + "CREATE FUNCTION app.fn_create_order() RETURNS void LANGUAGE sql AS $$\n"
        "  INSERT INTO app.tb_order (id) VALUES (gen_random_uuid());\n$$;\n",
    )

    (finding,) = found
    assert finding.line_number == 8


def test_a_procedure_is_judged(tmp_path: Path) -> None:
    found, _ = _inserts(
        tmp_path,
        _ORDER + "CREATE PROCEDURE app.pr_create_order() LANGUAGE plpgsql AS $$\n"
        "BEGIN\n  INSERT INTO app.tb_order (id) VALUES (gen_random_uuid());\nEND;\n$$;\n",
    )

    assert len(found) == 1


def test_an_unqualified_target_is_the_table_the_model_holds(tmp_path: Path) -> None:
    found, _ = _inserts(
        tmp_path,
        "CREATE TABLE tb_order (id uuid NOT NULL, "
        + SCOPED
        + ");\n"
        + _function("  INSERT INTO tb_order (id) VALUES (gen_random_uuid());"),
    )

    assert len(found) == 1


def test_dynamic_execute_is_declared_unread(tmp_path: Path) -> None:
    found, report = _inserts(
        tmp_path,
        _ORDER
        + _function(
            "  EXECUTE format('INSERT INTO %I.tb_order (id) VALUES ($1)', 'app')\n"
            "    USING gen_random_uuid();"
        ),
    )

    assert found == []
    reason = _not_judged(report)
    assert "(line 9)" in reason
    assert "run time" in reason
    assert "not judged" in reason


def test_a_fragment_that_cannot_be_read_is_reported_never_passed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from confiture.core import plpgsql_fragments

    slots = dict(plpgsql_fragments.SLOTS)
    del slots[("PLpgSQL_stmt_execsql", "sqlstmt")]
    monkeypatch.setattr(plpgsql_fragments, "SLOTS", slots)

    found, report = _inserts(
        tmp_path,
        _ORDER + _function("  INSERT INTO app.tb_order (id) VALUES (gen_random_uuid());"),
    )

    assert found == []
    reason = _not_judged(report)
    assert "no reading for PLpgSQL_stmt_execsql.sqlstmt" in reason
    assert "not judged" in reason


def test_a_body_the_compiler_refuses_is_reported_never_passed(tmp_path: Path) -> None:
    found, report = _inserts(
        tmp_path,
        _ORDER + "CREATE FUNCTION app.fn_create_order() RETURNS void\n"
        "LANGUAGE plpgsql AS $$\n"
        "BEGIN INSERT INTO app.tb_order (id) VALUES (gen_random_uuid()); END IF; END; $$;\n",
    )

    assert found == []
    reason = _not_judged(report)
    assert "could not be read" in reason
    assert "(line 7)" in reason


# -- Reading ------------------------------------------------------------------


def test_an_insert_in_a_comment_or_a_literal_is_not_an_insert(tmp_path: Path) -> None:
    found, _ = _inserts(
        tmp_path,
        _ORDER
        + _function(
            "  -- INSERT INTO app.tb_order (id) VALUES (gen_random_uuid());\n"
            "  RAISE NOTICE 'INSERT INTO app.tb_order (id) VALUES (1)';"
        ),
    )

    assert found == []


def test_a_begin_atomic_body_is_judged(tmp_path: Path) -> None:
    found, _ = _inserts(
        tmp_path,
        _ORDER + "CREATE FUNCTION app.fn_create_order() RETURNS void LANGUAGE sql BEGIN ATOMIC\n"
        "  INSERT INTO app.tb_order (id) VALUES (gen_random_uuid());\nEND;\n",
    )

    (finding,) = found
    assert finding.line_number == 8


def test_a_quoted_discriminator_is_the_column_it_names(tmp_path: Path) -> None:
    found, _ = _inserts(
        tmp_path,
        _ORDER
        + _function(
            '  INSERT INTO "app"."tb_order" ("id", "tenant_id") VALUES (gen_random_uuid(), p_tenant);'
        ),
    )

    assert found == []
