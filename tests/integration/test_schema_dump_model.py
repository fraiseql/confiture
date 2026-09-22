"""``confiture schema dump-model``: the model's one wire form, the same bytes on every run.

A Rust ``build_schema`` once disagreed with Python about a digest because nobody
had pinned the bytes. The dump is what a port is checked against, so it is pinned
here: two runs — under different hash seeds, in separate processes — write the
same bytes, and the model inside is ``SchemaModel.to_json()``'s, from DDL or from
a database.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import psycopg
import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.core.schema_exporter import load_schema, schema_files
from confiture.platform import SchemaModel

runner = CliRunner()
REPO_ROOT = Path(__file__).resolve().parents[2]
EX08 = REPO_ROOT / "examples" / "08-generated-seeds" / "db" / "schema"
GOLDENS = REPO_ROOT / "tests" / "fixtures" / "model_goldens" / "model"
CONFITURE = str(Path(sys.executable).parent / "confiture")


def _validator() -> Draft202012Validator:
    registry = Registry().with_resources(
        (name, Resource.from_contents(load_schema(name), default_specification=DRAFT202012))
        for name in schema_files()
    )
    return Draft202012Validator(load_schema("schema-dump-model.schema.json"), registry=registry)


def _dump(*argv: str, seed: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONHASHSEED": seed}
    return subprocess.run(
        [CONFITURE, "schema", "dump-model", *argv],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


@pytest.mark.parametrize(
    "source",
    [
        ["--env", "local"],
        ["tests/fixtures/every_change/new.sql"],
        ["examples/02-fraiseql-integration/db/schema", "examples/08-generated-seeds/db/schema"],
    ],
    ids=["db-schema", "every-change", "routines-views-triggers"],
)
def test_two_processes_under_two_hash_seeds_write_the_same_bytes(source: list[str]) -> None:
    """`str` hashing is randomised per process; nothing in the wire may follow it."""
    first = _dump(*source, seed="1")
    second = _dump(*source, seed="2")
    assert first.returncode == 0, first.stderr
    assert json.loads(first.stdout)["model"], "an empty model proves nothing"
    assert first.stdout == second.stdout


def test_the_payload_is_the_model_in_the_envelope() -> None:
    result = runner.invoke(
        app, ["schema", "dump-model", "--env", "local", "--project-dir", str(REPO_ROOT)]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert list(payload) == ["model", "ok", "command", "parser"]
    assert payload["command"] == "schema dump-model"
    recorded = SchemaModel.from_json((GOLDENS / "db-schema.json").read_text())
    assert SchemaModel.from_json(json.dumps(payload["model"])) == recorded
    assert list(_validator().iter_errors(payload)) == []


def test_paths_are_read_in_order(tmp_path: Path) -> None:
    (tmp_path / "a.sql").write_text("CREATE TABLE t (x INT);\n")
    (tmp_path / "b.sql").write_text("ALTER TABLE t ADD COLUMN y TEXT;\n")
    result = runner.invoke(
        app, ["schema", "dump-model", str(tmp_path / "a.sql"), str(tmp_path / "b.sql")]
    )
    assert result.exit_code == 0, result.output
    (table,) = json.loads(result.stdout)["model"]["tables"]
    assert [c["name"] for c in table["columns"]] == ["x", "y"]


def test_a_database_dumps_the_same_wire(fresh_database: str) -> None:
    with psycopg.connect(fresh_database, autocommit=True) as conn:
        for sql in sorted(EX08.rglob("*.sql")):
            conn.execute(sql.read_text())
    result = runner.invoke(
        app,
        [
            "schema",
            "dump-model",
            "--database-url",
            fresh_database,
            "--schemas",
            "prep_seed,catalog",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert list(_validator().iter_errors(payload)) == []
    names = sorted(f"{t['schema']}.{t['name']}" for t in payload["model"]["tables"])
    assert names == [
        "catalog.tb_product",
        "catalog.tb_vendor",
        "prep_seed.tb_product",
        "prep_seed.tb_vendor",
    ]


def test_text_names_what_the_model_holds(tmp_path: Path) -> None:
    (tmp_path / "s.sql").write_text("CREATE TABLE t (x INT);\nCREATE VIEW v AS SELECT x FROM t;\n")
    result = runner.invoke(
        app, ["schema", "dump-model", str(tmp_path / "s.sql"), "--format", "text"]
    )
    assert result.exit_code == 0, result.output
    assert "1 table" in result.output
    assert "1 view" in result.output


@pytest.mark.parametrize(
    "argv",
    [[], ["db/schema", "--env", "local"], ["--env", "local", "--database-url", "postgresql://x/y"]],
    ids=["no-source", "paths-and-env", "env-and-database"],
)
def test_it_reads_exactly_one_source(argv: list[str]) -> None:
    result = runner.invoke(app, ["schema", "dump-model", *argv])
    assert result.exit_code == 2, result.output
    assert "exactly one source" in result.output


def test_ddl_postgresql_rejects_is_the_error_envelope(tmp_path: Path) -> None:
    (tmp_path / "bad.sql").write_text("CREATE TABLE (;\n")
    result = runner.invoke(app, ["schema", "dump-model", str(tmp_path / "bad.sql")])
    assert result.exit_code == 5, result.output
    envelope = json.loads(result.stdout)
    assert (envelope["ok"], envelope["error"]["code"]) == (False, "DIFFER_400")
