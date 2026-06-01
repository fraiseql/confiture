"""Integration tests for `migrate current` and MigratorSession.current_revision (#141).

Each test uses an isolated tracking table (dropped up front) so it does not
depend on or pollute the shared tb_confiture state in confiture_test.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
import pytest
import yaml
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.core.migrator import Migrator
from confiture.exceptions import DatabaseNotInitializedError

runner = CliRunner()
_TABLE = "tb_current_it"


def _drop(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute(f"DROP TABLE IF EXISTS {_TABLE} CASCADE")
    conn.commit()


def _create_empty(conn: psycopg.Connection) -> None:
    Migrator(connection=conn, migration_table=_TABLE).initialize()
    conn.commit()


def _insert(
    conn: psycopg.Connection, version: str, name: str, applied_at: datetime, checksum=None
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {_TABLE} (slug, version, name, applied_at, checksum) "
            f"VALUES (%s, %s, %s, %s, %s)",
            (f"{version}_{name}", version, name, applied_at, checksum),
        )
    conn.commit()


def _connect(url):
    """Connect, or skip when no DB is reachable (mirrors test_db_connection)."""
    try:
        return psycopg.connect(url)
    except psycopg.OperationalError as e:
        pytest.skip(f"PostgreSQL not available: {e}")


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
def conn(test_db_url: str):
    c = _connect(test_db_url)
    try:
        _drop(c)
        yield c
    finally:
        _drop(c)
        c.close()


def _seed_three(conn: psycopg.Connection) -> str:
    _create_empty(conn)
    base = datetime(2026, 5, 31, 14, 0, 0, tzinfo=UTC)
    _insert(conn, "20260531_1400_a", "a", base, "sha256:aaa")
    _insert(conn, "20260531_1415_b", "b", base + timedelta(minutes=15), "sha256:bbb")
    _insert(conn, "20260531_1430_c", "c", base + timedelta(minutes=30), "sha256:ccc")
    return "20260531_1430_c"


# ── session API ───────────────────────────────────────────────────────────────


def test_current_revision_returns_latest(conn, cfg) -> None:
    latest = _seed_three(conn)
    with Migrator.from_config(str(cfg)) as s:
        cur = s.current_revision()
    assert cur is not None
    assert cur.version == latest
    assert cur.applied_at is not None
    assert cur.checksum == "sha256:ccc"


def test_current_revision_none_when_empty(conn, cfg) -> None:
    _create_empty(conn)
    with Migrator.from_config(str(cfg)) as s:
        assert s.current_revision() is None


def test_current_revision_raises_when_table_absent(conn, cfg) -> None:
    # conn fixture dropped the table; do not create it.
    with Migrator.from_config(str(cfg)) as s:
        with pytest.raises(DatabaseNotInitializedError) as e:
            s.current_revision()
    assert e.value.error_code == "PRECON_1001"
    assert e.value.exit_code == 2


# ── CLI ─────────────────────────────────────────────────────────────────────


def test_current_human_prints_bare_revision(conn, cfg) -> None:
    latest = _seed_three(conn)
    r = runner.invoke(app, ["migrate", "current", "-c", str(cfg)])
    assert r.exit_code == 0, r.output
    assert r.output.strip() == latest


def test_current_json(conn, cfg) -> None:
    latest = _seed_three(conn)
    r = runner.invoke(app, ["migrate", "current", "-c", str(cfg), "--format", "json"])
    assert r.exit_code == 0, r.output
    payload = json.loads(r.stdout)
    assert payload["revision"] == latest
    assert payload["applied_at"] is not None
    assert payload["checksum"] == "sha256:ccc"


def test_current_empty_table_exit0_null(conn, cfg) -> None:
    _create_empty(conn)
    r = runner.invoke(app, ["migrate", "current", "-c", str(cfg), "--format", "json"])
    assert r.exit_code == 0, r.output
    assert json.loads(r.stdout)["revision"] is None


def test_current_absent_table_exit2(conn, cfg) -> None:
    r = runner.invoke(app, ["migrate", "current", "-c", str(cfg)])
    assert r.exit_code == 2, r.output


def test_current_absent_table_json_envelope(conn, cfg) -> None:
    r = runner.invoke(app, ["migrate", "current", "-c", str(cfg), "--format", "json"])
    assert r.exit_code == 2, r.output
    payload = json.loads(r.stdout)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "PRECON_1001"


def test_current_baseline_null_checksum(conn, cfg) -> None:
    """A row applied without a checksum (e.g. via baseline) emits checksum: null."""
    _create_empty(conn)
    _insert(conn, "20260101_0000_base", "base", datetime(2026, 1, 1, tzinfo=UTC), None)
    r = runner.invoke(app, ["migrate", "current", "-c", str(cfg), "--format", "json"])
    assert r.exit_code == 0, r.output
    payload = json.loads(r.stdout)
    assert payload["revision"] == "20260101_0000_base"
    assert payload["checksum"] is None
