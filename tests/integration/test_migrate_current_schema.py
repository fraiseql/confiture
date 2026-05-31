"""Validate `migrate current --format json` output against its schema (#141)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import psycopg
import pytest
import yaml
from jsonschema import Draft202012Validator
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.core.migrator import Migrator

runner = CliRunner()
_TABLE = "tb_current_schema_it"
_SCHEMAS_DIR = Path(__file__).resolve().parents[2] / "docs" / "reference" / "json-schemas"


def _validator() -> Draft202012Validator:
    return Draft202012Validator(
        json.loads((_SCHEMAS_DIR / "migrate-current.schema.json").read_text())
    )


@pytest.fixture
def cfg(tmp_path: Path, test_db_url: str):
    p = tmp_path / "env.yaml"
    p.write_text(
        yaml.safe_dump(
            {
                "name": "test",
                "database_url": test_db_url,
                "include_dirs": ["db/schema"],
                "migration": {"tracking_table": _TABLE},
            }
        )
    )
    return p


@pytest.fixture
def conn(test_db_url: str):
    c = psycopg.connect(test_db_url)
    with c.cursor() as cur:
        cur.execute(f"DROP TABLE IF EXISTS {_TABLE} CASCADE")
    c.commit()
    try:
        yield c
    finally:
        with c.cursor() as cur:
            cur.execute(f"DROP TABLE IF EXISTS {_TABLE} CASCADE")
        c.commit()
        c.close()


def test_schema_valid_draft_2020_12() -> None:
    Draft202012Validator.check_schema(
        json.loads((_SCHEMAS_DIR / "migrate-current.schema.json").read_text())
    )


def test_applied_payload_validates(conn, cfg) -> None:
    Migrator(connection=conn, migration_table=_TABLE).initialize()
    with conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {_TABLE} (slug, version, name, applied_at, checksum) "
            f"VALUES (%s, %s, %s, %s, %s)",
            ("v1_a", "v1", "a", datetime(2026, 5, 31, tzinfo=UTC), "sha256:x"),
        )
    conn.commit()
    r = runner.invoke(app, ["migrate", "current", "-c", str(cfg), "--format", "json"])
    assert r.exit_code == 0, r.output
    _validator().validate(json.loads(r.stdout))


def test_empty_payload_validates(conn, cfg) -> None:
    Migrator(connection=conn, migration_table=_TABLE).initialize()
    conn.commit()
    r = runner.invoke(app, ["migrate", "current", "-c", str(cfg), "--format", "json"])
    assert r.exit_code == 0, r.output
    payload = json.loads(r.stdout)
    _validator().validate(payload)
    assert payload["revision"] is None
