"""Validate ``migrate fix --idempotent --format json`` output against its schema."""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator
from typer.testing import CliRunner

from confiture.cli.main import app

SCHEMA_FILE = "migrate-fix.schema.json"


def _load(schemas_dir: Path, name: str) -> dict:
    return json.loads((schemas_dir / name).read_text())


def _validator(schemas_dir, registry) -> Draft202012Validator:
    return Draft202012Validator(_load(schemas_dir, SCHEMA_FILE), registry=registry)


def test_schema_is_valid_draft_2020_12(schemas_dir):
    Draft202012Validator.check_schema(_load(schemas_dir, SCHEMA_FILE))


def test_fix_empty_migrations_dir_validates(tmp_path, schemas_dir, schema_registry):
    """No migration files — empty-input envelope."""
    migs = tmp_path / "db" / "migrations"
    migs.mkdir(parents=True)
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "migrate",
            "fix",
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
    assert payload["hints"] == []


def test_fix_dry_run_preview_validates(tmp_path, schemas_dir, schema_registry):
    """A non-idempotent migration with --dry-run → status: preview."""
    migs = tmp_path / "db" / "migrations"
    migs.mkdir(parents=True)
    (migs / "20260527000001_init.up.sql").write_text("CREATE TABLE users (id INT PRIMARY KEY);\n")

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "migrate",
            "fix",
            "--idempotent",
            "--dry-run",
            "--migrations-dir",
            str(migs),
            "--format",
            "json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    _validator(schemas_dir, schema_registry).validate(payload)
    assert payload["status"] == "preview"
    assert payload["total_files_changed"] == 1
    # Verify file wasn't modified on disk.
    assert "IF NOT EXISTS" not in (migs / "20260527000001_init.up.sql").read_text().upper()


def test_fix_apply_validates(tmp_path, schemas_dir, schema_registry):
    """A non-idempotent migration without --dry-run → status: fixed; file rewritten."""
    migs = tmp_path / "db" / "migrations"
    migs.mkdir(parents=True)
    f = migs / "20260527000002_init.up.sql"
    f.write_text("CREATE TABLE users (id INT PRIMARY KEY);\n")

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "migrate",
            "fix",
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
    assert payload["status"] == "fixed"
    assert "IF NOT EXISTS" in f.read_text().upper()
