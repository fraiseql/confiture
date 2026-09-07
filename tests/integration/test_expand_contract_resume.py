"""An online run that dies between stages resumes from its checkpoint, through ``migrate steps``.

Each stage of an expand/contract plan is recorded in ``tb_confiture_steps``
as it starts and as it finishes. A process that dies after ``expand`` leaves
the row behind; ``migrate steps`` lists it, ``migrate steps --resume``
continues from the first stage not done, and only when ``contract`` has
finished does the migration reach the ledger. Against the local database.
"""

from __future__ import annotations

import json
from pathlib import Path

import psycopg
import pytest
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.core._migrator.events import UpEvent
from confiture.core.expand_contract import plan
from confiture.core.schema_facts import server_major
from confiture.core.step_runner import CheckpointStore, run

runner = CliRunner()
VERSION = "20260101000000"
SQL = "ALTER TABLE orders ADD COLUMN status text NOT NULL DEFAULT 'new';\n"


class Crash(Exception):
    """The process dying — raised from the observer after a stage finishes."""


def _project(tmp_path: Path, test_db_url: str) -> list[str]:
    config = tmp_path / "local.yaml"
    config.write_text(f"name: test\ndatabase_url: {test_db_url}\n")
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / f"{VERSION}_add_status.up.sql").write_text(SQL)
    (migrations / f"{VERSION}_add_status.down.sql").write_text(
        "ALTER TABLE orders DROP COLUMN status;\n"
    )
    return ["--config", str(config), "--migrations-dir", str(migrations)]


def _column(conn: psycopg.Connection) -> tuple[str, str] | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT is_nullable, column_default FROM information_schema.columns "
            "WHERE table_name = 'orders' AND column_name = 'status'"
        )
        return cur.fetchone()


def _crash_after(stage: str):
    def observer(event: UpEvent) -> None:
        if event.kind == "stage_done" and event.name == stage:
            raise Crash(stage)

    return observer


def test_a_crash_after_expand_is_resumed_by_migrate_steps(
    clean_test_db: psycopg.Connection, test_db_url: str, tmp_path: Path
) -> None:
    with clean_test_db.cursor() as cur:
        cur.execute("CREATE TABLE orders (id integer PRIMARY KEY)")
        cur.execute("INSERT INTO orders SELECT g FROM generate_series(1, 1000) g")
    clean_test_db.commit()
    common = _project(tmp_path, test_db_url)
    store = CheckpointStore(clean_test_db)
    store.ensure()
    staged = plan(SQL, server_version=server_major(clean_test_db))[0]

    with pytest.raises(Crash):
        run(staged, clean_test_db, migration=VERSION, store=store, on_event=_crash_after("expand"))

    # The expand stage landed and is on record; nothing after it ran.
    assert _column(clean_test_db) == ("YES", "'new'::text")
    listed = runner.invoke(app, ["migrate", "steps", "--format", "json", *common])
    assert listed.exit_code == 0, listed.output
    steps = json.loads(listed.output)["steps"]
    assert [(s["migration"], s["stage"], s["state"]) for s in steps] == [
        (VERSION, "expand", "done")
    ]

    resumed = runner.invoke(app, ["migrate", "steps", "--resume", VERSION, *common])
    assert resumed.exit_code == 0, resumed.output

    assert _column(clean_test_db) == ("NO", "'new'::text")
    states = {s.stage: s.state for s in store.records(VERSION)}
    assert states == {"expand": "done", "backfill": "done", "contract": "done"}
    with clean_test_db.cursor() as cur:
        cur.execute("SELECT version FROM tb_confiture")
        assert cur.fetchall() == [(VERSION,)]
    with clean_test_db.cursor() as cur:
        cur.execute("SELECT count(*) FROM orders WHERE status = 'new'")
        assert cur.fetchone() == (1000,)


def test_the_ledger_is_written_only_after_contract(
    clean_test_db: psycopg.Connection, test_db_url: str, tmp_path: Path
) -> None:
    with clean_test_db.cursor() as cur:
        cur.execute("CREATE TABLE orders (id integer PRIMARY KEY)")
    clean_test_db.commit()
    _project(tmp_path, test_db_url)
    store = CheckpointStore(clean_test_db)
    store.ensure()
    staged = plan(SQL, server_version=server_major(clean_test_db))[0]

    with pytest.raises(Crash):
        run(
            staged, clean_test_db, migration=VERSION, store=store, on_event=_crash_after("backfill")
        )

    assert {s.stage: s.state for s in store.records(VERSION)} == {
        "expand": "done",
        "backfill": "done",
    }
    with clean_test_db.cursor() as cur:
        cur.execute("SELECT to_regclass('tb_confiture')")
        ledger = cur.fetchone()[0]
    assert (
        ledger is None
    )  # the runner never touches the ledger; `migrate steps --resume` does, after contract
