"""``confiture build`` reports the size of the file it wrote, in bytes (#429).

It printed ``len(schema)`` — characters. A schema with any non-ASCII text (an
accented COMMENT, a translated label in a seed) is longer on disk than that, so
the figure matched neither ``ls`` nor ``wc -c`` nor a CI step comparing bundles.
"""

from __future__ import annotations

import json
from pathlib import Path

from tests.unit.test_build_selection_is_stable import golden_project
from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()


def _project(tmp_path: Path) -> Path:
    project = golden_project(tmp_path)
    (project / "db/schema/10_tables/30_comments.sql").write_text(
        "COMMENT ON TABLE orders IS 'Commandes passées — données réelles, déjà vérifiées';\n",
        encoding="utf-8",
    )
    return project


def _build(project: Path, output: Path, *extra: str):
    return runner.invoke(
        app,
        [
            "build",
            "--env",
            "local",
            "--project-dir",
            str(project),
            "--output",
            str(output),
            *extra,
        ],
    )


def test_json_reports_the_bytes_on_disk(tmp_path: Path) -> None:
    project = _project(tmp_path)
    output = tmp_path / "built.sql"
    report = tmp_path / "report.json"

    result = _build(project, output, "--format", "json", "--report", str(report))

    assert result.exit_code == 0, result.output
    payload = json.loads(report.read_text())
    assert payload["schema_size_bytes"] == output.stat().st_size


def test_text_prints_the_bytes_on_disk(tmp_path: Path) -> None:
    project = _project(tmp_path)
    output = tmp_path / "built.sql"

    result = _build(project, output)

    assert result.exit_code == 0, result.output
    assert f"Size: {output.stat().st_size:,} bytes" in result.output
