"""Schema conformance for `migrate verify` on a ledger-less database (#182b).

Two payloads must stay contract-valid:

- the degraded `--allow-uninitialized` payload, against
  `migrate-verify.schema.json` (which sets ``additionalProperties: false``, so
  `ledger_present` had to be declared, not merely emitted);
- the error envelope on the default path, carrying `PRECON_1001`.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012
from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()

SCHEMAS_DIR = Path(__file__).resolve().parents[3] / "docs" / "reference" / "json-schemas"


def _load(name: str) -> dict:
    return json.loads((SCHEMAS_DIR / name).read_text())


def _envelope_validator() -> Draft202012Validator:
    issue = _load("issue-object.schema.json")
    registry = Registry().with_resource(
        uri="issue-object.schema.json",
        resource=Resource.from_contents(issue, default_specification=DRAFT202012),
    )
    return Draft202012Validator(_load("error-envelope.schema.json"), registry=registry)


@pytest.fixture
def cfg(tmp_path: Path) -> Path:
    p = tmp_path / "env.yaml"
    p.write_text(
        yaml.safe_dump(
            {
                "name": "test",
                "database_url": "postgresql://localhost/nonexistent_for_test",
                "include_dirs": ["db/schema"],
            }
        )
    )
    return p


@pytest.fixture
def migrations_dir(tmp_path: Path) -> Path:
    d = tmp_path / "migrations"
    d.mkdir()
    (d / "20260101000000_init.up.sql").write_text("CREATE TABLE t (id int);")
    return d


def _invoke(cfg: Path, migrations_dir: Path, *extra: str):
    with (
        patch("confiture.core.connection.create_connection", return_value=MagicMock()),
        patch("confiture.core.migrator.Migrator.tracking_table_exists", return_value=False),
    ):
        return runner.invoke(
            app,
            [
                "migrate",
                "verify",
                "-c",
                str(cfg),
                "--migrations-dir",
                str(migrations_dir),
                "--format",
                "json",
                *extra,
            ],
        )


def test_verify_schema_is_valid_draft_2020_12() -> None:
    Draft202012Validator.check_schema(_load("migrate-verify.schema.json"))


def test_schema_declares_ledger_present_as_optional() -> None:
    """`ledger_present` must be declared (additionalProperties is false) but
    must NOT be required — old consumers reading the field's absence stay valid.
    """
    schema = _load("migrate-verify.schema.json")

    assert schema["additionalProperties"] is False
    assert "ledger_present" in schema["properties"]
    assert "ledger_present" not in schema["required"]


def test_absent_ledger_json_emits_error_envelope(cfg: Path, migrations_dir: Path) -> None:
    result = _invoke(cfg, migrations_dir)

    assert result.exit_code == 2
    payload = json.loads(result.stdout)
    _envelope_validator().validate(payload)
    assert payload["error"]["code"] == "PRECON_1001"


def test_allow_uninitialized_payload_validates(cfg: Path, migrations_dir: Path) -> None:
    result = _invoke(cfg, migrations_dir, "--allow-uninitialized")

    assert result.exit_code == 0
    payload = json.loads(result.stdout)

    schema = _load("migrate-verify.schema.json")
    Draft202012Validator(schema).validate(payload)

    assert payload["ledger_present"] is False
    assert payload["failed_count"] == 0
    assert payload["total_applied"] == 0
    assert payload["results"] == []
