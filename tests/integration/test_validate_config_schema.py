"""Validate `validate-config --format json` output against its schema (#144)."""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012
from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()
_SCHEMAS_DIR = Path(__file__).resolve().parents[2] / "docs" / "reference" / "json-schemas"


def _validator() -> Draft202012Validator:
    issue = json.loads((_SCHEMAS_DIR / "issue-object.schema.json").read_text())
    registry = Registry().with_resource(
        uri="issue-object.schema.json",
        resource=Resource.from_contents(issue, default_specification=DRAFT202012),
    )
    return Draft202012Validator(
        json.loads((_SCHEMAS_DIR / "validate-config.schema.json").read_text()), registry=registry
    )


def test_schema_valid_draft_2020_12() -> None:
    Draft202012Validator.check_schema(
        json.loads((_SCHEMAS_DIR / "validate-config.schema.json").read_text())
    )


def test_valid_report_validates(tmp_path: Path) -> None:
    (tmp_path / "db" / "schema").mkdir(parents=True)
    migs = tmp_path / "db" / "migrations"
    migs.mkdir(parents=True)
    (migs / "20260101000000_a.up.sql").write_text("SELECT 1;")
    (migs / "20260101000000_a.down.sql").write_text("SELECT 1;")
    cfg = tmp_path / "env.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {"name": "t", "database_url": "postgresql://localhost/app", "include_dirs": ["db/schema"]}
        )
    )
    r = runner.invoke(
        app, ["validate-config", "-c", str(cfg), "--migrations-path", str(migs), "--format", "json"]
    )
    assert r.exit_code == 0, r.output
    _validator().validate(json.loads(r.stdout))


def test_invalid_report_validates(tmp_path: Path) -> None:
    migs = tmp_path / "migrations"
    migs.mkdir()
    r = runner.invoke(
        app,
        ["validate-config", "--database-url", "not-a-dsn",
         "--migrations-path", str(migs), "--format", "json"],
    )
    assert r.exit_code == 5, r.output
    payload = json.loads(r.stdout)
    _validator().validate(payload)
    assert payload["valid"] is False
