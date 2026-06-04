"""Unit tests for the MCP HTTP transport adapter (``core/mcp_http``).

``create_app`` wraps an :class:`MCPServer` in a FastAPI app exposing
``POST /mcp`` (JSON-RPC) and ``GET /health``. The DB connection and the
server are mocked here so the adapter's own wiring — endpoint shapes, the
invalid-JSON guard, and the optional-dependency ImportError guards — is
tested without a database or a live HTTP server.
"""

from __future__ import annotations

import sys

import pytest

from confiture.core import mcp_http

# The adapter only matters when its optional extra is installed.
pytest.importorskip("fastapi")
pytest.importorskip("httpx")  # FastAPI's TestClient transport


def _patch_backend(monkeypatch, handle_message_return):
    """Mock psycopg.connect + MCPServer so create_app needs no real DB.

    Returns the mock server instance so tests can assert on its calls.
    """
    from unittest.mock import MagicMock

    import psycopg

    monkeypatch.setattr(psycopg, "connect", MagicMock(return_value=MagicMock()))

    mock_server = MagicMock()
    mock_server.handle_message.return_value = handle_message_return

    import confiture.core.mcp_server as mcp_server_mod

    monkeypatch.setattr(
        mcp_server_mod, "MCPServer", MagicMock(return_value=mock_server)
    )
    return mock_server


def test_create_app_exposes_health_and_mcp_routes(monkeypatch):
    _patch_backend(monkeypatch, {"jsonrpc": "2.0", "id": 1, "result": {}})

    app = mcp_http.create_app("postgresql://localhost/whatever")

    assert app.title == "confiture-mcp"
    paths = {route.path for route in app.routes}
    assert "/health" in paths
    assert "/mcp" in paths


def test_health_endpoint_reports_ok(monkeypatch):
    _patch_backend(monkeypatch, {})
    from fastapi.testclient import TestClient

    app = mcp_http.create_app("postgresql://localhost/whatever")
    with TestClient(app) as client:
        resp = client.get("/health")

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "server": "confiture-mcp"}


def test_mcp_endpoint_delegates_to_server_handle_message(monkeypatch):
    rpc_response = {"jsonrpc": "2.0", "id": 7, "result": {"tools": []}}
    server = _patch_backend(monkeypatch, rpc_response)
    from fastapi.testclient import TestClient

    app = mcp_http.create_app("postgresql://localhost/whatever")
    request = {"jsonrpc": "2.0", "id": 7, "method": "tools/list"}
    with TestClient(app) as client:
        resp = client.post("/mcp", json=request)

    assert resp.status_code == 200
    assert resp.json() == rpc_response
    server.handle_message.assert_called_once_with(request)


def test_mcp_endpoint_rejects_invalid_json(monkeypatch):
    _patch_backend(monkeypatch, {})
    from fastapi.testclient import TestClient

    app = mcp_http.create_app("postgresql://localhost/whatever")
    with TestClient(app) as client:
        resp = client.post(
            "/mcp",
            content=b"not json",
            headers={"Content-Type": "application/json"},
        )

    assert resp.status_code == 400
    assert resp.json() == {"error": "Invalid JSON body"}


def test_create_app_raises_helpful_error_without_fastapi(monkeypatch):
    """The optional-dependency guard fires when fastapi is missing."""
    monkeypatch.setitem(sys.modules, "fastapi", None)
    with pytest.raises(ImportError) as exc:
        mcp_http.create_app("postgresql://localhost/whatever")
    assert "fastapi" in str(exc.value)
    assert "mcp-http" in str(exc.value)


def test_serve_raises_helpful_error_without_uvicorn(monkeypatch):
    """serve() guards on uvicorn before doing any work."""
    monkeypatch.setitem(sys.modules, "uvicorn", None)
    with pytest.raises(ImportError) as exc:
        mcp_http.serve("postgresql://localhost/whatever")
    assert "uvicorn" in str(exc.value)
    assert "mcp-http" in str(exc.value)
