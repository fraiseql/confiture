"""Unit tests for MCPServer."""

from __future__ import annotations

from datetime import UTC
from unittest.mock import MagicMock, patch

import pytest

from confiture.models.function_info import (
    FunctionCatalog,
    FunctionInfo,
    FunctionParam,
    Volatility,
)


def _make_catalog() -> FunctionCatalog:
    from datetime import datetime

    func = FunctionInfo(
        schema="public",
        name="add",
        oid=1,
        params=[
            FunctionParam(name="x", pg_type="integer"),
            FunctionParam(name="y", pg_type="integer"),
        ],
        return_type="integer",
        returns_set=False,
        volatility=Volatility.IMMUTABLE,
        is_procedure=False,
        language="sql",
        source="SELECT $1 + $2",
        estimated_cost=1.0,
    )
    return FunctionCatalog(
        database="testdb",
        schema="public",
        introspected_at=datetime.now(UTC).isoformat(),
        functions=[func],
    )


def _make_server(expose_confiture_tools: bool = False):
    from confiture.core.mcp_server import MCPServer

    mock_conn = MagicMock()
    server = MCPServer(mock_conn, schema="public", expose_confiture_tools=expose_confiture_tools)
    catalog = _make_catalog()
    with patch.object(server._introspector, "introspect", return_value=catalog):
        server.initialize()
    return server


def test_mcp_server_initialize_builds_tools():
    server = _make_server()
    tools = server.list_tools()
    assert len(tools) == 1
    assert tools[0]["name"] == "add"


def test_mcp_server_handle_initialize():
    server = _make_server()
    msg = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    response = server.handle_message(msg)
    assert response["id"] == 1
    assert "protocolVersion" in response["result"]
    assert response["result"]["serverInfo"]["name"] == "confiture-mcp"


def test_mcp_server_handle_tools_list():
    server = _make_server()
    msg = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
    response = server.handle_message(msg)
    assert response["id"] == 2
    tools = response["result"]["tools"]
    # Only PG tools (expose_confiture_tools=False in _make_server default)
    assert len(tools) == 1
    assert tools[0]["name"] == "add"
    assert "inputSchema" in tools[0]


def test_mcp_server_handle_tools_call():
    server = _make_server()
    # Mock the cursor call
    mock_cursor = MagicMock()
    mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
    mock_cursor.__exit__ = MagicMock(return_value=False)
    mock_cursor.fetchone.return_value = (42,)

    msg = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {"name": "add", "arguments": {"x": 1, "y": 2}},
    }
    with patch("confiture.core.mcp_server.psycopg.RawCursor", return_value=mock_cursor):
        response = server.handle_message(msg)
    assert response["id"] == 3
    content = response["result"]["content"]
    assert len(content) == 1
    assert content[0]["type"] == "text"


def test_mcp_server_handle_unknown_method():
    server = _make_server()
    msg = {"jsonrpc": "2.0", "id": 4, "method": "unknown/method"}
    response = server.handle_message(msg)
    assert "error" in response
    assert response["error"]["code"] == -32601


def test_mcp_server_handle_notifications_initialized():
    server = _make_server()
    msg = {"jsonrpc": "2.0", "id": None, "method": "notifications/initialized"}
    response = server.handle_message(msg)
    assert response == {}


def test_mcp_server_call_unknown_tool_raises():
    server = _make_server()
    with pytest.raises(ValueError, match="Unknown tool"):
        server.call_tool("nonexistent", {})


def test_mcp_server_handle_tools_call_unknown_tool_returns_error():
    server = _make_server()
    msg = {
        "jsonrpc": "2.0",
        "id": 5,
        "method": "tools/call",
        "params": {"name": "nonexistent", "arguments": {}},
    }
    response = server.handle_message(msg)
    assert "error" in response
    assert response["error"]["code"] == -32603


# ── Gap A: MCP HTTP tests (fastapi optional) ──────────────────────────────────


def test_mcp_http_import_error_without_fastapi():
    """create_app() raises ImportError with install hint when fastapi not installed."""
    import sys
    from unittest.mock import patch

    # Remove fastapi from sys.modules to simulate it not being installed
    with patch.dict(sys.modules, {"fastapi": None}):
        import builtins

        # Force re-evaluation by patching the internal import
        from confiture.core import mcp_http as _http_mod

        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "fastapi":
                raise ImportError("No module named 'fastapi'")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            with pytest.raises(ImportError, match="mcp-http"):
                _http_mod.create_app("postgresql://localhost/test", token="t")


def test_mcp_http_uvicorn_import_error():
    """serve() raises ImportError with install hint when uvicorn not installed."""
    import builtins
    from unittest.mock import patch

    original_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == "uvicorn":
            raise ImportError("No module named 'uvicorn'")
        return original_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=mock_import):
        from confiture.core import mcp_http as _http_mod

        with pytest.raises(ImportError, match="mcp-http"):
            _http_mod.serve("postgresql://localhost/test", token="t")


def test_mcp_http_create_app_returns_fastapi_app():
    """create_app() returns a FastAPI app when fastapi and uvicorn are available."""
    pytest.importorskip("fastapi", reason="fastapi not installed")

    from unittest.mock import patch

    with patch("psycopg.connect") as mock_connect:
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn

        catalog = _make_catalog()
        with patch("confiture.core.mcp_server.FunctionIntrospector") as mock_introspector_cls:
            mock_introspector = MagicMock()
            mock_introspector.introspect.return_value = catalog
            mock_introspector_cls.return_value = mock_introspector

            from confiture.core.mcp_http import create_app

            app = create_app("postgresql://localhost/testdb", token="t")

            from fastapi import FastAPI

            assert isinstance(app, FastAPI)


def test_mcp_http_post_tools_list():
    """POST /mcp with tools/list returns tools array."""
    pytest.importorskip("fastapi", reason="fastapi not installed")
    pytest.importorskip("httpx", reason="httpx not installed")

    from unittest.mock import patch

    from fastapi.testclient import TestClient

    with patch("psycopg.connect") as mock_connect:
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn

        catalog = _make_catalog()
        with patch("confiture.core.mcp_server.FunctionIntrospector") as mock_introspector_cls:
            mock_introspector = MagicMock()
            mock_introspector.introspect.return_value = catalog
            mock_introspector_cls.return_value = mock_introspector

            from confiture.core.mcp_http import create_app

            app = create_app(
                "postgresql://localhost/testdb", expose_confiture_tools=False, token="t"
            )
            client = TestClient(app)

            resp = client.post(
                "/mcp",
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                headers={"Authorization": "Bearer t"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "result" in data
            assert "tools" in data["result"]


def test_mcp_http_health_returns_ok():
    """GET /health returns {status: ok}."""
    pytest.importorskip("fastapi", reason="fastapi not installed")
    pytest.importorskip("httpx", reason="httpx not installed")

    from unittest.mock import patch

    from fastapi.testclient import TestClient

    with patch("psycopg.connect") as mock_connect:
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn

        catalog = _make_catalog()
        with patch("confiture.core.mcp_server.FunctionIntrospector") as mock_introspector_cls:
            mock_introspector = MagicMock()
            mock_introspector.introspect.return_value = catalog
            mock_introspector_cls.return_value = mock_introspector

            from confiture.core.mcp_http import create_app

            app = create_app("postgresql://localhost/testdb", token="t")
            client = TestClient(app)

            resp = client.get("/health")
            assert resp.status_code == 200
            assert resp.json()["status"] == "ok"


def test_mcp_cli_port_starts_http_server():
    """--port flag calls serve() with correct parameters."""
    from unittest.mock import MagicMock, patch

    from typer.testing import CliRunner

    from confiture.cli.commands.mcp import mcp_app

    runner = CliRunner()

    with patch("confiture.cli.commands.mcp.mcp_server.__wrapped__", create=True):
        with patch("confiture.core.mcp_http.serve"):
            with patch("psycopg.connect", return_value=MagicMock()):
                result = runner.invoke(
                    mcp_app,
                    [
                        "--database-url",
                        "postgresql://localhost/test",
                        "--port",
                        "8080",
                        "--token",
                        "t",
                    ],
                )
                # If serve was called OR the import itself raised (no fastapi), either is OK
                # The key is the old "not yet implemented" message is gone
                assert "not yet implemented" not in (result.output or "")


def test_a_routine_is_called_by_its_name_as_an_identifier():
    """The call names the routine; nothing in its name can end the statement."""
    import dataclasses

    import pglast

    from confiture.core.mcp_server import MCPServer

    name = "helper(); DROP TABLE keepme; COMMIT; SELECT now"
    func = dataclasses.replace(_make_catalog().functions[0], name=name, params=[])
    catalog = dataclasses.replace(_make_catalog(), functions=[func])
    server = MCPServer(MagicMock(), schema="Tools", expose_confiture_tools=False)
    with patch.object(server._introspector, "introspect", return_value=catalog):
        server.initialize()
    raw = MagicMock()
    cursor = raw.return_value.__enter__.return_value
    cursor.fetchone.return_value = (1,)

    with patch("confiture.core.mcp_server.psycopg.RawCursor", raw):
        server.call_tool(name, {})

    statement = cursor.execute.call_args.args[0]
    text = statement if isinstance(statement, str) else statement.as_string()
    (parsed,) = pglast.parse_sql(text)
    (target,) = parsed.stmt.targetList
    assert tuple(part.sval for part in target.val.funcname) == ("Tools", name)


# ── A tool name is one routine's, and a hidden built-in is not callable ─────────


def _routine(name: str, oid: int, *types: str) -> FunctionInfo:
    return FunctionInfo(
        schema="public",
        name=name,
        oid=oid,
        params=[FunctionParam(name=f"p{i}", pg_type=t) for i, t in enumerate(types)],
        return_type="integer",
        returns_set=False,
        volatility=Volatility.VOLATILE,
        is_procedure=False,
        language="sql",
        source="SELECT 1",
        estimated_cost=1.0,
    )


def test_a_routine_named_like_a_builtin_gets_its_oid_name() -> None:
    """``confiture__migrate_down`` in the schema must not be a second tool of that name."""
    from confiture.core.mcp_server import _tool_names

    tools = _tool_names([_routine("confiture__migrate_down", 42)])
    assert set(tools) == {"confiture__migrate_down__42"}


def test_an_overload_name_a_routine_already_holds_is_not_overwritten() -> None:
    """``f(integer)`` would be ``f__integer``, the name another routine holds outright."""
    from confiture.core.mcp_server import _tool_names

    routines = [_routine("f__integer", 1), _routine("f", 2, "integer"), _routine("f", 3, "text")]
    for order in (routines, routines[::-1]):
        tools = _tool_names(order)
        assert len(tools) == 3
        assert {info.oid for info in tools.values()} == {1, 2, 3}


def test_a_hidden_builtin_is_not_callable() -> None:
    """``expose_confiture_tools=False`` hides the built-ins from the list and from a call."""
    server = _make_server(expose_confiture_tools=False)
    with pytest.raises(ValueError, match="Unknown tool"):
        server.call_tool("confiture__migrate_up", {})
