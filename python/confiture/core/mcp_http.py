"""HTTP transport adapter for MCPServer using FastAPI.

Only importable when fastapi and uvicorn are installed (optional extras: mcp-http).

Install with::

    uv add 'fraiseql-confiture[mcp-http]'

Usage::

    export CONFITURE_MCP_TOKEN="$(openssl rand -hex 32)"
    confiture mcp --database-url $DB_URL --port 8080
    # Then POST JSON to http://127.0.0.1:8080/mcp with
    # "Authorization: Bearer $CONFITURE_MCP_TOKEN"

A tool reached here runs migrations, so ``POST /mcp`` answers only a request that
carries the bearer token the server was started with (401 otherwise), is sent as
``application/json`` (415) and has no ``Origin`` header or a loopback one (403).
Any web page open in a browser on the same machine can reach a local port: a
cross-origin ``text/plain`` POST needs no CORS preflight, and a DNS-rebound page
calls the port as its own origin. The ``Origin`` rule is the MCP HTTP transport's
own, and it applies to every route.
"""

import hmac
from typing import Any
from urllib.parse import urlsplit

import psycopg

from confiture import __version__
from confiture.core import mcp_server as _mcp_server

#: The hosts an ``Origin`` header may name: this machine, on any port.
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def _is_loopback_origin(origin: str) -> bool:
    """Whether *origin* is an ``http(s)`` origin on this machine; ``null`` is not."""
    parts = urlsplit(origin)
    return parts.scheme in ("http", "https") and parts.hostname in _LOOPBACK_HOSTS


def _bearer_matches(authorization: str | None, token: str) -> bool:
    """Whether an ``Authorization`` header carries *token* as a bearer token."""
    scheme, _, given = (authorization or "").partition(" ")
    return scheme.lower() == "bearer" and hmac.compare_digest(
        given.strip().encode(), token.encode()
    )


def _is_json(content_type: str | None) -> bool:
    """Whether a ``Content-Type`` header names ``application/json``, parameters aside."""
    return (content_type or "").split(";")[0].strip().lower() == "application/json"


def create_app(
    database_url: str,
    schema: str = "public",
    name_pattern: str | None = None,
    expose_confiture_tools: bool = True,
    *,
    token: str,
) -> Any:
    """Build and return a FastAPI app wrapping MCPServer.

    Args:
        database_url: PostgreSQL connection URL.
        schema: Schema to introspect for PG functions.
        name_pattern: SQL LIKE filter for function names.
        expose_confiture_tools: Include confiture__ built-in tools.
        token: The bearer token every ``POST /mcp`` must carry.

    Returns:
        FastAPI application with POST /mcp and GET /health endpoints.

    Raises:
        ValueError: If *token* is empty; nothing is connected.
        ImportError: If fastapi is not installed (install with [mcp-http] extra).
    """
    if not token:
        msg = "HTTP mode needs a non-empty bearer token"
        raise ValueError(msg)
    try:
        # Reason: optional dependency — extra 'mcp-http'; imported where used so the core never requires it
        from fastapi import FastAPI, Request

        # Reason: optional dependency — extra 'mcp-http'; imported where used so the core never requires it
        from fastapi.responses import JSONResponse
    except ImportError as e:
        msg = "HTTP mode requires 'fastapi'. Install with: uv add 'fraiseql-confiture[mcp-http]'"
        raise ImportError(msg) from e

    conn = psycopg.connect(database_url)
    server = _mcp_server.MCPServer(
        conn,
        schema=schema,
        name_pattern=name_pattern,
        expose_confiture_tools=expose_confiture_tools,
    )
    server.initialize()

    app = FastAPI(
        title="confiture-mcp",
        version=__version__,
        description="Confiture MCP server over HTTP",
        # The schema pages would describe the tools to anyone who reaches the port.
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.middleware("http")
    async def refuse_foreign_origins(request: Request, call_next: Any) -> Any:
        """The MCP transport's DNS-rebinding rule: a browser origin must be this machine."""
        origin = request.headers.get("origin")
        if origin is not None and not _is_loopback_origin(origin):
            return JSONResponse(status_code=403, content={"error": "Origin not allowed"})
        return await call_next(request)

    @app.post("/mcp")
    async def mcp_endpoint(request: Request) -> JSONResponse:
        """Handle JSON-RPC MCP requests."""
        if not _bearer_matches(request.headers.get("authorization"), token):
            return JSONResponse(
                status_code=401,
                content={"error": "A bearer token is required"},
                headers={"WWW-Authenticate": "Bearer"},
            )
        if not _is_json(request.headers.get("content-type")):
            return JSONResponse(
                status_code=415,
                content={"error": "Content-Type must be application/json"},
            )
        try:
            body: dict[str, Any] = await request.json()
        except ValueError:
            return JSONResponse(
                status_code=400,
                content={"error": "Invalid JSON body"},
            )
        response = server.handle_message(body)
        return JSONResponse(content=response)

    @app.get("/health")
    async def health() -> dict[str, str]:
        """Health check endpoint."""
        return {"status": "ok", "server": "confiture-mcp"}

    return app


def serve(
    database_url: str,
    port: int = 8080,
    host: str = "127.0.0.1",
    schema: str = "public",
    name_pattern: str | None = None,
    expose_confiture_tools: bool = True,
    *,
    token: str,
) -> None:
    """Start uvicorn serving the MCP HTTP app.

    This function blocks until the server is stopped (e.g. Ctrl+C).

    Args:
        database_url: PostgreSQL connection URL.
        port: Port to listen on (default: 8080).
        host: Host interface (default: 127.0.0.1).
        schema: Schema to introspect for PG functions.
        name_pattern: SQL LIKE filter for function names.
        expose_confiture_tools: Include confiture__ built-in tools.
        token: The bearer token every ``POST /mcp`` must carry.

    Raises:
        ValueError: If *token* is empty.
        ImportError: If uvicorn is not installed (install with [mcp-http] extra).
    """
    try:
        # Reason: optional dependency — extra 'mcp-http'; imported where used so the core never requires it
        import uvicorn
    except ImportError as e:
        msg = "HTTP mode requires 'uvicorn'. Install with: uv add 'fraiseql-confiture[mcp-http]'"
        raise ImportError(msg) from e

    app = create_app(
        database_url=database_url,
        schema=schema,
        name_pattern=name_pattern,
        expose_confiture_tools=expose_confiture_tools,
        token=token,
    )
    uvicorn.run(app, host=host, port=port)
