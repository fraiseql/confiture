"""An MCP tool call is one statement: committed when it returns, rolled back when it raises (#373).

Both transports opened their connection with autocommit off and nothing ever
committed or rolled back. A write an agent made was invisible to every other
session and vanished when the server stopped; the connection sat ``idle in
transaction`` holding the locks the call took; and one failed call aborted the
transaction, so every call after it failed too.

The connections MCP opens are in autocommit. A connection a library caller hands
``MCPServer`` is never switched — confiture does not change the mode of a
connection it did not open — so one in a transaction is refused.
"""

from __future__ import annotations

from collections.abc import Iterator

import psycopg
import pytest

from confiture.core.mcp_server import MCPServer
from confiture.exceptions import ConfigurationError

pytestmark = pytest.mark.integration


@pytest.fixture
def database(fresh_database: str) -> str:
    with psycopg.connect(fresh_database, autocommit=True) as conn:
        conn.execute("CREATE TABLE item (id int PRIMARY KEY)")
        conn.execute("INSERT INTO item VALUES (1)")
        conn.execute(
            "CREATE FUNCTION fn_insert(p_id int) RETURNS int LANGUAGE sql"
            " AS 'INSERT INTO item VALUES (p_id) RETURNING id'"
        )
        conn.execute(
            "CREATE FUNCTION fn_fail() RETURNS int LANGUAGE plpgsql"
            " AS $$BEGIN RAISE EXCEPTION 'no'; END$$"
        )
        conn.execute(
            "CREATE FUNCTION fn_lock() RETURNS int LANGUAGE sql"
            " AS 'SELECT id FROM item WHERE id = 1 FOR UPDATE'"
        )
        conn.execute(
            "CREATE PROCEDURE pr_commit(p_id int) LANGUAGE plpgsql"
            " AS $$BEGIN INSERT INTO item VALUES (p_id); COMMIT; END$$"
        )
    return fresh_database


@pytest.fixture
def server(database: str) -> Iterator[MCPServer]:
    """A server on the connection both transports open: ``MCPServer.from_url``'s."""
    server = MCPServer.from_url(database, expose_confiture_tools=False)
    server.initialize()
    yield server
    server.close()


def _ids(database: str) -> list[int]:
    with psycopg.connect(database) as conn:
        return [row[0] for row in conn.execute("SELECT id FROM item ORDER BY id").fetchall()]


def test_a_write_is_seen_by_another_session(server: MCPServer, database: str) -> None:
    assert server.call_tool("fn_insert", {"p_id": 2}) == 2
    assert _ids(database) == [1, 2]


def test_a_failed_call_does_not_fail_the_next(server: MCPServer, database: str) -> None:
    with pytest.raises(psycopg.errors.RaiseException):
        server.call_tool("fn_fail", {})
    assert server.call_tool("fn_insert", {"p_id": 3}) == 3
    assert _ids(database) == [1, 3]


def test_a_call_releases_the_locks_it_took(server: MCPServer, database: str) -> None:
    assert server.call_tool("fn_lock", {}) == 1
    with psycopg.connect(database) as other:
        other.execute("SET lock_timeout = '500ms'")
        assert other.execute("SELECT id FROM item WHERE id = 1 FOR UPDATE").fetchone() == (1,)


def test_a_procedure_that_commits_can_be_called(server: MCPServer, database: str) -> None:
    """A transaction-control statement is refused inside an explicit transaction block."""
    assert server.call_tool("pr_commit", {"p_id": 4}) is None
    assert _ids(database) == [1, 4]


def test_a_callers_connection_in_a_transaction_is_refused_not_switched(database: str) -> None:
    with psycopg.connect(database) as conn:
        with pytest.raises(ConfigurationError) as excinfo:
            MCPServer(conn)
        assert excinfo.value.error_code == "CONFIG_013"
        assert conn.autocommit is False


def test_a_server_that_owns_its_connection_reconnects_after_losing_it(
    server: MCPServer, database: str
) -> None:
    """A broken connection it opened is replaced; the call that broke it still fails."""
    with psycopg.connect(database, autocommit=True) as admin:
        admin.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity"
            " WHERE datname = current_database() AND pid <> pg_backend_pid()"
        )
    with pytest.raises(psycopg.OperationalError):
        server.call_tool("fn_insert", {"p_id": 5})
    assert server.call_tool("fn_insert", {"p_id": 6}) == 6
