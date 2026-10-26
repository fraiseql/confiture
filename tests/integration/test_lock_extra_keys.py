"""``locking.extra_keys``: ``migrate up``/``down`` also take another tool's advisory key (#768).

FraiseQL's boot DDL takes ``pg_advisory_xact_lock(0x4652414953450001)``, one
``bigint``; confiture's own lock is two ``int4`` keys. PostgreSQL keeps the two
forms apart, so the locks never contend unless confiture takes the other key too.
Each test holds the key on a second session the way FraiseQL does — inside an
open transaction — and watches what confiture does about it.
"""

import json
import time
from collections.abc import Generator
from pathlib import Path

import psycopg
import pytest
import yaml
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.core.locking import (
    LOCK_HOLDER_TABLE,
    LockAcquisitionError,
    LockConfig,
    LockMode,
    MigrationLock,
)
from confiture.core.migrator import Migrator
from confiture.exceptions import MigrationError

runner = CliRunner()

FRAISEQL_KEY = 0x4652414953450001
OTHER_KEY = -42  # a negative int8 is a key too
_TABLE = "tb_lock_extra_keys_it"
_CREATED = "t_lock_extra_keys_it"


def _connect(url: str) -> psycopg.Connection:
    try:
        return psycopg.connect(url)
    except psycopg.OperationalError as e:
        pytest.skip(f"PostgreSQL not available: {e}")


def _advisory_locks(conn: psycopg.Connection, pid: int) -> int:
    with conn.cursor() as cur:
        cur.execute(t"SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND pid = {pid}")
        row = cur.fetchone()
    conn.commit()
    return int(row[0]) if row else 0


def _exists(conn: psycopg.Connection, name: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(t"SELECT to_regclass({name}) IS NOT NULL")
        row = cur.fetchone()
    conn.commit()
    return bool(row and row[0])


@pytest.fixture
def observer(test_db_url: str) -> Generator[psycopg.Connection]:
    """A third session that reads the catalog and cleans up afterwards."""
    conn = _connect(test_db_url)
    try:
        yield conn
    finally:
        conn.rollback()
        with conn.cursor() as cur:
            for name in (_CREATED, _TABLE, LOCK_HOLDER_TABLE):
                cur.execute(t"DROP TABLE IF EXISTS {name:i} CASCADE")
        conn.commit()
        conn.close()


@pytest.fixture
def holder(test_db_url: str) -> Generator[psycopg.Connection]:
    """A session holding FraiseQL's key the way FraiseQL does: in an open transaction."""
    conn = _connect(test_db_url)
    with conn.cursor() as cur:
        cur.execute(t"SELECT pg_advisory_xact_lock({FRAISEQL_KEY}::bigint)")
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()


@pytest.fixture
def migrations_dir(tmp_path: Path) -> Path:
    d = tmp_path / "migrations"
    d.mkdir()
    (d / "20260101000001_a.up.sql").write_text(f"CREATE TABLE {_CREATED} (id int);")
    (d / "20260101000001_a.down.sql").write_text(f"DROP TABLE {_CREATED};")
    return d


def _config(tmp_path: Path, url: str, extra_keys: list[int] | None) -> Path:
    """An environment file where ``migrate up`` reads its ``migration:`` block."""
    env_dir = tmp_path / "db" / "environments"
    env_dir.mkdir(parents=True, exist_ok=True)
    migration: dict[str, object] = {"tracking_table": _TABLE}
    if extra_keys is not None:
        migration["locking"] = {"extra_keys": extra_keys}
    path = env_dir / "test.yaml"
    path.write_text(
        yaml.safe_dump(
            {"name": "test", "database_url": url, "include_dirs": [], "migration": migration}
        )
    )
    return path


def _up(config: Path, migrations_dir: Path, *extra: str):
    return runner.invoke(
        app,
        ["migrate", "up", "-c", str(config), "--migrations-dir", str(migrations_dir), *extra],
    )


class TestMigrateUpTakesTheExtraKey:
    def test_waits_for_the_key_and_times_out_with_the_lock_error(
        self, tmp_path, test_db_url, holder, observer, migrations_dir
    ) -> None:
        config = _config(tmp_path, test_db_url, [FRAISEQL_KEY])
        started = time.monotonic()
        result = _up(config, migrations_dir, "--lock-timeout", "500", "--format", "json")
        assert result.exit_code == 6, result.output  # LOCK_1300
        assert time.monotonic() - started >= 0.5  # it waited
        payload = json.loads(result.stdout)
        assert payload["error"]["code"] == "LOCK_1300"
        assert str(FRAISEQL_KEY) in payload["error"]["message"]
        assert not _exists(observer, _CREATED)

    def test_without_the_setting_it_proceeds(
        self, tmp_path, test_db_url, holder, observer, migrations_dir
    ) -> None:
        config = _config(tmp_path, test_db_url, None)
        result = _up(config, migrations_dir, "--lock-timeout", "500")
        assert result.exit_code == 0, result.output
        assert _exists(observer, _CREATED)

    def test_with_the_key_free_it_proceeds(
        self, tmp_path, test_db_url, observer, migrations_dir
    ) -> None:
        config = _config(tmp_path, test_db_url, [FRAISEQL_KEY, OTHER_KEY])
        result = _up(config, migrations_dir)
        assert result.exit_code == 0, result.output
        assert _exists(observer, _CREATED)

    def test_migrate_down_waits_for_the_key_too(
        self, tmp_path, test_db_url, observer, migrations_dir
    ) -> None:
        config = _config(tmp_path, test_db_url, [FRAISEQL_KEY])
        assert _up(config, migrations_dir).exit_code == 0
        holding = _connect(test_db_url)
        try:
            with holding.cursor() as cur:
                cur.execute(t"SELECT pg_advisory_xact_lock({FRAISEQL_KEY}::bigint)")
            result = runner.invoke(
                app,
                [
                    "migrate",
                    "down",
                    "-c",
                    str(config),
                    "--migrations-dir",
                    str(migrations_dir),
                    "--lock-timeout",
                    "500",
                ],
            )
        finally:
            holding.rollback()
            holding.close()
        assert result.exit_code == 6, result.output
        assert _exists(observer, _CREATED)


class TestKeysAreReleased:
    def test_after_a_successful_run(self, test_db_url, observer, migrations_dir) -> None:
        conn = _connect(test_db_url)
        try:
            Migrator(conn, migration_table=_TABLE).migrate_up(
                migrations_dir=migrations_dir,
                lock_config=LockConfig(extra_keys=(FRAISEQL_KEY, OTHER_KEY)),
            )
            assert _advisory_locks(observer, conn.info.backend_pid) == 0
        finally:
            conn.close()
        assert _exists(observer, _CREATED)

    def test_after_a_failing_migration(self, test_db_url, observer, migrations_dir) -> None:
        (migrations_dir / "20260101000002_b.up.sql").write_text("SELECT 1/0;")
        (migrations_dir / "20260101000002_b.down.sql").write_text("SELECT 1;")
        conn = _connect(test_db_url)
        try:
            with pytest.raises((MigrationError, psycopg.Error)):
                Migrator(conn, migration_table=_TABLE).migrate_up(
                    migrations_dir=migrations_dir,
                    lock_config=LockConfig(extra_keys=(FRAISEQL_KEY, OTHER_KEY)),
                )
            assert _advisory_locks(observer, conn.info.backend_pid) == 0
        finally:
            conn.close()

    def test_when_a_later_key_times_out(self, test_db_url, holder, observer) -> None:
        conn = _connect(test_db_url)
        try:
            lock = MigrationLock(
                conn, LockConfig(timeout_ms=300, extra_keys=(OTHER_KEY, FRAISEQL_KEY))
            )
            with pytest.raises(LockAcquisitionError) as caught, lock.acquire():
                pytest.fail("the lock was taken while FraiseQL's key was held")
            assert caught.value.timeout is True
            assert _advisory_locks(observer, conn.info.backend_pid) == 0
        finally:
            conn.close()

    def test_non_blocking_fails_fast_and_releases(self, test_db_url, holder, observer) -> None:
        conn = _connect(test_db_url)
        try:
            lock = MigrationLock(
                conn,
                LockConfig(mode=LockMode.NON_BLOCKING, extra_keys=(OTHER_KEY, FRAISEQL_KEY)),
            )
            started = time.monotonic()
            with pytest.raises(LockAcquisitionError) as caught, lock.acquire():
                pytest.fail("the lock was taken while FraiseQL's key was held")
            assert time.monotonic() - started < 1.0
            assert caught.value.timeout is False
            assert str(FRAISEQL_KEY) in str(caught.value)
            assert _advisory_locks(observer, conn.info.backend_pid) == 0
        finally:
            conn.close()

    def test_keys_are_held_in_the_one_bigint_form(self, test_db_url, observer) -> None:
        conn = _connect(test_db_url)
        try:
            lock = MigrationLock(conn, LockConfig(extra_keys=(FRAISEQL_KEY, OTHER_KEY)))
            with lock.acquire():
                with observer.cursor() as cur:
                    cur.execute(
                        t"""
                        SELECT (classid::bigint << 32) | objid::bigint, objsubid
                        FROM pg_locks
                        WHERE locktype = 'advisory' AND pid = {conn.info.backend_pid}
                        ORDER BY objsubid DESC
                        """
                    )
                    rows = cur.fetchall()
                observer.commit()
            held = {(int(r[0]), int(r[1])) for r in rows}
            # One two-int4 lock (objsubid 2) and the two one-bigint keys (objsubid 1).
            assert sum(1 for _, sub in held if sub == 2) == 1
            assert {FRAISEQL_KEY, OTHER_KEY} <= {k for k, sub in held if sub == 1}
            assert _advisory_locks(observer, conn.info.backend_pid) == 0
        finally:
            conn.close()
