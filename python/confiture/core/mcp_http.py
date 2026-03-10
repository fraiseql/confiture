"""HTTP transport adapter for MCPServer using FastAPI.

Only importable when fastapi and uvicorn are installed (optional extras: mcp-http).

Install with::

    uv add 'fraiseql-confiture[mcp-http]'

Usage::

    confiture mcp --database-url $DB_URL --port 8080
    # Then POST to http://localhost:8080/mcp
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass


def create_app(
    database_url: str,
    schema: str = "public",
    name_pattern: str | None = None,
    expose_confiture_tools: bool = True,
) -> Any:
    """Build and return a FastAPI app wrapping MCPServer.

    Args:
        database_url: PostgreSQL connection URL.
        schema: Schema to introspect for PG functions.
        name_pattern: SQL LIKE filter for function names.
        expose_confiture_tools: Include confiture__ built-in tools.

    Returns:
        FastAPI application with POST /mcp and GET /health endpoints.

    Raises:
        ImportError: If fastapi is not installed (install with [mcp-http] extra).
    """
    try:
        from fastapi import FastAPI, Request  # type: ignore[import-untyped]
        from fastapi.responses import JSONResponse  # type: ignore[import-untyped]
    except ImportError as e:
        msg = (
            "HTTP mode requires 'fastapi'. "
            "Install with: uv add 'fraiseql-confiture[mcp-http]'"
        )
        raise ImportError(msg) from e

    import psycopg

    from confiture.core.mcp_server import MCPServer

    conn = psycopg.connect(database_url)
    server = MCPServer(
        conn,
        schema=schema,
        name_pattern=name_pattern,
        expose_confiture_tools=expose_confiture_tools,
    )
    server.initialize()

    app = FastAPI(
        title="confiture-mcp",
        version="0.8.0",
        description="Confiture MCP server over HTTP",
    )

    @app.post("/mcp")
    async def mcp_endpoint(request: Request) -> JSONResponse:
        """Handle JSON-RPC MCP requests."""
        try:
            body: dict[str, Any] = await request.json()
        except Exception:
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

    Raises:
        ImportError: If uvicorn is not installed (install with [mcp-http] extra).
    """
    try:
        import uvicorn  # type: ignore[import-untyped]
    except ImportError as e:
        msg = (
            "HTTP mode requires 'uvicorn'. "
            "Install with: uv add 'fraiseql-confiture[mcp-http]'"
        )
        raise ImportError(msg) from e

    app = create_app(
        database_url=database_url,
        schema=schema,
        name_pattern=name_pattern,
        expose_confiture_tools=expose_confiture_tools,
    )
    uvicorn.run(app, host=host, port=port)
