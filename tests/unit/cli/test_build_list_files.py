"""``confiture build --list-files``: what the build would read, and why.

The surface a project diffs across an upgrade — it prints the selection and
builds nothing.
"""

from __future__ import annotations

import json
from pathlib import Path

from tests.unit.test_build_selection_is_stable import GOLDEN_ORDER, golden_project
from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()


def _invoke(project: Path, *extra: str):
    return runner.invoke(
        app,
        ["build", "--env", "local", "--project-dir", str(project), "--list-files", *extra],
    )


def test_list_files_prints_one_line_per_file_with_its_provenance(tmp_path: Path) -> None:
    """Every selected file names the entry, the order and the pattern that found it."""
    project = golden_project(tmp_path)

    result = _invoke(project)

    assert result.exit_code == 0
    for relative in GOLDEN_ORDER:
        assert relative in result.stdout
    assert "order 0" in result.stdout
    assert "**/*.sql" in result.stdout


def test_list_files_builds_nothing(tmp_path: Path) -> None:
    """No schema file is written, whatever ``--output`` says."""
    project = golden_project(tmp_path)
    output = tmp_path / "schema.sql"

    result = _invoke(project, "--output", str(output))

    assert result.exit_code == 0
    assert not output.exists()
    assert not (project / "db" / "generated").exists()


def test_list_files_json_carries_the_selection_in_build_order(tmp_path: Path) -> None:
    """The JSON payload is the same selection, in the same order."""
    project = golden_project(tmp_path)

    result = _invoke(project, "--format", "json")

    payload = json.loads(result.stdout)
    assert payload["env"] == "local"
    assert payload["total"] == len(GOLDEN_ORDER)
    assert [entry["path"] for entry in payload["files"]] == GOLDEN_ORDER
    assert payload["files"][0]["entry"] == "db/functions"
    assert payload["files"][0]["order"] == 0
    assert payload["files"][0]["pattern"] == "**/*.sql"
    assert payload["patterns"] == []
