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


def test_resolved_table_validates(tmp_path, schemas_dir, schema_registry, monkeypatch):
    """`resolved_table` names the relation the session actually read (0.41.0, #188).

    A bare `tracking_table` resolves through `search_path`, so the configured
    name alone no longer identifies a relation. `additionalProperties: false`
    means the key had to be declared in the schema, not merely emitted.
    """
    from unittest.mock import MagicMock

    from confiture.config.environment import Environment
    from confiture.core.ledger import LedgerProbe

    migs = tmp_path / "db" / "migrations"
    migs.mkdir(parents=True)
    (migs / "20260527000000_init.up.sql").write_text("CREATE TABLE IF NOT EXISTS u (id INT);\n")
    cfg = tmp_path / "env.yaml"
    cfg.write_text("name: test\ndatabase_url: postgresql://localhost/test\n")

    migrator = MagicMock()
    migrator.tracking_table_exists.return_value = True
    migrator.get_applied_versions.return_value = []
    migrator.get_applied_migrations_with_timestamps.return_value = []

    env = Environment.model_validate(
        {"name": "test", "database_url": "postgresql://localhost/test"}
    )
    monkeypatch.setattr("confiture.core.connection.load_config", lambda *a, **k: env)
    monkeypatch.setattr("confiture.core.connection.create_connection", lambda *a, **k: MagicMock())
    monkeypatch.setattr("confiture.core.migrator.Migrator", lambda *a, **k: migrator)
    probe = MagicMock(return_value=LedgerProbe(exists=True, resolved_name="staging.tb_confiture"))
    monkeypatch.setattr("confiture.core.ledger.probe_ledger", probe)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "migrate",
            "status",
            "--config",
            str(cfg),
            "--migrations-dir",
            str(migs),
            "--format",
            "json",
        ],
    )

    assert probe.called, "ledger probe double unused — patch target is stale"
    payload = json.loads(result.stdout)
    _validator(schemas_dir, schema_registry).validate(payload)
    assert payload["resolved_table"] == "staging.tb_confiture"
