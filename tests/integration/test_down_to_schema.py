"""Validate `migrate down-to --format json` output against its schema (#142)."""

from __future__ import annotations

import json
from pathlib import Path

import psycopg
import pytest
import yaml
from jsonschema import Draft202012Validator
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.core.migrator import Migrator

runner = CliRunner()
_TABLE = "tb_downto_schema_it"
_SCHEMAS_DIR = Path(__file__).resolve().parents[2] / "docs" / "reference" / "json-schemas"
_VERSIONS = [("20260101000001", "a"), ("20260102000002", "b"), ("20260103000003", "c")]


def _tname(name: str) -> str:
    return f"tb_dts_{name}"


def _validator() -> Draft202012Validator:
    return Draft202012Validator(
        json.loads((_SCHEMAS_DIR / "migrate-down-to.schema.json").read_text())
    )


@pytest.fixture
def conn(test_db_url: str):
    c = psycopg.connect(test_db_url)

    def _clean() -> None:
        with c.cursor() as cur:
            cur.execute(f"DROP TABLE IF EXISTS {_TABLE} CASCADE")
            for _v, n in _VERSIONS:
                cur.execute(f"DROP TABLE IF EXISTS {_tname(n)} CASCADE")
        c.commit()

    _clean()
    try:
        yield c
    finally:
        _clean()
        c.close()


@pytest.fixture
def project(tmp_path: Path, test_db_url: str):
    md = tmp_path / "migrations"
    md.mkdir()
    for version, name in _VERSIONS:
        tbl = _tname(name)
        (md / f"{version}_{name}.up.sql").write_text(f"CREATE TABLE {tbl} (id int);")
        (md / f"{version}_{name}.down.sql").write_text(f"DROP TABLE {tbl};")
    cfg = tmp_path / "env.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "name": "test",
                "database_url": test_db_url,
                "include_dirs": ["db/schema"],
                "migration": {"tracking_table": _TABLE},
            }
        )
    )
    with Migrator.from_config(str(cfg), migrations_dir=md) as s:
        s.up()
    return cfg, md


def test_schema_valid_draft_2020_12() -> None:
    Draft202012Validator.check_schema(
        json.loads((_SCHEMAS_DIR / "migrate-down-to.schema.json").read_text())
    )


def test_down_to_payload_validates(conn, project) -> None:
    cfg, md = project
    r = runner.invoke(
        app,
        [
            "migrate",
            "down-to",
            "20260101000001",
            "-c",
            str(cfg),
            "--migrations-dir",
            str(md),
            "--format",
            "json",
        ],
    )
    assert r.exit_code == 0, r.output
    _validator().validate(json.loads(r.stdout))
