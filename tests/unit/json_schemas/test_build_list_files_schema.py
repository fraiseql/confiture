"""Validate ``confiture build --list-files --format json`` against its schema."""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator
from typer.testing import CliRunner

from confiture.cli.main import app
from tests.unit.test_build_selection_is_stable import golden_project

SCHEMA_FILE = "build-list-files.schema.json"


def _load(schemas_dir: Path, name: str) -> dict:
    return json.loads((schemas_dir / name).read_text())


def _payload(project: Path) -> dict:
    result = CliRunner().invoke(
        app,
        [
            "build",
            "--env",
            "local",
            "--project-dir",
            str(project),
            "--list-files",
            "--format",
            "json",
        ],
    )
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


def test_list_files_payload_validates_against_schema(tmp_path, schemas_dir, schema_registry):
    schema = _load(schemas_dir, SCHEMA_FILE)
    Draft202012Validator(schema, registry=schema_registry).validate(
        _payload(golden_project(tmp_path))
    )


def test_schema_is_valid_draft_2020_12(schemas_dir):
    Draft202012Validator.check_schema(_load(schemas_dir, SCHEMA_FILE))
