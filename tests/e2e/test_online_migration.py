"""``migrate up --online`` runs a rewrite as expand → backfill → contract, never holding the table long.

A type change rewrites the table; online, the same change is a new column, a
dual-write trigger, a batched backfill and a swap, each stage checkpointed. A
run that dies mid-backfill is resumed by ``migrate steps --resume`` with every
row accounted for. The lock measurement lives with the benchmarks
(``tests/performance/test_online_migration_lock.py``). Against the local
database, 200 000 rows.
"""

from __future__ import annotations

from pathlib import Path

import psycopg
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.core import migrator as _core_migrator
from confiture.core._migrator.events import UpEvent

runner = CliRunner()
ROWS = 200_000
VERSION = "20260101000000"
SQL = "ALTER TABLE orders ALTER COLUMN total TYPE bigint;\n"


def _project(tmp_path: Path, test_db_url: str) -> tuple[Path, Path]:
    config = tmp_path / "local.yaml"
    config.write_text(f"name: test\ndatabase_url: {test_db_url}\n")
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / f"{VERSION}_widen_total.up.sql").write_text(SQL)
    (migrations / f"{VERSION}_widen_total.down.sql").write_text(
        "ALTER TABLE orders ALTER COLUMN total TYPE integer;\n"
    )
    return config, migrations


def _orders(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "CREATE TABLE orders (id integer PRIMARY KEY, total integer NOT NULL, note text)"
        )
        cur.execute(
            "INSERT INTO orders SELECT g, g, repeat('x', 256) FROM generate_series(1, %s) g",
            (ROWS,),
        )
    conn.commit()


def _widened(conn: psycopg.Connection) -> tuple[str, int]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_name = 'orders' AND column_name = 'total'"
        )
        data_type = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM orders WHERE total = id")
        return data_type, cur.fetchone()[0]


def test_online_applies_a_rewrite_as_stages(
    clean_test_db: psycopg.Connection, test_db_url: str, tmp_path: Path
) -> None:
    _orders(clean_test_db)
    config, migrations = _project(tmp_path, test_db_url)
    common = ["--migrations-dir", str(migrations), "--config", str(config)]

    result = runner.invoke(app, ["migrate", "up", "--online", "--allow-destructive", *common])
    assert result.exit_code == 0, result.output

    assert _widened(clean_test_db) == ("bigint", ROWS)
    with clean_test_db.cursor() as cur:
        cur.execute("SELECT version FROM tb_confiture")
        assert cur.fetchall() == [(VERSION,)]
        cur.execute("SELECT stage, state FROM tb_confiture_steps ORDER BY updated_at")
        assert cur.fetchall() == [("expand", "done"), ("backfill", "done"), ("contract", "done")]
    clean_test_db.rollback()


class Crash(Exception):
    """The process dying mid-backfill."""


def test_a_crash_mid_backfill_is_resumed_with_every_row(
    clean_test_db: psycopg.Connection, test_db_url: str, tmp_path: Path
) -> None:
    _orders(clean_test_db)
    config, migrations = _project(tmp_path, test_db_url)
    seen = {"batches": 0}

    def die_on_the_third_batch(event: UpEvent) -> None:
        if event.kind == "backfill_progress":
            seen["batches"] += 1
            if seen["batches"] == 3:
                raise Crash("died mid-backfill")

    # The apply loop reports a migration that raises as a failed migration — the
    # same state a killed process leaves: a checkpoint, no ledger row.
    with _core_migrator.MigratorSession(
        None, migrations, database_url_override=test_db_url, command="test"
    ) as session:
        result = session.up(online=True, allow_destructive=True, on_event=die_on_the_third_batch)
    assert result.success is False, result
    assert any("died mid-backfill" in error for error in result.errors), result.errors

    with clean_test_db.cursor() as cur:
        cur.execute("SELECT count(*) FROM orders WHERE total__new IS NOT NULL")
        partial = cur.fetchone()[0]
    clean_test_db.rollback()  # or this connection's open transaction blocks the resume's DDL
    assert 0 < partial < ROWS

    resumed = runner.invoke(
        app,
        ["migrate", "steps", "--resume", VERSION, "--allow-destructive",
         "--migrations-dir", str(migrations), "--config", str(config)],
    )  # fmt: skip
    assert resumed.exit_code == 0, resumed.output
    assert _widened(clean_test_db) == ("bigint", ROWS)
