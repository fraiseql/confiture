"""The lock-holder table lives beside the tracking table, never at the head of search_path (#826)."""

from collections.abc import Generator

import psycopg
import pytest

from confiture.core.locking import LOCK_HOLDER_TABLE, LockConfig, MigrationLock

_SCHEMA = "lock_holder_826_it"


def _connect(url: str) -> psycopg.Connection:
    try:
        return psycopg.connect(url)
    except psycopg.OperationalError as e:
        pytest.skip(f"PostgreSQL not available: {e}")


@pytest.fixture
def conn(test_db_url: str) -> Generator[psycopg.Connection]:
    """A session whose search_path starts with a schema other than the ledger's."""
    conn = _connect(test_db_url)
    with conn.cursor() as cur:
        cur.execute(t"DROP SCHEMA IF EXISTS {_SCHEMA:i} CASCADE")
        cur.execute(t"DROP TABLE IF EXISTS public.{LOCK_HOLDER_TABLE:i}")
        cur.execute(t"CREATE SCHEMA {_SCHEMA:i}")
        cur.execute(t"SET search_path TO {_SCHEMA:i}, public")
    conn.commit()
    try:
        yield conn
    finally:
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute(t"DROP SCHEMA IF EXISTS {_SCHEMA:i} CASCADE")
            cur.execute(t"DROP TABLE IF EXISTS public.{LOCK_HOLDER_TABLE:i}")
        conn.commit()
        conn.close()


def _schemas_holding_it(conn: psycopg.Connection) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(
            t"""SELECT schemaname FROM pg_tables
                WHERE tablename = {LOCK_HOLDER_TABLE} AND schemaname IN ({_SCHEMA}, 'public')
                ORDER BY 1"""
        )
        rows = cur.fetchall()
    conn.commit()
    return [row[0] for row in rows]


def test_holder_table_lands_in_the_given_schema(conn: psycopg.Connection) -> None:
    lock = MigrationLock(conn, LockConfig(holder_schema="public", command="test"))
    with lock.acquire():
        holder = lock.read_lock_holder()

    assert _schemas_holding_it(conn) == ["public"]
    assert holder is not None and holder.command == "test"


def test_without_a_schema_the_holder_resolves_like_a_bare_ledger(conn: psycopg.Connection) -> None:
    with MigrationLock(conn, LockConfig()).acquire():
        pass

    assert _schemas_holding_it(conn) == [_SCHEMA]
