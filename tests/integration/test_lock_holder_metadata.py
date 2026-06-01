"""Integration tests for lock-holder identity metadata (issue #147, Phase 1)."""

from __future__ import annotations

import os
import socket

import psycopg
import pytest

from confiture.core.locking import (
    LOCK_HOLDER_TABLE,
    LockAcquisitionError,
    LockConfig,
    LockMode,
    MigrationLock,
)

# Isolated test lock id (advisory locks on confiture_test otherwise share the
# db-derived id). Distinct per module so we don't collide with the real lock.
_LOCK_ID = 920147001


def _connect(url: str) -> psycopg.Connection:
    """Connect, or skip the test when no DB is reachable (mirrors test_db_connection)."""
    try:
        return psycopg.connect(url)
    except psycopg.OperationalError as e:
        pytest.skip(f"PostgreSQL not available: {e}")


def _clean(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute(f"DELETE FROM {LOCK_HOLDER_TABLE} WHERE lock_id = %s", (_LOCK_ID,))
    conn.commit()


@pytest.fixture
def conns(test_db_url: str):
    a = _connect(test_db_url)
    b = _connect(test_db_url)
    try:
        # ensure the table exists for cleanup, ignore if not yet created
        with a.cursor() as cur:
            cur.execute(
                f"CREATE TABLE IF NOT EXISTS {LOCK_HOLDER_TABLE} ("
                "lock_id BIGINT PRIMARY KEY, pid INT, hostname TEXT, usename TEXT, "
                "command TEXT, acquired_at TIMESTAMPTZ NOT NULL DEFAULT now())"
            )
        a.commit()
        _clean(a)
        yield a, b
    finally:
        _clean(a)
        a.close()
        b.close()


def test_identity_written_on_acquire(conns) -> None:
    conn_a, conn_b = conns
    lock_a = MigrationLock(conn_a, LockConfig(lock_id=_LOCK_ID, command="confiture migrate up"))
    with lock_a.acquire():
        reader = MigrationLock(conn_b, LockConfig(lock_id=_LOCK_ID))
        holder = reader.read_lock_holder()
        assert holder is not None
        assert holder.pid == os.getpid()
        assert holder.hostname == socket.gethostname()
        assert holder.command == "confiture migrate up"
        assert holder.acquired_at is not None
        assert holder.held_for_seconds is not None and holder.held_for_seconds >= 0
        assert holder.live  # advisory lock is genuinely held


def test_identity_cleared_on_release(conns) -> None:
    conn_a, conn_b = conns
    lock_a = MigrationLock(conn_a, LockConfig(lock_id=_LOCK_ID, command="x"))
    with lock_a.acquire():
        pass
    reader = MigrationLock(conn_b, LockConfig(lock_id=_LOCK_ID))
    assert reader.read_lock_holder() is None  # row cleared on release


def test_contention_attaches_holder(conns) -> None:
    conn_a, conn_b = conns
    lock_a = MigrationLock(conn_a, LockConfig(lock_id=_LOCK_ID, command="confiture migrate up"))
    with lock_a.acquire():
        lock_b = MigrationLock(conn_b, LockConfig(lock_id=_LOCK_ID, mode=LockMode.NON_BLOCKING))
        with pytest.raises(LockAcquisitionError) as e:
            lock_b._acquire_lock()
    assert e.value.holder is not None
    assert e.value.holder.command == "confiture migrate up"
    assert e.value.holder.pid == os.getpid()
    assert e.value.holder.held_for_seconds >= 0


def test_read_holder_none_without_table(test_db_url) -> None:
    """Graceful degradation: no metadata table → holder is None, no raise."""
    conn = _connect(test_db_url)
    try:
        with conn.cursor() as cur:
            cur.execute(f"DROP TABLE IF EXISTS {LOCK_HOLDER_TABLE} CASCADE")
        conn.commit()
        reader = MigrationLock(conn, LockConfig(lock_id=_LOCK_ID))
        assert reader._safe_read_lock_holder() is None
    finally:
        conn.close()


def test_crash_safety_stale_row_recognized(test_db_url, conns) -> None:
    """A crashed holder auto-releases the advisory lock; the lingering metadata
    row is recognized as stale (not live), and a new acquirer still succeeds."""
    _conn_a, reader_conn = conns

    # Holder acquires + writes (committed) metadata, then "crashes" — closes the
    # connection WITHOUT releasing. The advisory lock auto-drops; the row stays.
    crasher = _connect(test_db_url)
    crasher_lock = MigrationLock(crasher, LockConfig(lock_id=_LOCK_ID, command="x"))
    crasher_lock._acquire_lock()
    crasher.close()

    reader = MigrationLock(reader_conn, LockConfig(lock_id=_LOCK_ID))
    holder = reader.read_lock_holder()
    assert holder is not None  # stale row lingers
    assert holder.live is False  # advisory lock gone → recognized as stale

    # Crash-safety: a new acquirer succeeds because the advisory lock released.
    new_lock = MigrationLock(reader_conn, LockConfig(lock_id=_LOCK_ID, mode=LockMode.NON_BLOCKING))
    with new_lock.acquire():
        pass  # no LockAcquisitionError → advisory-lock crash-safety preserved
