"""``confiture migrate rebuild``, run by its command line against a real database.

fraisier drives this command at deploy time — ``fraisier/dbops/confiture.py``
runs ``confiture migrate rebuild -c <config> -y --drop-schemas`` — so the first
test uses that argv verbatim. The rest pin what the flags promise: ``--dry-run``
changes nothing, ``--seed``/``--verify`` report what they did, ``--backup-tracking``
keeps the ledger it is about to clear, and a schema that cannot be built drops
nothing, because the build runs before the first ``DROP SCHEMA``.

Every test runs in a database of its own: ``--drop-schemas`` drops every user
schema it can see.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
import yaml
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.error_codes import exit_code_of

pytestmark = pytest.mark.integration

runner = CliRunner()

_VERSIONS = ("20260101000000", "20260102000000")


@pytest.fixture
def project(tmp_path: Path, fresh_database: str) -> Iterator[Path]:
    """A project whose DDL declares ``widgets``, with two migrations and one seed."""
    schema = tmp_path / "db" / "schema"
    schema.mkdir(parents=True)
    (schema / "10_widgets.sql").write_text(
        "CREATE TABLE widgets (id BIGINT PRIMARY KEY, label TEXT NOT NULL);\n"
    )
    migrations = tmp_path / "db" / "migrations"
    migrations.mkdir(parents=True)
    for version, name in zip(_VERSIONS, ("create_widgets", "add_label"), strict=True):
        (migrations / f"{version}_{name}.up.sql").write_text("SELECT 1;\n")
        (migrations / f"{version}_{name}.down.sql").write_text("SELECT 1;\n")
    seeds = tmp_path / "db" / "seeds"
    seeds.mkdir(parents=True)
    (seeds / "01_widgets.sql").write_text("INSERT INTO widgets VALUES (1, 'first');\n")
    (tmp_path / "confiture.yaml").write_text(
        yaml.safe_dump(
            {"name": "test", "database_url": fresh_database, "include_dirs": ["db/schema"]}
        )
    )
    old = Path.cwd()
    os.chdir(tmp_path)
    try:
        yield tmp_path
    finally:
        os.chdir(old)


@pytest.fixture
def db(fresh_database: str) -> Iterator[psycopg.Connection]:
    """The project's database, holding what a restored backup would: a stale
    ``widgets`` without ``label`` and a schema the DDL does not declare."""
    with psycopg.connect(fresh_database, autocommit=True) as conn:
        conn.execute("CREATE TABLE widgets (id BIGINT PRIMARY KEY)")
        conn.execute("CREATE SCHEMA legacy")
        conn.execute("CREATE TABLE legacy.junk (id INT)")
        yield conn


def _schemas(conn: psycopg.Connection) -> set[str]:
    rows = conn.execute("SELECT nspname FROM pg_namespace WHERE nspname NOT LIKE 'pg\\_%'")
    return {row[0] for row in rows} - {"information_schema"}


def _columns(conn: psycopg.Connection, table: str) -> list[str]:
    rows = conn.execute(
        "SELECT attname FROM pg_attribute WHERE attrelid = %s::regclass "
        "AND attnum > 0 AND NOT attisdropped ORDER BY attnum",
        (table,),
    )
    return [row[0] for row in rows]


def _ledger(conn: psycopg.Connection) -> list[str]:
    return [row[0] for row in conn.execute("SELECT version FROM tb_confiture ORDER BY version")]


def _json(stdout: str) -> dict:
    """The payload, which must be all of stdout: a consumer parses the stream."""
    return json.loads(stdout)


def test_fraisiers_argv_rebuilds_the_database_from_its_ddl(
    project: Path, db: psycopg.Connection
) -> None:
    result = runner.invoke(
        app, ["migrate", "rebuild", "-c", "confiture.yaml", "-y", "--drop-schemas"]
    )

    assert result.exit_code == 0, result.output
    assert _schemas(db) == {"public"}
    assert _columns(db, "widgets") == ["id", "label"]
    assert _ledger(db) == list(_VERSIONS)


def test_a_rebuilt_database_has_nothing_pending(project: Path, db: psycopg.Connection) -> None:
    rebuilt = runner.invoke(
        app, ["migrate", "rebuild", "-c", "confiture.yaml", "-y", "--drop-schemas"]
    )
    assert rebuilt.exit_code == 0, rebuilt.output

    status = runner.invoke(app, ["migrate", "status", "-c", "confiture.yaml", "--format", "json"])

    assert status.exit_code == 0, status.output
    assert _json(status.stdout)["summary"]["pending"] == 0


def test_dry_run_reports_the_plan_and_changes_nothing(
    project: Path, db: psycopg.Connection
) -> None:
    result = runner.invoke(
        app,
        [
            "migrate",
            "rebuild",
            "-c",
            "confiture.yaml",
            "--drop-schemas",
            "--dry-run",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = _json(result.stdout)
    assert payload["dry_run"] is True
    assert sorted(payload["schemas_dropped"]) == ["legacy", "public"]
    assert [m["version"] for m in payload["marked"]] == list(_VERSIONS)
    assert _schemas(db) == {"legacy", "public"}
    assert _columns(db, "widgets") == ["id"]


def test_seed_and_verify_do_what_they_report(project: Path, db: psycopg.Connection) -> None:
    result = runner.invoke(
        app,
        [
            "migrate",
            "rebuild",
            "-c",
            "confiture.yaml",
            "-y",
            "--drop-schemas",
            "--seed",
            "--verify",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = _json(result.stdout)
    assert (payload["seeds_applied"], payload["verified"]) == (1, True)
    assert db.execute("SELECT label FROM widgets").fetchall() == [("first",)]


def test_backup_tracking_keeps_the_ledger_it_clears(project: Path, db: psycopg.Connection) -> None:
    first = runner.invoke(
        app, ["migrate", "rebuild", "-c", "confiture.yaml", "-y", "--drop-schemas"]
    )
    assert first.exit_code == 0, first.output
    db.execute("DELETE FROM tb_confiture WHERE version = %s", (_VERSIONS[1],))

    result = runner.invoke(
        app,
        ["migrate", "rebuild", "-c", "confiture.yaml", "-y", "--drop-schemas", "--backup-tracking"],
    )

    assert result.exit_code == 0, result.output
    (backup,) = project.glob("tb_confiture_backup_*.json")
    assert [row["version"] for row in json.loads(backup.read_text())] == [_VERSIONS[0]]
    assert _ledger(db) == list(_VERSIONS)


def test_a_schema_that_cannot_be_built_drops_nothing(project: Path, db: psycopg.Connection) -> None:
    config = yaml.safe_load((project / "confiture.yaml").read_text())
    config["include_dirs"] = ["db/no_such_dir"]
    (project / "confiture.yaml").write_text(yaml.safe_dump(config))

    result = runner.invoke(
        app,
        ["migrate", "rebuild", "-c", "confiture.yaml", "-y", "--drop-schemas", "--format", "json"],
    )

    assert result.exit_code == exit_code_of("MIGR_001"), result.output
    assert _schemas(db) == {"legacy", "public"}
    assert _columns(db, "widgets") == ["id"]
