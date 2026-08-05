"""Schema conformance for ``migrate introspect --format json`` (#186).

Introspect emits three different payloads from three separate ``json.dumps``
call sites. The interesting property is that all three carry ``ledger_present``
and match the schema — three independent emit sites is how a shape silently
stops agreeing.

The deprecated ``tb_confiture_present`` alias was added in 0.39.0 and removed in
0.40.0 as announced; ``test_deprecated_alias_is_gone`` pins the removal so it
cannot creep back in.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from jsonschema import Draft202012Validator
from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()

SCHEMAS_DIR = Path(__file__).resolve().parents[3] / "docs" / "reference" / "json-schemas"


def _validator() -> Draft202012Validator:
    return Draft202012Validator(
        json.loads((SCHEMAS_DIR / "migrate-introspect.schema.json").read_text())
    )


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


def _invoke(cfg: Path, snapshots: Path):
    return runner.invoke(
        app,
        [
            "migrate",
            "introspect",
            "--config",
            str(cfg),
            "--snapshots-dir",
            str(snapshots),
            "--format",
            "json",
        ],
    )


@patch("confiture.core.connection.create_connection")
@patch("confiture.core.migrator.Migrator")
def test_missing_snapshots_dir_matches_schema(
    migrator_cls, _conn, cfg: Path, tmp_path: Path
) -> None:
    migrator_cls.return_value.tracking_table_exists.return_value = True

    result = _invoke(cfg, tmp_path / "does_not_exist")

    payload = json.loads(result.stdout)
    _validator().validate(payload)
    assert payload["error"] == "snapshots_dir not found"
    assert payload["detected_version"] is None


@patch("confiture.core.connection.create_connection")
@patch("confiture.core.migrator.Migrator")
@patch("confiture.core.baseline_detector.BaselineDetector")
def test_exact_match_matches_schema(
    detector_cls, migrator_cls, _conn, cfg: Path, tmp_path: Path
) -> None:
    snapshots = tmp_path / "snapshots"
    snapshots.mkdir()
    (snapshots / "20260101000000_init.sql").write_text("CREATE TABLE t (id INT);\n")

    migrator_cls.return_value.tracking_table_exists.return_value = False
    detector = detector_cls.return_value
    detector.introspect_live_schema.return_value = "CREATE TABLE t (id INT);"
    detector.find_matching_snapshot.return_value = "20260101000000"

    result = _invoke(cfg, snapshots)

    payload = json.loads(result.stdout)
    _validator().validate(payload)
    assert payload["confidence"] == "exact"
    assert payload["detected_version"] == "20260101000000"


@patch("confiture.core.connection.create_connection")
@patch("confiture.core.migrator.Migrator")
@patch("confiture.core.baseline_detector.BaselineDetector")
def test_no_match_with_closest_matches_schema(
    detector_cls, migrator_cls, _conn, cfg: Path, tmp_path: Path
) -> None:
    snapshots = tmp_path / "snapshots"
    snapshots.mkdir()
    (snapshots / "20260101000000_init.sql").write_text("CREATE TABLE t (id INT);\n")

    migrator_cls.return_value.tracking_table_exists.return_value = True
    detector = detector_cls.return_value
    detector.introspect_live_schema.return_value = "CREATE TABLE other (id INT);"
    detector.find_matching_snapshot.return_value = None
    detector.last_closest = ("20260101000000", 0.4213456)

    result = _invoke(cfg, snapshots)

    payload = json.loads(result.stdout)
    _validator().validate(payload)
    assert payload["confidence"] == "none"
    assert payload["closest_version"] == "20260101000000"
    assert payload["closest_similarity"] == pytest.approx(0.4213)


@patch("confiture.core.connection.create_connection")
@patch("confiture.core.migrator.Migrator")
def test_deprecated_alias_is_gone(migrator_cls, _conn, cfg: Path, tmp_path: Path) -> None:
    """``tb_confiture_present`` was removed in 0.40.0 as announced (#186).

    It hardcoded the default table name, so it lied to every project that had
    configured ``tracking_table`` — which is why it only ever existed as a
    one-release upgrade path.
    """
    migrator_cls.return_value.tracking_table_exists.return_value = True

    payload = json.loads(_invoke(cfg, tmp_path / "nope").stdout)

    assert "tb_confiture_present" not in payload
    assert "ledger_present" in payload


def test_schema_no_longer_declares_the_removed_key() -> None:
    """The schema sets additionalProperties: false, so a re-added key would fail
    validation — but the property declaration itself must go too, or the schema
    would keep advertising a key nothing emits."""
    schema = json.loads((SCHEMAS_DIR / "migrate-introspect.schema.json").read_text())
    assert "tb_confiture_present" not in schema["properties"]
    assert "tb_confiture_present" not in schema["required"]
