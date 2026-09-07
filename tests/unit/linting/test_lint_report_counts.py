"""``lint --format json`` reports how many tables and columns it read.

The payload carried ``tables_checked: 0`` and ``columns_checked: 0`` for every
schema — the converter hard-coded them because the linter "did not track"
them. It reads an inventory now, so the counts are what it inventoried.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.core.linting.schema_linter import LintConfig, SchemaLinter

SQL = (
    "CREATE TABLE tb_a (id int PRIMARY KEY, name text);\nCOMMENT ON TABLE tb_a IS 'a';\n"
    "CREATE TABLE tb_b (id int PRIMARY KEY);\nCOMMENT ON TABLE tb_b IS 'b';\n"
    "CREATE VIEW v AS SELECT 1 AS a;\nCOMMENT ON VIEW v IS 'v';\n"
)


def test_the_core_report_counts_tables_and_columns() -> None:
    report = SchemaLinter(config=LintConfig(enabled=True)).lint(schema=SQL)
    assert report.tables_checked == 2
    assert report.columns_checked == 3


@pytest.fixture
def project(tmp_path: Path) -> Iterator[Path]:
    (tmp_path / "db" / "schema").mkdir(parents=True)
    (tmp_path / "db" / "migrations").mkdir(parents=True)
    (tmp_path / "db" / "environments").mkdir(parents=True)
    (tmp_path / "db" / "environments" / "local.yaml").write_text(
        "database_url: postgresql://localhost/test\ninclude_dirs:\n  - path: db/schema\n"
    )
    (tmp_path / "db" / "schema" / "010.sql").write_text(SQL)
    old_cwd = Path.cwd()
    os.chdir(tmp_path)
    try:
        yield tmp_path
    finally:
        os.chdir(old_cwd)


def test_the_json_payload_carries_the_counts(project: Path) -> None:
    result = CliRunner().invoke(app, ["lint", "--format", "json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["tables_checked"] == 2
    assert payload["columns_checked"] == 3
