"""Validate ``confiture lint --list-rules --format json`` against its schema (#150)."""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator
from typer.testing import CliRunner

from confiture.cli.main import app

SCHEMA_FILE = "lint-list-rules.schema.json"


def _load(schemas_dir: Path, name: str) -> dict:
    return json.loads((schemas_dir / name).read_text())


def _payload() -> dict:
    result = CliRunner().invoke(app, ["lint", "--list-rules", "--format", "json"])
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


def test_list_rules_payload_validates_against_schema(schemas_dir, schema_registry):
    schema = _load(schemas_dir, SCHEMA_FILE)
    Draft202012Validator(schema, registry=schema_registry).validate(_payload())


def test_every_registry_rule_is_in_the_payload():
    """The document is generated from the registry, not maintained beside it."""
    from confiture.core.linting.rule_registry import LINT_RULES

    codes = [rule["code"] for rule in _payload()["rules"]]
    assert codes == [rule.code for rule in LINT_RULES]


def test_schema_is_valid_draft_2020_12(schemas_dir):
    Draft202012Validator.check_schema(_load(schemas_dir, SCHEMA_FILE))
