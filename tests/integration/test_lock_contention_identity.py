"""Lock-contention identity surfacing via the migrate CLI (issue #147, Phase 2).

Writer A holds the migration lock on a real connection; the second writer hits
contention and must surface A's identity in stderr (human) and the #145
envelope (JSON).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import psycopg
import pytest
import yaml
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.core.locking import LOCK_HOLDER_TABLE, LockConfig, MigrationLock

runner = CliRunner()
_TABLE = "tb_lockid_it"


@pytest.fixture
def cfg(tmp_path: Path, test_db_url: str) -> Path:
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
def migrations_dir(tmp_path: Path) -> Path:
    d = tmp_path / "migrations"
    d.mkdir()
    (d / "20260101000001_a.up.sql").write_text("SELECT 1;")
    (d / "20260101000001_a.down.sql").write_text("SELECT 1;")
    return d


@pytest.fixture
def holder_connection(test_db_url: str):
    """A connection that holds the real migration lock + writes its identity."""
    conn = psycopg.connect(test_db_url)
    # Use the real (db-derived) lock id so the CLI's lock collides with ours.
    lock = MigrationLock(conn, LockConfig(command="confiture migrate up"))
    acquired = lock.acquire()
    acquired.__enter__()
    try:
        yield conn
    finally:
        acquired.__exit__(None, None, None)
        with conn.cursor() as cur:
            cur.execute(f"DROP TABLE IF EXISTS {LOCK_HOLDER_TABLE} CASCADE")
            cur.execute(f"DROP TABLE IF EXISTS {_TABLE} CASCADE")
        conn.commit()
        conn.close()


def test_contention_json_surfaces_holder(holder_connection, cfg, migrations_dir) -> None:
    result = runner.invoke(
        app,
        ["migrate", "up", "-c", str(cfg), "--migrations-dir", str(migrations_dir),
         "--lock-timeout", "500", "--format", "json"],
    )
    assert result.exit_code == 6, result.output  # LOCK_1300 → 6
    # migrate up prints human progress preamble before the error envelope in
    # JSON mode (pre-existing); the envelope is the final JSON document.
    payload = json.loads(result.stdout[result.stdout.index("{") :])
    assert payload["ok"] is False
    assert payload["error"]["code"] == "LOCK_1300"
    holder = payload["error"]["details"]["holder"]
    assert holder["pid"] == os.getpid()
    assert holder["command"] == "confiture migrate up"
    assert holder["held_for_seconds"] >= 0


def test_contention_human_names_holder(holder_connection, cfg, migrations_dir) -> None:
    result = runner.invoke(
        app,
        ["migrate", "up", "-c", str(cfg), "--migrations-dir", str(migrations_dir),
         "--lock-timeout", "500"],
    )
    assert result.exit_code == 6, result.output
    # Human output names the holder (command + pid).
    assert "confiture migrate up" in result.output
    assert str(os.getpid()) in result.output
