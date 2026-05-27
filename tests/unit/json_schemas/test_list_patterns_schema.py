"""Validate ``migrate validate --list-patterns --format json`` output against its schema."""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator
from typer.testing import CliRunner

from confiture.cli.main import app

SCHEMA_FILE = "migrate-validate-list-patterns.schema.json"


def _load(schemas_dir: Path, name: str) -> dict:
    return json.loads((schemas_dir / name).read_text())


def test_list_patterns_payload_validates_against_schema(schemas_dir, schema_registry):
    runner = CliRunner()
    result = runner.invoke(
        app, ["migrate", "validate", "--list-patterns", "--format", "json"]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)

    schema = _load(schemas_dir, SCHEMA_FILE)
    validator = Draft202012Validator(schema, registry=schema_registry)
    validator.validate(payload)


def test_hints_field_present_and_empty_by_default(schemas_dir, schema_registry):
    """`hints` is pre-allocated for Phase 05; today it's always an empty list."""
    runner = CliRunner()
    result = runner.invoke(
        app, ["migrate", "validate", "--list-patterns", "--format", "json"]
    )
    payload = json.loads(result.stdout)
    assert payload["hints"] == []


def test_schema_is_valid_draft_2020_12(schemas_dir):
    """The schema document itself is a valid Draft 2020-12 schema."""
    schema = _load(schemas_dir, SCHEMA_FILE)
    Draft202012Validator.check_schema(schema)
