"""Validate ``migrate validate --check-acls --format json`` output."""

from __future__ import annotations

import json
from pathlib import Path
from textwrap import dedent

from jsonschema import Draft202012Validator
from typer.testing import CliRunner

from confiture.cli.main import app

SCHEMA_FILE = "migrate-validate-check-acl-coverage.schema.json"


def _load(schemas_dir: Path, name: str) -> dict:
    return json.loads((schemas_dir / name).read_text())


def _validator(schemas_dir, registry) -> Draft202012Validator:
    return Draft202012Validator(_load(schemas_dir, SCHEMA_FILE), registry=registry)


def _project(tmp_path: Path) -> tuple[Path, Path]:
    """Build a minimal project with a config and a migration."""
    config = tmp_path / "confiture.yaml"
    config.write_text(
        dedent(
            """\
            environment: test
            database:
              host: localhost
              port: 5432
              name: confiture_test
              user: confiture
            migration:
              dir: db/migrations
            acls:
              - schema: public
                apply_to: ALL_TABLES
                grants:
                  - role: app_reader
                    privileges: [SELECT]
            """
        )
    )
    migs = tmp_path / "db" / "migrations"
    migs.mkdir(parents=True)
    return config, migs


def test_schema_is_valid_draft_2020_12(schemas_dir):
    schema = _load(schemas_dir, SCHEMA_FILE)
    Draft202012Validator.check_schema(schema)


def test_check_acls_empty_migrations_validates(tmp_path, schemas_dir, schema_registry):
    """No migrations to lint — empty violations list, hints array present."""
    config, migs = _project(tmp_path)
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "migrate",
            "validate",
            "--check-acls",
            "-c",
            str(config),
            "--migrations-dir",
            str(migs),
            "--format",
            "json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    _validator(schemas_dir, schema_registry).validate(payload)
    assert payload["check"] == "acl_coverage"
    assert payload["violations"] == []
    assert payload["hints"] == []


def test_check_acls_violation_validates(tmp_path, schemas_dir, schema_registry):
    """A CREATE TABLE without matching grants — at least one violation."""
    config, migs = _project(tmp_path)
    (migs / "20260527000000_init.up.sql").write_text(
        "CREATE TABLE IF NOT EXISTS public.orders (id INT PRIMARY KEY);\n"
    )
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "migrate",
            "validate",
            "--check-acls",
            "-c",
            str(config),
            "--migrations-dir",
            str(migs),
            "--format",
            "json",
        ],
    )
    # Exit code may be 0 or 1 depending on severity; we only assert shape.
    payload = json.loads(result.stdout)
    _validator(schemas_dir, schema_registry).validate(payload)
    assert payload["check"] == "acl_coverage"
