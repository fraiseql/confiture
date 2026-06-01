"""Integration tests for `migrate down-to` and MigratorSession.down_to (#142).

Uses an isolated tracking table and uniquely-named target tables so the tests
neither depend on nor pollute the shared confiture_test state.
"""

from __future__ import annotations

import json
from pathlib import Path

import psycopg
import pytest
import yaml
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.core.migrator import Migrator
from confiture.exceptions import MigrationError, RollbackError

runner = CliRunner()
_TABLE = "tb_downto_it"
_VERSIONS = [
    ("20260101000001", "a"),
    ("20260102000002", "b"),
    ("20260103000003", "c"),
    ("20260104000004", "d"),
]


def _tname(name: str) -> str:
    return f"tb_dt_{name}"


def _write_migrations(migrations_dir: Path, *, omit_down: set[str] | None = None) -> None:
    omit_down = omit_down or set()
    for version, name in _VERSIONS:
        tbl = _tname(name)
        (migrations_dir / f"{version}_{name}.up.sql").write_text(f"CREATE TABLE {tbl} (id int);")
        if name not in omit_down:
            (migrations_dir / f"{version}_{name}.down.sql").write_text(f"DROP TABLE {tbl};")


def _connect(url):
    """Connect, or skip when no DB is reachable (mirrors test_db_connection)."""
    try:
        return psycopg.connect(url)
    except psycopg.OperationalError as e:
        pytest.skip(f"PostgreSQL not available: {e}")


@pytest.fixture
def conn(test_db_url: str):
    c = _connect(test_db_url)

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
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
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
    return cfg, migrations_dir


def _apply_all(cfg: Path, migrations_dir: Path) -> None:
    with Migrator.from_config(str(cfg), migrations_dir=migrations_dir) as s:
        s.up()


def _table_exists(conn: psycopg.Connection, name: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass(%s)", (name,))
        return cur.fetchone()[0] is not None


# ── session API ───────────────────────────────────────────────────────────────


def test_down_to_rolls_back_to_target(conn, project) -> None:
    cfg, md = project
    _write_migrations(md)
    _apply_all(cfg, md)

    with Migrator.from_config(str(cfg), migrations_dir=md) as s:
        result = s.down_to("20260102000002")
    assert result.to == "20260102000002"
    assert result.from_ == "20260104000004"
    assert result.rolled_back == ["20260104000004", "20260103000003"]

    # c and d rolled back (tables dropped); a and b remain.
    assert _table_exists(conn, _tname("a"))
    assert _table_exists(conn, _tname("b"))
    assert not _table_exists(conn, _tname("c"))
    assert not _table_exists(conn, _tname("d"))

    with Migrator.from_config(str(cfg), migrations_dir=md) as s:
        assert s.current_revision().version == "20260102000002"  # reuses #141


def test_down_to_noop_when_already_there(conn, project) -> None:
    cfg, md = project
    _write_migrations(md)
    _apply_all(cfg, md)
    with Migrator.from_config(str(cfg), migrations_dir=md) as s:
        result = s.down_to("20260104000004")
    assert result.rolled_back == []
    assert result.noop


def test_down_to_missing_down_raises_before_applying(conn, project) -> None:
    cfg, md = project
    _write_migrations(md)
    _apply_all(cfg, md)
    # Remove c's .down.sql after applying → reaching past it is irreversible.
    (md / "20260103000003_c.down.sql").unlink()

    with Migrator.from_config(str(cfg), migrations_dir=md) as s:
        before = s.current_revision().version
        with pytest.raises(RollbackError) as e:
            s.down_to("20260101000001")
    assert e.value.error_code == "ROLLBACK_600"
    assert "20260103000003" in str(e.value)
    # NOTHING rolled back — atomic refusal.
    with Migrator.from_config(str(cfg), migrations_dir=md) as s:
        assert s.current_revision().version == before
    assert _table_exists(conn, _tname("c"))
    assert _table_exists(conn, _tname("d"))


def test_down_to_unknown_revision_raises(conn, project) -> None:
    cfg, md = project
    _write_migrations(md)
    _apply_all(cfg, md)
    with Migrator.from_config(str(cfg), migrations_dir=md) as s:
        with pytest.raises(MigrationError) as e:
            s.down_to("nope")
    assert e.value.error_code == "MIGR_100"


# ── CLI ─────────────────────────────────────────────────────────────────────


def test_down_to_json_plan_and_result(conn, project) -> None:
    cfg, md = project
    _write_migrations(md)
    _apply_all(cfg, md)
    r = runner.invoke(
        app,
        [
            "migrate",
            "down-to",
            "20260102000002",
            "-c",
            str(cfg),
            "--migrations-dir",
            str(md),
            "--format",
            "json",
        ],
    )
    assert r.exit_code == 0, r.output
    p = json.loads(r.stdout)
    assert p["from"] == "20260104000004"
    assert p["to"] == "20260102000002"
    assert p["rolled_back"] == ["20260104000004", "20260103000003"]
    assert p["skipped"] == []
    assert p["errors"] == []


def test_down_to_unknown_revision_exits_3(conn, project) -> None:
    cfg, md = project
    _write_migrations(md)
    _apply_all(cfg, md)
    r = runner.invoke(
        app,
        ["migrate", "down-to", "nope", "-c", str(cfg), "--migrations-dir", str(md)],
    )
    assert r.exit_code == 3, r.output


def test_down_to_irreversible_aborts_exit_8(conn, project) -> None:
    cfg, md = project
    _write_migrations(md)
    _apply_all(cfg, md)
    (md / "20260103000003_c.down.sql").unlink()
    r = runner.invoke(
        app,
        ["migrate", "down-to", "20260101000001", "-c", str(cfg), "--migrations-dir", str(md)],
    )
    assert r.exit_code == 8, r.output  # ROLLBACK_600 → 8
    # DB unchanged — atomic-refusal guarantee.
    assert _table_exists(conn, _tname("c"))
    assert _table_exists(conn, _tname("d"))


def test_down_to_dry_run_does_not_apply(conn, project) -> None:
    cfg, md = project
    _write_migrations(md)
    _apply_all(cfg, md)
    r = runner.invoke(
        app,
        [
            "migrate",
            "down-to",
            "20260102000002",
            "-c",
            str(cfg),
            "--migrations-dir",
            str(md),
            "--dry-run",
            "--format",
            "json",
        ],
    )
    assert r.exit_code == 0, r.output
    p = json.loads(r.stdout)
    assert p["rolled_back"] == ["20260104000004", "20260103000003"]
    # Nothing actually rolled back.
    assert _table_exists(conn, _tname("c"))
    assert _table_exists(conn, _tname("d"))


def test_down_to_noop_cli(conn, project) -> None:
    cfg, md = project
    _write_migrations(md)
    _apply_all(cfg, md)
    r = runner.invoke(
        app,
        ["migrate", "down-to", "20260104000004", "-c", str(cfg), "--migrations-dir", str(md)],
    )
    assert r.exit_code == 0, r.output
    assert "already at" in r.output.lower()
