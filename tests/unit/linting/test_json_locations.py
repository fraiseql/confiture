"""Every ``confiture lint`` finding reports the file and the line it came from.

`LintViolation` has carried `file_path` and `line_number` since the linter was
written; `_convert_linter_report` copied five fields and dropped both, so
`lint --format json` described *what* was wrong and never *where*. Three of the
rules this campaign adds are worth nothing without a location, so the plumbing
is pinned here: the model carries the fields, the JSON payload publishes them,
the CSV writer emits them, and an inventory-backed finding names its own source
file rather than an offset into the concatenated build.
"""

from __future__ import annotations

import csv
import io
import json
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()

_FIRST = """CREATE SCHEMA IF NOT EXISTS app;

CREATE TABLE app.tb_widget (
    id BIGINT PRIMARY KEY,
    userPassword TEXT
);
"""

_SECOND = """CREATE TABLE app.tb_gadget (
    id BIGINT
);
"""


@pytest.fixture
def two_file_project(tmp_path: Path) -> Iterator[Path]:
    """Two schema files, so a finding's file is a real answer and not a constant."""
    (tmp_path / "db" / "schema").mkdir(parents=True)
    (tmp_path / "db" / "environments").mkdir(parents=True)
    (tmp_path / "db" / "environments" / "local.yaml").write_text(
        "database_url: postgresql://localhost/test\ninclude_dirs:\n  - path: db/schema\n"
    )
    (tmp_path / "db" / "schema" / "010_widget.sql").write_text(_FIRST)
    (tmp_path / "db" / "schema" / "020_gadget.sql").write_text(_SECOND)

    old_cwd = Path.cwd()
    os.chdir(tmp_path)
    try:
        yield tmp_path
    finally:
        os.chdir(old_cwd)


def _lint_json(*args: str) -> dict:
    result = runner.invoke(app, ["lint", "--format", "json", *args])
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


def test_every_json_finding_carries_a_file_and_a_line(two_file_project: Path) -> None:
    items = _lint_json()["violations"]["items"]

    assert items, "fixture produced no findings"
    for item in items:
        assert "file" in item, f"{item['rule_id']} has no file key"
        assert "line" in item, f"{item['rule_id']} has no line key"


def test_a_finding_names_the_file_that_defines_the_object(two_file_project: Path) -> None:
    by_location = {
        (item["rule_id"], item["location"]): item for item in _lint_json()["violations"]["items"]
    }

    gadget = by_location[("pk_001", "app.tb_gadget")]
    assert gadget["file"] == "db/schema/020_gadget.sql"
    assert gadget["line"] == 1

    widget = by_location[("doc_001", "app.tb_widget")]
    assert widget["file"] == "db/schema/010_widget.sql"
    assert widget["line"] == 3


def test_a_column_finding_names_its_table_s_file(two_file_project: Path) -> None:
    items = _lint_json()["violations"]["items"]

    column = next(item for item in items if item["rule_id"] == "naming_002")
    assert column["file"] == "db/schema/010_widget.sql"
    assert column["line"] == 5


def test_a_finding_with_no_location_emits_null_not_empty_string() -> None:
    """A whole-string lint knows no file: the keys are present and ``null``."""
    from confiture.cli.helpers import _convert_linter_report
    from confiture.core.linting.schema_linter import LintReport, LintViolation, RuleSeverity

    linter_report = LintReport(
        warnings=[
            LintViolation(
                rule_id="naming_001",
                rule_name="Table Naming Convention",
                severity=RuleSeverity.WARNING,
                object_type="table",
                object_name="BadName",
                message="nope",
            )
        ]
    )

    item = _convert_linter_report(linter_report, schema_name="local").to_dict()["violations"][
        "items"
    ][0]

    assert item["file"] is None
    assert item["line"] is None


def test_csv_output_carries_the_location_columns(two_file_project: Path) -> None:
    result = runner.invoke(app, ["lint", "--format", "csv"])
    assert result.exit_code == 0, result.output

    rows = list(csv.DictReader(io.StringIO(result.stdout)))
    assert rows, "fixture produced no findings"
    assert "file" in rows[0] and "line" in rows[0]
    assert any(row["file"] == "db/schema/020_gadget.sql" for row in rows)
