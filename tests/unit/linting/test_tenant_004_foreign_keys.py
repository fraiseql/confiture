"""``tenant_004``: a foreign key cannot cross tenants.

A foreign key between two tenant tables carries the discriminator on both sides,
at the same position — ``(tenant_id, fk_order) REFERENCES tb_order (tenant_id, id)``
— so PostgreSQL itself refuses a row that points at another tenant's row. A global
table cannot point at a tenant's row at all; a tenant table may point at a global
one. A table whose tenancy nobody decided is ``tenant_002``'s finding, not judged here.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.unit.linting.tenant_projects import SCOPED, TENANCY, findings

from confiture.core.linting.rule_registry import LINT_RULES, resolve_selection

_ORDER = f"CREATE TABLE app.tb_order (id uuid NOT NULL, {SCOPED}, PRIMARY KEY (tenant_id, id));\n"


def _fk(tmp_path: Path, sql: str, project_yaml: str | None = TENANCY):
    return findings(tmp_path, sql, "tenant_004", "check_tenant_foreign_keys", project_yaml)


def test_a_single_column_fk_between_tenant_tables_is_reported(tmp_path: Path) -> None:
    found, _ = _fk(
        tmp_path,
        _ORDER + f"CREATE TABLE app.tb_order_line (id uuid PRIMARY KEY, {SCOPED},\n"
        "  fk_order uuid NOT NULL REFERENCES app.tb_order (id));\n",
    )

    (finding,) = found
    assert finding.object_name == "app.tb_order_line"
    assert "app.tb_order" in finding.message
    assert "(tenant_id, fk_order) REFERENCES app.tb_order (tenant_id, id)" in (
        finding.suggested_fix or ""
    )


def test_a_composite_fk_carrying_the_discriminator_is_clean(tmp_path: Path) -> None:
    found, _ = _fk(
        tmp_path,
        _ORDER + f"CREATE TABLE app.tb_order_line (id uuid PRIMARY KEY, {SCOPED},\n"
        "  fk_order uuid NOT NULL,\n"
        "  FOREIGN KEY (tenant_id, fk_order) REFERENCES app.tb_order (tenant_id, id));\n",
    )

    assert found == []


def test_the_discriminator_must_sit_at_the_same_position_on_both_sides(tmp_path: Path) -> None:
    found, _ = _fk(
        tmp_path,
        f"CREATE TABLE app.tb_order (id uuid NOT NULL, {SCOPED}, UNIQUE (id, tenant_id),"
        " PRIMARY KEY (tenant_id, id));\n"
        f"CREATE TABLE app.tb_order_line (id uuid PRIMARY KEY, {SCOPED}, fk_order uuid,\n"
        "  FOREIGN KEY (tenant_id, fk_order) REFERENCES app.tb_order (id, tenant_id));\n",
    )

    assert len(found) == 1


def test_an_fk_naming_no_columns_references_the_target_primary_key(tmp_path: Path) -> None:
    clean, _ = _fk(
        tmp_path / "composite",
        _ORDER + f"CREATE TABLE app.tb_order_line (id uuid PRIMARY KEY, {SCOPED}, fk_order uuid,\n"
        "  FOREIGN KEY (tenant_id, fk_order) REFERENCES app.tb_order);\n",
    )
    crossing, _ = _fk(
        tmp_path / "single",
        f"CREATE TABLE app.tb_order (id uuid PRIMARY KEY, {SCOPED});\n"
        f"CREATE TABLE app.tb_order_line (id uuid PRIMARY KEY, {SCOPED},\n"
        "  fk_order uuid REFERENCES app.tb_order);\n",
    )

    assert clean == []
    (finding,) = crossing
    assert "app.tb_order needs PRIMARY KEY (tenant_id, id) or UNIQUE (tenant_id, id)" in (
        finding.suggested_fix or ""
    )


def test_the_hint_omits_the_target_key_when_it_already_exists(tmp_path: Path) -> None:
    found, _ = _fk(
        tmp_path,
        _ORDER + f"CREATE TABLE app.tb_order_line (id uuid PRIMARY KEY, {SCOPED},\n"
        "  fk_order uuid REFERENCES app.tb_order (id));\n",
    )

    (finding,) = found
    assert "needs" not in (finding.suggested_fix or "")


def test_the_discriminator_referencing_the_root_is_not_a_crossing(tmp_path: Path) -> None:
    found, _ = _fk(tmp_path, _ORDER)

    assert found == []


def test_another_column_referencing_the_root_points_at_another_tenant(tmp_path: Path) -> None:
    found, _ = _fk(
        tmp_path,
        f"CREATE TABLE app.tb_partner (id uuid PRIMARY KEY, {SCOPED},\n"
        "  fk_partner_org uuid REFERENCES management.tb_organization (id));\n",
    )

    (finding,) = found
    assert "fk_partner_org" in finding.message


# -- the root's tenant id is the column the discriminator references --------------

_SURROGATE_ROOT = (
    "CREATE SCHEMA tenancy;\n"
    "CREATE TABLE tenancy.tb_account (id bigint PRIMARY KEY, tenant_uuid uuid NOT NULL UNIQUE);\n"
    "CREATE TABLE tenancy.tb_note (id uuid PRIMARY KEY,\n"
    "  tenant_id uuid NOT NULL REFERENCES tenancy.tb_account (tenant_uuid)"
)
_SURROGATE = "tenancy:\n  root: tenancy.tb_account\n"


def test_the_discriminator_referencing_a_roots_unique_tenant_id_is_clean(tmp_path: Path) -> None:
    """A root with a surrogate primary key publishes its tenant id as a UNIQUE column."""
    found, _ = _fk(tmp_path, _SURROGATE_ROOT + ");\n", _SURROGATE)

    assert found == []


def test_another_column_referencing_the_roots_tenant_id_is_reported(tmp_path: Path) -> None:
    found, _ = _fk(
        tmp_path,
        _SURROGATE_ROOT + ",\n  fk_partner uuid REFERENCES tenancy.tb_account (tenant_uuid));\n",
        _SURROGATE,
    )

    (finding,) = found
    assert "fk_partner" in finding.message


def test_a_column_referencing_the_roots_surrogate_key_is_reported(tmp_path: Path) -> None:
    found, _ = _fk(
        tmp_path,
        _SURROGATE_ROOT + ",\n  fk_owner bigint REFERENCES tenancy.tb_account (id));\n",
        _SURROGATE,
    )

    (finding,) = found
    assert "fk_owner" in finding.message


def test_a_global_table_referencing_a_tenant_table_is_reported(tmp_path: Path) -> None:
    found, _ = _fk(
        tmp_path,
        _ORDER + "CREATE TABLE catalog.tb_sample (id int PRIMARY KEY,\n"
        "  fk_order uuid, fk_tenant uuid,\n"
        "  FOREIGN KEY (fk_tenant, fk_order) REFERENCES app.tb_order (tenant_id, id));\n",
    )

    (finding,) = found
    assert finding.object_name == "catalog.tb_sample"
    assert "global" in finding.message


def test_a_tenant_table_referencing_a_global_table_is_clean(tmp_path: Path) -> None:
    found, _ = _fk(
        tmp_path,
        "CREATE TABLE catalog.tb_paper_format (id int PRIMARY KEY);\n"
        f"CREATE TABLE app.tb_order (id uuid PRIMARY KEY, {SCOPED},\n"
        "  fk_paper_format int REFERENCES catalog.tb_paper_format (id));\n",
    )

    assert found == []


def test_an_fk_to_or_from_an_undecided_table_is_not_judged(tmp_path: Path) -> None:
    found, _ = _fk(
        tmp_path,
        _ORDER + "CREATE TABLE app.tb_note (id uuid PRIMARY KEY,\n"
        "  fk_order uuid REFERENCES app.tb_order (id));\n"
        f"CREATE TABLE app.tb_order_note (id uuid PRIMARY KEY, {SCOPED},\n"
        "  fk_note uuid REFERENCES app.tb_note (id));\n",
    )

    assert found == []


def test_an_fk_added_by_alter_table_is_judged(tmp_path: Path) -> None:
    found, _ = _fk(
        tmp_path,
        _ORDER + f"CREATE TABLE app.tb_order_line (id uuid PRIMARY KEY, {SCOPED}, fk_order uuid);\n"
        "ALTER TABLE app.tb_order_line ADD CONSTRAINT fk FOREIGN KEY (fk_order)"
        " REFERENCES app.tb_order (id);\n",
    )

    assert len(found) == 1


def test_without_a_tenancy_block_the_rule_says_it_did_not_run(tmp_path: Path) -> None:
    found, report = _fk(tmp_path, _ORDER, project_yaml=None)

    assert found == []
    assert [(s.code, s.state) for s in report.skipped] == [("tenant_004", "skipped")]


def test_tenant_004_is_on_when_the_project_declares_tenancy() -> None:
    (rule,) = [r for r in LINT_RULES if r.code == "tenant_004"]

    assert (rule.family, rule.severity, rule.default_on, rule.enabled_by) == (
        "tenant",
        "warning",
        False,
        "tenancy",
    )
    assert "tenant_004" in resolve_selection(None, (), declared=frozenset({"tenancy"}))


@pytest.mark.parametrize("ignored", [["tenant_004"], ["tenant"]])
def test_ignore_still_turns_it_off(ignored: list[str]) -> None:
    assert "tenant_004" not in resolve_selection(None, ignored, declared=frozenset({"tenancy"}))
