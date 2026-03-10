"""Unit tests for MCPServer."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from confiture.models.function_info import (
    FunctionCatalog,
    FunctionInfo,
    FunctionParam,
    Volatility,
)
from confiture.models.mcp_models import MCPTool


def _make_catalog() -> FunctionCatalog:
    from datetime import datetime, timezone

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
        introspected_at=datetime.now(timezone.utc).isoformat(),
        functions=[func],
    )


def _make_server():
    from confiture.core.mcp_server import MCPServer

    mock_conn = MagicMock()
    server = MCPServer(mock_conn, schema="public")
    catalog = _make_catalog()
    with patch.object(server._introspector, "introspect", return_value=catalog):
        server.initialize()
    return server


def test_mcp_server_initialize_builds_tools():
    server = _make_server()
    tools = server.list_tools()
    assert len(tools) == 1
    assert tools[0].name == "add"


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
    server._conn.cursor.return_value = mock_cursor

    msg = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {"name": "add", "arguments": {"x": 1, "y": 2}},
    }
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
