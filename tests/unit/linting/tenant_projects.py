"""A tenant-scoped project on disk, linted, and the findings of one ``tenant`` rule.

Every ``tenant`` rule reads ``db/project.yaml``'s ``tenancy:`` block, so each test
needs a project directory holding one; this writes it and runs one switch.
"""

from __future__ import annotations

from pathlib import Path

from confiture.core.linting.schema_linter import (
    LintConfig,
    LintReport,
    LintViolation,
    SchemaLinter,
)

#: The table of tenants and the schemas the tests put their tables in.
ROOT = """
CREATE SCHEMA management;
CREATE SCHEMA app;
CREATE SCHEMA catalog;
CREATE TABLE management.tb_organization (id uuid PRIMARY KEY, name text NOT NULL);
"""

#: ``db/project.yaml``: ``app`` is tenant-scoped, ``catalog`` is global.
TENANCY = "tenancy:\n  root: management.tb_organization\n  global_schemas: [catalog]\n"

#: A column that makes a table tenant-scoped, written inline.
SCOPED = "tenant_id uuid NOT NULL REFERENCES management.tb_organization (id)"


def project(tmp_path: Path, project_yaml: str | None = TENANCY) -> Path:
    """A project whose one environment reads ``db/schema``, with *project_yaml*."""
    (tmp_path / "db" / "schema").mkdir(parents=True)
    (tmp_path / "db" / "environments").mkdir()
    (tmp_path / "db" / "environments" / "local.yaml").write_text(
        "name: local\ndatabase_url: postgresql://localhost:1/app\n"
        f"include_dirs:\n  - {tmp_path / 'db' / 'schema'}\n"
    )
    if project_yaml is not None:
        (tmp_path / "db" / "project.yaml").write_text(project_yaml)
    return tmp_path


def findings(
    tmp_path: Path,
    sql: str,
    code: str,
    switch: str,
    project_yaml: str | None = TENANCY,
) -> tuple[list[LintViolation], LintReport]:
    """Lint ``ROOT + sql`` with the one *switch* on; *code*'s findings and the report."""
    linter = SchemaLinter(
        env="local",
        project_dir=project(tmp_path, project_yaml),
        config=LintConfig(**{switch: True}),
    )
    report = linter.lint(ROOT + sql)
    return [
        v for v in (*report.errors, *report.warnings, *report.info) if v.rule_id == code
    ], report
