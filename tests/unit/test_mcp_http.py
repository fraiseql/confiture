"""Unit tests for the MCP HTTP transport adapter (``core/mcp_http``).

``create_app`` wraps an :class:`MCPServer` in a FastAPI app exposing
``POST /mcp`` (JSON-RPC) and ``GET /health``. The DB connection and the
server are mocked here so the adapter's own wiring — endpoint shapes, the
request guards, and the optional-dependency ImportError guards — is
tested without a database or a live HTTP server.

A tool reached over HTTP runs migrations, so ``POST /mcp`` answers only a request
carrying the bearer token the server was started with, sent as JSON, from no
browser origin or a loopback one: a web page's cross-origin ``text/plain`` POST
needs no CORS preflight, and the MCP transport's DNS-rebinding rule is an
``Origin`` check.
"""

from __future__ import annotations

import json
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

    monkeypatch.setattr(mcp_server_mod, "MCPServer", MagicMock(return_value=mock_server))
    return mock_server


TOKEN = "a-token-the-server-was-started-with"
AUTHORIZED = {"Authorization": f"Bearer {TOKEN}"}
URL = "postgresql://localhost/whatever"
CALL = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {"name": "confiture__migrate_down", "arguments": {}},
}


def test_create_app_exposes_health_and_mcp_routes(monkeypatch):
    _patch_backend(monkeypatch, {"jsonrpc": "2.0", "id": 1, "result": {}})

    app = mcp_http.create_app(URL, token=TOKEN)

    assert app.title == "confiture-mcp"
    paths = {route.path for route in app.routes}
    assert "/health" in paths
    assert "/mcp" in paths


def test_health_endpoint_reports_ok(monkeypatch):
    _patch_backend(monkeypatch, {})
    from fastapi.testclient import TestClient

    app = mcp_http.create_app(URL, token=TOKEN)
    with TestClient(app) as client:
        resp = client.get("/health")

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "server": "confiture-mcp"}


def test_mcp_endpoint_delegates_to_server_handle_message(monkeypatch):
    rpc_response = {"jsonrpc": "2.0", "id": 7, "result": {"tools": []}}
    server = _patch_backend(monkeypatch, rpc_response)
    from fastapi.testclient import TestClient

    app = mcp_http.create_app(URL, token=TOKEN)
    request = {"jsonrpc": "2.0", "id": 7, "method": "tools/list"}
    with TestClient(app) as client:
        resp = client.post("/mcp", json=request, headers=AUTHORIZED)

    assert resp.status_code == 200
    assert resp.json() == rpc_response
    server.handle_message.assert_called_once_with(request)


def test_mcp_endpoint_rejects_invalid_json(monkeypatch):
    _patch_backend(monkeypatch, {})
    from fastapi.testclient import TestClient

    app = mcp_http.create_app(URL, token=TOKEN)
    with TestClient(app) as client:
        resp = client.post(
            "/mcp",
            content=b"not json",
            headers={**AUTHORIZED, "Content-Type": "application/json"},
        )

    assert resp.status_code == 400
    assert resp.json() == {"error": "Invalid JSON body"}


def test_create_app_raises_helpful_error_without_fastapi(monkeypatch):
    """The optional-dependency guard fires when fastapi is missing."""
    monkeypatch.setitem(sys.modules, "fastapi", None)
    with pytest.raises(ImportError) as exc:
        mcp_http.create_app(URL, token=TOKEN)
    assert "fastapi" in str(exc.value)
    assert "mcp-http" in str(exc.value)


def test_serve_raises_helpful_error_without_uvicorn(monkeypatch):
    """serve() guards on uvicorn before doing any work."""
    monkeypatch.setitem(sys.modules, "uvicorn", None)
    with pytest.raises(ImportError) as exc:
        mcp_http.serve(URL, token=TOKEN)
    assert "uvicorn" in str(exc.value)
    assert "mcp-http" in str(exc.value)


def test_http_rejects_foreign_origin_non_json_and_missing_token(monkeypatch):
    server = _patch_backend(monkeypatch, {"jsonrpc": "2.0", "id": 1, "result": {"content": []}})
    from fastapi.testclient import TestClient

    body = json.dumps(CALL)
    refused = [
        (415, {"content": body, "headers": {**AUTHORIZED, "Content-Type": "text/plain"}}),
        (415, {"content": body, "headers": AUTHORIZED}),
        (403, {"json": CALL, "headers": {**AUTHORIZED, "Origin": "https://evil.example"}}),
        (403, {"json": CALL, "headers": {**AUTHORIZED, "Origin": "http://localhost.evil.example"}}),
        (403, {"json": CALL, "headers": {**AUTHORIZED, "Origin": "null"}}),
        (401, {"json": CALL}),
        (401, {"json": CALL, "headers": {"Authorization": "Bearer not-the-token"}}),
        (401, {"json": CALL, "headers": {"Authorization": TOKEN}}),
    ]
    loopback = [None, "http://localhost:3000", "http://127.0.0.1", "https://[::1]:8443"]

    with TestClient(mcp_http.create_app(URL, token=TOKEN)) as client:
        statuses = [client.post("/mcp", **request).status_code for _, request in refused]
        assert statuses == [status for status, _ in refused]
        server.handle_message.assert_not_called()

        for origin in loopback:
            headers = {**AUTHORIZED, **({"Origin": origin} if origin else {})}
            assert client.post("/mcp", json=CALL, headers=headers).status_code == 200, origin

    assert server.handle_message.call_count == len(loopback)


def test_a_refused_token_asks_for_a_bearer_token(monkeypatch):
    _patch_backend(monkeypatch, {})
    from fastapi.testclient import TestClient

    with TestClient(mcp_http.create_app(URL, token=TOKEN)) as client:
        resp = client.post("/mcp", json=CALL)

    assert resp.headers["WWW-Authenticate"] == "Bearer"
    assert TOKEN not in resp.text


def test_create_app_refuses_an_empty_token_before_connecting(monkeypatch):
    _patch_backend(monkeypatch, {})
    import psycopg

    with pytest.raises(ValueError, match="token"):
        mcp_http.create_app(URL, token="")
    psycopg.connect.assert_not_called()
