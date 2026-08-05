"""Schema conformance for ``verify-checksums --format json`` (#189).

``verify-checksums`` was text-only while every other command grew a structured
surface. This covers all four paths it can take, because they are separate
``return``/``raise`` points and each one is a chance to emit a different shape:

* clean — no mismatches;
* mismatches found — the CI-gate path, which exits 1;
* no ledger under ``--allow-uninitialized`` — the crash-turned-graceful path
  0.37.0 added, which previously ``return``ed after a Rich print and so had no
  JSON at all;
* no ledger without that flag — the error envelope, ``PRECON_1001``.
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
from confiture.core.ledger import LedgerProbe

runner = CliRunner()

SCHEMAS_DIR = Path(__file__).resolve().parents[3] / "docs" / "reference" / "json-schemas"


def _load(name: str) -> dict:
    return json.loads((SCHEMAS_DIR / name).read_text())


def _validator(schema_name: str) -> Draft202012Validator:
    issue = _load("issue-object.schema.json")
    registry = Registry().with_resource(
        uri="issue-object.schema.json",
        resource=Resource.from_contents(issue, default_specification=DRAFT202012),
    )
    return Draft202012Validator(_load(schema_name), registry=registry)


@pytest.fixture
def cfg(tmp_path: Path) -> Path:
    p = tmp_path / "env.yaml"
    p.write_text(
        yaml.safe_dump(
            {
                "name": "test",
                "database_url": "postgresql://localhost/nonexistent_for_test",
                "include_dirs": ["db/schema"],
                "migration": {"tracking_table": "audit.tb_migrations"},
            }
        )
    )
    return p


@pytest.fixture
def migrations_dir(tmp_path: Path) -> Path:
    d = tmp_path / "migrations"
    d.mkdir()
    (d / "20260101000000_init.up.sql").write_text("SELECT 1;\n")
    return d


def _invoke(cfg: Path, migrations_dir: Path, *extra: str):
    return runner.invoke(
        app,
        [
            "verify-checksums",
            "--config",
            str(cfg),
            "--migrations-dir",
            str(migrations_dir),
            "--format",
            "json",
            *extra,
        ],
    )


def _mismatch(version: str, name: str) -> MagicMock:
    m = MagicMock()
    m.version = version
    m.name = name
    m.file_path = f"db/migrations/{version}_{name}.up.sql"
    m.expected = "a" * 64
    m.actual = "b" * 64
    return m


@patch("confiture.core.connection.create_connection")
@patch(
    "confiture.core.ledger.probe_ledger",
    return_value=LedgerProbe(exists=True, resolved_name="audit.tb_migrations"),
)
@patch("confiture.core.checksum.MigrationChecksumVerifier")
def test_clean_run_matches_schema(
    verifier_cls, probe, _conn, cfg: Path, migrations_dir: Path
) -> None:
    verifier_cls.return_value.verify_all.return_value = []
    verifier_cls.return_value.count_applied.return_value = 3

    result = _invoke(cfg, migrations_dir)

    # Naming the seam, not just asserting the shape. When 0.41.0 moved this
    # command from `ledger_exists` to `probe_ledger`, the stale patch bound to
    # nothing and the real probe ran against the MagicMock connection — whose
    # row is truthy, so it read as *present* and this test kept passing while
    # testing nothing at all.
    assert probe.called, "ledger probe double unused — patch target is stale"
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    _validator("verify-checksums.schema.json").validate(payload)
    assert payload["ok"] is True
    assert payload["ledger_present"] is True
    assert payload["issues"] == []
    assert payload["summary"]["mismatched"] == 0
    assert payload["summary"]["resolved_table"] == "audit.tb_migrations"


@patch("confiture.core.connection.create_connection")
@patch(
    "confiture.core.ledger.probe_ledger",
    return_value=LedgerProbe(exists=True, resolved_name="audit.tb_migrations"),
)
@patch("confiture.core.checksum.MigrationChecksumVerifier")
def test_mismatch_run_matches_schema(
    verifier_cls, probe, _conn, cfg: Path, migrations_dir: Path
) -> None:
    verifier_cls.return_value.verify_all.return_value = [
        _mismatch("20260101000000", "init"),
        _mismatch("20260102000000", "widgets"),
    ]
    verifier_cls.return_value.count_applied.return_value = 5

    result = _invoke(cfg, migrations_dir)

    # success-signal: verification ran and found mismatches (the CI gate).
    assert result.exit_code == 1, result.output
    payload = json.loads(result.stdout)
    _validator("verify-checksums.schema.json").validate(payload)
    assert payload["ok"] is False
    assert payload["summary"]["mismatched"] == 2
    assert len(payload["issues"]) == 2
    assert payload["issues"][0]["code"] == "CHECKSUM_MISMATCH"
    # The configured ledger, never the hardcoded default (#190).
    assert "tb_confiture" not in result.stdout


@patch("confiture.core.connection.create_connection")
@patch("confiture.core.ledger.find_ledger_relations", return_value=[])
@patch("confiture.core.ledger.probe_ledger", return_value=LedgerProbe(exists=False))
def test_no_ledger_with_allow_uninitialized_matches_schema(
    probe, _elsewhere, _conn, cfg: Path, migrations_dir: Path
) -> None:
    """The degraded path must emit JSON, not `return` after a Rich print."""
    result = _invoke(cfg, migrations_dir, "--allow-uninitialized")

    assert probe.called, "ledger probe double unused — patch target is stale"
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    _validator("verify-checksums.schema.json").validate(payload)
    assert payload["ok"] is True
    assert payload["ledger_present"] is False
    assert payload["summary"]["checked"] == 0
    # Nothing resolved, so nothing to name — the key is declared, not omitted.
    assert payload["summary"]["resolved_table"] is None


@patch("confiture.core.connection.create_connection")
@patch("confiture.core.ledger.find_ledger_relations", return_value=[])
@patch("confiture.core.ledger.probe_ledger", return_value=LedgerProbe(exists=False))
def test_no_ledger_without_flag_emits_error_envelope(
    probe, _elsewhere, _conn, cfg: Path, migrations_dir: Path
) -> None:
    result = _invoke(cfg, migrations_dir)

    assert probe.called, "ledger probe double unused — patch target is stale"
    assert result.exit_code == 2, result.output
    payload = json.loads(result.stdout)
    _validator("error-envelope.schema.json").validate(payload)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "PRECON_1001"
