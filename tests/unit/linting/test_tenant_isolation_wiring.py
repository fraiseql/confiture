"""SchemaLinter ↔ TenantIsolationRule wiring (Phase 04b, cluster D).

The tenant-isolation rule existed but was never reachable from `confiture
lint` — no config flag invoked it. These tests pin the wiring: the check is
opt-in (default off, so existing lint output is unchanged) and, when enabled,
surfaces tenant_001 violations through the normal LintReport.
"""

from __future__ import annotations

from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.core.linting.schema_linter import LintConfig, SchemaLinter

# A multi-tenant schema whose function INSERTs the tenant FK-less row: the view
# derives tenant_id from tb_item.fk_org, but fn_create_item omits fk_org.
_TENANT_SCHEMA = """
CREATE VIEW v_item AS
SELECT i.id, i.name, o.id AS tenant_id
FROM tb_item i
JOIN tv_organization o ON i.fk_org = o.pk_organization;

CREATE FUNCTION fn_create_item() RETURNS VOID AS $$
BEGIN
    INSERT INTO tb_item (id, name) VALUES (1, 'test');
END;
$$ LANGUAGE plpgsql;
"""


def _tenant_ids(report) -> list[str]:
    return [v.rule_id for v in (*report.errors, *report.warnings, *report.info)]


def test_check_tenant_isolation_is_opt_in() -> None:
    """The flag defaults off and the default lint run raises no tenant_001."""
    assert LintConfig().check_tenant_isolation is False
    report = SchemaLinter().lint(schema=_TENANT_SCHEMA)
    assert "tenant_001" not in _tenant_ids(report)


def test_tenant_isolation_fires_when_enabled() -> None:
    """With the flag on, the missing-FK INSERT is reported as tenant_001."""
    config = LintConfig(check_tenant_isolation=True)
    report = SchemaLinter(config=config).lint(schema=_TENANT_SCHEMA)
    tenant = [
        v for v in (*report.errors, *report.warnings, *report.info) if v.rule_id == "tenant_001"
    ]
    assert tenant, "expected a tenant_001 violation when check_tenant_isolation=True"
    assert "fk_org" in tenant[0].message


def test_lint_cli_exposes_the_flag() -> None:
    """`confiture lint --help` advertises --check-tenant-isolation (CLI-reachable)."""
    result = CliRunner().invoke(app, ["lint", "--help"])
    assert result.exit_code == 0
    assert "--check-tenant-isolation" in result.output
