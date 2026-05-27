"""Validate ``migrate preflight --format json`` outputs against their schemas.

Two shapes are covered:
* default (no --against): static analysis only, no DB
* `--against <url>`: static analysis + execution outcomes (mocked here)
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.models.results import (
    PreflightAgainstMigration,
    PreflightAgainstResult,
)

PREFLIGHT_SCHEMA = "migrate-preflight.schema.json"
AGAINST_SCHEMA = "migrate-preflight-against.schema.json"


def _load(schemas_dir: Path, name: str) -> dict:
    return json.loads((schemas_dir / name).read_text())


def _build_registry(schemas_dir: Path) -> Registry:
    """Registry including the preflight $defs file as well as common."""
    registry: Registry = Registry()
    for filename in ("_common.schema.json", "_preflight_defs.schema.json"):
        content = _load(schemas_dir, filename)
        resource = Resource.from_contents(content, default_specification=DRAFT202012)
        registry = registry.with_resource(uri=filename, resource=resource)
    return registry


def test_preflight_schemas_are_valid_draft_2020_12(schemas_dir):
    for name in (PREFLIGHT_SCHEMA, AGAINST_SCHEMA, "_preflight_defs.schema.json"):
        Draft202012Validator.check_schema(_load(schemas_dir, name))


def test_preflight_no_against_validates(tmp_path, schemas_dir):
    """Default preflight — no DB needed."""
    migs = tmp_path / "db" / "migrations"
    migs.mkdir(parents=True)
    (migs / "20260527000000_init.up.sql").write_text("CREATE TABLE x (id INT);\n")
    (migs / "20260527000000_init.down.sql").write_text("DROP TABLE x;\n")

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "migrate",
            "preflight",
            "--migrations-dir",
            str(migs),
            "--format",
            "json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)

    registry = _build_registry(schemas_dir)
    Draft202012Validator(_load(schemas_dir, PREFLIGHT_SCHEMA), registry=registry).validate(payload)
    assert payload["hints"] == []
    assert "safe_to_deploy" in payload


def test_preflight_against_validates(tmp_path, schemas_dir):
    """--against path — mock the session.run_against to return a fixture."""
    migs = tmp_path / "db" / "migrations"
    migs.mkdir(parents=True)
    (migs / "20260527000000_init.up.sql").write_text(
        "CREATE TABLE IF NOT EXISTS x (id INT);\n"
    )
    (migs / "20260527000000_init.down.sql").write_text("DROP TABLE IF EXISTS x;\n")

    fixture = PreflightAgainstResult(
        migrations=[
            PreflightAgainstMigration(
                version="20260527000000",
                name="init",
                success=True,
                error=None,
                skipped=False,
                skipped_reason=None,
                execution_time_ms=42,
            )
        ],
        against_url="postgresql://user:secret@localhost/preflight",
        db_consumed=False,
    )

    mock_session = MagicMock()
    mock_session.__enter__ = lambda s: mock_session
    mock_session.__exit__ = MagicMock(return_value=False)
    mock_session.run_against.return_value = fixture

    runner = CliRunner()
    with patch(
        "confiture.cli.commands.migrate_analysis.MigratorSession",
        return_value=mock_session,
    ):
        result = runner.invoke(
            app,
            [
                "migrate",
                "preflight",
                "--against",
                "postgresql://user:secret@localhost/preflight",
                "--migrations-dir",
                str(migs),
                "--format",
                "json",
            ],
        )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)

    registry = _build_registry(schemas_dir)
    Draft202012Validator(_load(schemas_dir, AGAINST_SCHEMA), registry=registry).validate(payload)

    # Spot-check the documented field-name traps:
    assert "success" in payload["against"]["migrations"][0]  # NOT "passed"
    assert payload["against"]["all_passed"] is True
    # URL is redacted — the password is stripped (the username is preserved).
    assert "secret" not in payload["against"]["against_url"]
    assert "user" in payload["against"]["against_url"]
    assert payload["hints"] == []
