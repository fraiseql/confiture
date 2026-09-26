"""SchemaLinter ↔ ``tenant_001`` wiring.

``LintConfig(check_tenant_isolation=True)`` is the library switch of
``tenant_001`` and ``--check-tenant-isolation`` its CLI alias; both keep their
names while the rule asks the family's question — does an ``INSERT`` into a
tenant table supply the discriminator.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests.unit.linting.tenant_projects import SCOPED, findings
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.core.linting.schema_linter import LintConfig, SchemaLinter

_TENANT_SCHEMA = f"""
CREATE TABLE app.tb_item (id uuid PRIMARY KEY, name text, {SCOPED});

CREATE FUNCTION app.fn_create_item() RETURNS void AS $$
BEGIN
    INSERT INTO app.tb_item (id, name) VALUES (gen_random_uuid(), 'test');
END;
$$ LANGUAGE plpgsql;
"""


def test_check_tenant_isolation_is_opt_in() -> None:
    """The switch defaults off and the default library run raises no tenant_001."""
    assert LintConfig().check_tenant_isolation is False
    report = SchemaLinter().lint(schema=_TENANT_SCHEMA)
    assert "tenant_001" not in [v.rule_id for v in (*report.errors, *report.warnings, *report.info)]


def test_the_switch_runs_the_rule(tmp_path: Path) -> None:
    found, _ = findings(tmp_path, _TENANT_SCHEMA, "tenant_001", "check_tenant_isolation")

    (finding,) = found
    assert "tenant_id" in finding.message


def test_lint_cli_exposes_the_flag() -> None:
    """`confiture lint --help` advertises --check-tenant-isolation (CLI-reachable)."""
    result = CliRunner().invoke(app, ["lint", "--help"])
    assert result.exit_code == 0
    # Strip ANSI: CI (FORCE_COLOR) renders colored help that splits the flag token.
    assert "--check-tenant-isolation" in re.sub(r"\x1b\[[0-9;]*m", "", result.output)
