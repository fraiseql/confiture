"""Validate ``migrate validate --idempotent --format json`` output against its schema."""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator
from typer.testing import CliRunner

from confiture.cli.main import app

SCHEMA_FILE = "migrate-validate-idempotent.schema.json"


def _load(schemas_dir: Path, name: str) -> dict:
    return json.loads((schemas_dir / name).read_text())


def _validator(schemas_dir, registry) -> Draft202012Validator:
    return Draft202012Validator(_load(schemas_dir, SCHEMA_FILE), registry=registry)


def test_schema_is_valid_draft_2020_12(schemas_dir):
    schema = _load(schemas_dir, SCHEMA_FILE)
    Draft202012Validator.check_schema(schema)


def test_empty_migrations_dir_validates(tmp_path, schemas_dir, schema_registry):
    """No migration files in directory → ok-envelope + quiet-success hint."""
    (tmp_path / "db" / "migrations").mkdir(parents=True)
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "migrate",
            "validate",
            "--idempotent",
            "--migrations-dir",
            str(tmp_path / "db" / "migrations"),
            "--format",
            "json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    _validator(schemas_dir, schema_registry).validate(payload)
    assert payload["status"] == "ok"
    # Phase 05: empty migration directory triggers a quiet-success hint.
    assert any("exists but contains no files" in h for h in payload["hints"])


def test_idempotent_migrations_validates(tmp_path, schemas_dir, schema_registry):
    """All migrations are idempotent — status: ok, no violations."""
    migs = tmp_path / "db" / "migrations"
    migs.mkdir(parents=True)
    (migs / "20260527000000_init.up.sql").write_text(
        "CREATE TABLE IF NOT EXISTS users (id INT PRIMARY KEY);\n"
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "migrate",
            "validate",
            "--idempotent",
            "--migrations-dir",
            str(migs),
            "--format",
            "json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    _validator(schemas_dir, schema_registry).validate(payload)
    assert payload["status"] == "ok"
    assert payload["violation_count"] == 0
    assert payload["files_scanned"] == 1


def test_non_idempotent_migration_validates(tmp_path, schemas_dir, schema_registry):
    """A migration with non-idempotent SQL — status: issues_found, violations populated."""
    migs = tmp_path / "db" / "migrations"
    migs.mkdir(parents=True)
    (migs / "20260527000001_bad.up.sql").write_text(
        "CREATE TABLE users (id INT PRIMARY KEY);\n"
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "migrate",
            "validate",
            "--idempotent",
            "--migrations-dir",
            str(migs),
            "--format",
            "json",
        ],
    )
    # Exit 1 because the migration is non-idempotent
    assert result.exit_code == 1, result.output
    payload = json.loads(result.stdout)
    _validator(schemas_dir, schema_registry).validate(payload)
    assert payload["status"] == "issues_found"
    assert payload["violation_count"] >= 1
    # Every violation conforms to the Violation sub-schema (covered by schema.validate).
    assert all("pattern" in v for v in payload["violations"])
    assert all("severity" in v for v in payload["violations"])


def test_hints_field_is_required_and_array(tmp_path, schemas_dir, schema_registry):
    """`hints` is pre-allocated per Phase 02 schema contract; always an array."""
    migs = tmp_path / "db" / "migrations"
    migs.mkdir(parents=True)
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "migrate",
            "validate",
            "--idempotent",
            "--migrations-dir",
            str(migs),
            "--format",
            "json",
        ],
    )
    payload = json.loads(result.stdout)
    assert isinstance(payload["hints"], list)
