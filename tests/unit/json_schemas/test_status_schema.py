"""Validate ``migrate status --format json`` output against its schema."""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator
from typer.testing import CliRunner

from confiture.cli.main import app

SCHEMA_FILE = "migrate-status.schema.json"


def _load(schemas_dir: Path, name: str) -> dict:
    return json.loads((schemas_dir / name).read_text())


def _validator(schemas_dir, registry) -> Draft202012Validator:
    return Draft202012Validator(_load(schemas_dir, SCHEMA_FILE), registry=registry)


def test_schema_is_valid_draft_2020_12(schemas_dir):
    Draft202012Validator.check_schema(_load(schemas_dir, SCHEMA_FILE))


def test_empty_migrations_dir_validates(tmp_path, schemas_dir, schema_registry):
    """No migration files → empty-input shape."""
    migs = tmp_path / "db" / "migrations"
    migs.mkdir(parents=True)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "migrate",
            "status",
            "--migrations-dir",
            str(migs),
            "--format",
            "json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    _validator(schemas_dir, schema_registry).validate(payload)
    assert payload["total"] == 0
    assert payload["current"] is None
    assert payload["hints"] == []


def test_status_without_config_validates(tmp_path, schemas_dir, schema_registry):
    """Migration files present, no --config → status=unknown per-migration."""
    migs = tmp_path / "db" / "migrations"
    migs.mkdir(parents=True)
    (migs / "20260527000000_init.up.sql").write_text("CREATE TABLE IF NOT EXISTS u (id INT);\n")

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "migrate",
            "status",
            "--migrations-dir",
            str(migs),
            "--format",
            "json",
        ],
    )
    payload = json.loads(result.stdout)
    _validator(schemas_dir, schema_registry).validate(payload)
    assert payload["tracking_table"] is None
    assert payload["total"] == 1
    assert all(m["status"] == "unknown" for m in payload["migrations"])
    assert payload["summary"] == {"applied": 0, "pending": 0, "total": 1}
    assert payload["hints"] == []
