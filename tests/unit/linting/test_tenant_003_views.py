"""``tenant_003``: a view publishes the discriminator, traced, or is declared global.

A view that reads a tenant relation must publish an output column named the
discriminator whose origin — traced as a plain column through aliases, joins,
subqueries, CTEs, ``*`` and set operations — is the discriminator of a tenant
relation it reads, or the key of the table of tenants. What the tracer cannot
resolve is a finding that says so, never a clean pass.
"""

from __future__ import annotations

from pathlib import Path

from confiture.core.linting.schema_linter import LintConfig, SchemaLinter

_ROOT = """
CREATE SCHEMA management;
CREATE SCHEMA app;
CREATE SCHEMA catalog;
CREATE TABLE management.tb_organization (id uuid PRIMARY KEY, name text NOT NULL);
CREATE TABLE app.tb_order (id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES management.tb_organization (id), total int);
CREATE TABLE app.tb_invoice (id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES management.tb_organization (id), fk_order uuid);
CREATE TABLE catalog.tb_supplier (id uuid PRIMARY KEY, name text, tenant_id uuid);
CREATE TABLE catalog.tb_paper_format (id uuid PRIMARY KEY, label text);
"""

_TENANCY = "tenancy:\n  root: management.tb_organization\n  global_schemas: [catalog]\n"


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


def _findings(tmp_path: Path, sql: str, project_yaml: str | None = _TENANCY):
    linter = SchemaLinter(
        env="local",
        project_dir=_project(tmp_path, project_yaml),
        config=LintConfig(check_tenant_views=True),
    )
    report = linter.lint(_ROOT + sql)
    return [
        v for v in (*report.errors, *report.warnings, *report.info) if v.rule_id == "tenant_003"
    ], report


def _objects(tmp_path: Path, sql: str) -> list[str]:
    findings, _ = _findings(tmp_path, sql)
    return sorted(f.object_name for f in findings)


# -- the plain case ------------------------------------------------------------


def test_a_view_publishing_the_discriminator_is_traced(tmp_path: Path) -> None:
    assert (
        _objects(
            tmp_path, "CREATE VIEW app.v_order AS SELECT o.tenant_id, o.id FROM app.tb_order o;"
        )
        == []
    )


def test_a_view_hiding_the_discriminator_is_reported(tmp_path: Path) -> None:
    findings, _ = _findings(tmp_path, "CREATE VIEW app.v_order AS SELECT o.id FROM app.tb_order o;")

    (finding,) = findings
    assert finding.object_name == "app.v_order"
    assert "tenant_id" in finding.message
    assert "app.tb_order" in finding.message
    assert "confiture:tenant-global" in (finding.suggested_fix or "")
    assert finding.line_number == 12


def test_an_unaliased_qualified_reference_is_traced(tmp_path: Path) -> None:
    sql = "CREATE VIEW app.v_order AS SELECT tb_order.tenant_id FROM app.tb_order;"
    assert _objects(tmp_path, sql) == []


def test_a_view_reading_only_global_relations_needs_no_declaration(tmp_path: Path) -> None:
    sql = "CREATE VIEW catalog.v_formats AS SELECT f.label FROM catalog.tb_paper_format f;"
    assert _objects(tmp_path, sql) == []


def test_without_tenancy_the_rule_reports_itself_skipped(tmp_path: Path) -> None:
    sql = "CREATE VIEW app.v_order AS SELECT o.id FROM app.tb_order o;"
    findings, report = _findings(tmp_path, sql, project_yaml=None)

    assert findings == []
    assert [s.code for s in report.skipped] == ["tenant_003"]


# -- shapes that still publish -------------------------------------------------


def test_a_star_publishes_the_discriminator(tmp_path: Path) -> None:
    assert _objects(tmp_path, "CREATE VIEW app.v_order AS SELECT * FROM app.tb_order;") == []


def test_a_qualified_star_publishes_the_discriminator(tmp_path: Path) -> None:
    sql = (
        "CREATE VIEW app.v_order AS SELECT o.*, f.label "
        "FROM app.tb_order o CROSS JOIN catalog.tb_paper_format f;"
    )
    assert _objects(tmp_path, sql) == []


def test_a_cte_publishes_the_discriminator(tmp_path: Path) -> None:
    sql = (
        "CREATE VIEW app.v_order AS WITH o AS (SELECT tenant_id, id FROM app.tb_order) "
        "SELECT o.tenant_id, o.id FROM o;"
    )
    assert _objects(tmp_path, sql) == []


def test_a_cte_column_list_renames_what_it_reads(tmp_path: Path) -> None:
    sql = (
        "CREATE VIEW app.v_order AS WITH o (tenant_id, x) AS (SELECT id, tenant_id "
        "FROM app.tb_order) SELECT tenant_id FROM o;"
    )
    (finding,) = _findings(tmp_path, sql)[0]
    assert "app.tb_order.id" in finding.message


def test_a_recursive_cte_publishes_the_discriminator(tmp_path: Path) -> None:
    sql = (
        "CREATE VIEW app.v_tree AS WITH RECURSIVE t AS ("
        "SELECT tenant_id, id, fk_order FROM app.tb_invoice WHERE fk_order IS NULL "
        "UNION ALL SELECT i.tenant_id, i.id, i.fk_order FROM app.tb_invoice i "
        "JOIN t ON i.fk_order = t.id) SELECT t.tenant_id, t.id FROM t;"
    )
    assert _objects(tmp_path, sql) == []


def test_a_subquery_in_from_publishes_the_discriminator(tmp_path: Path) -> None:
    sql = (
        "CREATE VIEW app.v_order AS SELECT s.tenant_id FROM "
        "(SELECT o.tenant_id, o.id FROM app.tb_order o) s;"
    )
    assert _objects(tmp_path, sql) == []


def test_a_subquery_column_list_renames_what_it_reads(tmp_path: Path) -> None:
    sql = (
        "CREATE VIEW app.v_order AS SELECT s.tenant_id FROM "
        "(SELECT o.id, o.tenant_id FROM app.tb_order o) s (tenant_id, x);"
    )
    (finding,) = _findings(tmp_path, sql)[0]
    assert "app.tb_order.id" in finding.message


def test_join_using_merges_the_discriminator(tmp_path: Path) -> None:
    sql = (
        "CREATE VIEW app.v_order AS SELECT tenant_id, o.id, i.id AS invoice "
        "FROM app.tb_order o JOIN app.tb_invoice i USING (tenant_id);"
    )
    assert _objects(tmp_path, sql) == []


def test_a_star_over_join_using_publishes_the_merged_column(tmp_path: Path) -> None:
    sql = (
        "CREATE VIEW app.v_order AS SELECT * FROM (SELECT tenant_id, id FROM app.tb_order) o "
        "NATURAL JOIN (SELECT tenant_id, fk_order FROM app.tb_invoice) i;"
    )
    assert _objects(tmp_path, sql) == []


def test_a_full_join_merged_column_is_not_plain(tmp_path: Path) -> None:
    sql = (
        "CREATE VIEW app.v_order AS SELECT tenant_id FROM app.tb_order o "
        "FULL JOIN app.tb_invoice i USING (tenant_id);"
    )
    (finding,) = _findings(tmp_path, sql)[0]
    assert "not a plain column" in finding.message


def test_a_union_all_of_two_tenant_tables_publishes(tmp_path: Path) -> None:
    sql = (
        "CREATE VIEW app.v_doc AS SELECT tenant_id, id FROM app.tb_order "
        "UNION ALL SELECT tenant_id, id FROM app.tb_invoice;"
    )
    assert _objects(tmp_path, sql) == []


def test_the_view_column_list_names_the_output(tmp_path: Path) -> None:
    sql = "CREATE VIEW app.v_order (tenant_id, id) AS SELECT o.tenant_id, o.id FROM app.tb_order o;"
    assert _objects(tmp_path, sql) == []


def test_the_roots_key_published_as_the_discriminator_is_traced(tmp_path: Path) -> None:
    sql = (
        "CREATE VIEW app.v_org AS SELECT o.id AS tenant_id, o.name "
        "FROM management.tb_organization o;"
    )
    assert _objects(tmp_path, sql) == []


def test_the_global_cross_join_root_fan_out_is_traced(tmp_path: Path) -> None:
    sql = (
        "CREATE TABLE app.tb_custom_format (id uuid PRIMARY KEY, label text,\n"
        "  tenant_id uuid NOT NULL REFERENCES management.tb_organization (id));\n"
        "CREATE VIEW app.v_paper_format AS\n"
        "SELECT o.id AS tenant_id, f.* FROM catalog.tb_paper_format f\n"
        "  CROSS JOIN management.tb_organization o\n"
        "UNION ALL\n"
        "SELECT c.tenant_id, c.id, c.label FROM app.tb_custom_format c;\n"
    )
    assert _objects(tmp_path, sql) == []


def test_a_materialized_view_is_a_view(tmp_path: Path) -> None:
    sql = "CREATE MATERIALIZED VIEW app.mv_order AS SELECT o.id FROM app.tb_order o;"
    assert _objects(tmp_path, sql) == ["app.mv_order"]


# -- shapes that do not publish -------------------------------------------------


def _message(tmp_path: Path, sql: str) -> str:
    (finding,) = _findings(tmp_path, sql)[0]
    return finding.message


def test_a_coalesce_over_the_discriminator_is_not_plain(tmp_path: Path) -> None:
    sql = (
        "CREATE VIEW app.v_order AS SELECT coalesce(o.tenant_id, i.tenant_id) AS tenant_id "
        "FROM app.tb_order o LEFT JOIN app.tb_invoice i ON i.fk_order = o.id;"
    )
    assert "not a plain column" in _message(tmp_path, sql)


def test_an_unaliased_coalesce_publishes_no_discriminator(tmp_path: Path) -> None:
    sql = "CREATE VIEW app.v_order AS SELECT coalesce(o.tenant_id, o.id) FROM app.tb_order o;"
    assert "publishes no tenant_id" in _message(tmp_path, sql)


def test_a_cast_of_the_discriminator_is_not_plain(tmp_path: Path) -> None:
    sql = "CREATE VIEW app.v_order AS SELECT o.tenant_id::text FROM app.tb_order o;"
    assert "not a plain column" in _message(tmp_path, sql)


def test_a_discriminator_taken_from_a_global_table_is_reported(tmp_path: Path) -> None:
    sql = (
        "CREATE VIEW app.v_order AS SELECT s.tenant_id, o.id "
        "FROM app.tb_order o JOIN catalog.tb_supplier s ON s.id = o.id;"
    )
    message = _message(tmp_path, sql)
    assert "catalog.tb_supplier.tenant_id" in message
    assert "not the tenant_id of a tenant relation" in message


def test_a_union_whose_branch_is_a_literal_is_not_plain(tmp_path: Path) -> None:
    sql = (
        "CREATE VIEW app.v_doc AS SELECT tenant_id, id FROM app.tb_order "
        "UNION SELECT NULL, id FROM app.tb_invoice;"
    )
    assert "not a plain column" in _message(tmp_path, sql)


def test_a_count_across_tenants_publishes_nothing(tmp_path: Path) -> None:
    sql = "CREATE VIEW app.v_order_count AS SELECT count(*) AS n FROM app.tb_order;"
    assert "publishes no tenant_id" in _message(tmp_path, sql)


def test_an_aggregate_grouped_by_the_discriminator_publishes_it(tmp_path: Path) -> None:
    sql = (
        "CREATE VIEW app.v_order_count AS SELECT tenant_id, count(*) AS n "
        "FROM app.tb_order GROUP BY tenant_id;"
    )
    assert _objects(tmp_path, sql) == []


def test_an_aggregate_of_the_discriminator_is_not_plain(tmp_path: Path) -> None:
    sql = "CREATE VIEW app.v_order AS SELECT max(tenant_id) AS tenant_id FROM app.tb_order;"
    assert "not a plain column" in _message(tmp_path, sql)


# -- reads through bodies and views ---------------------------------------------

_COUNTER = (
    "CREATE FUNCTION app.f_supplier_order_count(p_supplier uuid) RETURNS bigint\n"
    "LANGUAGE sql STABLE AS $$ SELECT count(*) FROM app.tb_order WHERE id = p_supplier $$;\n"
)


def test_a_view_reading_tenant_data_through_a_function_is_reported(tmp_path: Path) -> None:
    sql = _COUNTER + (
        "CREATE VIEW app.v_supplier AS SELECT s.id, s.name, "
        "app.f_supplier_order_count(s.id) AS orders FROM catalog.tb_supplier s;\n"
    )
    message = _message(tmp_path, sql)
    assert "app.tb_order" in message
    assert "publishes no tenant_id" in message


def test_a_plpgsql_body_is_read_too(tmp_path: Path) -> None:
    sql = (
        "CREATE FUNCTION app.f_open(p uuid) RETURNS boolean LANGUAGE plpgsql AS $$\n"
        "BEGIN RETURN EXISTS (SELECT 1 FROM app.tb_invoice WHERE fk_order = p); END $$;\n"
        "CREATE VIEW app.v_supplier AS SELECT s.id, app.f_open(s.id) AS open "
        "FROM catalog.tb_supplier s;\n"
    )
    assert "app.tb_invoice" in _message(tmp_path, sql)


def test_a_view_over_a_traced_view_is_traced(tmp_path: Path) -> None:
    sql = (
        "CREATE VIEW app.v_order AS SELECT o.tenant_id, o.id FROM app.tb_order o;\n"
        "CREATE VIEW app.v_order_2 AS SELECT v.tenant_id, v.id FROM app.v_order v;\n"
    )
    assert _objects(tmp_path, sql) == []


def test_a_view_over_an_unpublishing_view_is_reported_too(tmp_path: Path) -> None:
    sql = (
        "CREATE VIEW app.v_order AS SELECT o.id FROM app.tb_order o;\n"
        "CREATE VIEW app.v_order_2 AS SELECT v.id FROM app.v_order v;\n"
    )
    findings, _ = _findings(tmp_path, sql)
    assert sorted(f.object_name for f in findings) == ["app.v_order", "app.v_order_2"]
    assert "app.v_order " in next(f for f in findings if f.object_name == "app.v_order_2").message


def test_a_view_over_a_global_view_needs_nothing(tmp_path: Path) -> None:
    sql = (
        "CREATE VIEW catalog.v_formats AS SELECT f.id, f.label FROM catalog.tb_paper_format f;\n"
        "CREATE VIEW app.v_formats AS SELECT v.label FROM catalog.v_formats v;\n"
    )
    assert _objects(tmp_path, sql) == []


def test_views_are_judged_whatever_order_their_files_list_them_in(tmp_path: Path) -> None:
    project = _project(tmp_path, _TENANCY)
    schema = project / "db" / "schema"
    (schema / "00_root.sql").write_text(_ROOT)
    (schema / "10_outer.sql").write_text(
        "CREATE VIEW app.v_outer AS SELECT i.tenant_id FROM app.v_inner i;\n"
    )
    (schema / "20_inner.sql").write_text(
        "CREATE VIEW app.v_inner AS SELECT o.tenant_id FROM app.tb_order o;\n"
    )
    linter = SchemaLinter(
        env="local", project_dir=project, config=LintConfig(check_tenant_views=True)
    )
    report = linter.lint()
    assert [v for v in report.warnings if v.rule_id == "tenant_003"] == []


# -- the declaration ----------------------------------------------------------


def test_a_declared_global_view_reading_tenant_data_is_accepted(tmp_path: Path) -> None:
    sql = (
        "-- confiture:tenant-global platform-wide order statistics\n"
        "CREATE VIEW app.v_order_count AS SELECT count(*) AS n FROM app.tb_order;\n"
    )
    assert _objects(tmp_path, sql) == []


def test_a_declaration_without_a_reason_is_reported(tmp_path: Path) -> None:
    sql = (
        "-- confiture:tenant-global\n"
        "CREATE VIEW app.v_order_count AS SELECT count(*) AS n FROM app.tb_order;\n"
    )
    assert "without a reason" in _message(tmp_path, sql)


def test_a_declaration_on_a_view_reading_no_tenant_relation_is_stale(tmp_path: Path) -> None:
    sql = (
        "-- confiture:tenant-global shared formats\n"
        "CREATE VIEW app.v_formats AS SELECT f.label FROM catalog.tb_paper_format f;\n"
    )
    message = _message(tmp_path, sql)
    assert "stale" in message
    assert "reads no tenant relation" in message


def test_a_declaration_on_a_view_publishing_the_discriminator_contradicts(
    tmp_path: Path,
) -> None:
    sql = (
        "-- confiture:tenant-global every order\n"
        "CREATE VIEW app.v_order AS SELECT o.tenant_id, o.id FROM app.tb_order o;\n"
    )
    assert "yet publishes tenant_id" in _message(tmp_path, sql)


def test_a_materialized_view_can_be_declared_global(tmp_path: Path) -> None:
    sql = (
        "-- confiture:tenant-global nightly platform totals\n"
        "CREATE MATERIALIZED VIEW app.mv_total AS SELECT sum(total) AS t FROM app.tb_order;\n"
    )
    assert _objects(tmp_path, sql) == []


# -- what the tracer cannot read is said, never passed --------------------------


def test_a_set_returning_function_in_from_is_unread(tmp_path: Path) -> None:
    sql = (
        "CREATE VIEW app.v_order AS SELECT tenant_id, o.id "
        "FROM generate_series(1, 3) g JOIN app.tb_order o ON true;"
    )
    message = _message(tmp_path, sql)
    assert "could not be traced" in message
    assert "set-returning function in FROM" in message


def test_a_star_over_a_set_returning_function_is_unread(tmp_path: Path) -> None:
    sql = (
        "CREATE VIEW app.v_order AS SELECT g.*, o.id "
        "FROM app.tb_order o, LATERAL jsonb_to_record('{}') AS g (tenant_id uuid);"
    )
    assert "could not be traced" in _message(tmp_path, sql)


def test_a_relation_the_model_lacks_is_unread(tmp_path: Path) -> None:
    sql = (
        "CREATE VIEW app.v_order AS SELECT x.tenant_id, o.id "
        "FROM app.tb_order o JOIN app.tb_elsewhere x ON x.id = o.id;"
    )
    message = _message(tmp_path, sql)
    assert "could not be traced" in message
    assert "app.tb_elsewhere is not in the model" in message


def test_a_view_that_reads_itself_is_unread_not_a_crash(tmp_path: Path) -> None:
    sql = (
        "CREATE VIEW app.v_a AS SELECT o.id FROM app.tb_order o;\n"
        "CREATE OR REPLACE VIEW app.v_a AS SELECT a.tenant_id FROM app.v_a a "
        "JOIN app.tb_order o ON o.id = a.tenant_id;\n"
    )
    findings, _ = _findings(tmp_path, sql)
    assert findings


# -- the root's key is what the discriminator references ------------------------

_SURROGATE_ROOT = """
CREATE SCHEMA tenancy;
CREATE TABLE tenancy.tb_account (pk_account bigint PRIMARY KEY, id uuid NOT NULL UNIQUE);
CREATE TABLE tenancy.tb_note (id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenancy.tb_account (id));
"""
_SURROGATE = "tenancy:\n  root: tenancy.tb_account\n"


def test_the_root_key_is_the_column_the_discriminator_references(tmp_path: Path) -> None:
    sql = _SURROGATE_ROOT + (
        "CREATE VIEW tenancy.v_account AS SELECT a.id AS tenant_id FROM tenancy.tb_account a;\n"
    )
    findings, _ = _findings(tmp_path, sql, project_yaml=_SURROGATE)
    assert findings == []


def test_the_roots_surrogate_key_is_not_the_tenant_id(tmp_path: Path) -> None:
    sql = _SURROGATE_ROOT + (
        "CREATE VIEW tenancy.v_account AS "
        "SELECT a.pk_account AS tenant_id FROM tenancy.tb_account a;\n"
    )
    (finding,) = _findings(tmp_path, sql, project_yaml=_SURROGATE)[0]
    assert "tenancy.tb_account.pk_account" in finding.message
    assert "the tenant id is tenancy.tb_account.id" in finding.message


def test_without_a_reference_the_roots_primary_key_is_the_tenant_id(tmp_path: Path) -> None:
    sql = (
        "CREATE SCHEMA tenancy;\n"
        "CREATE TABLE tenancy.tb_account (pk_account bigint PRIMARY KEY, id uuid UNIQUE);\n"
        "CREATE VIEW tenancy.v_account AS SELECT a.id AS tenant_id FROM tenancy.tb_account a;\n"
    )
    (finding,) = _findings(tmp_path, sql, project_yaml=_SURROGATE)[0]
    assert "the tenant id is tenancy.tb_account.pk_account" in finding.message
    assert "references" in finding.message


def test_discriminators_referencing_different_root_columns_decide_no_tenant_id(
    tmp_path: Path,
) -> None:
    sql = _SURROGATE_ROOT + (
        "CREATE TABLE tenancy.tb_tag (id uuid PRIMARY KEY,\n"
        "  tenant_id bigint NOT NULL REFERENCES tenancy.tb_account (pk_account));\n"
        "CREATE VIEW tenancy.v_account AS SELECT a.id AS tenant_id FROM tenancy.tb_account a;\n"
    )
    (finding,) = _findings(tmp_path, sql, project_yaml=_SURROGATE)[0]
    assert "undecided" in finding.message


def test_a_view_calling_a_routine_whose_body_was_not_read_is_unread(tmp_path: Path) -> None:
    sql = (
        "CREATE FUNCTION app.f_opaque(p uuid) RETURNS int LANGUAGE plpgsql AS $$\n"
        "BEGIN RETURN (SELECT count(*) FROM app.tb_order WHERE id = p; END $$;\n"
        "CREATE VIEW catalog_like AS SELECT f.label, app.f_opaque(f.id) AS n "
        "FROM catalog.tb_paper_format f;\n"
    )
    message = _message(tmp_path, sql)
    assert "could not be traced" in message
    assert "app.f_opaque" in message


def test_a_table_defined_twice_is_read_by_its_first_definition(tmp_path: Path) -> None:
    sql = (
        "CREATE TABLE app.tb_twice (id uuid PRIMARY KEY, tenant_id uuid NOT NULL);\n"
        "CREATE TABLE app.tb_twice (id uuid PRIMARY KEY);\n"
        "CREATE VIEW app.v_twice AS SELECT t.id FROM app.tb_twice t;\n"
    )
    assert _objects(tmp_path, sql) == ["app.v_twice"]
