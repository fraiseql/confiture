"""``confiture generate from-branch | preview | diff``: migrations from a pgGit branch.

Registered into ``confiture``'s own ``generate`` group by :func:`confiture_pggit.register`,
beside the ``generate`` commands ``confiture`` ships.
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from confiture.cli.error_json import cli_boundary, fail
from confiture.cli.helpers import connect
from confiture.cli.options import config_option, output_option
from confiture.exceptions import ConfiturError
from confiture_pggit import (
    MigrationGenerator,
    PgGitClient,
    PgGitNotAvailableError,
    is_pggit_available,
)

console = Console()


def _get_generator(config_path: Path):
    """Create a MigrationGenerator from config file.

    Args:
        config_path: Path to environment config file

    Returns:
        Tuple of (MigrationGenerator, Connection)

    Raises:
        typer.Exit: If pgGit is not available
    """

    # Load config and create connection
    conn = connect(config_path)

    # Check if pgGit is available
    if not is_pggit_available(conn):
        conn.close()
        fail(
            ConfiturError(
                "pgGit extension is not installed on this database.",
                error_code="PRECON_1000",
                resolution_hint=(
                    "Install it with `CREATE EXTENSION pggit CASCADE;` "
                    "(pgGit is for development databases only)."
                ),
            ),
            json_mode=False,
        )

    try:
        generator = MigrationGenerator(conn)
        return generator, conn
    except PgGitNotAvailableError as e:
        conn.close()
        fail(
            ConfiturError(str(e), error_code="PRECON_1000"),
            json_mode=False,
        )


@cli_boundary
def generate_from_branch(
    branch: str = typer.Argument(..., help="Branch name to generate migrations from"),
    base: str = typer.Option(
        "main",
        "--base",
        "-b",
        help="Base branch to compare against (default: main)",
    ),
    output: Path = output_option(
        Path("db/migrations"), help="Output directory for migration files (default: db/migrations)"
    ),
    combined: bool = typer.Option(
        False,
        "--combined",
        "-c",
        help="Generate single combined migration (default: off)",
    ),
    config: Path = config_option(short=False),
) -> None:
    """Generate migrations from a pgGit branch.

    Analyzes commits on BRANCH that aren't in BASE and generates
    Confiture migration files that can be deployed to production.

    Examples:
        confiture generate from-branch feature/payments
        confiture generate from-branch feature/payments --combined
        confiture generate from-branch feature/payments -o db/migrations
        confiture generate from-branch hotfix/bug-123 --base release/1.0
    """
    try:
        generator, conn = _get_generator(config)

        console.print(f"[cyan]Generating migrations from branch '{branch}'...[/cyan]")
        console.print(f"[dim]Base branch: {base}[/dim]\n")

        if combined:
            migration = generator.generate_combined(branch, base, output)
            if migration:
                console.print("[green]Generated combined migration:[/green]")
                console.print(f"  File: {output / f'{migration.version}_{migration.name}.py'}")
                console.print(f"  Changes: {migration.metadata.get('changes_count', 'N/A')}")
            else:
                console.print("[yellow]No changes between branches - nothing to generate.[/yellow]")
        else:
            migrations = generator.generate_from_branch(branch, base, output)
            if migrations:
                console.print(f"[green]Generated {len(migrations)} migration(s):[/green]")
                for m in migrations:
                    console.print(f"  - {m.version}_{m.name}.py")
                console.print(f"\n[dim]Output directory: {output.absolute()}[/dim]")
            else:
                console.print("[yellow]No changes between branches - nothing to generate.[/yellow]")

        conn.close()

    except typer.Exit:
        raise
    # Reason: text-only command: the message names the operation that failed, whatever failed
    except Exception as e:
        fail(ConfiturError(f"Error generating migrations: {e}"), json_mode=False)


@cli_boundary
def preview_generation(
    branch: str = typer.Argument(..., help="Branch name to preview"),
    base: str = typer.Option(
        "main",
        "--base",
        "-b",
        help="Base branch to compare against (default: main)",
    ),
    config: Path = config_option(),
) -> None:
    """Preview what migrations would be generated.

    Shows changes without writing any files. Use this to review
    what would be generated before running `generate from-branch`.

    Examples:
        confiture generate preview feature/payments
        confiture generate preview feature/payments --base develop
    """
    try:
        generator, conn = _get_generator(config)

        console.print(f"[cyan]Previewing migrations from '{branch}' vs '{base}'...[/cyan]\n")

        changes = generator.preview(branch, base)

        if not changes:
            console.print("[yellow]No changes between branches.[/yellow]")
            conn.close()
            return

        # Create table
        table = Table(title=f"Changes: {base} → {branch}")
        table.add_column("Operation", style="cyan")
        table.add_column("Type", style="magenta")
        table.add_column("Name", style="white")
        table.add_column("Has DDL", style="dim")

        for change in changes:
            op = change["operation"]
            op_color = {
                "CREATE": "green",
                "ALTER": "yellow",
                "DROP": "red",
            }.get(op, "white")

            has_ddl = "Yes" if change["has_new_ddl"] else "No"

            table.add_row(
                f"[{op_color}]{op}[/{op_color}]",
                change["object_type"],
                change["object_name"],
                has_ddl,
            )

        console.print(table)
        console.print(f"\n[dim]Total changes: {len(changes)}[/dim]")
        console.print(
            "\n[dim]Run 'confiture generate from-branch' to generate migration files.[/dim]"
        )

        conn.close()

    except typer.Exit:
        raise
    # Reason: text-only command: the message names the operation that failed, whatever failed
    except Exception as e:
        fail(ConfiturError(f"Error previewing: {e}"), json_mode=False)


@cli_boundary
def show_diff(
    branch: str = typer.Argument(..., help="Branch name to diff"),
    base: str = typer.Option(
        "main",
        "--base",
        "-b",
        help="Base branch to compare against (default: main)",
    ),
    show_sql: bool = typer.Option(
        False,
        "--show-sql",
        "-s",
        help="Show the actual SQL for each change (default: off)",
    ),
    config: Path = config_option(),
) -> None:
    """Show detailed diff between branches.

    Similar to preview but can show the actual SQL statements.

    Examples:
        confiture generate diff feature/payments
        confiture generate diff feature/payments --show-sql
    """
    try:
        conn = connect(config)

        if not is_pggit_available(conn):
            conn.close()
            fail(
                ConfiturError(
                    "pgGit not available.",
                    error_code="PRECON_1000",
                    resolution_hint="Install it with `CREATE EXTENSION pggit CASCADE;`.",
                ),
                json_mode=False,
            )

        client = PgGitClient(conn)
        diff = client.diff(base, branch)

        if not diff:
            console.print("[yellow]No differences between branches.[/yellow]")
            conn.close()
            return

        console.print(f"[cyan]Diff: {base} → {branch}[/cyan]\n")

        for entry in diff:
            op = entry.operation
            op_color = {"CREATE": "green", "ALTER": "yellow", "DROP": "red"}.get(op, "white")

            console.print(
                f"[{op_color}]{op}[/{op_color}] {entry.object_type} [bold]{entry.object_name}[/bold]"
            )

            if show_sql and entry.new_ddl:
                console.print(
                    f"[dim]  {entry.new_ddl[:200]}{'...' if len(entry.new_ddl) > 200 else ''}[/dim]"
                )

        console.print(f"\n[dim]Total: {len(diff)} change(s)[/dim]")

        conn.close()

    except typer.Exit:
        raise
    # Reason: text-only command: the message names the operation that failed, whatever failed
    except Exception as e:
        fail(ConfiturError(f"Error: {e}"), json_mode=False)
