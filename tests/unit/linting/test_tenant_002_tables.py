"""``tenant_002``: every table carries the tenant discriminator, or is declared global.

Tenancy is a column, never an inference: a table is tenant-scoped because it has
``tenant_id NOT NULL`` referencing the table of tenants, or global because
``db/project.yaml`` names its schema global or its ``CREATE`` says so with a
reason. A table that is neither is a decision nobody made — the finding.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.unit.linting.tenant_projects import TENANCY, findings

from confiture.core.linting.rule_registry import LINT_RULES, resolve_selection


def _findings(tmp_path: Path, sql: str, project_yaml: str | None = TENANCY):
    return findings(tmp_path, sql, "tenant_002", "check_tenant_tables", project_yaml)


def test_a_table_carrying_the_discriminator_is_tenant_scoped(tmp_path: Path) -> None:
    findings, _ = _findings(
        tmp_path,
        "CREATE TABLE app.tb_order (id uuid PRIMARY KEY, "
        "tenant_id uuid NOT NULL REFERENCES management.tb_organization (id));\n",
    )

    assert findings == []


def test_a_table_that_is_neither_scoped_nor_global_is_reported(tmp_path: Path) -> None:
    findings, _ = _findings(tmp_path, "CREATE TABLE app.tb_order_line (id uuid PRIMARY KEY);\n")

    (finding,) = findings
    assert finding.object_name == "app.tb_order_line"
    assert "tenant_id" in finding.message
    assert "confiture:tenant-global" in (finding.suggested_fix or "")


def test_a_nullable_discriminator_is_reported_at_the_column(tmp_path: Path) -> None:
    findings, _ = _findings(
        tmp_path,
        "CREATE TABLE app.tb_order (id uuid PRIMARY KEY,\n"
        "  tenant_id uuid REFERENCES management.tb_organization (id));\n",
    )

    (finding,) = findings
    assert "NOT NULL" in finding.message
    assert finding.line_number == 7


def test_a_discriminator_that_does_not_reference_the_root_is_reported(tmp_path: Path) -> None:
    findings, _ = _findings(
        tmp_path, "CREATE TABLE app.tb_order (id uuid PRIMARY KEY, tenant_id uuid NOT NULL);\n"
    )

    (finding,) = findings
    assert "management.tb_organization" in finding.message


def test_a_table_in_a_global_schema_is_global(tmp_path: Path) -> None:
    findings, _ = _findings(
        tmp_path, "CREATE TABLE catalog.tb_paper_format (id int PRIMARY KEY);\n"
    )

    assert findings == []


def test_the_root_carries_no_discriminator_of_its_own(tmp_path: Path) -> None:
    findings, _ = _findings(tmp_path, "")

    assert findings == []


def test_a_table_declared_global_with_a_reason_is_global(tmp_path: Path) -> None:
    findings, _ = _findings(
        tmp_path,
        "-- confiture:tenant-global shared country list\n"
        "CREATE TABLE app.tb_country (code text PRIMARY KEY);\n",
    )

    assert findings == []


def test_a_global_declaration_needs_a_reason(tmp_path: Path) -> None:
    findings, _ = _findings(
        tmp_path,
        "-- confiture:tenant-global\nCREATE TABLE app.tb_country (code text PRIMARY KEY);\n",
    )

    (finding,) = findings
    assert "reason" in finding.message


def test_a_table_declared_global_that_carries_the_discriminator_is_a_contradiction(
    tmp_path: Path,
) -> None:
    findings, _ = _findings(
        tmp_path,
        "-- confiture:tenant-global shared list\n"
        "CREATE TABLE app.tb_country (code text PRIMARY KEY, "
        "tenant_id uuid NOT NULL REFERENCES management.tb_organization (id));\n",
    )

    (finding,) = findings
    assert "declared global" in finding.message


def test_a_discriminator_added_by_a_later_alter_counts(tmp_path: Path) -> None:
    findings, _ = _findings(
        tmp_path,
        "CREATE TABLE app.tb_order (id uuid PRIMARY KEY);\n"
        "ALTER TABLE app.tb_order ADD COLUMN tenant_id uuid NOT NULL "
        "REFERENCES management.tb_organization (id);\n",
    )

    assert findings == []


def test_a_partition_follows_its_parent(tmp_path: Path) -> None:
    findings, _ = _findings(
        tmp_path,
        "CREATE TABLE app.tb_event (id uuid, at date, "
        "tenant_id uuid NOT NULL REFERENCES management.tb_organization (id)) PARTITION BY RANGE (at);\n"
        "CREATE TABLE app.tb_event_2026 PARTITION OF app.tb_event "
        "FOR VALUES FROM ('2026-01-01') TO ('2027-01-01');\n",
    )

    assert findings == []


def test_without_a_tenancy_block_the_rule_says_it_did_not_run(tmp_path: Path) -> None:
    findings, report = _findings(
        tmp_path, "CREATE TABLE app.tb_order_line (id uuid PRIMARY KEY);\n", project_yaml=None
    )

    assert findings == []
    assert [(s.code, s.state) for s in report.skipped] == [("tenant_002", "skipped")]
    assert "db/project.yaml" in report.skipped[0].reason


def test_tenant_002_is_on_when_the_project_declares_tenancy() -> None:
    (rule,) = [r for r in LINT_RULES if r.code == "tenant_002"]

    assert (rule.family, rule.severity, rule.default_on, rule.enabled_by) == (
        "tenant",
        "warning",
        False,
        "tenancy",
    )
    assert "tenant_002" in resolve_selection(None, (), declared=frozenset({"tenancy"}))
    assert "tenant_002" not in resolve_selection(None, ())


@pytest.mark.parametrize("ignored", [["tenant_002"], ["tenant"]])
def test_ignore_still_turns_it_off(ignored: list[str]) -> None:
    assert "tenant_002" not in resolve_selection(None, ignored, declared=frozenset({"tenancy"}))


def test_a_table_defined_twice_is_reported_once(tmp_path: Path) -> None:
    """``build_001`` reports the duplicate; tenancy is a property of the object."""
    findings, _ = _findings(
        tmp_path,
        "CREATE TABLE IF NOT EXISTS app.tb_order_line (id uuid PRIMARY KEY);\n"
        "CREATE TABLE IF NOT EXISTS app.tb_order_line (id uuid PRIMARY KEY);\n",
    )

    assert [f.object_name for f in findings] == ["app.tb_order_line"]


def test_discriminators_that_reference_different_root_columns_are_reported(
    tmp_path: Path,
) -> None:
    """Which root column is the tenant id is then undecided, and every rule that
    needs it stops judging; the disagreement itself is the finding, on the root."""
    findings, _ = _findings(
        tmp_path,
        "ALTER TABLE management.tb_organization ADD COLUMN code text NOT NULL UNIQUE;\n"
        "CREATE TABLE app.tb_order (id uuid PRIMARY KEY, "
        "tenant_id uuid NOT NULL REFERENCES management.tb_organization (id));\n"
        "CREATE TABLE app.tb_invoice (id uuid PRIMARY KEY, "
        "tenant_id text NOT NULL REFERENCES management.tb_organization (code));\n",
    )

    (finding,) = findings
    assert finding.object_name == "management.tb_organization"
    assert "code" in finding.message
    assert "id" in finding.message
