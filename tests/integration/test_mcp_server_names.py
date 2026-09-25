"""An exposed routine is called by the name the catalogue holds, whatever it spells.

The routine's name comes from ``pg_proc`` and the schema from ``--schema``; the
call composes both as identifiers, so a name that reads as a statement is only
ever a name, and a mixed-case one is not folded onto another routine.
"""

from __future__ import annotations

from collections.abc import Iterator

import psycopg
import pytest
from psycopg import sql

from confiture.core.mcp_server import MCPServer

pytestmark = pytest.mark.integration

#: A routine name that ends the call an unquoted rendering opens.
_INJECTED = "helper(); DROP TABLE keepme; COMMIT; SELECT now"


def _function(name: str, schema: str, returns: int) -> sql.Composed:
    return sql.SQL("CREATE FUNCTION {}() RETURNS int LANGUAGE sql AS {}").format(
        sql.Identifier(schema, name), sql.Literal(f"SELECT {returns}")
    )


@pytest.fixture
def database(fresh_database: str) -> str:
    with psycopg.connect(fresh_database, autocommit=True) as conn:
        conn.execute("CREATE TABLE keepme (x int)")
        conn.execute('CREATE SCHEMA "Tools"')
        conn.execute(_function("helper", "public", 1))
        conn.execute(_function(_INJECTED, "public", 2))
        conn.execute(_function("helper", "Tools", 3))
        conn.execute(_function("Helper", "Tools", 4))
        conn.execute(
            'CREATE FUNCTION "Tools"."Add"(x int, y int) RETURNS int'
            " LANGUAGE sql AS 'SELECT x + y'"
        )
        conn.execute(
            sql.SQL("CREATE PROCEDURE {}() LANGUAGE sql AS {}").format(
                sql.Identifier("public", "touch; DROP TABLE keepme"),
                sql.Literal("SELECT 1"),
            )
        )
    return fresh_database


@pytest.fixture
def call(database: str) -> Iterator[object]:
    connections: list[psycopg.Connection] = []

    def _call(schema: str, name: str, arguments: dict[str, object] | None = None) -> object:
        conn = psycopg.connect(database, autocommit=True)
        connections.append(conn)
        server = MCPServer(conn, schema=schema, expose_confiture_tools=False)
        server.initialize()
        return server.call_tool(name, arguments or {})

    yield _call
    for conn in connections:
        conn.close()


def _kept(database: str) -> object:
    with psycopg.connect(database) as conn:
        return conn.execute("SELECT to_regclass('keepme')::text").fetchone()


def test_a_function_named_like_a_statement_is_called_and_nothing_else_runs(
    database: str, call
) -> None:
    returned = call("public", _INJECTED)

    assert (returned, _kept(database)) == (2, ("keepme",))


def test_a_procedure_named_like_a_statement_is_called_and_nothing_else_runs(
    database: str, call
) -> None:
    returned = call("public", "touch; DROP TABLE keepme")

    assert (returned, _kept(database)) == (None, ("keepme",))


def test_a_mixed_case_schema_and_name_call_that_routine(call) -> None:
    assert (call("Tools", "Helper"), call("Tools", "helper")) == (4, 3)


def test_arguments_are_bound_to_the_named_routine(call) -> None:
    assert call("Tools", "Add", {"x": 40, "y": 2}) == 42


def test_a_percent_in_a_routine_name_is_part_of_the_name(database: str, call) -> None:
    """#375: psycopg read ``%f`` in the composed call as a placeholder once arguments came."""
    with psycopg.connect(database, autocommit=True) as conn:
        conn.execute(
            sql.SQL(
                "CREATE FUNCTION {}(x int) RETURNS int LANGUAGE sql AS 'SELECT x * 100'"
            ).format(sql.Identifier("public", "pct%fn"))
        )
    assert call("public", "pct%fn", {"x": 7}) == 700


def test_each_overload_is_its_own_tool_and_reaches_its_own_body(database: str) -> None:
    """#375: a call picked the first overload of a name, whatever its arguments."""
    with psycopg.connect(database, autocommit=True) as conn:
        conn.execute('CREATE SCHEMA "Over"')
        conn.execute(
            """CREATE FUNCTION "Over".f(x int) RETURNS text LANGUAGE sql AS $$SELECT 'int'$$"""
        )
        conn.execute(
            """CREATE FUNCTION "Over".f(x text) RETURNS text LANGUAGE sql AS $$SELECT 'text'$$"""
        )
        conn.execute("""CREATE FUNCTION "Over".g() RETURNS text LANGUAGE sql AS $$SELECT 'g'$$""")
    server = MCPServer.from_url(database, schema="Over", expose_confiture_tools=False)
    try:
        server.initialize()
        names = sorted(tool["name"] for tool in server.list_tools())
        assert names == ["f__integer", "f__text", "g"]
        assert server.call_tool("f__integer", {"x": 1}) == "int"
        assert server.call_tool("f__text", {"x": "1"}) == "text"
        assert server.call_tool("g", {}) == "g"
    finally:
        server.close()
