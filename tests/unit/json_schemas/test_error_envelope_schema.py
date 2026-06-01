"""Validate the #145 error envelope against its published JSON Schema.

The envelope schema $refs issue-object.schema.json, so the registry resolves
both relative URIs.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import psycopg
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012
from typer.testing import CliRunner

from confiture.cli.main import app

SCHEMAS_DIR = Path(__file__).resolve().parents[3] / "docs" / "reference" / "json-schemas"
_UNREACHABLE = "postgresql://localhost:1/nope"


def _load(name: str) -> dict:
    return json.loads((SCHEMAS_DIR / name).read_text())


def _envelope_validator() -> Draft202012Validator:
    issue = _load("issue-object.schema.json")
    registry = Registry().with_resource(
        uri="issue-object.schema.json",
        resource=Resource.from_contents(issue, default_specification=DRAFT202012),
    )
    return Draft202012Validator(_load("error-envelope.schema.json"), registry=registry)


def test_envelope_schema_is_valid_draft_2020_12() -> None:
    Draft202012Validator.check_schema(_load("error-envelope.schema.json"))
    Draft202012Validator.check_schema(_load("issue-object.schema.json"))


def test_real_connection_failure_envelope_validates(tmp_path: Path) -> None:
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    with patch(
        "confiture.core.connection.psycopg.connect",
        side_effect=psycopg.OperationalError("connection refused"),
    ):
        result = CliRunner().invoke(
            app,
            [
                "migrate",
                "up",
                "--database-url",
                _UNREACHABLE,
                "--migrations-dir",
                str(migrations_dir),
                "--format",
                "json",
            ],
        )
    assert result.exit_code == 3, result.output
    payload = json.loads(result.stdout)
    _envelope_validator().validate(payload)
    assert payload["error"]["code"] == "CONFIG_006"


def test_real_duplicate_version_envelope_validates(tmp_path: Path) -> None:
    d = tmp_path / "migrations"
    d.mkdir()
    for name in ("20260101000001_a", "20260101000001_b"):
        (d / f"{name}.up.sql").write_text("SELECT 1;")
        (d / f"{name}.down.sql").write_text("SELECT 1;")
    result = CliRunner().invoke(
        app,
        [
            "migrate",
            "up",
            "--database-url",
            _UNREACHABLE,
            "--migrations-dir",
            str(d),
            "--format",
            "json",
        ],
    )
    assert result.exit_code == 3, result.output
    _envelope_validator().validate(json.loads(result.stdout))
