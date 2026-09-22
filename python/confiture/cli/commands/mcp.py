"""MCP server command.

HTTP mode (``--port``) serves tools that run migrations, so it starts only with a
bearer token, from ``--token`` or ``CONFITURE_MCP_TOKEN``, and ``core.mcp_http``
refuses a request without it. None is generated: a token nobody chose is one
nobody holds, and printing it would put it in a log.
"""

from __future__ import annotations

import typer

from confiture.cli.error_json import fail
from confiture.cli.helpers import console
from confiture.cli.options import database_url_option
from confiture.core.connection import DatabaseError, connect_url
from confiture.core.mcp_server import MCPServer
from confiture.exceptions import ConfigurationError, ConfiturError

#: The environment variable ``--token`` falls back to.
TOKEN_ENV = "CONFITURE_MCP_TOKEN"

mcp_app = typer.Typer(
    help="Experimental: run confiture as an MCP server. "
    "Its options and tools may change in any release.",
    no_args_is_help=True,
)


@mcp_app.callback(invoke_without_command=True)
def mcp_server(
    database_url: str = database_url_option(...),
    schema: str = typer.Option("public", "--schema", "-s", help="Schema to expose"),
    stdio: bool = typer.Option(False, "--stdio", help="Run in stdio mode (for Claude Code)"),
    include: str | None = typer.Option(None, "--include", help="LIKE pattern to filter functions"),
    port: int | None = typer.Option(
        None, "--port", help="Serve over HTTP on this port (needs the [mcp-http] extra)"
    ),
    no_confiture_tools: bool = typer.Option(
        False,
        "--no-confiture-tools",
        help="Disable built-in Confiture migration/introspection tools",
    ),
    token: str | None = typer.Option(
        None,
        "--token",
        envvar=TOKEN_ENV,
        show_envvar=False,
        help=(
            "Bearer token every HTTP request must carry; required with --port. "
            f"Defaults to ${TOKEN_ENV}, which keeps it out of the process list"
        ),
    ),
) -> None:
    """Expose Confiture operations and PostgreSQL stored functions as MCP tools."""

    if port is not None:
        if not token:
            raise typer.BadParameter(
                f"HTTP mode needs a bearer token: pass --token or set {TOKEN_ENV}.",
                param_hint="--token",
            )
        try:
            # Reason: optional dependency — core.mcp_http needs the [mcp-http] extra (fastapi, uvicorn)
            from confiture.core.mcp_http import serve
        except ImportError:
            # No registry code: a missing optional extra is an environment
            # gap, not a confiture-domain failure — generic ConfiturError → exit 1.
            fail(
                ConfiturError(
                    "HTTP mode requires optional extras.",
                    resolution_hint="Install with: uv add 'fraiseql-confiture[mcp-http]'",
                ),
                json_mode=False,
            )

        serve(
            database_url=database_url,
            port=port,
            schema=schema,
            name_pattern=include,
            expose_confiture_tools=not no_confiture_tools,
            token=token,
        )
        return

    try:
        conn = connect_url(database_url)
    except DatabaseError as e:
        fail(
            ConfigurationError(
                f"Connection failed: {e}",
                error_code="CONFIG_006",
                resolution_hint="Check database URL, host, port, and credentials.",
            ),
            json_mode=False,
        )

    server = MCPServer(
        conn,
        schema=schema,
        name_pattern=include,
        expose_confiture_tools=not no_confiture_tools,
    )

    if stdio:
        server.serve_stdio()
        conn.close()
    else:
        # Default: show info and wait
        server.initialize()
        tools = server.list_tools()
        console.print(f"[green]MCP server ready.[/green] {len(tools)} tool(s) available.")
        console.print("[dim]Use --stdio to run in stdio mode for Claude Code integration.[/dim]")
        for t in tools:
            console.print(f"  [cyan]{t['name']}[/cyan]: {t['description']}")
        conn.close()
