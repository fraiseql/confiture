"""MCP server command."""

from __future__ import annotations

import typer

from confiture.cli.helpers import console, error_console

mcp_app = typer.Typer(help="Run confiture as an MCP server.", no_args_is_help=True)


@mcp_app.callback(invoke_without_command=True)
def mcp_server(
    database_url: str = typer.Option(..., "--database-url", "-d", help="PostgreSQL connection URL"),
    schema: str = typer.Option("public", "--schema", "-s", help="Schema to expose"),
    stdio: bool = typer.Option(False, "--stdio", help="Run in stdio mode (for Claude Code)"),
    include: str | None = typer.Option(None, "--include", help="LIKE pattern to filter functions"),
    port: int | None = typer.Option(None, "--port", help="HTTP port (not yet implemented)"),
    no_confiture_tools: bool = typer.Option(
        False,
        "--no-confiture-tools",
        help="Disable built-in Confiture migration/introspection tools",
    ),
) -> None:
    """Expose Confiture operations and PostgreSQL stored functions as MCP tools."""
    import psycopg

    from confiture.core.mcp_server import MCPServer

    if port is not None:
        try:
            from confiture.core.mcp_http import serve
        except ImportError as exc:
            error_console.print(
                "[red]HTTP mode requires optional extras.[/red]\n"
                "Install with: uv add 'fraiseql-confiture[mcp-http]'"
            )
            raise typer.Exit(1) from exc

        serve(
            database_url=database_url,
            port=port,
            schema=schema,
            name_pattern=include,
            expose_confiture_tools=not no_confiture_tools,
        )
        return

    try:
        conn = psycopg.connect(database_url)
    except Exception as e:
        error_console.print(f"[red]Connection failed: {e}[/red]")
        raise typer.Exit(1) from e

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
