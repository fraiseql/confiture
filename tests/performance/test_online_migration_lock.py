"""The online run never holds the table as long as the rewrite it replaces.

A type change on 200 000 wide rows rewrites the table under ACCESS EXCLUSIVE
for as long as the rewrite takes; ``migrate up --online`` runs it as expand,
backfill and contract, each statement a metadata change. A sampler on a second
connection watches ``pg_locks`` and reports the longest continuous
ACCESS EXCLUSIVE hold on the table: under 100 ms online, and below the classic
rewrite's on the same machine. A wall-clock bound, so a benchmark.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import psycopg
import pytest
from typer.testing import CliRunner

from confiture.cli.main import app

pytestmark = pytest.mark.benchmark

runner = CliRunner()
ROWS = 200_000
VERSION = "20260101000000"
SQL = "ALTER TABLE orders ALTER COLUMN total TYPE bigint;\n"


class LockSampler:
    """The longest continuous ACCESS EXCLUSIVE hold on a table, sampled from another connection."""

    def __init__(self, url: str, table: str, interval: float = 0.001) -> None:
        self._url, self._table, self._interval = url, table, interval
        self.longest_ms = 0.0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._sample, daemon=True)

    def __enter__(self) -> LockSampler:
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        self._thread.join(timeout=5)

    def _sample(self) -> None:
        held_since: float | None = None
        with psycopg.connect(self._url, autocommit=True) as conn:
            while not self._stop.is_set():
                held = conn.execute(
                    "SELECT count(*) FROM pg_locks WHERE granted AND mode = 'AccessExclusiveLock' "
                    "AND relation = %s::regclass AND pid <> pg_backend_pid()",
                    (self._table,),
                ).fetchone()[0]
                now = time.perf_counter()
                if held:
                    held_since = held_since if held_since is not None else now
                    self.longest_ms = max(self.longest_ms, (now - held_since) * 1000)
                else:
                    held_since = None
                time.sleep(self._interval)


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


def test_online_never_holds_the_table_as_long_as_the_rewrite(
    clean_test_db: psycopg.Connection, test_db_url: str, tmp_path: Path
) -> None:
    _orders(clean_test_db)
    config, migrations = _project(tmp_path, test_db_url)
    common = ["--migrations-dir", str(migrations), "--config", str(config)]

    with LockSampler(test_db_url, "orders") as classic:
        with clean_test_db.cursor() as cur:
            cur.execute(SQL)  # the classic rewrite, for the yardstick
        clean_test_db.commit()
    with clean_test_db.cursor() as cur:
        cur.execute("ALTER TABLE orders ALTER COLUMN total TYPE integer")
    clean_test_db.commit()

    with LockSampler(test_db_url, "orders") as online:
        result = runner.invoke(app, ["migrate", "up", "--online", "--allow-destructive", *common])
    assert result.exit_code == 0, result.output

    assert _widened(clean_test_db) == ("bigint", ROWS)
    assert online.longest_ms < 100, f"online held ACCESS EXCLUSIVE for {online.longest_ms:.0f} ms"
    assert online.longest_ms < classic.longest_ms, (online.longest_ms, classic.longest_ms)
    with clean_test_db.cursor() as cur:
        cur.execute("SELECT version FROM tb_confiture")
        assert cur.fetchall() == [(VERSION,)]
