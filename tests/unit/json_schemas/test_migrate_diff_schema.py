"""Validate ``migrate diff --format json`` output against its schema (issue #196)."""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator
from typer.testing import CliRunner

from confiture.cli.main import app

SCHEMA_FILE = "migrate-diff.schema.json"
FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "desired_state" / "emit_ddl"


def _load(schemas_dir: Path, name: str) -> dict:
    return json.loads((schemas_dir / name).read_text())


def _validator(schemas_dir, registry) -> Draft202012Validator:
    return Draft202012Validator(_load(schemas_dir, SCHEMA_FILE), registry=registry)


def test_schema_is_valid_draft_2020_12(schemas_dir):
    Draft202012Validator.check_schema(_load(schemas_dir, SCHEMA_FILE))


def test_diff_against_an_artifact_validates(tmp_path, schemas_dir, schema_registry):
    current = tmp_path / "current.sql"
    current.write_text((FIXTURE / "user.sql").read_text())
    result = CliRunner().invoke(
        app, ["migrate", "diff", "--from", str(current), "--to", str(FIXTURE), "--format", "json"]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    _validator(schemas_dir, schema_registry).validate(payload)
    assert payload["source"] == {"kind": "sql", "path": str(FIXTURE)}


def test_generated_migration_payload_validates(tmp_path, schemas_dir, schema_registry):
    current = tmp_path / "current.sql"
    current.write_text((FIXTURE / "user.sql").read_text())
    result = CliRunner().invoke(
        app,
        [
            "migrate",
            "diff",
            "--from",
            str(current),
            "--to",
            str(FIXTURE),
            "--generate",
            "--name",
            "add_posts",
            "--migrations-dir",
            str(tmp_path / "migrations"),
            "--format",
            "json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    _validator(schemas_dir, schema_registry).validate(payload)
    assert payload["migration_generated"] is True


def test_failure_payload_validates(tmp_path, schemas_dir, schema_registry):
    result = CliRunner().invoke(
        app,
        [
            "migrate",
            "diff",
            "--from",
            str(tmp_path / "absent.sql"),
            "--to",
            str(FIXTURE),
            "--format",
            "json",
        ],
    )
    assert result.exit_code == 1
    payload = json.loads(result.output)
    _validator(schemas_dir, schema_registry).validate(payload)
    assert payload["success"] is False and payload["source"] is None
